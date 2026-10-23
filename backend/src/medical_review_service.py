"""Read and append signed medical-review amendments without editing originals."""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.clinical_write_access import active_clinician, require_report_review
from src.models import AuditLog, DoctorReview, MedicalReport, MedicalReviewRevision, Notification
from src.patient_access import require_clinical_history


REVIEW_STATUSES = {"APPROVED", "MODIFIED", "REJECTED"}


def latest_revision(db, report_id):
    return db.query(MedicalReviewRevision).filter(
        MedicalReviewRevision.report_id == report_id,
    ).order_by(MedicalReviewRevision.revision_number.desc()).first()


def review_projection(original, latest=None):
    """Preserve existing review keys while making the newest signed text visible."""
    if original is None:
        return None
    current = latest or original
    return {
        "id": current.id,
        "original_review_id": original.id,
        "revision_number": latest.revision_number if latest else 1,
        "review_status": current.review_status,
        "clinical_notes": current.clinical_notes,
        "final_assessment": current.final_assessment,
        "corrected_parameters": latest.corrected_parameters if latest else None,
        "reviewed_at": (current.signed_at if latest else original.reviewed_at).strftime("%Y-%m-%d %H:%M")
                       if (current.signed_at if latest else original.reviewed_at) else "",
        "doctor_id": current.author_doctor_id if latest else original.doctor_id,
    }


def read_review_revisions(db, actor, report_id):
    report = db.get(MedicalReport, report_id)
    if report is None:
        raise HTTPException(404, "Medical report not found")
    require_clinical_history(db, actor, report.patient_id)
    original = db.query(DoctorReview).filter(DoctorReview.report_id == report_id).first()
    if original is None:
        raise HTTPException(404, "Signed review not found")
    amendments = db.query(MedicalReviewRevision).filter(
        MedicalReviewRevision.report_id == report_id,
    ).order_by(MedicalReviewRevision.revision_number.asc()).all()
    rows = [{
        "id": original.id, "original_review_id": original.id, "revision_number": 1,
        "previous_revision_id": None, "doctor_id": original.doctor_id,
        "review_status": original.review_status, "clinical_notes": original.clinical_notes,
        "final_assessment": original.final_assessment, "corrected_parameters": None,
        "amendment_reason": None, "signed_at": original.reviewed_at,
        "created_at": original.reviewed_at,
    }]
    rows.extend({
        "id": row.id, "original_review_id": row.original_review_id,
        "revision_number": row.revision_number, "previous_revision_id": row.previous_revision_id,
        "doctor_id": row.author_doctor_id, "review_status": row.review_status,
        "clinical_notes": row.clinical_notes, "final_assessment": row.final_assessment,
        "corrected_parameters": row.corrected_parameters,
        "amendment_reason": row.amendment_reason, "signed_at": row.signed_at,
        "created_at": row.created_at,
    } for row in amendments)
    return rows


def append_review_revision(db, actor, report_id, payload):
    doctor = active_clinician(db, actor)
    reason = (payload.amendment_reason or "").strip()
    if not reason:
        raise HTTPException(422, "An amendment reason is required")
    if payload.review_status not in REVIEW_STATUSES:
        raise HTTPException(422, "Invalid review status")

    # Serializes writers for this report. A stale expected number returns 409;
    # database uniqueness protects direct writers and unexpected races.
    report = db.query(MedicalReport).filter(MedicalReport.id == report_id).with_for_update().populate_existing().first()
    if report is None:
        raise HTTPException(404, "Medical report not found")
    original = db.query(DoctorReview).filter(DoctorReview.report_id == report_id).first()
    if original is None:
        raise HTTPException(409, "The report has no signed review to amend")
    if doctor.id != original.doctor_id:
        require_report_review(db, actor, report, doctor)

    previous = latest_revision(db, report_id)
    current_number = previous.revision_number if previous else 1
    if payload.expected_revision_number != current_number:
        raise HTTPException(409, "The signed review changed; reload its revisions before amending")
    row = MedicalReviewRevision(
        report_id=report_id, original_review_id=original.id,
        revision_number=current_number + 1,
        previous_revision_id=previous.id if previous else None,
        author_user_id=actor.user_id, author_doctor_id=doctor.id,
        review_status=payload.review_status, clinical_notes=payload.clinical_notes,
        final_assessment=payload.final_assessment,
        corrected_parameters=payload.corrected_parameters, amendment_reason=reason,
    )
    db.add(row)
    db.add(Notification(user_id=report.patient_id, title="Medical report review amended",
                        message="A clinician signed an amendment to your medical report review.", type="REPORT"))
    db.add(AuditLog(user_id=actor.user_id, action="medical_report_review_amended",
                    details={"report_id": report_id, "original_review_id": original.id,
                             "revision_number": current_number + 1, "doctor_id": doctor.id,
                             "previous_revision_id": row.previous_revision_id}))
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A review amendment was signed concurrently; reload before retrying") from exc
    except Exception:
        db.rollback()
        raise
    return {
        "id": row.id, "report_id": report_id, "original_review_id": original.id,
        "revision_number": row.revision_number, "previous_revision_id": row.previous_revision_id,
        "doctor_id": doctor.id, "signed_at": row.signed_at,
        "created_at": row.created_at,
    }
