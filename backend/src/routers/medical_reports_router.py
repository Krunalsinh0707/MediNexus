from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import json
import logging
from pathlib import Path
from datetime import datetime

from src.database import get_db
from src.models import MedicalReport, ReportExtraction, AIAnalysis, DoctorReview, Doctor, Department, User, Notification, ReportReviewRequest, AuditLog
from src.auth import get_current_user
from src.patient_access import require_clinical_history
from src.clinical_write_access import active_clinician, require_report_creation, require_report_review
from src.medical_review_service import append_review_revision, latest_revision, read_review_revisions, review_projection
from src.pdf_service import extract_parameters_from_pdf
from src.ml.department_detector import detect_department
from src.security.rate_limiter import rate_limit
from src.security.file_security import (
    sanitize_filename,
    sanitize_original_filename,
    validate_uploaded_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/medical-reports", tags=["Digital Medical Reports"])


def _report_upload_directory() -> Path:
    default_root = Path(__file__).resolve().parents[2] / "uploads"
    return Path(os.getenv("HMS_UPLOAD_ROOT", default_root)).resolve() / "reports"

class HospitalReportCreate(BaseModel):
    patient_id: int
    department_id: int
    report_title: str
    report_type: str
    findings: str
    parameters: dict

class DoctorReviewCreate(BaseModel):
    review_status: str # APPROVED, MODIFIED, REJECTED
    clinical_notes: Optional[str] = None
    final_assessment: Optional[str] = None
    corrected_parameters: Optional[dict] = None


class DoctorReviewAmendment(BaseModel):
    expected_revision_number: int = Field(..., ge=1)
    review_status: str
    # An amendment is a complete signed snapshot; omissions must not clear text.
    clinical_notes: Optional[str] = Field(...)
    final_assessment: Optional[str] = Field(...)
    corrected_parameters: Optional[dict] = Field(...)
    amendment_reason: str = Field(..., min_length=1)

class RequestReportReviewModel(BaseModel):
    doctor_id: Optional[int] = None
    notes: Optional[str] = None

@router.get("/my")
def get_my_reports(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    reports = db.query(MedicalReport).filter(MedicalReport.patient_id == current_user.user_id).order_by(MedicalReport.created_at.desc()).all()
    result = []
    for r in reports:
        dept = db.query(Department).filter(Department.id == r.department_id).first() if r.department_id else None
        doc = db.query(Doctor).filter(Doctor.id == r.doctor_id).first() if r.doctor_id else None
        doc_user = db.query(User).filter(User.id == doc.user_id).first() if doc else None
        
        ai = db.query(AIAnalysis).filter(AIAnalysis.report_id == r.id).first()
        review = db.query(DoctorReview).filter(DoctorReview.report_id == r.id).first()
        ext = db.query(ReportExtraction).filter(ReportExtraction.report_id == r.id).first()

        review_req = db.query(ReportReviewRequest).filter(
            ReportReviewRequest.report_id == r.id
        ).order_by(ReportReviewRequest.created_at.desc()).first()

        review_request_info = None
        if review_req:
            req_doc = db.query(Doctor).filter(Doctor.id == review_req.doctor_id).first()
            req_doc_user = db.query(User).filter(User.id == req_doc.user_id).first() if req_doc else None
            review_request_info = {
                "id": review_req.id,
                "status": review_req.status,
                "doctor_id": review_req.doctor_id,
                "doctor_name": f"Dr. {req_doc_user.full_name}" if req_doc_user else "Physician",
                "notes": review_req.notes,
                "created_at": review_req.created_at.strftime("%Y-%m-%d %H:%M") if review_req.created_at else "",
                "completed_at": review_req.completed_at.strftime("%Y-%m-%d %H:%M") if review_req.completed_at else ""
            }

        result.append({
            "id": r.id,
            "report_source": r.report_source,
            "report_title": r.report_title,
            "report_type": r.report_type,
            "report_date": r.report_date.strftime("%Y-%m-%d") if r.report_date else (r.created_at.strftime("%Y-%m-%d") if r.created_at else ""),
            "department_name": dept.name if dept else "General",
            "department_id": r.department_id,
            "doctor_id": r.doctor_id,
            "doctor_name": doc_user.full_name if doc_user else "Hospital Medical Staff",
            "status": r.status,
            "original_filename": r.original_filename,
            "extracted_parameters": ext.extracted_json if ext and ext.extracted_json else {},
            "ai_analysis": {
                "prediction": ai.prediction,
                "probability": ai.probability,
                "risk_level": ai.risk_level,
                "important_factors": ai.important_factors,
                "explanation": ai.explanation
            } if ai else None,
            "doctor_review": review_projection(review, latest_revision(db, r.id) if review else None),
            "review_request": review_request_info
        })
    return result

@router.post("/upload")
async def upload_existing_report(
    file: UploadFile = File(...),
    report_title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    _limiter: None = Depends(rate_limit(max_requests=10, window_seconds=60, prefix="report_upload"))
):
    # Validate uploaded file for MIME type, magic bytes, and size limit
    content = await validate_uploaded_file(file, max_size_bytes=10 * 1024 * 1024)
    safe_filename = sanitize_filename(file.filename, prefix=f"user_{current_user.user_id}_")
    clean_original_filename = sanitize_original_filename(file.filename)
    upload_directory = _report_upload_directory()
    upload_directory.mkdir(parents=True, exist_ok=True)
    file_path = upload_directory / safe_filename

    try:
        file_path.write_bytes(content)
    except OSError as exc:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        logger.error("Unable to store validated report upload: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to store uploaded report") from exc

    title = (report_title or file.filename or "Uploaded Report").strip()[:150]

    # Create Medical Report record
    new_report = MedicalReport(
        patient_id=current_user.user_id,
        report_source="existing_upload",
        report_title=title,
        report_type="Uploaded Diagnostic Report",
        original_filename=clean_original_filename,
        # Store a portable key; resolve it relative to HMS_UPLOAD_ROOT for reads.
        file_path=(Path("reports") / safe_filename).as_posix(),
        status="UPLOADED"
    )
    db.add(new_report)
    try:
        db.flush()

        # OCR failures preserve the validated upload and route it for manual review.
        extracted_data = {}
        raw_text = ""
        try:
            if safe_filename.lower().endswith(".pdf"):
                extracted_data = extract_parameters_from_pdf(str(file_path))
                raw_text = json.dumps(extracted_data)
            else:
                raw_text = "Image report upload"
        except Exception as exc:
            logger.warning("[OCR] Extraction warning: %s", exc)

        extraction = ReportExtraction(
            report_id=new_report.id,
            ocr_raw_text=raw_text,
            extracted_json=extracted_data,
            validation_status="VALID" if extracted_data else "NEEDS_REVIEW",
            confidence_score=0.92 if extracted_data else 0.50
        )
        db.add(extraction)

        dept_slug = detect_department(extracted_data, raw_text)
        dept = db.query(Department).filter(Department.code == dept_slug.upper()[:6]).first()
        if not dept:
            dept = db.query(Department).filter(Department.name.ilike(f"%{dept_slug}%")).first()

        if dept:
            new_report.department_id = dept.id

        # Both states are valid persisted enum labels and are visible in the
        # assigned review queue. Empty/failed OCR remains an unprocessed upload.
        new_report.status = "OCR_EXTRACTED" if extracted_data else "UPLOADED"
        db.commit()
    except Exception:
        db.rollback()
        try:
            file_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            logger.error("Failed to remove rolled-back report file %s: %s", file_path, cleanup_error)
        raise

    return {
        "message": "Report uploaded and extracted successfully",
        "report_id": new_report.id,
        "extracted_parameters": extracted_data
    }

@router.post("/hospital")
def create_hospital_report(data: HospitalReportCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doctor = require_report_creation(db, current_user, data.patient_id, data.department_id)

    patient = db.query(User).filter(User.id == data.patient_id).first()
    if not patient or patient.role not in ('patient', 'user'):
        raise HTTPException(status_code=404, detail="Target patient account not found")

    dept = db.query(Department).filter(Department.id == data.department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    new_report = MedicalReport(
        patient_id=data.patient_id,
        doctor_id=doctor.id,
        department_id=data.department_id,
        report_source="hospital",
        report_title=data.report_title[:150],
        report_type=data.report_type[:100],
        status="DOCTOR_REVIEWED"
    )
    db.add(new_report)
    # Allocate the ID without committing a report that has no signed review.
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise

    # Doctor Review record
    review = DoctorReview(
        report_id=new_report.id,
        doctor_id=doctor.id,
        review_status="APPROVED",
        clinical_notes=data.findings,
        final_assessment=f"Hospital Report Generated: {data.report_title}"
    )
    db.add(review)
    new_report.status = "FINALIZED"

    # Notify patient
    notif = Notification(
        user_id=data.patient_id,
        title="New Hospital Medical Report",
        message=f"New report '{data.report_title}' has been generated by your doctor.",
        type="REPORT"
    )
    db.add(notif)
    db.add(AuditLog(user_id=current_user.user_id, action="hospital_report_created",
                    details={"report_id": new_report.id, "patient_id": data.patient_id, "doctor_id": doctor.id}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": "Hospital report created successfully", "report_id": new_report.id}

@router.get("/doctor/queue")
def get_reports_pending_review(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from sqlalchemy import exists, select
    doctor = active_clinician(db, current_user)
    assigned = exists(select(ReportReviewRequest.id).where(
        ReportReviewRequest.report_id == MedicalReport.id,
        ReportReviewRequest.patient_id == MedicalReport.patient_id,
        ReportReviewRequest.doctor_id == doctor.id,
        ReportReviewRequest.status.in_(("PENDING", "IN_REVIEW")),
    ))
    query = db.query(MedicalReport).filter(
        MedicalReport.status.in_(["AI_PRE_ANALYZED", "UPLOADED", "OCR_EXTRACTED"]),
        assigned,
    )

    reports = query.order_by(MedicalReport.created_at.desc()).all()
    result = []
    for r in reports:
        patient = db.query(User).filter(User.id == r.patient_id).first()
        ext = db.query(ReportExtraction).filter(ReportExtraction.report_id == r.id).first()
        ai = db.query(AIAnalysis).filter(AIAnalysis.report_id == r.id).first()
        result.append({
            "id": r.id,
            "patient_id": r.patient_id,
            "patient_name": patient.full_name if patient else "Patient",
            "patient_email": patient.email if patient else "",
            "report_title": r.report_title,
            "report_type": r.report_type,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
            "status": r.status,
            "extracted_json": ext.extracted_json if ext else {},
            "ai_analysis": {
                "model_name": ai.model_name,
                "prediction": ai.prediction,
                "probability": ai.probability,
                "risk_level": ai.risk_level,
                "important_factors": ai.important_factors,
                "explanation": ai.explanation
            } if ai else None
        })
    return result

@router.get("/patient/{patient_id}")
def get_patient_reports_for_doctor(patient_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_clinical_history(db, current_user, patient_id)

    reports = db.query(MedicalReport).filter(MedicalReport.patient_id == patient_id).order_by(MedicalReport.created_at.desc()).all()
    result = []
    for r in reports:
        dept = db.query(Department).filter(Department.id == r.department_id).first() if r.department_id else None
        doc = db.query(Doctor).filter(Doctor.id == r.doctor_id).first() if r.doctor_id else None
        doc_user = db.query(User).filter(User.id == doc.user_id).first() if doc else None
        ai = db.query(AIAnalysis).filter(AIAnalysis.report_id == r.id).first()
        review = db.query(DoctorReview).filter(DoctorReview.report_id == r.id).first()
        ext = db.query(ReportExtraction).filter(ReportExtraction.report_id == r.id).first()

        result.append({
            "id": r.id,
            "report_source": r.report_source,
            "report_title": r.report_title,
            "report_type": r.report_type,
            "report_date": r.report_date.strftime("%Y-%m-%d") if r.report_date else "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            "department_name": dept.name if dept else "General",
            "doctor_name": doc_user.full_name if doc_user else "Hospital Medical Staff",
            "status": r.status,
            "original_filename": r.original_filename,
            "extracted_parameters": ext.extracted_json if ext and ext.extracted_json else {},
            "ai_analysis": {
                "model_name": ai.model_name,
                "prediction": ai.prediction,
                "probability": ai.probability,
                "risk_level": ai.risk_level,
                "important_factors": ai.important_factors,
                "explanation": ai.explanation
            } if ai else None,
            "doctor_review": review_projection(review, latest_revision(db, r.id) if review else None),
        })
    return result


@router.get("/{report_id}/review/revisions")
def get_report_review_revisions(report_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return read_review_revisions(db, current_user, report_id)


@router.post("/{report_id}/review/revisions")
def amend_report_review(report_id: int, payload: DoctorReviewAmendment,
                        db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return append_review_revision(db, current_user, report_id, payload)


@router.post("/{report_id}/review")
def review_report(report_id: int, review_data: DoctorReviewCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    doctor = active_clinician(db, current_user)
    if review_data.review_status not in {"APPROVED", "MODIFIED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Invalid clinical review status")
    report = db.query(MedicalReport).filter(MedicalReport.id == report_id).with_for_update().populate_existing().first()
    if not report:
        raise HTTPException(status_code=404, detail="Medical report not found")
    require_report_review(db, current_user, report, doctor)

    existing_review = db.query(DoctorReview).filter(DoctorReview.report_id == report_id).first()
    if existing_review:
        raise HTTPException(status_code=409, detail="This report already has a review; revisions require a separate workflow")
    new_review = DoctorReview(
        report_id=report_id,
        doctor_id=doctor.id,
        review_status=review_data.review_status,
        clinical_notes=review_data.clinical_notes,
        final_assessment=review_data.final_assessment
    )
    db.add(new_review)

    report.status = "DOCTOR_REVIEWED" if review_data.review_status == "APPROVED" else "FINALIZED"
    report.doctor_id = doctor.id

    # Mark any pending ReportReviewRequest as COMPLETED
    from src.models import ReportReviewRequest
    pending_reqs = db.query(ReportReviewRequest).filter(
        ReportReviewRequest.report_id == report_id,
        ReportReviewRequest.patient_id == report.patient_id,
        ReportReviewRequest.doctor_id == doctor.id,
        ReportReviewRequest.status.in_(("PENDING", "IN_REVIEW"))
    ).all()
    for pr in pending_reqs:
        pr.status = "COMPLETED"
        pr.completed_at = datetime.utcnow()

    # Notify patient
    notif = Notification(
        user_id=report.patient_id,
        title="Medical Report Reviewed by Doctor",
        message=f"Your report '{report.report_title}' has been reviewed and signed by Dr. {doctor.user.full_name}.",
        type="REPORT"
    )
    db.add(notif)
    db.add(AuditLog(user_id=current_user.user_id, action="medical_report_reviewed",
                    details={"report_id": report_id, "patient_id": report.patient_id, "doctor_id": doctor.id}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": "Doctor review finalized successfully"}


@router.post("/{report_id}/request-review")
def request_report_review(
    report_id: int, 
    data: Optional[RequestReportReviewModel] = None, 
    db: Session = Depends(get_db), 
    current_user = Depends(get_current_user)
):
    if current_user.role not in ('patient', 'user'):
        raise HTTPException(status_code=403, detail="Only patients may request review of their own reports")
    from src.clinical_chat.clinical_actions import create_report_review_request
    doc_id = data.doctor_id if data else None
    notes = data.notes if data else None
    res = create_report_review_request(db, current_user.user_id, report_id, doc_id, notes)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to submit report for review"))
    return res

