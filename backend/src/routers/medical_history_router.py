"""Authorized, read-only projections of existing patient records."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.auth import get_current_user
from src.database import get_db
from src.medical_history import history_page
from src.models import AuditLog
from src.patient_access import PatientAccess, patient_read_access, require_clinical_history
from src.schemas.medical_history import HistoryPage


router = APIRouter(prefix="/medical-history", tags=["Medical History"])


def _read(db, actor, patient_id, patient_view, limit, after, before, cursor):
    try:
        result = history_page(db, patient_id, patient_view, limit, after, before, cursor)
        # No clinical content is placed in the audit row.
        db.add(AuditLog(user_id=actor.user_id, action="Medical history viewed", status="Success",
                        details={"patient_id": patient_id, "scope": "self" if patient_view else "clinical",
                                 "result_count": len(result.items)}))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/me", response_model=HistoryPage)
def my_history(limit: int = Query(25, ge=1, le=50), after: datetime | None = None,
               before: datetime | None = None, cursor: str | None = None,
               db: Session = Depends(get_db), actor=Depends(get_current_user)):
    if patient_read_access(db, actor, actor.user_id) != PatientAccess.SELF:
        raise HTTPException(404, "Patient record not found")
    return _read(db, actor, actor.user_id, True, limit, after, before, cursor)


@router.get("/patients/{patient_id}", response_model=HistoryPage)
def patient_history(patient_id: int, limit: int = Query(25, ge=1, le=50),
                    after: datetime | None = None, before: datetime | None = None,
                    cursor: str | None = None, db: Session = Depends(get_db),
                    actor=Depends(get_current_user)):
    if patient_id < 1 or require_clinical_history(db, actor, patient_id) != PatientAccess.CLINICAL:
        raise HTTPException(404, "Patient record not found")
    return _read(db, actor, patient_id, False, limit, after, before, cursor)
