"""Source-level RIS workflow. No DICOM or PACS capability is implied."""
from dataclasses import dataclass
import os
from fastapi import HTTPException
from sqlalchemy import func,inspect,or_
from src import clinical_order_service as orders
from src.clinical_order_models import (ClinicalOrder,ImagingOrderDetail,ImagingStudy,
 RadiologyReportEvent,RadiologyReportRevision,RadiologyStaffAssignment,RadiologyWorkflow,RadiologyWorkflowEvent)
from src.models import AuditLog,Department,Doctor,Encounter,Notification,User
from src.schemas.clinical_orders import ClinicalOrderCreate

TABLES=("imaging_order_details","radiology_staff_assignments","radiology_workflows","radiology_workflow_events","imaging_studies","radiology_report_revisions","radiology_report_events")
TRANSITIONS={
 "AWAITING_REVIEW":{"ACCEPTED","CLARIFICATION_REQUESTED","REJECTED"},
 "CLARIFICATION_REQUESTED":{"ACCEPTED","REJECTED"},"ACCEPTED":{"SCHEDULED","CANCELLED"},
 "SCHEDULED":{"READY_FOR_IMAGING","CANCELLED"},"READY_FOR_IMAGING":{"ACQUISITION_IN_PROGRESS","CANCELLED"},
 "ACQUISITION_IN_PROGRESS":{"ACQUISITION_COMPLETED","CANCELLED"},
 "ACQUISITION_COMPLETED":{"INTERPRETATION_IN_PROGRESS"},"INTERPRETATION_IN_PROGRESS":set(),
 "REPORT_DRAFT":set(),"REPORT_VERIFIED":set(),"REPORT_FINALIZED":set(),"REPORT_REJECTED":set(),
 "REJECTED":set(),"CANCELLED":set(),
}
@dataclass(frozen=True)
class RadiologyActor: user_id:int; assignment_id:int; department_id:int; assignment_role:str
def fail(s,d): raise HTTPException(s,d)
def require_schema(db):
 orders.require_order_schema(db)
 try:
  i=inspect(db.get_bind()); missing=[n for n in TABLES if not i.has_table(n,schema="public")]
 except Exception as exc: raise HTTPException(503,"Radiology storage readiness could not be verified") from exc
 if missing: raise HTTPException(503,"Radiology storage is not installed")
def department(db):
 code=os.getenv("HMS_RADIOLOGY_DEPARTMENT_CODE","RAD").strip().upper()
 row=db.query(Department).filter(func.upper(Department.code)==code).first()
 if row is None: fail(422,f"Radiology department '{code}' is not configured")
 return row
def actor_for(db,token):
 user=db.get(User,token.user_id)
 if user is None or not user.password_hash: fail(401,"An eligible portal account is required")
 if user.role!="department_admin": fail(403,"An assigned radiology staff account is required")
 code=os.getenv("HMS_RADIOLOGY_DEPARTMENT_CODE","RAD").strip().upper()
 a=db.query(RadiologyStaffAssignment).join(Department,Department.id==RadiologyStaffAssignment.department_id).filter(
  RadiologyStaffAssignment.user_id==user.id,RadiologyStaffAssignment.is_active==1,func.upper(Department.code)==code).first()
 if a is None or a.assignment_role not in {"RAD_STAFF","RADIOLOGIST","RAD_MANAGER"}: fail(403,"No supported active radiology assignment exists")
 from src.workforce_service import source_assignment_current
 if not source_assignment_current(db,"RADIOLOGY",a.id): fail(403,"The managed radiology assignment is suspended, revoked, or expired")
 return RadiologyActor(user.id,a.id,a.department_id,a.assignment_role)
def create_imaging_order(db,actor,data):
 if actor.role not in orders.CLINICAL_ROLES or actor.doctor_id is None: fail(403,"An active clinician is required")
 dept=department(db)
 generic=ClinicalOrderCreate(patient_id=data.patient_id,encounter_id=data.encounter_id,destination_department_id=dept.id,
  order_type="IMAGING",priority=data.priority,order_code=data.procedure_code,display_name=data.requested_procedure,clinical_indication=data.clinical_indication)
 order=orders.create_order(db,actor,generic,allow_imaging=True)
 db.add(ImagingOrderDetail(order_id=order.id,modality=data.modality.upper(),body_region=data.body_region,requested_procedure=data.requested_procedure))
 db.add(AuditLog(user_id=actor.user_id,action="Imaging order details recorded",status="Success",details={"order_id":order.id,"patient_id":order.patient_id,"encounter_id":order.encounter_id,"department_id":dept.id}))
 db.flush(); return order
