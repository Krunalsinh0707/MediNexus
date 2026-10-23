import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from fastapi import HTTPException
from src.encounter_service import refuse_linked_appointment_change

from src.models import (
    User, Doctor, Department, Appointment,
    MedicalReport, DoctorReview, ReportExtraction, AIAnalysis,
    ReportReviewRequest, Notification, PatientReport, CbcReport,
    ClinicalConversation
)
from src.clinical_chat.audit_service import audit_service

logger = logging.getLogger(__name__)

STANDARD_HOURLY_SLOTS = ["09:00 AM", "10:00 AM", "11:00 AM", "02:00 PM", "03:00 PM", "04:00 PM"]

DAY_NAME_MAP = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday"
}
DAY_SHORT_MAP = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun"
}


def _doctor_works_on_date(doctor: Doctor, target_date: date) -> bool:
    """
    Checks if doctor is active and works on target_date based on doctor.availability JSON.
    Default if no availability defined is Monday to Friday.
    """
    if doctor.status != "Active":
        return False

    avail = doctor.availability or {}
    weekday = target_date.weekday() # 0 = Monday, 6 = Sunday

    # If availability has explicit days
    days_val = avail.get("days")
    if isinstance(days_val, list):
        target_name = DAY_NAME_MAP.get(weekday, "").lower()
        target_short = DAY_SHORT_MAP.get(weekday, "").lower()
        return any(d.lower() in [target_name, target_short] for d in days_val)
    elif isinstance(days_val, str):
        days_str = days_val.lower()
        if "mon" in days_str and "fri" in days_str:
            return weekday < 5 # Monday-Friday
        if "mon" in days_str and "sat" in days_str:
            return weekday < 6 # Monday-Saturday
        if "all" in days_str or "everyday" in days_str or "7 days" in days_str:
            return True
        target_short = DAY_SHORT_MAP.get(weekday, "").lower()
        return target_short in days_str

    # Default to Monday through Friday
    return weekday < 5


def list_patient_reports(db: Session, patient_id: int) -> Dict[str, Any]:
    """
    Retrieves all medical reports owned by the authenticated patient.
    Enforces strict patient ownership.
    """
    try:
        reports = (
            db.query(MedicalReport)
            .filter(MedicalReport.patient_id == patient_id)
            .order_by(MedicalReport.report_date.desc(), MedicalReport.id.desc())
            .all()
        )

        formatted_reports = []
        for r in reports:
            doc = db.query(Doctor).filter(Doctor.id == r.doctor_id).first() if r.doctor_id else None
            doc_name = f"Dr. {doc.user.full_name}" if doc and doc.user else None
            dept = db.query(Department).filter(Department.id == r.department_id).first() if r.department_id else None
            dept_name = dept.name if dept else None

            review = db.query(DoctorReview).filter(DoctorReview.report_id == r.id).first()
            pending_review = db.query(ReportReviewRequest).filter(
                ReportReviewRequest.report_id == r.id,
                ReportReviewRequest.status == "PENDING"
            ).first()

            formatted_reports.append({
                "id": r.id,
                "title": r.report_title,
                "type": r.report_type or "Diagnostic Report",
                "date": r.report_date.strftime("%Y-%m-%d") if r.report_date else (r.created_at.strftime("%Y-%m-%d") if r.created_at else None),
                "status": r.status,
                "doctor_id": r.doctor_id,
                "doctor_name": doc_name,
                "department_id": r.department_id,
                "department_name": dept_name,
                "has_review": review is not None,
                "review_status": review.review_status if review else None,
                "is_pending_review": pending_review is not None
            })

        return {
            "success": True,
            "reports": formatted_reports,
            "count": len(formatted_reports)
        }
    except Exception as e:
        logger.error(f"Error listing reports for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "DATABASE_ERROR",
            "message": "Unable to retrieve patient reports at this time."
        }


