"""Scoped chronology over existing clinical records; no new persistence model.

Each source row appears at most once. A correction remains visible as a distinct
revision, while its predecessor is marked as corrected. Dates use recorded or
created timestamps rather than a patient's unverified claimed event date.
"""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import json

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, literal, or_, select, tuple_, union_all

from src.auth import SECRET_KEY
from src.models import (
    AIAnalysis, CbcReport, DoctorReview, MedicalReviewRevision, Encounter, EncounterAllergyReview,
    EncounterDiagnosis, EncounterNote, EncounterVitals, HeartReport,
    HypertensionReport, MedicalRecord, MedicalReport, PatientAllergy, PatientReport,
)
from src.schemas.medical_history import HistoryEvent, HistoryPage


MAX_PAGE_SIZE = 50


def _sources(patient_id: int, patient_view: bool):
    """Source, timestamp and scope predicates; all joins constrain patient ID."""
    completed = Encounter.status == "COMPLETED"
    notes = select(EncounterNote).join(Encounter, Encounter.id == EncounterNote.encounter_id)
    note_scope = and_(Encounter.patient_id == patient_id, EncounterNote.signed_at.is_not(None))
    if patient_view:
        note_scope = and_(note_scope, completed, EncounterNote.patient_summary != "")
    sources = [("signed_note", EncounterNote, EncounterNote.signed_at, notes, note_scope)]

    reports = select(MedicalReport)
    report_scope = MedicalReport.patient_id == patient_id
    if patient_view:
        # A hospital report may be committed before its separate review row.
        report_scope = and_(report_scope, or_(MedicalReport.report_source != "hospital",
            MedicalReport.report_source.is_(None),
            exists(select(DoctorReview.id).where(DoctorReview.report_id == MedicalReport.id))))
    sources.append(("report", MedicalReport, MedicalReport.created_at, reports,
                    report_scope))

    reviews = select(DoctorReview).join(MedicalReport, MedicalReport.id == DoctorReview.report_id)
    sources.append(("report_review", DoctorReview, DoctorReview.reviewed_at, reviews,
                    MedicalReport.patient_id == patient_id))
    amendments = select(MedicalReviewRevision).join(MedicalReport,
        MedicalReport.id == MedicalReviewRevision.report_id)
    sources.append(("report_review_revision", MedicalReviewRevision,
                    MedicalReviewRevision.signed_at, amendments,
                    MedicalReport.patient_id == patient_id))

    analyses = select(AIAnalysis).join(MedicalReport, MedicalReport.id == AIAnalysis.report_id)
    sources.append(("ai_report_assessment", AIAnalysis, AIAnalysis.created_at, analyses,
                    MedicalReport.patient_id == patient_id))

    for kind, model in (("ai_diabetes_assessment", PatientReport), ("ai_cbc_assessment", CbcReport),
                        ("ai_heart_assessment", HeartReport), ("ai_hypertension_assessment", HypertensionReport)):
        sources.append((kind, model, model.created_at, select(model), model.user_id == patient_id))

    if not patient_view:
        sources.append(("encounter", Encounter, Encounter.checked_in_at, select(Encounter),
                        Encounter.patient_id == patient_id))
        for kind, model, timestamp in (
            ("vitals", EncounterVitals, EncounterVitals.measured_at),
            ("diagnosis", EncounterDiagnosis, EncounterDiagnosis.recorded_at),
            ("allergy_review", EncounterAllergyReview, EncounterAllergyReview.reviewed_at),
        ):
            sources.append((kind, model, timestamp,
                            select(model).join(Encounter, Encounter.id == model.encounter_id),
                            Encounter.patient_id == patient_id))
        sources.extend((
            ("allergy", PatientAllergy, PatientAllergy.recorded_at, select(PatientAllergy),
             PatientAllergy.patient_id == patient_id),
            ("legacy_record", MedicalRecord, func.coalesce(MedicalRecord.updated_at, MedicalRecord.created_at), select(MedicalRecord),
             MedicalRecord.patient_id == patient_id),
        ))
    return sources