def queue_query(db,actor,search=None,priority=None,status=None,order_id=None,encounter_id=None,modality=None,body_region=None):
 q=db.query(ClinicalOrder).join(ImagingOrderDetail,ImagingOrderDetail.order_id==ClinicalOrder.id).join(User,User.id==ClinicalOrder.patient_id).outerjoin(RadiologyWorkflow,RadiologyWorkflow.order_id==ClinicalOrder.id).filter(
  ClinicalOrder.order_type=="IMAGING",ClinicalOrder.signed_at.is_not(None),ClinicalOrder.destination_department_id==actor.department_id)
 if order_id:q=q.filter(ClinicalOrder.id==order_id)
 if encounter_id:q=q.filter(ClinicalOrder.encounter_id==encounter_id)
 if priority:q=q.filter(ClinicalOrder.priority==priority)
 if modality:q=q.filter(func.upper(ImagingOrderDetail.modality)==modality.upper())
 if body_region:q=q.filter(ImagingOrderDetail.body_region.ilike(f"%{body_region.strip()}%"))
 if status:
  if status=="AWAITING_REVIEW":q=q.filter(RadiologyWorkflow.id.is_(None),ClinicalOrder.status!="CANCELLED")
  elif status=="ORDER_CANCELLED":q=q.filter(ClinicalOrder.status=="CANCELLED")
  else:q=q.filter(RadiologyWorkflow.status==status,ClinicalOrder.status!="CANCELLED")
 if search:
  term=f"%{search.strip()}%";q=q.filter(or_(User.mrn.ilike(term),ClinicalOrder.display_name.ilike(term),ClinicalOrder.order_code.ilike(term)))
 return q
def readable(db,actor,oid,lock=False):
 q=queue_query(db,actor,order_id=oid)
 if lock:q=q.with_for_update().populate_existing()
 row=q.first()
 if row is None:fail(404,"Imaging order not found")
 return row
def workflow_for(db,order,actor,lock=False):
 q=db.query(RadiologyWorkflow).filter(RadiologyWorkflow.order_id==order.id)
 if lock:q=q.with_for_update().populate_existing()
 w=q.first()
 if w and w.department_id!=actor.department_id:fail(409,"Radiology workflow department mismatch")
 return w
def event(db,actor,w,source,target,reason=None):db.add(RadiologyWorkflowEvent(workflow_id=w.id,sequence=w.version,workflow_version=w.version,from_status=source,to_status=target,actor_user_id=actor.user_id,actor_assignment_id=actor.assignment_id,reason=reason))
def audit(db,actor,o,w,action):db.add(AuditLog(user_id=actor.user_id,action="Radiology "+action,status="Success",details={"order_id":o.id,"patient_id":o.patient_id,"workflow_id":w.id,"department_id":actor.department_id,"status":w.status,"version":w.version}))
def transition(db,actor,oid,data):
 o=readable(db,actor,oid,True)
 if o.status!="SIGNED":fail(409,"Only a currently signed imaging order can be processed")
 w=workflow_for(db,o,actor,True);source=w.status if w else "AWAITING_REVIEW";version=w.version if w else 0
 if version!=data.expected_version:fail(409,"This radiology workflow changed. Reload before retrying")
 if data.status not in TRANSITIONS.get(source,set()):fail(409,f"Radiology workflow cannot move from {source} to {data.status}")
 if w is None:w=RadiologyWorkflow(order_id=o.id,department_id=actor.department_id,status=data.status,version=1,last_reason=data.reason);db.add(w);db.flush()
 else:w.status=data.status;w.version+=1;w.last_reason=data.reason
 if data.status=="SCHEDULED":w.scheduled_at=data.scheduled_at
 detail=db.query(ImagingOrderDetail).filter(ImagingOrderDetail.order_id==o.id).first()
 study=db.query(ImagingStudy).filter(ImagingStudy.order_id==o.id).with_for_update().populate_existing().first()
 if data.status=="ACQUISITION_IN_PROGRESS":
  if study:fail(409,"An imaging study already exists")
  study=ImagingStudy(workflow_id=w.id,order_id=o.id,patient_id=o.patient_id,encounter_id=o.encounter_id,study_identifier=data.study_identifier,modality=detail.modality,body_region=detail.body_region,status=data.status,version=1,acquisition_started_at=func.now(),acquired_by_user_id=actor.user_id);db.add(study)
 elif data.status=="ACQUISITION_COMPLETED":
  if study is None or study.status!="ACQUISITION_IN_PROGRESS":fail(409,"An active acquisition is required")
  study.status=data.status;study.version+=1;study.acquisition_completed_at=func.now()
 event(db,actor,w,source,data.status,data.reason)
 if data.status in {"CLARIFICATION_REQUESTED","REJECTED","CANCELLED"}:db.add(Notification(user_id=o.requested_by_user_id,title="Imaging order update",message="An imaging order requires clinician review.",type="RADIOLOGY_REVIEW"))
 audit(db,actor,o,w,data.status.lower());db.flush();return o
