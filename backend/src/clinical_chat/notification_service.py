from typing import Optional, List
from sqlalchemy.orm import Session

from src.models import (
    Notification, ClinicalAlert, ClinicalConversation,
    Department, Doctor, User, DoctorDepartmentMembership
)

class ClinicalNotificationService:
    """
    Manages in-app clinical escalation alerts and notifications.
    Includes alert deduplication to prevent alert fatigue.
    """
    def trigger_clinical_alert_if_needed(
        self,
        db: Session,
        conversation: ClinicalConversation,
        urgency: str,
        reason: str
    ) -> Optional[ClinicalAlert]:
        """
        Creates a ClinicalAlert and sends notifications if urgency is HIGH_PRIORITY or EMERGENCY_REVIEW.
        Deduplicates against existing active alerts for the same conversation and urgency.
        """
        if urgency not in ["HIGH_PRIORITY", "EMERGENCY_REVIEW"]:
            return None

        dedupe_key = f"conv_{conversation.id}_{urgency}"

        # Check for active existing alert with same dedupe_key
        existing_alert = db.query(ClinicalAlert).filter(
            ClinicalAlert.conversation_id == conversation.id,
            ClinicalAlert.dedupe_key == dedupe_key,
            ClinicalAlert.status == "TRIGGERED"
        ).first()

        if existing_alert:
            # Active alert already exists; do not duplicate
            return existing_alert

        # Create new ClinicalAlert
        alert = ClinicalAlert(
            conversation_id=conversation.id,
            status="TRIGGERED",
            reason=reason,
            urgency=urgency,
            department_id=conversation.department_id,
            assigned_doctor_id=conversation.assigned_doctor_id,
            dedupe_key=dedupe_key
        )
        db.add(alert)
        db.flush()

        # Update conversation escalation status
        conversation.escalation_status = "PENDING_ACK"
        if conversation.status == "OPEN":
            conversation.status = "AWAITING_DOCTOR"

        # Dispatch notifications to authorized clinicians
        self._notify_clinicians_for_alert(db, conversation, alert)

        return alert

    def _notify_clinicians_for_alert(
        self,
        db: Session,
        conversation: ClinicalConversation,
        alert: ClinicalAlert
    ):
        recipient_user_ids = set()

        # 1. Assigned Doctor
        if conversation.assigned_doctor_id:
            doc = db.query(Doctor).filter(Doctor.id == conversation.assigned_doctor_id).first()
            if doc and doc.user_id:
                recipient_user_ids.add(doc.user_id)

        # 2. Department Responders & Leads
        if conversation.department_id:
            memberships = db.query(DoctorDepartmentMembership).filter(
                DoctorDepartmentMembership.department_id == conversation.department_id,
                DoctorDepartmentMembership.is_active == True,
                DoctorDepartmentMembership.role.in_(["RESPONDER", "LEAD"])
            ).all()
            from src.workforce_service import source_assignment_current
            for m in memberships:
                if not source_assignment_current(db, "DOCTOR", m.id):
                    continue
                doc = db.query(Doctor).filter(Doctor.id == m.doctor_id).first()
                if doc and doc.user_id:
                    recipient_user_ids.add(doc.user_id)

            dept = db.query(Department).filter(Department.id == conversation.department_id).first()
            if dept and dept.head_doctor_id:
                head_doc = db.query(Doctor).filter(Doctor.id == dept.head_doctor_id).first()
                if head_doc and head_doc.user_id:
                    recipient_user_ids.add(head_doc.user_id)

        # 3. If Emergency Review, notify all emergency doctors
        if alert.urgency == "EMERGENCY_REVIEW":
            emerg_users = db.query(User).filter(User.role == "emergency_doctor").all()
            for eu in emerg_users:
                recipient_user_ids.add(eu.id)

        # Department name for notice
        dept_name = "Emergency / Clinical Queue"
        if conversation.department_id:
            d = db.query(Department).filter(Department.id == conversation.department_id).first()
            if d:
                dept_name = d.name

        # Create persistent Notification entries
        title = f"🚨 Clinical Alert: {alert.urgency.replace('_', ' ')}"
        message = (
            f"Urgent clinical conversation #{conversation.id} flagged in {dept_name}. "
            f"Triage: {alert.reason[:80]}."
        )
        notif_type = "EMERGENCY" if alert.urgency == "EMERGENCY_REVIEW" else "ALERT"

        for uid in recipient_user_ids:
            db.add(Notification(
                user_id=uid,
                title=title,
                message=message,
                type=notif_type,
                is_read=False
            ))

    def notify_patient_of_doctor_reply(
        self,
        db: Session,
        conversation: ClinicalConversation,
        doctor_name: str
    ):
        """Notifies the patient that a licensed clinician has reviewed and replied to their conversation."""
        db.add(Notification(
            user_id=conversation.patient_id,
            title="Doctor Response Received",
            message=f"Dr. {doctor_name} has provided a clinical response to your consultation.",
            type="INFO",
            is_read=False
        ))

notification_service = ClinicalNotificationService()
