from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src import radiology_service as service
from src.auth import get_current_user
from src.database import get_db
from src.schemas.radiology import ImagingOrderCreate,RadiologyQueueResponse,RadiologyReportCreate,RadiologyReportTransition,RadiologyTransition
router=APIRouter(prefix="/radiology",tags=["Radiology"])
def staff(db:Session=Depends(get_db),token=Depends(get_current_user)):
 service.require_schema(db);return service.actor_for(db,token)
def clinician(db:Session=Depends(get_db),token=Depends(get_current_user)):
 service.require_schema(db);return service.orders.actor_for(db,token)
def mutate(db,callback,*args):
 try:
  o=callback(db,*args);result=service.projection(db,args[0],o) if isinstance(args[0],service.RadiologyActor) else service.orders.projection(db,args[0],o);db.commit();return result
 except IntegrityError:db.rollback();raise HTTPException(409,"A conflicting radiology update was saved. Reload before retrying") from None
 except Exception:db.rollback();raise
@router.post("/orders",status_code=201)
def create(data:ImagingOrderCreate,db:Session=Depends(get_db),actor=Depends(clinician)):return mutate(db,service.create_imaging_order,actor,data)
@router.get("/orders",response_model=RadiologyQueueResponse)
def queue(search:str|None=Query(None,max_length=255),order_id:int|None=Query(None,gt=0),encounter_id:int|None=Query(None,gt=0),modality:str|None=None,body_region:str|None=None,priority:str|None=None,status:str|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),db:Session=Depends(get_db),actor=Depends(staff)):
 if priority and priority not in {"ROUTINE","URGENT","STAT"}:raise HTTPException(422,"Unknown priority")
 if status and status not in set(service.TRANSITIONS)|{"ORDER_CANCELLED"}:raise HTTPException(422,"Unknown radiology status")
 q=service.queue_query(db,actor,search,priority,status,order_id,encounter_id,modality,body_region);total=q.count();rows=q.order_by(service.ClinicalOrder.created_at.desc()).offset(offset).limit(limit).all();return {"items":[service.projection(db,actor,o) for o in rows],"total":total}
@router.get("/orders/{order_id}")
def detail(order_id:int,db:Session=Depends(get_db),actor=Depends(staff)):return service.projection(db,actor,service.readable(db,actor,order_id))
@router.get("/orders/{order_id}/released-report")
def released(order_id:int,db:Session=Depends(get_db),actor=Depends(clinician)):return service.released_report(db,actor,order_id)
@router.post("/orders/{order_id}/transitions")
def transition(order_id:int,data:RadiologyTransition,db:Session=Depends(get_db),actor=Depends(staff)):return mutate(db,service.transition,actor,order_id,data)
@router.post("/orders/{order_id}/reports",status_code=201)
def report(order_id:int,data:RadiologyReportCreate,db:Session=Depends(get_db),actor=Depends(staff)):return mutate(db,service.create_report,actor,order_id,data)
@router.post("/orders/{order_id}/reports/{report_id}/transitions")
def report_transition(order_id:int,report_id:int,data:RadiologyReportTransition,db:Session=Depends(get_db),actor=Depends(staff)):return mutate(db,service.transition_report,actor,order_id,report_id,data)