def create_report(db,actor,oid,data):
 if actor.assignment_role not in {"RADIOLOGIST","RAD_MANAGER"}:fail(403,"A radiologist assignment is required")
 o=readable(db,actor,oid,True);w=workflow_for(db,o,actor,True)
 if o.status!="SIGNED":fail(409,"Only a currently signed imaging order can receive a report")
 if not w or w.status not in {"INTERPRETATION_IN_PROGRESS","REPORT_FINALIZED","REPORT_REJECTED"}:fail(409,"Interpretation must be active before report drafting")
 if w.version!=data.expected_workflow_version:fail(409,"This radiology workflow changed. Reload")
 study=db.query(ImagingStudy).filter(ImagingStudy.id==data.study_id,ImagingStudy.order_id==o.id,ImagingStudy.patient_id==o.patient_id,ImagingStudy.encounter_id==o.encounter_id,ImagingStudy.status=="ACQUISITION_COMPLETED").with_for_update().populate_existing().first()
 if not study:fail(422,"The completed study does not belong to this order, patient, and encounter")
 prior=db.query(RadiologyReportRevision).filter(RadiologyReportRevision.order_id==o.id).order_by(RadiologyReportRevision.revision_number.desc()).with_for_update().populate_existing().first()
 if prior and prior.status not in {"FINALIZED","REJECTED"}:fail(409,"An unfinished report revision exists")
 if prior and not data.amendment_reason:fail(422,"An amendment reason is required")
 if not prior and data.amendment_reason:fail(422,"An amendment reason is valid only after finalization or rejection")
 r=RadiologyReportRevision(workflow_id=w.id,study_id=study.id,order_id=o.id,revision_number=prior.revision_number+1 if prior else 1,previous_revision_id=prior.id if prior else None,findings=data.findings,impression=data.impression,status="DRAFT",version=1,amendment_reason=data.amendment_reason,authored_by_user_id=actor.user_id)
 db.add(r);db.flush();db.add(RadiologyReportEvent(report_revision_id=r.id,sequence=1,report_version=1,from_status=None,to_status="DRAFT",actor_user_id=actor.user_id,reason=data.amendment_reason))
 source=w.status;w.status="REPORT_DRAFT";w.version+=1;event(db,actor,w,source,w.status,"amendment" if prior else None);audit(db,actor,o,w,"report drafted");db.flush();return o
def transition_report(db,actor,oid,rid,data):
 if actor.assignment_role not in {"RADIOLOGIST","RAD_MANAGER"}:fail(403,"A radiologist assignment is required")
 o=readable(db,actor,oid,True);w=workflow_for(db,o,actor,True)
 if o.status!="SIGNED":fail(409,"Only a currently signed imaging order can be finalized")
 if not w or w.version!=data.expected_workflow_version:fail(409,"This radiology workflow changed. Reload")
 r=db.query(RadiologyReportRevision).filter(RadiologyReportRevision.id==rid,RadiologyReportRevision.order_id==o.id).with_for_update().populate_existing().first()
 if not r:fail(404,"Radiology report revision not found")
 if r.version!=data.expected_report_version:fail(409,"This report changed. Reload")
 allowed={"DRAFT":{"VERIFIED","REJECTED"},"VERIFIED":{"FINALIZED","REJECTED"}}
 if data.status not in allowed.get(r.status,set()):fail(409,f"Report cannot move from {r.status} to {data.status}")
 source=r.status;r.status=data.status;r.version+=1
 if data.status=="VERIFIED":r.verified_by_user_id=actor.user_id;r.verified_at=func.now()
 elif data.status=="FINALIZED":
  r.finalized_by_user_id=actor.user_id;r.finalized_at=func.now()
  db.add(Notification(user_id=o.requested_by_user_id,title="Imaging report available",message="A finalized imaging report is ready for clinical follow-up.",type="RADIOLOGY_RESULT"))
 db.add(RadiologyReportEvent(report_revision_id=r.id,sequence=r.version,report_version=r.version,from_status=source,to_status=data.status,actor_user_id=actor.user_id,reason=data.comment))
 ws=w.status;w.status={"VERIFIED":"REPORT_VERIFIED","FINALIZED":"REPORT_FINALIZED","REJECTED":"REPORT_REJECTED"}[data.status];w.version+=1;event(db,actor,w,ws,w.status,data.comment);audit(db,actor,o,w,"report "+data.status.lower());db.flush();return o
