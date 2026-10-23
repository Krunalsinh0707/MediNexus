"""Department-scoped, migration-gated insurance and claim endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import insurance_service as service
from src.auth import get_current_user
from src.billing_service import actor_for, staff
from src.database import get_db
from src.insurance_models import InsurancePolicy, InsuranceClaim
from src.schemas.insurance import (PolicyCreate, PolicyUpdate, EligibilityRecord,
    ExpectedVersion, ClaimCreate, ClaimCorrection, ClaimTransition, ManualReconciliation)

router = APIRouter(prefix="/insurance", tags=["Insurance and Claims"])


def insurance_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    service.require_schema(db)
    return actor_for(db, token)


def save(db, operation):
    try:
        result = operation()
        db.flush()
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicting insurance update; reload before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.get("/policies")
def policies(patient_id: int | None = Query(None, gt=0),
             department_id: int | None = Query(None, gt=0),
             limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
             db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    query = db.query(InsurancePolicy)
    if actor.role in {"patient", "user"}:
        if patient_id is not None and patient_id != actor.user_id:
            raise HTTPException(404, "Policy not found")
        query = query.filter(InsurancePolicy.patient_id == actor.user_id,
                             InsurancePolicy.released_at.is_not(None))
    else:
        query = query.filter(InsurancePolicy.department_id.in_(actor.departments))
        if patient_id is not None:
            query = query.filter(InsurancePolicy.patient_id == patient_id)
    if department_id is not None:
        if actor.departments:
            staff(actor, department_id)
        query = query.filter(InsurancePolicy.department_id == department_id)
    rows = query.order_by(InsurancePolicy.id.desc()).offset(offset).limit(limit).all()
    return {"items": [service.policy_projection(db, actor, row) for row in rows],
            "limit": limit, "offset": offset}


@router.post("/policies", status_code=201)
def create_policy(data: PolicyCreate, db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    def operation():
        row = service.create_policy(db, actor, data)
        db.flush()
        return service.policy_projection(db, actor, row)
    return save(db, operation)


@router.get("/policies/{policy_id}")
def policy_detail(policy_id: int, db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return service.policy_projection(db, actor, service.policy_for(db, actor, policy_id))


def policy_mutation(db, actor, policy_id, action, data):
    def operation():
        row = service.policy_for(db, actor, policy_id, lock=True)
        action(db, actor, row, data)
        db.flush()
        return service.policy_projection(db, actor, row)
    return save(db, operation)


@router.put("/policies/{policy_id}")
def update_policy(policy_id: int, data: PolicyUpdate,
                  db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return policy_mutation(db, actor, policy_id, service.update_policy, data)


@router.post("/policies/{policy_id}/eligibility")
def eligibility(policy_id: int, data: EligibilityRecord,
                db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return policy_mutation(db, actor, policy_id, service.record_eligibility, data)


@router.post("/policies/{policy_id}/release")
def release_policy(policy_id: int, data: ExpectedVersion,
                   db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return policy_mutation(db, actor, policy_id, service.release_policy, data)


@router.get("/claims")
def claims(patient_id: int | None = Query(None, gt=0),
           department_id: int | None = Query(None, gt=0),
           status: str | None = None, limit: int = Query(50, ge=1, le=100),
           offset: int = Query(0, ge=0, le=10000),
           db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    query = db.query(InsuranceClaim)
    if actor.role in {"patient", "user"}:
        if patient_id is not None and patient_id != actor.user_id:
            raise HTTPException(404, "Claim not found")
        query = query.filter(InsuranceClaim.patient_id == actor.user_id,
                             InsuranceClaim.released_at.is_not(None))
    else:
        query = query.filter(InsuranceClaim.department_id.in_(actor.departments))
        if patient_id is not None:
            query = query.filter(InsuranceClaim.patient_id == patient_id)
    if department_id is not None:
        if actor.departments:
            staff(actor, department_id)
        query = query.filter(InsuranceClaim.department_id == department_id)
    if status:
        if status not in service.TRANSITIONS:
            raise HTTPException(422, "Unknown claim status")
        query = query.filter(InsuranceClaim.status == status)
    rows = query.order_by(InsuranceClaim.id.desc()).offset(offset).limit(limit).all()
    return {"items": [service.claim_projection(db, actor, row) for row in rows],
            "limit": limit, "offset": offset}


@router.post("/claims", status_code=201)
def create_claim(data: ClaimCreate, db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    def operation():
        row = service.create_claim(db, actor, data)
        db.flush()
        return service.claim_projection(db, actor, row)
    return save(db, operation)


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: int, db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return service.claim_projection(db, actor, service.claim_for(db, actor, claim_id))


def claim_mutation(db, actor, claim_id, action, data):
    def operation():
        row = service.claim_for(db, actor, claim_id, lock=True)
        action(db, actor, row, data)
        db.flush()
        return service.claim_projection(db, actor, row)
    return save(db, operation)


@router.post("/claims/{claim_id}/transitions")
def transition(claim_id: int, data: ClaimTransition,
               db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return claim_mutation(db, actor, claim_id, service.transition_claim, data)


@router.post("/claims/{claim_id}/corrections")
def correction(claim_id: int, data: ClaimCorrection,
               db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return claim_mutation(db, actor, claim_id, service.correct_claim, data)


@router.post("/claims/{claim_id}/release")
def release_claim(claim_id: int, data: ExpectedVersion,
                  db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return claim_mutation(db, actor, claim_id, service.release_claim, data)


@router.post("/claims/{claim_id}/remittances")
def reconcile(claim_id: int, data: ManualReconciliation,
              db: Session = Depends(get_db), actor=Depends(insurance_actor)):
    return claim_mutation(db, actor, claim_id, service.reconcile_remittance, data)
