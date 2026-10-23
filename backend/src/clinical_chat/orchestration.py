from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from src.models import (
    ClinicalConversation, ClinicalMessage, ClinicalAssignment,
    ClinicalAlert, ClinicalAIAnalysis, ClinicalEvent,
    Department, Doctor, User
)
from src.clinical_chat.classification import classifier
from src.clinical_chat.routing import clinical_router
from src.clinical_chat.notification_service import notification_service
from src.clinical_chat.audit_service import audit_service
from src.clinical_chat.llm_service import llm_service
from src.clinical_chat.intent_service import intent_service
import logging

logger = logging.getLogger(__name__)

class ClinicalChatOrchestrator:
    """
    Central clinical workflow orchestrator.
    Executes message intake, deterministic triage classification, department routing,
    alert creation, bounded AI response generation, and audit logging in a strict sequence.
    """

    def create_conversation(
        self,
        db: Session,
        patient_id: int,
        title: Optional[str] = None,
        initial_message: Optional[str] = None
    ) -> ClinicalConversation:
        """
        Creates a new clinical consultation thread for an authenticated patient.
        """
        conv = ClinicalConversation(
            patient_id=patient_id,
            title=title or "Clinical Consultation",
            status="OPEN",
            urgency="NORMAL",
            escalation_status="NONE"
        )
        db.add(conv)
        db.flush()

        audit_service.log_event(
            db=db,
            conversation_id=conv.id,
            event_type="CONVERSATION_CREATED",
            actor_user_id=patient_id,
            state_before=None,
            state_after={"status": "OPEN", "urgency": "NORMAL"},
            reason="Patient initiated clinical consultation"
        )

        if initial_message and initial_message.strip():
            self.process_patient_message(
                db=db,
                conversation=conv,
                patient_id=patient_id,
                message_text=initial_message.strip()
            )
        else:
            welcome_msg = ClinicalMessage(
                conversation_id=conv.id,
                sender_type="assistant",
                sender_user_id=None,
                body="Hello! I'm HealthBot. How can I help you today?"
            )
            db.add(welcome_msg)

        db.commit()
        db.refresh(conv)
        return conv

    def process_patient_message(
        self,
        db: Session,
        conversation: ClinicalConversation,
        patient_id: int,
        message_text: str
    ) -> Dict[str, Any]:
        """
        Processes an incoming patient message with deterministic safety classification and routing.
        """
        if len(message_text) > 4000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message length exceeds maximum allowable limit of 4000 characters."
            )

        # 1. Persist the patient message immediately
        patient_msg = ClinicalMessage(
            conversation_id=conversation.id,
            sender_type="patient",
            sender_user_id=patient_id,
            body=message_text
        )
        db.add(patient_msg)
        db.flush()

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="MESSAGE_SENT_PATIENT",
            actor_user_id=patient_id,
            reason="Patient submitted message"
        )

        # Update title if it's default
        if conversation.title in ["Clinical Conversation", "Clinical Consultation", "New Health Conversation"]:
            conversation.title = message_text[:40] + ("..." if len(message_text) > 40 else "")

        # 2. Run deterministic clinical triage classifier
        classification = classifier.classify(message_text)
        new_urgency = classification["urgency"]
        category = classification["category"]
        evidence_codes = classification["evidence_codes"]
        emergency_notice = classification["emergency_notice"]

        # Track previous state
        state_before = {
            "urgency": conversation.urgency,
            "department_id": conversation.department_id,
            "assigned_doctor_id": conversation.assigned_doctor_id,
            "status": conversation.status,
            "escalation_status": conversation.escalation_status
        }

        # 3. Determine if urgency needs escalation (cannot be silently downgraded by a single normal message)
        urgency_rank = {
            "NORMAL": 1,
            "LOW_PRIORITY": 2,
            "MODERATE": 3,
            "HIGH_PRIORITY": 4,
            "EMERGENCY_REVIEW": 5
        }
        current_rank = urgency_rank.get(conversation.urgency, 1)
        new_rank = urgency_rank.get(new_urgency, 1)

        effective_urgency = new_urgency if new_rank > current_rank else conversation.urgency
        conversation.urgency = effective_urgency

        # 4. Department routing and clinician assignment
        department_id, assigned_doctor_id, rule_version = clinical_router.route_conversation(
            db=db,
            urgency=effective_urgency,
            category=category,
            evidence_codes=evidence_codes
        )
        if not conversation.department_id:
            conversation.department_id = department_id
        if not conversation.assigned_doctor_id and assigned_doctor_id:
            conversation.assigned_doctor_id = assigned_doctor_id

        # 5. Persist AI / Rule Analysis record
        ai_analysis = ClinicalAIAnalysis(
            conversation_id=conversation.id,
            message_id=patient_msg.id,
            category=category,
            confidence=classification["confidence"],
            evidence_codes=evidence_codes,
            model_rule_version=classification["model_rule_version"],
            human_review_required=classification["human_review_required"]
        )
        db.add(ai_analysis)
        db.flush()

        # 6. Trigger alert & notifications if urgent or emergency
        if effective_urgency in ["HIGH_PRIORITY", "EMERGENCY_REVIEW"]:
            alert_reason = f"{category}: {', '.join(evidence_codes)}"
            alert = notification_service.trigger_clinical_alert_if_needed(
                db=db,
                conversation=conversation,
                urgency=effective_urgency,
                reason=alert_reason
            )
            audit_service.log_event(
                db=db,
                conversation_id=conversation.id,
                event_type="ALERT_TRIGGERED",
                actor_user_id=None,
                state_before=state_before,
                state_after={"urgency": effective_urgency, "escalation_status": conversation.escalation_status},
                reason=alert_reason
            )

        state_after = {
            "urgency": conversation.urgency,
            "department_id": conversation.department_id,
            "assigned_doctor_id": conversation.assigned_doctor_id,
            "status": conversation.status,
            "escalation_status": conversation.escalation_status
        }
        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="URGENCY_CLASSIFIED",
            actor_user_id=None,
            state_before=state_before,
            state_after=state_after,
            reason=f"Classification: {effective_urgency}, category: {category}"
        )

        # 7. Retrieve recent conversation history
        history_msgs = (
            db.query(ClinicalMessage)
            .filter(ClinicalMessage.conversation_id == conversation.id)
            .order_by(ClinicalMessage.created_at.asc())
            .limit(10)
            .all()
        )
        conv_history = [{"sender": m.sender_type, "body": m.body} for m in history_msgs]

        # 8. Generate bounded Assistant response via Structured Intent Understanding or LLM
        assistant_text = None
        intent_result = None
        try:
            intent_result = intent_service.process_intent_structured(
                db=db,
                patient_id=patient_id,
                message_text=message_text,
                conv_history=conv_history,
                conversation=conversation
            )

            # Audit event for intent and workflow state
            if intent_result.is_ambiguous:
                audit_service.log_event(
                    db=db,
                    conversation_id=conversation.id,
                    event_type="CLARIFICATION_REQUESTED",
                    actor_user_id=patient_id,
                    reason=f"Ambiguous intent: {intent_result.intent}"
                )
            elif intent_result.intent != "UNKNOWN":
                audit_service.log_event(
                    db=db,
                    conversation_id=conversation.id,
                    event_type=f"INTENT_{intent_result.intent}",
                    actor_user_id=patient_id,
                    reason=f"Structured intent executed: {intent_result.intent}"
                )

            if intent_result.intent != "UNKNOWN" or intent_result.is_ambiguous:
                if emergency_notice:
                    assistant_text = f"{emergency_notice}\n\n---\n\n{intent_result.response_text}"
                else:
                    assistant_text = intent_result.response_text
            else:
                # Informational fallback via bounded LLM service (NO RAG or patient medical context dump)
                assistant_text = llm_service.generate_patient_reply(
                    user_message=message_text,
                    urgency=effective_urgency,
                    category=category,
                    conversation_history=conv_history,
                    rag_chunks=None,
                    emergency_notice=emergency_notice
                )
        except Exception as e:
            logger.error(f"[ERROR] Chatbot backend error processing message: {e}", exc_info=True)
            print(f"[ERROR] Chatbot processing exception: {e}")
            assistant_text = "I'm having trouble processing that request right now. Please try again."

        if not assistant_text:
            assistant_text = "I'm having trouble processing that request right now. Please try again."

        assistant_msg = ClinicalMessage(
            conversation_id=conversation.id,
            sender_type="assistant",
            sender_user_id=None,
            body=assistant_text
        )
        db.add(assistant_msg)
        conversation.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(conversation)

        return {
            "conversation_id": conversation.id,
            "status": conversation.status,
            "urgency": conversation.urgency,
            "escalation_status": conversation.escalation_status,
            "patient_message": {
                "id": patient_msg.id,
                "body": patient_msg.body,
                "created_at": patient_msg.created_at.isoformat() if patient_msg.created_at else None
            },
            "assistant_message": {
                "id": assistant_msg.id,
                "body": assistant_msg.body,
                "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None
            },
            "intent": intent_result.intent if intent_result else "UNKNOWN",
            "workflow_state": conversation.workflow_state,
            "clarification_options": intent_result.clarification_options if intent_result else None,
            "action_result": intent_result.action_result if intent_result else None
        }

    def process_doctor_reply(
        self,
        db: Session,
        conversation: ClinicalConversation,
        doctor_user_id: int,
        message_text: str
    ) -> ClinicalMessage:
        """
        Records a doctor's clinical response to a consultation.
        """
        if len(message_text) > 4000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message length exceeds maximum allowable limit of 4000 characters."
            )

        doctor = db.query(Doctor).filter(Doctor.user_id == doctor_user_id, Doctor.status == "Active").first()
        if (doctor is None or doctor.user is None or not doctor.user.password_hash
                or doctor.user.role not in {"doctor", "emergency_doctor"}):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active clinician profile required")
        doctor_name = doctor.user.full_name

        msg = ClinicalMessage(
            conversation_id=conversation.id,
            sender_type="doctor",
            sender_user_id=doctor_user_id,
            body=message_text
        )
        db.add(msg)

        # Update conversation status
        conversation.status = "DOCTOR_RESPONDED"
        conversation.updated_at = datetime.utcnow()

        # If doctor wasn't assigned, assign this responding doctor
        if doctor and not conversation.assigned_doctor_id:
            conversation.assigned_doctor_id = doctor.id

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="MESSAGE_SENT_DOCTOR",
            actor_user_id=doctor_user_id,
            reason="Clinician sent clinical advice"
        )

        # Notify patient
        notification_service.notify_patient_of_doctor_reply(
            db=db,
            conversation=conversation,
            doctor_name=doctor_name
        )

        db.commit()
        db.refresh(msg)
        return msg

    def acknowledge_alert(
        self,
        db: Session,
        conversation: ClinicalConversation,
        doctor_user_id: int,
        notes: Optional[str] = None
    ) -> ClinicalConversation:
        """
        Doctor acknowledges active escalation alert.
        """
        doctor = db.query(Doctor).filter(Doctor.user_id == doctor_user_id).first()
        state_before = {"escalation_status": conversation.escalation_status, "status": conversation.status}

        # Find active alert
        active_alert = db.query(ClinicalAlert).filter(
            ClinicalAlert.conversation_id == conversation.id,
            ClinicalAlert.status == "TRIGGERED"
        ).first()

        now = datetime.utcnow()
        if active_alert:
            active_alert.status = "ACKNOWLEDGED"
            active_alert.acknowledged_at = now
            active_alert.acknowledged_by_user_id = doctor_user_id

        conversation.escalation_status = "ACKNOWLEDGED"
        conversation.updated_at = now
        if doctor and not conversation.assigned_doctor_id:
            conversation.assigned_doctor_id = doctor.id

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="ALERT_ACKNOWLEDGED",
            actor_user_id=doctor_user_id,
            state_before=state_before,
            state_after={"escalation_status": "ACKNOWLEDGED"},
            reason=notes or "Clinician acknowledged active escalation"
        )

        db.commit()
        db.refresh(conversation)
        return conversation

    def assign_conversation(
        self,
        db: Session,
        conversation: ClinicalConversation,
        actor_user_id: int,
        doctor_id: Optional[int],
        department_id: Optional[int],
        reason: Optional[str] = None
    ) -> ClinicalConversation:
        """
        Assigns or transfers a conversation to a doctor or department.
        """
        state_before = {
            "department_id": conversation.department_id,
            "assigned_doctor_id": conversation.assigned_doctor_id
        }

        # Deactivate previous active assignment records
        db.query(ClinicalAssignment).filter(
            ClinicalAssignment.conversation_id == conversation.id,
            ClinicalAssignment.is_active == True
        ).update({"is_active": False, "unassigned_at": datetime.utcnow()})

        if department_id:
            conversation.department_id = department_id
        if doctor_id:
            conversation.assigned_doctor_id = doctor_id

        new_assignment = ClinicalAssignment(
            conversation_id=conversation.id,
            department_id=conversation.department_id,
            doctor_id=conversation.assigned_doctor_id,
            assigned_by_user_id=actor_user_id,
            reason=reason or "Clinical assignment update",
            is_active=True
        )
        db.add(new_assignment)
        conversation.updated_at = datetime.utcnow()

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="DOCTOR_ASSIGNED",
            actor_user_id=actor_user_id,
            state_before=state_before,
            state_after={
                "department_id": conversation.department_id,
                "assigned_doctor_id": conversation.assigned_doctor_id
            },
            reason=reason or "Assigned clinician"
        )

        db.commit()
        db.refresh(conversation)
        return conversation

    def escalate_conversation(
        self,
        db: Session,
        conversation: ClinicalConversation,
        actor_user_id: int,
        target_urgency: str,
        reason: str,
        department_id: Optional[int] = None
    ) -> ClinicalConversation:
        """
        Manually escalates a conversation's urgency and creates an alert.
        """
        state_before = {
            "urgency": conversation.urgency,
            "escalation_status": conversation.escalation_status
        }

        conversation.urgency = target_urgency
        if department_id:
            conversation.department_id = department_id
        conversation.escalation_status = "PENDING_ACK"
        conversation.status = "ESCALATED"
        conversation.updated_at = datetime.utcnow()

        # Trigger alert
        notification_service.trigger_clinical_alert_if_needed(
            db=db,
            conversation=conversation,
            urgency=target_urgency,
            reason=f"Manual clinical escalation: {reason}"
        )

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="CONVERSATION_ESCALATED",
            actor_user_id=actor_user_id,
            state_before=state_before,
            state_after={"urgency": target_urgency, "escalation_status": "PENDING_ACK"},
            reason=reason
        )

        db.commit()
        db.refresh(conversation)
        return conversation

    def resolve_conversation(
        self,
        db: Session,
        conversation: ClinicalConversation,
        actor_user_id: int,
        resolution_notes: Optional[str] = None
    ) -> ClinicalConversation:
        """
        Marks a conversation and its alerts as resolved.
        """
        state_before = {
            "status": conversation.status,
            "escalation_status": conversation.escalation_status
        }

        now = datetime.utcnow()
        conversation.status = "RESOLVED"
        conversation.escalation_status = "RESOLVED"
        conversation.resolved_at = now
        conversation.updated_at = now

        # Mark all active alerts resolved
        db.query(ClinicalAlert).filter(
            ClinicalAlert.conversation_id == conversation.id,
            ClinicalAlert.status.in_(["TRIGGERED", "ACKNOWLEDGED"])
        ).update({"status": "RESOLVED", "resolved_at": now})

        audit_service.log_event(
            db=db,
            conversation_id=conversation.id,
            event_type="CONVERSATION_RESOLVED",
            actor_user_id=actor_user_id,
            state_before=state_before,
            state_after={"status": "RESOLVED", "escalation_status": "RESOLVED"},
            reason=resolution_notes or "Consultation clinically resolved"
        )

        db.commit()
        db.refresh(conversation)
        return conversation

orchestrator = ClinicalChatOrchestrator()
