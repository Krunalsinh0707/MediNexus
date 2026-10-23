"""Department-scoped, migration-gated billing API."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import billing_service as service
from src.auth import get_current_user
from src.billing_models import BillingTariff, BillingInvoice
from src.database import get_db
from src.models import User
from src.models import Appointment
from src.encounter_models import Encounter
from src.inpatient_models import InpatientAdmission, Ward
from src.schemas.billing import (TariffCreate, InvoiceCreate, ChargeCreate, IssueInvoice,
    CancelInvoice, AdjustmentRequest, AdjustmentDecision, ManualPayment,
    ReversePayment, RefundRequest)

router = APIRouter(prefix="/billing", tags=["Billing"])


def billing_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_schema(db)
    return service.actor_for(db, token)


def mutation(db, actor, invoice_id, operation, *args):
    try:
        row = service.invoice_for(db, actor, invoice_id, lock=True)
        operation(db, actor, row, *args)
        db.flush()
        result = service.projection(db, actor, row)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicting billing update; reload and retry") from None
    except Exception:
        db.rollback()
        raise


@router.get("/patients")
def search_patients(q: str = Query(min_length=1, max_length=100),
                    db: Session = Depends(get_db), actor=Depends(billing_actor)):
    if not actor.departments:
        raise HTTPException(403, "Billing staff only")
    term = q.strip()
    if not term:
        raise HTTPException(422, "Search text required")
    invoice_patients = db.query(BillingInvoice.patient_id).filter(BillingInvoice.department_id.in_(actor.departments))
    appointment_patients = db.query(Appointment.patient_id).filter(Appointment.department_id.in_(actor.departments))
    encounter_patients = db.query(Encounter.patient_id).filter(Encounter.department_id.in_(actor.departments))
    sources = [invoice_patients, appointment_patients, encounter_patients]
    if "inpatient_admissions" in set(inspect(db.get_bind()).get_table_names(schema="public")):
        sources.append(db.query(InpatientAdmission.patient_id).join(Ward, Ward.id == InpatientAdmission.ward_id).filter(
            Ward.department_id.in_(actor.departments)))
    scoped = invoice_patients.union(*sources[1:]).subquery()
    query = db.query(User).filter(User.id.in_(db.query(scoped.c.patient_id)),
        or_(User.mrn.ilike(f"%{term}%"), User.full_name.ilike(f"%{term}%")))
    if term.isdecimal():
        query = db.query(User).filter(User.id.in_(db.query(scoped.c.patient_id)),
            or_(User.id == int(term), User.mrn.ilike(f"%{term}%"),
                User.full_name.ilike(f"%{term}%")))
    return [{"id": p.id, "mrn": p.mrn, "full_name": p.full_name}
            for p in query.order_by(User.id).limit(30).all()]


@router.get("/tariffs")
def tariffs(department_id: int = Query(gt=0), db: Session = Depends(get_db),
            actor=Depends(billing_actor)):
    service.staff(actor, department_id)
    rows = db.query(BillingTariff).filter(BillingTariff.department_id == department_id,
        BillingTariff.is_active == 1).order_by(BillingTariff.service_code).all()
    return [{"id": r.id, "service_code": r.service_code, "description": r.description,
             "unit_price": str(r.unit_price), "currency": r.currency,
             "tax_required": bool(r.tax_required)} for r in rows]


@router.post("/tariffs", status_code=201)
def create_tariff(data: TariffCreate, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    service.staff(actor, data.department_id, manager=True)
    try:
        row = BillingTariff(**data.model_dump(exclude={"tax_required"}),
            tax_required=int(data.tax_required), approved_by_user_id=actor.user_id)
        db.add(row)
        db.flush()
        from src.models import AuditLog
        db.add(AuditLog(user_id=actor.user_id, action="billing.tariff_created",
                        details={"tariff_id": row.id, "department_id": data.department_id}))
        db.commit()
        return {"id": row.id, "service_code": row.service_code,
                "description": row.description, "unit_price": str(row.unit_price),
                "currency": row.currency, "tax_required": bool(row.tax_required)}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Tariff code already exists in this department") from None
    except Exception:
        db.rollback()
        raise


@router.get("/invoices")
def invoices(patient_id: int | None = Query(None, gt=0),
             department_id: int | None = Query(None, gt=0),
             encounter_id: int | None = Query(None, gt=0),
             status: str | None = None, from_date: date | None = None,
             to_date: date | None = None, limit: int = Query(50, ge=1, le=100),
             offset: int = Query(0, ge=0, le=10000),
             db: Session = Depends(get_db), actor=Depends(billing_actor)):
    query = db.query(BillingInvoice)
    if actor.role in {"patient", "user"}:
        if patient_id is not None and patient_id != actor.user_id:
            raise HTTPException(404, "Invoice not found")
        query = query.filter(BillingInvoice.patient_id == actor.user_id,
            BillingInvoice.status == "ISSUED", BillingInvoice.released_at.is_not(None))
    else:
        query = query.filter(BillingInvoice.department_id.in_(actor.departments))
        if patient_id:
            query = query.filter(BillingInvoice.patient_id == patient_id)
    if department_id:
        if actor.departments:
            service.staff(actor, department_id)
        query = query.filter(BillingInvoice.department_id == department_id)
    if encounter_id:
        query = query.filter(BillingInvoice.encounter_id == encounter_id)
    if from_date:
        query = query.filter(BillingInvoice.created_at >= from_date)
    if to_date:
        query = query.filter(BillingInvoice.created_at < date.fromordinal(to_date.toordinal() + 1))
    if status and status not in {"DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED"}:
        raise HTTPException(422, "Unknown invoice status")
    if status in {"DRAFT", "CANCELLED"}:
        query = query.filter(BillingInvoice.status == status)
    elif status:
        query = query.filter(BillingInvoice.status == "ISSUED")
    # Derived paid/overdue states depend on charges and payments. Apply their
    # filter before pagination so a page never quietly omits matching invoices.
    if status in {"PARTIALLY_PAID", "PAID", "OVERDUE"}:
        candidates = [service.projection(db, actor, row) for row in query.order_by(BillingInvoice.id.desc()).all()]
        items = [item for item in candidates if item["status"] == status][offset:offset + limit]
    else:
        rows = query.order_by(BillingInvoice.id.desc()).offset(offset).limit(limit).all()
        items = [service.projection(db, actor, row) for row in rows]
        if status:
            items = [item for item in items if item["status"] == status]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/patients/{patient_id}/statement")
def statement(patient_id: int, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    service.patient_scope(actor, patient_id)
    patient = db.query(User).filter(User.id == patient_id).first()
    if patient is None:
        raise HTTPException(404, "Patient not found")
    query = db.query(BillingInvoice).filter(BillingInvoice.patient_id == patient_id)
    if actor.role in {"patient", "user"}:
        query = query.filter(BillingInvoice.status == "ISSUED", BillingInvoice.released_at.is_not(None))
    else:
        query = query.filter(BillingInvoice.department_id.in_(actor.departments))
    rows = query.order_by(BillingInvoice.id).all()
    if not rows and actor.role not in {"patient", "user"}:
        raise HTTPException(404, "No authorized billing statement for this patient")
    items = [service.projection(db, actor, row) for row in rows]
    # Mixed currencies must never be added together.
    by_currency = {}
    pending_tax_configuration = []
    for item in items:
        currency = item["currency"]
        if item["outstanding"] is None:
            pending_tax_configuration.append(item["id"])
        else:
            by_currency[currency] = by_currency.get(currency, service.Decimal(0)) + service.Decimal(item["outstanding"])
    return {"patient": {"id": patient.id, "mrn": patient.mrn,
                         "full_name": patient.full_name},
            "invoices": items, "outstanding_by_currency": {k: str(v) for k, v in by_currency.items()},
            "totals_exclude_tax_pending_invoice_ids": pending_tax_configuration}


@router.post("/invoices", status_code=201)
def create_invoice(data: InvoiceCreate, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    try:
        row = service.create_invoice(db, actor, data)
        result = service.projection(db, actor, row)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Invoice creation conflict; reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/invoices/{invoice_id}")
def detail(invoice_id: int, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return service.projection(db, actor, service.invoice_for(db, actor, invoice_id))


@router.post("/invoices/{invoice_id}/charges")
def charge(invoice_id: int, data: ChargeCreate, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.add_charge, data)


@router.post("/invoices/{invoice_id}/issue")
def issue(invoice_id: int, data: IssueInvoice, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.issue, data)


@router.post("/invoices/{invoice_id}/cancel")
def cancel(invoice_id: int, data: CancelInvoice, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.cancel, data)


@router.post("/invoices/{invoice_id}/adjustments")
def adjust(invoice_id: int, data: AdjustmentRequest, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.request_adjustment, data)


@router.post("/invoices/{invoice_id}/adjustments/{adjustment_id}/decision")
def decide(invoice_id: int, adjustment_id: int, data: AdjustmentDecision,
           db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.decide_adjustment, adjustment_id, data)


@router.post("/invoices/{invoice_id}/payments")
def payment(invoice_id: int, data: ManualPayment, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.record_payment, data)


@router.post("/invoices/{invoice_id}/payments/{payment_id}/reverse")
def reverse(invoice_id: int, payment_id: int, data: ReversePayment,
            db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.reverse_payment, payment_id, data)


@router.post("/invoices/{invoice_id}/refund-requests")
def refund(invoice_id: int, data: RefundRequest, db: Session = Depends(get_db), actor=Depends(billing_actor)):
    return mutation(db, actor, invoice_id, service.request_refund, data)
