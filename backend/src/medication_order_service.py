"""Structured prescribing built on the shared clinical-order lifecycle.

This module does not dispense, administer, or deduct inventory. Callers own
commit and rollback, and storage remains gated pending an approved migration.
"""

import os
import re

from fastapi import HTTPException
from sqlalchemy import func, inspect

from src import clinical_order_service as orders
from src.clinical_order_models import ClinicalOrder, MedicationOrderDetail
from src.models import AuditLog, Department, Encounter, EncounterAllergyReview
from src.schemas.clinical_orders import ClinicalOrderCreate


MEDICATION_TABLES = ("medication_order_details",)


def require_medication_schema(db):
    orders.require_order_schema(db)
    try:
        inspector = inspect(db.get_bind())
        missing = [name for name in MEDICATION_TABLES if not inspector.has_table(name, schema="public")]
    except Exception as exc:
        raise HTTPException(503, "Medication order storage readiness could not be verified") from exc
    if missing:
        raise HTTPException(503, "Medication order storage is not installed")


def pharmacy_department(db):
    code = os.getenv("HMS_PHARMACY_DEPARTMENT_CODE", "PHARM").strip().upper()
    if not code:
        orders.fail(503, "Pharmacy department configuration is missing")
    department = db.query(Department).filter(func.upper(Department.code) == code).first()
    if department is None:
        orders.fail(422, f"Pharmacy department '{code}' is not configured")
    return department


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def allergy_warnings(context, medication_identifier, display_name):
    medication_terms = {normalized(medication_identifier), normalized(display_name)} - {""}
    warnings = []
    for row in context.get("current_records", []):
        if row.get("status") != "ACTIVE":
            continue
        substance = str(row.get("substance") or "").strip()
        exact = normalized(substance) in medication_terms
        warnings.append({
            "source": "clinician_recorded",
            "match": "EXACT_TEXT_MATCH" if exact else "REVIEW_RECORDED_ALLERGY",
            "substance": substance,
            "severity": row.get("severity"),
            "message": (
                "Medication text exactly matches a recorded active allergy; verify before signing."
                if exact else
                "An active allergy is recorded. No comprehensive drug-allergy interaction check was performed."
            ),
        })
    for value in context.get("legacy_unverified", []):
        text = str(value).strip()
        if text:
            warnings.append({
                "source": "legacy_unverified",
                "match": "REVIEW_LEGACY_TEXT",
                "substance": text,
                "severity": None,
                "message": "Unverified legacy allergy text requires clinician review.",
            })
    return warnings


def current_allergy_review(db, encounter, snapshot):
    review = db.query(EncounterAllergyReview).filter(
        EncounterAllergyReview.encounter_id == encounter.id,
    ).order_by(EncounterAllergyReview.id.desc()).first()
    if review is None or review.snapshot != snapshot:
        orders.fail(409, "Review the patient's current allergies for this visit before prescribing")
    return review


def create_medication_order(db, actor, data):
    if actor.role not in orders.CLINICAL_ROLES or actor.doctor_id is None:
        orders.fail(403, "An active clinician is required to prescribe medication")
    if data.allergy_review_acknowledged is not True:
        orders.fail(422, "Explicit allergy-review acknowledgement is required")
    department = pharmacy_department(db)
    generic = ClinicalOrderCreate(
        patient_id=data.patient_id,
        encounter_id=data.encounter_id,
        destination_department_id=department.id,
        order_type="MEDICATION",
        priority=data.priority,
        order_code=data.medication_identifier,
        display_name=data.medication_display_name,
        clinical_indication=None,
    )
    order = orders.create_order(db, actor, generic, allow_medication=True)

    encounter = db.get(Encounter, order.encounter_id)
    context = orders.encounter_service.allergy_context(db, actor, encounter)
    review = current_allergy_review(db, encounter, context["current_records"])
    warnings = allergy_warnings(context, data.medication_identifier, data.medication_display_name)
    detail = MedicationOrderDetail(
        order_id=order.id,
        medication_identifier_system=data.medication_identifier_system,
        medication_identifier=data.medication_identifier,
        medication_display_name=data.medication_display_name,
        dose=data.dose,
        dose_unit=data.dose_unit,
        route=data.route,
        frequency=data.frequency,
        duration_value=data.duration_value,
        duration_unit=data.duration_unit,
        quantity=data.quantity,
        quantity_unit=data.quantity_unit,
        start_date=data.start_date,
        instructions=data.instructions,
        allergy_review_id=review.id,
        allergy_warning_snapshot=warnings,
        allergy_acknowledged_at=orders.now(),
    )
    db.add(detail)
    db.add(AuditLog(
        user_id=actor.user_id,
        action="Medication prescription details recorded",
        status="Success",
        details={
            "order_id": order.id,
            "patient_id": order.patient_id,
            "encounter_id": order.encounter_id,
            "allergy_review_id": review.id,
            "allergy_warning_count": len(warnings),
            "version": order.version,
        },
    ))
    db.flush()
    return order


def medication_query(db, actor, patient_id=None, encounter_id=None):
    return orders.readable_query(db, actor, patient_id, encounter_id).filter(
        ClinicalOrder.order_type == "MEDICATION"
    )


def readable_medication(db, actor, order_id, lock=False):
    order = orders.readable(db, actor, order_id, lock=lock)
    if order.order_type != "MEDICATION":
        orders.fail(404, "Medication order not found")
    return order


def detail_for(db, order):
    detail = db.query(MedicationOrderDetail).filter(MedicationOrderDetail.order_id == order.id).first()
    if detail is None:
        orders.fail(503, "Medication order detail is unavailable")
    return detail


def projection(db, actor, order):
    detail = detail_for(db, order)
    warning_snapshot = detail.allergy_warning_snapshot if actor.role in orders.CLINICAL_ROLES else []
    medication = {
        name: getattr(detail, name)
        for name in (
            "id order_id medication_identifier_system medication_identifier medication_display_name "
            "dose dose_unit route frequency duration_value duration_unit quantity quantity_unit "
            "start_date instructions allergy_acknowledged_at"
        ).split()
    }
    medication["allergy_review_id"] = detail.allergy_review_id if actor.role in orders.CLINICAL_ROLES else None
    medication["allergy_warnings"] = warning_snapshot or []
    return {"order": orders.projection(db, actor, order), "medication": medication}


def transition_medication_order(db, actor, order_id, data):
    order = orders.transition_order(db, actor, order_id, data, required_order_type="MEDICATION")
    detail_for(db, order)
    return order
