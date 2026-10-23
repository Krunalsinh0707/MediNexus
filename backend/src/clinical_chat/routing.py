from typing import Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.models import (
    Department, Doctor, ClinicalRoutingRule,
    DoctorDepartmentMembership
)

class ClinicalRouter:
    """
    Department routing and clinician assignment engine.
    Resolves target departments from database-configured routing rules, with deterministic safety fallbacks.
    """
    def route_conversation(
        self,
        db: Session,
        urgency: str,
        category: str,
        evidence_codes: list
    ) -> Tuple[Optional[int], Optional[int], str]:
        """
        Determines target department_id, assigned_doctor_id, and rule_version.
        Returns: (department_id, assigned_doctor_id, rule_version)
        """
        # 1. Fetch all enabled routing rules
        rules = db.query(ClinicalRoutingRule).filter(ClinicalRoutingRule.is_enabled == True).all()

        matched_rule = None
        # Check rule match by category or evidence codes
        for r in rules:
            cat_lower = (r.category_or_indicator or "").lower()
            if cat_lower in category.lower():
                matched_rule = r
                break
            for ev in evidence_codes:
                if cat_lower in ev.lower():
                    matched_rule = r
                    break
            if matched_rule:
                break

        department_id = None
        rule_version = matched_rule.version if matched_rule else "1.0-default"

        if matched_rule:
            department_id = matched_rule.department_id

        # 2. Deterministic Fallback if not matched
        if not department_id:
            if urgency == "EMERGENCY_REVIEW":
                emerg_dept = db.query(Department).filter(Department.code == "EMERG").first()
                department_id = emerg_dept.id if emerg_dept else None
            else:
                genmed_dept = db.query(Department).filter(Department.code == "GENMED").first()
                department_id = genmed_dept.id if genmed_dept else None

        # If department is still None, pick any first department as ultimate fallback
        if not department_id:
            first_dept = db.query(Department).first()
            department_id = first_dept.id if first_dept else None

        # 3. Resolve Assigned Doctor (Responder or Department Lead)
        assigned_doctor_id = self._resolve_assigned_doctor(db, department_id, urgency)

        return department_id, assigned_doctor_id, rule_version

    def _resolve_assigned_doctor(
        self,
        db: Session,
        department_id: Optional[int],
        urgency: str
    ) -> Optional[int]:
        if not department_id:
            return None

        # 1. Look for active RESPONDER or LEAD in doctor_department_memberships
        memberships = db.query(DoctorDepartmentMembership).filter(
            DoctorDepartmentMembership.department_id == department_id,
            DoctorDepartmentMembership.is_active == True,
            DoctorDepartmentMembership.role.in_(["RESPONDER", "LEAD"])
        ).all()

        from src.workforce_service import source_assignment_current
        for membership in memberships:
            if not source_assignment_current(db, "DOCTOR", membership.id):
                continue
            # Check doctor status is Active
            doc = db.query(Doctor).filter(Doctor.id == membership.doctor_id, Doctor.status == "Active").first()
            if doc:
                return doc.id

        # 2. Look for Department.head_doctor_id
        dept = db.query(Department).filter(Department.id == department_id).first()
        if dept and dept.head_doctor_id:
            doc = db.query(Doctor).filter(Doctor.id == dept.head_doctor_id, Doctor.status == "Active").first()
            if doc:
                return doc.id

        # 3. Look for any active Doctor in that department
        primary_doc = db.query(Doctor).filter(
            Doctor.department_id == department_id,
            Doctor.status == "Active"
        ).first()

        if primary_doc:
            return primary_doc.id

        # If it's EMERGENCY_REVIEW, try finding any emergency doctor
        if urgency == "EMERGENCY_REVIEW":
            emerg_dept = db.query(Department).filter(Department.code == "EMERG").first()
            if emerg_dept and emerg_dept.id != department_id:
                any_emerg = db.query(Doctor).filter(Doctor.department_id == emerg_dept.id, Doctor.status == "Active").first()
                if any_emerg:
                    return any_emerg.id

        return None

clinical_router = ClinicalRouter()
