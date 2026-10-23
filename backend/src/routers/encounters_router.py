"""Role-scoped outpatient visits; no report/chat authorization is broadened."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth import get_current_user
from src.database import get_db
from src import encounter_service as service
from src.models import AuditLog, Encounter, EncounterVitals, EncounterDiagnosis, PatientAllergy
from src.schemas.encounters import (
    EncounterCreate, Assignment, Transition, NoteWrite, AddendumWrite,
    VitalsWrite, DiagnosisWrite, AllergyWrite, AllergyReview,
)

router = APIRouter(prefix="/encounters", tags=["Encounters"])


def encounter_actor(db: Session = Depends(get_db), token=Depends(get_current_user)):
    return service.actor_for(db, token)


def mutate(db, actor, action, *args, **kwargs):
    try:
        encounter = action(db, actor, *args, **kwargs)
        db.flush()
        result = service.detail(db, actor, encounter)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A conflicting record was saved. Reload the visit before retrying") from None
    except Exception:
        db.rollback()
        raise


@router.post("", status_code=201)
def create(data: EncounterCreate, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.create_encounter, data)


@router.get("")
def list_visits(patient_id: int | None = Query(default=None, gt=0), status: str | None = None,
                limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
                db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    query = service.readable_query(db, actor, patient_id)
    if status:
        if status not in {"CHECKED_IN", "IN_PROGRESS", "COMPLETED", "CANCELLED"}:
            raise HTTPException(422, "Unknown visit status")
        query = query.filter(Encounter.status == status)
    total = query.count()
    items = query.order_by(Encounter.checked_in_at.desc(), Encounter.id.desc()).offset(offset).limit(limit).all()
    result = {"items": [service.overview(db, row) for row in items], "total": total}
    db.add(AuditLog(user_id=actor.user_id, action="Encounter list viewed", status="Success",
                    details={"patient_id": patient_id, "status": status, "result_count": len(items)}))
    db.commit()
    return result


@router.get("/{encounter_id}")
def get_visit(encounter_id: int, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    encounter = service.readable(db, actor, encounter_id)
    result = service.detail(db, actor, encounter)
    service.audit(db, actor, encounter, "viewed")
    db.commit()
    return result


@router.put("/{encounter_id}/assignment")
def assign(encounter_id: int, data: Assignment, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.assign, encounter_id, data)


@router.post("/{encounter_id}/transitions")
def transition(encounter_id: int, data: Transition, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.transition, encounter_id, data)


@router.post("/{encounter_id}/notes")
def note(encounter_id: int, data: NoteWrite, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.write_note, encounter_id, data)


@router.post("/{encounter_id}/addenda")
def addendum(encounter_id: int, data: AddendumWrite, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.write_note, encounter_id, data, addendum=True)


@router.post("/{encounter_id}/vitals")
def vitals(encounter_id: int, data: VitalsWrite, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.write_observation, encounter_id, data, EncounterVitals)


@router.post("/{encounter_id}/diagnoses")
def diagnosis(encounter_id: int, data: DiagnosisWrite, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.write_observation, encounter_id, data, EncounterDiagnosis)


@router.get("/{encounter_id}/allergies")
def allergies(encounter_id: int, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    encounter = service.readable(db, actor, encounter_id)
    result = service.allergy_context(db, actor, encounter)
    service.audit(db, actor, encounter, "allergy context viewed")
    db.commit()
    return result


@router.post("/{encounter_id}/allergies")
def allergy(encounter_id: int, data: AllergyWrite, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.write_observation, encounter_id, data, PatientAllergy)


@router.post("/{encounter_id}/allergy-review")
def review(encounter_id: int, data: AllergyReview, db: Session = Depends(get_db), actor=Depends(encounter_actor)):
    return mutate(db, actor, service.review_allergies, encounter_id, data)