def get_patient_report(db: Session, patient_id: int, report_id: int) -> Dict[str, Any]:
    """
    Retrieves full details of a specific report owned by the patient.
    Strictly verifies ownership: patient_id == report.patient_id.
    """
    try:
        report = db.query(MedicalReport).filter(MedicalReport.id == report_id).first()
        if not report:
            return {
                "success": False,
                "error": "NOT_FOUND",
                "message": "Report not found."
            }

        if report.patient_id != patient_id:
            logger.warning(f"Patient {patient_id} attempted unauthorized access to report {report_id}")
            return {
                "success": False,
                "error": "NOT_AUTHORIZED",
                "message": "You are not authorized to access this report."
            }

        doc = db.query(Doctor).filter(Doctor.id == report.doctor_id).first() if report.doctor_id else None
        doc_name = f"Dr. {doc.user.full_name}" if doc and doc.user else None
        dept = db.query(Department).filter(Department.id == report.department_id).first() if report.department_id else None

        ext = db.query(ReportExtraction).filter(ReportExtraction.report_id == report.id).first()
        ai = db.query(AIAnalysis).filter(AIAnalysis.report_id == report.id).first()
        review = db.query(DoctorReview).filter(DoctorReview.report_id == report.id).first()

        return {
            "success": True,
            "report": {
                "id": report.id,
                "title": report.report_title,
                "type": report.report_type,
                "date": report.report_date.strftime("%Y-%m-%d") if report.report_date else None,
                "status": report.status,
                "doctor_id": report.doctor_id,
                "doctor_name": doc_name,
                "department_id": report.department_id,
                "department_name": dept.name if dept else None,
                "extracted_parameters": ext.extracted_json if ext else {},
                "ai_summary": ai.explanation if ai else None,
                "ai_prediction": ai.prediction if ai else None,
                "ai_risk": ai.risk_level if ai else None,
                "doctor_notes": review.clinical_notes if review else None,
                "doctor_assessment": review.final_assessment if review else None,
                "reviewed_at": review.reviewed_at.strftime("%Y-%m-%d %H:%M") if review and review.reviewed_at else None
            }
        }
    except Exception as e:
        logger.error(f"Error fetching report {report_id} for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "DATABASE_ERROR",
            "message": "Unable to fetch report details."
        }


def get_latest_patient_report(db: Session, patient_id: int) -> Dict[str, Any]:
    """
    Finds the latest medical report for the authenticated patient.
    Checks MedicalReport first; if none, checks legacy CbcReport/PatientReport.
    """
    try:
        report = (
            db.query(MedicalReport)
            .filter(MedicalReport.patient_id == patient_id)
            .order_by(MedicalReport.report_date.desc(), MedicalReport.id.desc())
            .first()
        )
        if report:
            return get_patient_report(db, patient_id, report.id)

        # Fallback check for legacy CbcReport
        cbc = (
            db.query(CbcReport)
            .filter(CbcReport.user_id == patient_id)
            .order_by(CbcReport.created_at.desc())
            .first()
        )
        if cbc:
            return {
                "success": True,
                "report": {
                    "id": cbc.id,
                    "title": "Complete Blood Count (CBC) Report",
                    "type": "CBC Blood Test",
                    "date": cbc.created_at.strftime("%Y-%m-%d") if cbc.created_at else None,
                    "status": "COMPLETED",
                    "doctor_name": "Hospital Medical Staff",
                    "extracted_parameters": {
                        "hemoglobin": cbc.hemoglobin,
                        "wbc": cbc.wbc_count,
                        "rbc": cbc.rbc_count,
                        "platelets": cbc.platelet_count
                    }
                }
            }

        return {
            "success": True,
            "report": None,
            "message": "No medical reports found on file for your account."
        }
    except Exception as e:
        logger.error(f"Error getting latest report for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "DATABASE_ERROR",
            "message": "Unable to locate recent medical reports."
        }