def projection(db,actor,o):
 d=db.query(ImagingOrderDetail).filter(ImagingOrderDetail.order_id==o.id).first();p=db.get(User,o.patient_id);e=db.get(Encounter,o.encounter_id);w=workflow_for(db,o,actor)
 if not d or not p or not e:raise HTTPException(503,"Imaging order relationships are incomplete")
 studies=db.query(ImagingStudy).filter(ImagingStudy.order_id==o.id).all();reports=db.query(RadiologyReportRevision).filter(RadiologyReportRevision.order_id==o.id).order_by(RadiologyReportRevision.revision_number).all();events=[] if not w else db.query(RadiologyWorkflowEvent).filter(RadiologyWorkflowEvent.workflow_id==w.id).order_by(RadiologyWorkflowEvent.sequence).all()
 status="ORDER_CANCELLED" if o.status=="CANCELLED" else w.status if w else "AWAITING_REVIEW"
 return {"order_id":o.id,"patient":{"id":p.id,"mrn":p.mrn,"full_name":p.full_name},"encounter":{"id":e.id,"status":e.status},"priority":o.priority,"order_status":o.status,"radiology_status":status,"version":w.version if w else 0,"modality":d.modality,"body_region":d.body_region,"requested_procedure":d.requested_procedure,"scheduled_at":w.scheduled_at if w else None,"pacs_available":False,"allowed_actions":[] if o.status=="CANCELLED" else sorted(TRANSITIONS.get(status,set())),"studies":[{n:getattr(s,n) for n in "id study_identifier modality body_region status version acquisition_started_at acquisition_completed_at acquired_by_user_id".split()} for s in studies],"reports":[{**{n:getattr(r,n) for n in "id study_id revision_number previous_revision_id findings impression status version amendment_reason authored_by_user_id verified_by_user_id finalized_by_user_id authored_at verified_at finalized_at".split()},"allowed_actions":[] if o.status=="CANCELLED" else ["VERIFIED","REJECTED"] if r.status=="DRAFT" and actor.assignment_role in {"RADIOLOGIST","RAD_MANAGER"} else ["FINALIZED","REJECTED"] if r.status=="VERIFIED" and actor.assignment_role in {"RADIOLOGIST","RAD_MANAGER"} else []} for r in reports],"events":[{"sequence":x.sequence,"from_status":x.from_status,"to_status":x.to_status,"actor_user_id":x.actor_user_id,"reason":x.reason,"created_at":x.created_at} for x in events]}
def released_report(db,actor,oid):
 if actor.role not in orders.CLINICAL_ROLES|orders.PATIENT_ROLES:fail(403,"Released imaging reports are restricted")
 o=orders.readable(db,actor,oid)
 if o.order_type!="IMAGING":fail(404,"Imaging order not found")
 if o.signed_at is None or o.status=="CANCELLED":fail(404,"Released imaging reports are unavailable for this order")
 rows=db.query(RadiologyReportRevision).join(ImagingStudy,ImagingStudy.id==RadiologyReportRevision.study_id).filter(RadiologyReportRevision.order_id==o.id,RadiologyReportRevision.status=="FINALIZED",ImagingStudy.order_id==o.id,ImagingStudy.patient_id==o.patient_id,ImagingStudy.encounter_id==o.encounter_id).order_by(RadiologyReportRevision.revision_number.desc()).all();r=rows[0] if rows else None
 response={"order_id":o.id,"patient_id":o.patient_id,"encounter_id":o.encounter_id,"report":None if not r else {"revision_number":r.revision_number,"findings":r.findings,"impression":r.impression,"finalized_at":r.finalized_at,"amended":r.revision_number>1},"pacs_available":False}
 if actor.role in orders.CLINICAL_ROLES:
  response["revision_history"]=[{"revision_number":row.revision_number,"findings":row.findings,"impression":row.impression,"finalized_at":row.finalized_at} for row in rows]
 return response