def _cursor_encode(patient_id, patient_view, after, before, row):
    data = {"p": patient_id, "v": patient_view, "a": after.isoformat() if after else None,
            "b": before.isoformat() if before else None, "t": row.occurred_at.isoformat(),
            "r": row.rank, "i": row.source_id}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")


def _cursor_decode(token, patient_id, patient_view, after, before):
    try:
        if len(token) > 1024:
            raise ValueError("oversized cursor")
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, signature = raw[:-32], raw[-32:]
        expected = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        data = json.loads(payload)
        if (data["p"], data["v"], data["a"], data["b"]) != (
            patient_id, patient_view, after.isoformat() if after else None,
            before.isoformat() if before else None,
        ):
            raise ValueError("cursor scope differs")
        timestamp = datetime.fromisoformat(data["t"])
        if timestamp.tzinfo is None or not isinstance(data["r"], int) or not isinstance(data["i"], int):
            raise ValueError("invalid cursor position")
        return timestamp, data["r"], data["i"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(422, "Invalid or mismatched history cursor") from exc


def _corrected(db, model, row):
    if model is DoctorReview:
        return db.query(MedicalReviewRevision.id).filter(
            MedicalReviewRevision.original_review_id == row.id).first() is not None
    if model is MedicalReviewRevision:
        return db.query(MedicalReviewRevision.id).filter(
            MedicalReviewRevision.previous_revision_id == row.id).first() is not None
    if not hasattr(model, "previous_id"):
        return False
    return db.query(model.id).filter(model.previous_id == row.id).first() is not None


def _project(db, kind, model, row, patient_view):
    """Use an allowlist: patient payloads never include draft or internal fields."""
    data = dict(id=f"{kind}:{row.id}", kind=kind, title="", summary=None,
                provenance="legacy_unverified", corrected=_corrected(db, model, row))
    if kind == "signed_note":
        data.update(title="Signed visit summary" if patient_view else "Signed clinical note",
                    summary=row.patient_summary if patient_view else row.assessment or row.subjective,
                    provenance="signed_clinical_finding", encounter_id=row.encounter_id,
                    clinician_user_id=row.author_user_id, status=row.kind)
        if not patient_view:
            data["details"] = {k: getattr(row, k) for k in
                               ("subjective", "objective", "assessment", "plan", "patient_summary", "revision", "reason")}
    elif kind == "report":
        data.update(title=row.report_title, summary=row.report_type,
                    provenance="clinician_recorded_report" if row.report_source == "hospital" and row.doctor_id else "legacy_unverified",
                    report_id=row.id, status=row.status)
    elif kind == "report_review":
        report = db.get(MedicalReport, row.report_id)
        verified = bool(report and report.doctor_id and report.doctor_id == row.doctor_id)
        data.update(title="Clinician report review", summary=row.final_assessment if not patient_view else None,
                    provenance="clinician_reviewed_report" if verified else "legacy_unverified",
                    report_id=row.report_id, status=row.review_status)
        if not patient_view:
            data["details"] = {"clinical_notes": row.clinical_notes}
    elif kind == "report_review_revision":
        data.update(title="Signed report-review amendment", summary=row.final_assessment if not patient_view else None,
                    provenance="signed_clinical_finding", report_id=row.report_id,
                    clinician_user_id=row.author_user_id, status=row.review_status)
        if not patient_view:
            data["details"] = {"clinical_notes": row.clinical_notes,
                               "amendment_reason": row.amendment_reason,
                               "revision_number": row.revision_number}
    elif kind == "ai_report_assessment":
        data.update(title="AI-generated report assessment", summary=row.prediction,
                    provenance="ai_generated_assessment", report_id=row.report_id,
                    status=row.risk_level, details={"model_name": row.model_name})
    elif kind.startswith("ai_"):
        prediction = getattr(row, "prediction", None) or getattr(row, "diabetes_prediction", None)
        data.update(title="Client-submitted legacy assessment", summary=prediction,
                    provenance="client_submitted_unverified")
    elif kind == "vitals":
        data.update(title="Measured vital signs", provenance="clinician_recorded_measurement",
                    encounter_id=row.encounter_id, clinician_user_id=row.recorded_by_user_id,
                    details={name: str(getattr(row, name)) if getattr(row, name) is not None else None
                             for name in ("systolic_mmhg", "diastolic_mmhg", "pulse_bpm", "respiratory_rate_per_min",
                                          "temperature_c", "spo2_percent", "weight_kg", "height_cm")})
    elif kind == "encounter":
        data.update(title="Hospital visit", summary=row.chief_complaint,
                    provenance="clinician_recorded_visit", encounter_id=row.id,
                    status=row.status, details={"appointment_id": row.appointment_id,
                                                "assigned_doctor_id": row.doctor_id})
    elif kind == "diagnosis":
        data.update(title="Clinician-recorded diagnosis", summary=row.description,
                    provenance="clinician_recorded_finding", encounter_id=row.encounter_id,
                    clinician_user_id=row.recorded_by_user_id, status=row.status,
                    details={"code": row.code, "coding_system": row.coding_system})
    elif kind == "allergy":
        data.update(title="Clinician-recorded allergy", summary=row.substance,
                    provenance="clinician_recorded_finding", encounter_id=row.source_encounter_id,
                    clinician_user_id=row.recorded_by_user_id, status=row.status,
                    details={"reaction": row.reaction, "severity": row.severity})
    elif kind == "allergy_review":
        data.update(title="Explicit allergy review", provenance="clinician_reviewed_information",
                    encounter_id=row.encounter_id, clinician_user_id=row.reviewed_by_user_id,
                    status=row.outcome)
    elif kind == "legacy_record":
        data.update(title="Legacy medical record (current snapshot)", summary=row.summary,
                    provenance="legacy_unverified",
                    details={"allergies": row.allergies, "medical_history": row.medical_history_json})
    return data


def history_page(db, patient_id: int, patient_view: bool, limit: int = 25,
                 after: datetime | None = None, before: datetime | None = None,
                 cursor: str | None = None) -> HistoryPage:
    if after and after.tzinfo is None or before and before.tzinfo is None or after and before and after >= before:
        raise HTTPException(422, "History date filters require an ordered timezone-aware range")
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise HTTPException(422, "History page size must be between 1 and 50")
    position = _cursor_decode(cursor, patient_id, patient_view, after, before) if cursor else None
    sources = _sources(patient_id, patient_view)
    selects = []
    models = {}
    for rank, (kind, model, timestamp, query, scope) in enumerate(sources):
        models[kind] = model
        statement = query.with_only_columns(
            literal(kind).label("kind"), model.id.label("source_id"),
            timestamp.label("occurred_at"), literal(rank).label("rank"),
        ).where(scope, timestamp.is_not(None))
        if after:
            statement = statement.where(timestamp >= after)
        if before:
            statement = statement.where(timestamp < before)
        selects.append(statement)
    events = union_all(*selects).subquery("history_events")
    statement = select(events).order_by(events.c.occurred_at.desc(), events.c.rank.desc(), events.c.source_id.desc())
    if position:
        statement = statement.where(tuple_(events.c.occurred_at, events.c.rank, events.c.source_id) < position)
    rows = db.execute(statement.limit(limit + 1)).all()
    visible = rows[:limit]
    items = []
    for event in visible:
        source = db.get(models[event.kind], event.source_id)
        if source is None:  # A concurrent deletion may remove a row after key selection.
            continue
        items.append(HistoryEvent(occurred_at=event.occurred_at,
                                  **_project(db, event.kind, models[event.kind], source, patient_view)))
    next_cursor = _cursor_encode(patient_id, patient_view, after, before, visible[-1]) if len(rows) > limit and visible else None
    return HistoryPage(items=items, next_cursor=next_cursor)