def create_report_review_request(
    db: Session,
    patient_id: int,
    report_id: int,
    doctor_id: Optional[int] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initiates a formal report review request from the patient to a designated doctor.
    - Validates ownership of the report.
    - Validates target doctor exists, is Active, and is authorized.
    - Prevents duplicate pending review requests.
    - Creates ReportReviewRequest record.
    - Notifies the doctor in-app.
    """
    try:
        # 1. Validate report ownership
        report = db.query(MedicalReport).filter(MedicalReport.id == report_id).with_for_update().populate_existing().first()
        if not report:
            return {
                "success": False,
                "error": "REPORT_NOT_FOUND",
                "message": f"Medical report #{report_id} was not found."
            }

        if report.patient_id != patient_id:
            logger.warning(f"Patient {patient_id} tried to request review for report {report_id} owned by {report.patient_id}")
            return {
                "success": False,
                "error": "NOT_AUTHORIZED",
                "message": "You can only submit reports that belong to your account."
            }

        if db.query(DoctorReview.id).filter(DoctorReview.report_id == report.id).first():
            return {
                "success": False,
                "error": "ALREADY_REVIEWED",
                "message": "This report already has a signed review; revisions need a separate clinical workflow."
            }

        # 2. Determine target doctor
        target_doctor_id = doctor_id or report.doctor_id
        if not target_doctor_id:
            # Cannot route silently: require doctor assignment or patient selection
            return {
                "success": False,
                "error": "NO_DOCTOR_ASSIGNED",
                "message": "This report does not have an assigned physician. Please select a doctor or department to route your review request."
            }

        doctor = db.query(Doctor).join(User, User.id == Doctor.user_id).filter(
            Doctor.id == target_doctor_id, Doctor.status == "Active",
            User.role.in_(("doctor", "emergency_doctor")), User.password_hash.is_not(None),
        ).first()
        if not doctor:
            return {
                "success": False,
                "error": "DOCTOR_UNAVAILABLE",
                "message": "The requested physician must have an active profile and account."
            }

        # 3. Check for existing pending review request
        existing_req = db.query(ReportReviewRequest).filter(
            ReportReviewRequest.report_id == report.id,
            ReportReviewRequest.status.in_(("PENDING", "IN_REVIEW"))
        ).first()

        if existing_req:
            return {
                "success": True,
                "already_pending": True,
                "request_id": existing_req.id,
                "message": f"Report '{report.report_title}' already has an active review request."
            }

        # 4. Create new ReportReviewRequest
        new_req = ReportReviewRequest(
            report_id=report.id,
            patient_id=patient_id,
            doctor_id=doctor.id,
            status="PENDING",
            notes=notes
        )
        db.add(new_req)

        # Update report assigned doctor if not already set
        if not report.doctor_id:
            report.doctor_id = doctor.id
        if not report.department_id and doctor.department_id:
            report.department_id = doctor.department_id

        patient = db.query(User).filter(User.id == patient_id).first()
        patient_name = patient.full_name if patient else "A patient"

        # 5. Create notification for doctor
        notif = Notification(
            user_id=doctor.user_id,
            title="New Report Review Request",
            message=f"{patient_name} submitted report '{report.report_title}' for clinical review.",
            type="REPORT"
        )
        db.add(notif)
        db.commit()
        db.refresh(new_req)

        doc_name = f"Dr. {doctor.user.full_name}" if doctor.user else "your physician"
        return {
            "success": True,
            "request_id": new_req.id,
            "report_id": report.id,
            "report_title": report.report_title,
            "doctor_id": doctor.id,
            "doctor_name": doc_name,
            "status": "PENDING",
            "message": f"Report '{report.report_title}' has been successfully submitted to {doc_name} for clinical review."
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting report {report_id} for review: {e}", exc_info=True)
        return {
            "success": False,
            "error": "SUBMISSION_FAILED",
            "message": "We encountered an error submitting your report for review. Please try again."
        }


def list_patient_appointments(db: Session, patient_id: int) -> Dict[str, Any]:
    """
    Retrieves all appointments for the authenticated patient with real doctor/department names.
    """
    try:
        appointments = (
            db.query(Appointment)
            .filter(Appointment.patient_id == patient_id)
            .order_by(Appointment.appointment_date.asc(), Appointment.id.asc())
            .all()
        )

        results = []
        for app in appointments:
            doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
            doc_name = f"Dr. {doc.user.full_name}" if doc and doc.user else "Physician"
            dept = db.query(Department).filter(Department.id == app.department_id).first()
            dept_name = dept.name if dept else (doc.department.name if doc and doc.department else "General")

            results.append({
                "id": app.id,
                "doctor_id": app.doctor_id,
                "doctor_name": doc_name,
                "specialization": doc.specialization if doc else "",
                "department_name": dept_name,
                "appointment_date": app.appointment_date.strftime("%Y-%m-%d"),
                "time_slot": app.time_slot,
                "status": app.status,
                "reason": app.reason,
                "is_upcoming": app.status in ["REQUESTED", "CONFIRMED"] and app.appointment_date.date() >= date.today()
            })

        return {
            "success": True,
            "appointments": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Error listing appointments for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "DATABASE_ERROR",
            "message": "Unable to retrieve your appointments at this time."
        }


def check_appointment_availability(
    db: Session,
    doctor_id: int,
    target_date: date
) -> Dict[str, Any]:
    """
    Calculates actual appointment slot availability for a specific doctor on target_date.
    Checks:
    - Doctor exists and is Active
    - Day of week matches doctor.availability
    - Queries real booked appointments on target_date (REQUESTED or CONFIRMED)
    - Removes booked slots from standard available slots
    """
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            return {
                "success": False,
                "error": "DOCTOR_NOT_FOUND",
                "message": "Doctor not found."
            }

        doc_name = f"Dr. {doctor.user.full_name}" if doctor.user else "Doctor"

        if doctor.status != "Active":
            return {
                "success": True,
                "doctor_id": doctor.id,
                "doctor_name": doc_name,
                "date": target_date.strftime("%Y-%m-%d"),
                "is_working_day": False,
                "available_slots": [],
                "message": f"{doc_name} is currently not taking appointments (status: {doctor.status})."
            }

        # Check if doctor works on this date
        if not _doctor_works_on_date(doctor, target_date):
            weekday_name = DAY_NAME_MAP.get(target_date.weekday(), "")
            return {
                "success": True,
                "doctor_id": doctor.id,
                "doctor_name": doc_name,
                "date": target_date.strftime("%Y-%m-%d"),
                "is_working_day": False,
                "available_slots": [],
                "message": f"{doc_name} does not have clinic hours on {weekday_name}s."
            }

        # Candidate slots for the doctor
        avail = doctor.availability or {}
        custom_slots = avail.get("slots")
        candidate_slots = custom_slots if isinstance(custom_slots, list) and custom_slots else list(STANDARD_HOURLY_SLOTS)

        # Query booked appointments on this target_date for this doctor
        start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
        end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

        booked_appointments = (
            db.query(Appointment.time_slot)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date >= start_of_day,
                Appointment.appointment_date <= end_of_day,
                Appointment.status.in_(["REQUESTED", "CONFIRMED"])
            )
            .all()
        )
        booked_slots = {b[0].strip().upper() for b in booked_appointments if b[0]}

        available_slots = [s for s in candidate_slots if s.strip().upper() not in booked_slots]

        return {
            "success": True,
            "doctor_id": doctor.id,
            "doctor_name": doc_name,
            "date": target_date.strftime("%Y-%m-%d"),
            "is_working_day": True,
            "available_slots": available_slots,
            "booked_slots_count": len(booked_slots),
            "message": f"Found {len(available_slots)} available slots for {doc_name} on {target_date.strftime('%Y-%m-%d')}."
        }
    except Exception as e:
        logger.error(f"Error checking availability for doctor {doctor_id} on {target_date}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "SERVICE_FAILURE",
            "message": "Appointment availability service is currently unavailable. Please try again."
        }


def create_appointment_request(
    db: Session,
    patient_id: int,
    doctor_id: int,
    appointment_date: date,
    time_slot: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates an appointment request for the authenticated patient after verifying real slot availability.
    """
    try:
        # 1. Verify doctor
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor or doctor.status != "Active":
            return {
                "success": False,
                "error": "DOCTOR_UNAVAILABLE",
                "message": "The selected doctor is currently unavailable."
            }

        # 2. Check slot availability
        avail_res = check_appointment_availability(db, doctor_id, appointment_date)
        if not avail_res.get("success"):
            return {
                "success": False,
                "error": "AVAILABILITY_CHECK_FAILED",
                "message": avail_res.get("message", "Unable to verify slot availability.")
            }

        available_slots = avail_res.get("available_slots", [])
        clean_slot = time_slot.strip().upper()
        matching_slot = next((s for s in available_slots if s.strip().upper() == clean_slot), None)

        if not matching_slot:
            return {
                "success": False,
                "error": "SLOT_UNAVAILABLE",
                "message": f"The slot '{time_slot}' on {appointment_date.strftime('%Y-%m-%d')} is no longer available. Available slots: {', '.join(available_slots) if available_slots else 'None'}."
            }

        # 3. Create appointment
        dt = datetime(appointment_date.year, appointment_date.month, appointment_date.day, 9, 0, 0)
        new_app = Appointment(
            patient_id=patient_id,
            doctor_id=doctor.id,
            department_id=doctor.department_id,
            appointment_date=dt,
            time_slot=matching_slot,
            reason=reason or "Consultation booked via HealthBot",
            status="REQUESTED"
        )
        db.add(new_app)

        # 4. Notify doctor
        patient = db.query(User).filter(User.id == patient_id).first()
        patient_name = patient.full_name if patient else "A patient"
        doc_name = f"Dr. {doctor.user.full_name}" if doctor.user else "Physician"

        notif = Notification(
            user_id=doctor.user_id,
            title="New Appointment Request",
            message=f"{patient_name} requested an appointment on {appointment_date.strftime('%Y-%m-%d')} at {matching_slot}.",
            type="APPOINTMENT"
        )
        db.add(notif)
        db.commit()
        db.refresh(new_app)

        return {
            "success": True,
            "appointment_id": new_app.id,
            "doctor_id": doctor.id,
            "doctor_name": doc_name,
            "date": appointment_date.strftime("%Y-%m-%d"),
            "time_slot": matching_slot,
            "status": "REQUESTED",
            "message": f"Appointment request successfully created with {doc_name} for {appointment_date.strftime('%Y-%m-%d')} at {matching_slot}."
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error booking appointment for patient {patient_id} with doctor {doctor_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "BOOKING_FAILED",
            "message": "Appointment booking service failed. Your appointment could not be scheduled."
        }


def cancel_patient_appointment(
    db: Session,
    patient_id: int,
    appointment_id: int
) -> Dict[str, Any]:
    """
    Cancels an appointment owned by the authenticated patient.
    Strictly verifies patient ownership and status transition rules.
    """
    try:
        app = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().populate_existing().first()
        if not app:
            return {
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Appointment #{appointment_id} not found."
            }

        if app.patient_id != patient_id:
            logger.warning(f"Patient {patient_id} attempted to cancel appointment {appointment_id} owned by {app.patient_id}")
            return {
                "success": False,
                "error": "NOT_AUTHORIZED",
                "message": "You are not authorized to cancel this appointment."
            }

        if app.status == "CANCELLED":
            return {
                "success": True,
                "already_cancelled": True,
                "appointment_id": app.id,
                "message": f"Appointment #{app.id} is already cancelled."
            }

        if app.status in ["COMPLETED", "REJECTED"]:
            return {
                "success": False,
                "error": "INVALID_STATE",
                "message": f"Cannot cancel an appointment that is already {app.status.lower()}."
            }

        refuse_linked_appointment_change(db, app.id)
        app.status = "CANCELLED"

        # Notify doctor
        doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
        if doc and doc.user_id:
            patient = db.query(User).filter(User.id == patient_id).first()
            patient_name = patient.full_name if patient else "A patient"
            notif = Notification(
                user_id=doc.user_id,
                title="Appointment Cancelled",
                message=f"{patient_name} has cancelled the appointment scheduled for {app.appointment_date.strftime('%Y-%m-%d')} ({app.time_slot}).",
                type="APPOINTMENT"
            )
            db.add(notif)

        db.commit()
        return {
            "success": True,
            "appointment_id": app.id,
            "status": "CANCELLED",
            "message": f"Your appointment #{app.id} on {app.appointment_date.strftime('%Y-%m-%d')} at {app.time_slot} has been successfully cancelled."
        }
    except HTTPException as exc:
        db.rollback()
        return {"success": False, "error": "VISIT_WORKFLOW_REQUIRED", "message": exc.detail}
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling appointment {appointment_id} for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "CANCELLATION_FAILED",
            "message": "Unable to cancel the appointment at this time. Please try again."
        }


def reschedule_patient_appointment(
    db: Session,
    patient_id: int,
    appointment_id: int,
    new_date: date,
    new_slot: str
) -> Dict[str, Any]:
    """
    Reschedules an existing appointment owned by the authenticated patient.
    Verifies ownership, status, and new slot availability before committing.
    """
    try:
        app = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().populate_existing().first()
        if not app:
            return {
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Appointment #{appointment_id} not found."
            }

        if app.patient_id != patient_id:
            return {
                "success": False,
                "error": "NOT_AUTHORIZED",
                "message": "You are not authorized to reschedule this appointment."
            }

        if app.status in ["CANCELLED", "COMPLETED", "REJECTED"]:
            return {
                "success": False,
                "error": "INVALID_STATE",
                "message": f"Cannot reschedule an appointment that is {app.status.lower()}."
            }

        refuse_linked_appointment_change(db, app.id)
        # Check new slot availability
        avail_res = check_appointment_availability(db, app.doctor_id, new_date)
        if not avail_res.get("success"):
            return {
                "success": False,
                "error": "AVAILABILITY_CHECK_FAILED",
                "message": "Could not verify availability for the requested new date."
            }

        available_slots = avail_res.get("available_slots", [])
        clean_slot = new_slot.strip().upper()
        matching_slot = next((s for s in available_slots if s.strip().upper() == clean_slot), None)

        if not matching_slot:
            return {
                "success": False,
                "error": "SLOT_UNAVAILABLE",
                "message": f"Slot '{new_slot}' is not available on {new_date.strftime('%Y-%m-%d')}."
            }

        old_date_str = app.appointment_date.strftime("%Y-%m-%d")
        old_slot_str = app.time_slot

        app.appointment_date = datetime(new_date.year, new_date.month, new_date.day, 9, 0, 0)
        app.time_slot = matching_slot
        app.status = "REQUESTED"

        doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
        if doc and doc.user_id:
            patient = db.query(User).filter(User.id == patient_id).first()
            patient_name = patient.full_name if patient else "A patient"
            notif = Notification(
                user_id=doc.user_id,
                title="Appointment Rescheduled",
                message=f"{patient_name} rescheduled their appointment from {old_date_str} ({old_slot_str}) to {new_date.strftime('%Y-%m-%d')} ({matching_slot}).",
                type="APPOINTMENT"
            )
            db.add(notif)

        db.commit()
        doc_name = f"Dr. {doc.user.full_name}" if doc and doc.user else "Physician"
        return {
            "success": True,
            "appointment_id": app.id,
            "doctor_name": doc_name,
            "new_date": new_date.strftime("%Y-%m-%d"),
            "new_time_slot": matching_slot,
            "message": f"Appointment #{app.id} successfully rescheduled to {new_date.strftime('%Y-%m-%d')} at {matching_slot} with {doc_name}."
        }
    except HTTPException as exc:
        db.rollback()
        return {"success": False, "error": "VISIT_WORKFLOW_REQUIRED", "message": exc.detail}
    except Exception as e:
        db.rollback()
        logger.error(f"Error rescheduling appointment {appointment_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "RESCHEDULE_FAILED",
            "message": "Appointment rescheduling failed. Please try again."
        }


def get_doctor_and_department_info(
    db: Session,
    doctor_name: Optional[str] = None,
    specialization: Optional[str] = None,
    department_name: Optional[str] = None,
    department_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Queries real doctor and department records.
    Never uses mock data or fabricated associations.
    """
    try:
        # If department query
        if department_name is not None or department_id is not None:
            dept_query = db.query(Department)
            if department_id:
                dept_query = dept_query.filter(Department.id == department_id)
            elif department_name:
                dept_query = dept_query.filter(Department.name.ilike(f"%{department_name}%"))

            departments = dept_query.all()
            dept_results = []
            for d in departments:
                doc_count = db.query(Doctor).filter(Doctor.department_id == d.id, Doctor.status == "Active").count()
                dept_results.append({
                    "id": d.id,
                    "name": d.name,
                    "code": d.code,
                    "description": d.description,
                    "active_doctors_count": doc_count
                })

            return {
                "success": True,
                "type": "departments",
                "departments": dept_results,
                "count": len(dept_results)
            }

        # If doctor query
        doc_query = db.query(Doctor).filter(Doctor.status == "Active")
        if doctor_name:
            clean_name = doctor_name.lower().replace("dr.", "").replace("dr", "").strip()
            doc_query = doc_query.join(User, Doctor.user_id == User.id).filter(User.full_name.ilike(f"%{clean_name}%"))
        if specialization:
            doc_query = doc_query.filter(Doctor.specialization.ilike(f"%{specialization}%"))

        doctors = doc_query.all()
        doc_results = []
        for doc in doctors:
            dept = db.query(Department).filter(Department.id == doc.department_id).first()
            doc_results.append({
                "id": doc.id,
                "name": f"Dr. {doc.user.full_name}" if doc.user else "Physician",
                "specialization": doc.specialization,
                "department_name": dept.name if dept else "General",
                "department_id": doc.department_id,
                "experience_years": doc.experience_years,
                "qualification": doc.qualification
            })

        return {
            "success": True,
            "type": "doctors",
            "doctors": doc_results,
            "count": len(doc_results)
        }
    except Exception as e:
        logger.error(f"Error querying doctors/departments: {e}", exc_info=True)
        return {
            "success": False,
            "error": "QUERY_ERROR",
            "message": "Unable to retrieve doctor or department information."
        }


def get_patient_doctor_relationship(db: Session, patient_id: int) -> Dict[str, Any]:
    """
    Resolves the patient's assigned or primary physician only from verified database records:
    1. Assigned doctor in ClinicalConversation
    2. Attending doctor from recent MedicalReport
    3. Doctor from recent Appointment
    Returns None if no verified relationship exists.
    """
    try:
        # Check active clinical conversations
        conv = (
            db.query(ClinicalConversation)
            .filter(
                ClinicalConversation.patient_id == patient_id,
                ClinicalConversation.assigned_doctor_id.isnot(None)
            )
            .order_by(ClinicalConversation.updated_at.desc())
            .first()
        )
        if conv and conv.assigned_doctor:
            doc = conv.assigned_doctor
            dept = db.query(Department).filter(Department.id == doc.department_id).first()
            return {
                "success": True,
                "has_relationship": True,
                "doctor": {
                    "id": doc.id,
                    "name": f"Dr. {doc.user.full_name}" if doc.user else "Doctor",
                    "specialization": doc.specialization,
                    "department_name": dept.name if dept else "General",
                    "source": "Consultation Assignment"
                }
            }

        # Check recent medical reports
        report = (
            db.query(MedicalReport)
            .filter(
                MedicalReport.patient_id == patient_id,
                MedicalReport.doctor_id.isnot(None)
            )
            .order_by(MedicalReport.created_at.desc())
            .first()
        )
        if report and report.doctor_id:
            doc = db.query(Doctor).filter(Doctor.id == report.doctor_id).first()
            if doc:
                dept = db.query(Department).filter(Department.id == doc.department_id).first()
                return {
                    "success": True,
                    "has_relationship": True,
                    "doctor": {
                        "id": doc.id,
                        "name": f"Dr. {doc.user.full_name}" if doc.user else "Doctor",
                        "specialization": doc.specialization,
                        "department_name": dept.name if dept else "General",
                        "source": "Medical Report Reviewer"
                    }
                }

        # Check recent appointments
        app = (
            db.query(Appointment)
            .filter(Appointment.patient_id == patient_id)
            .order_by(Appointment.appointment_date.desc())
            .first()
        )
        if app and app.doctor_id:
            doc = db.query(Doctor).filter(Doctor.id == app.doctor_id).first()
            if doc:
                dept = db.query(Department).filter(Department.id == doc.department_id).first()
                return {
                    "success": True,
                    "has_relationship": True,
                    "doctor": {
                        "id": doc.id,
                        "name": f"Dr. {doc.user.full_name}" if doc.user else "Doctor",
                        "specialization": doc.specialization,
                        "department_name": dept.name if dept else "General",
                        "source": "Appointment History"
                    }
                }

        return {
            "success": True,
            "has_relationship": False,
            "doctor": None,
            "message": "You currently do not have an assigned primary physician on file."
        }
    except Exception as e:
        logger.error(f"Error determining doctor relationship for patient {patient_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "LOOKUP_FAILED",
            "message": "Unable to check assigned physician records."
        }
