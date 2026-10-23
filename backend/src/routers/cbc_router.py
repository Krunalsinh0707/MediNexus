from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from typing import Optional
import os
import shutil
import json
import logging
from pathlib import Path

from src.database import get_db_connection
from src.auth import get_current_user
from src.pdf_service import extract_cbc_from_file
from src.cbc_analysis import interpret_cbc, process_manual_cbc
from src.security.rate_limiter import rate_limit
from src.security.file_security import validate_uploaded_file, sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter(tags=["CBC Analysis"])


def _cbc_upload_directory() -> Path:
    default_root = Path(__file__).resolve().parents[2] / "uploads"
    return Path(os.getenv("HMS_UPLOAD_ROOT", default_root)).resolve()

class ManualCbcInput(BaseModel):
    Hemoglobin: Optional[float] = None
    RBC: Optional[float] = None
    WBC: Optional[float] = None
    Platelets: Optional[float] = None
    ESR: Optional[float] = None
    MCV: Optional[float] = None
    MCH: Optional[float] = None
    RDW: Optional[float] = None
    Neutrophils: Optional[float] = None
    Lymphocytes: Optional[float] = None
    Monocytes: Optional[float] = None
    Eosinophils: Optional[float] = None
    Basophils: Optional[float] = None

class CbcReportSave(BaseModel):
    cbc: dict
    interpretation: dict
    source: str = "manual"

@router.post("/cbc/upload-report")
async def upload_cbc_report(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    _limiter: None = Depends(rate_limit(max_requests=10, window_seconds=60, prefix="cbc_upload"))
):
    content = await validate_uploaded_file(file, max_size_bytes=10 * 1024 * 1024)
    safe_filename = sanitize_filename(file.filename, prefix=f"cbc_{current_user.user_id}_")

    upload_directory = _cbc_upload_directory()
    upload_directory.mkdir(parents=True, exist_ok=True)
    file_path = upload_directory / safe_filename

    try:
        file_path.write_bytes(content)
        cbc_data = extract_cbc_from_file(str(file_path))
        interpretation = interpret_cbc(cbc_data)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    
    # Auto-index extracted CBC document into ChromaDB vector store for RAG
    try:
        from src.clinical_chat.vector_store import vector_store
        text_summary = f"Uploaded CBC Report '{file.filename}': Extracted Hematology Data: {json.dumps(cbc_data)} | Health Score: {interpretation.get('health_score')}/100 | Urgency: {interpretation.get('urgency')}"
        vector_store.add_document_chunks(
            user_id=current_user.user_id,
            doc_id=safe_filename,
            chunks=[text_summary],
            metadata={"filename": safe_filename, "type": "cbc_report"}
        )
    except Exception as e:
        logger.warning(f"[WARNING] Failed to index CBC upload in ChromaDB: {e}")

    return {"cbc": cbc_data, "interpretation": interpretation}


@router.post("/cbc/analyze")
async def analyze_manual_cbc(data: ManualCbcInput, current_user=Depends(get_current_user)):
    input_data = {k: v for k, v in data.dict().items() if v is not None}
    cbc_data = process_manual_cbc(input_data)
    interpretation = interpret_cbc(cbc_data)

    return {"cbc": cbc_data, "interpretation": interpretation}


@router.post("/cbc/save")
async def save_cbc_report(report: CbcReportSave, current_user=Depends(get_current_user)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cbc_reports (user_id, cbc_json, interpretation_json, probability, source)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            current_user.user_id,
            json.dumps(report.cbc),
            json.dumps(report.interpretation),
            report.interpretation.get("ml_model_insights", {}).get("probability"),
            report.source
        ))
        conn.commit()
        return {"status": "saved"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving CBC report: {e}")
        raise HTTPException(status_code=500, detail="Failed to save CBC report")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()


@router.get("/cbc/history")
async def get_cbc_history(limit: int = 50, offset: int = 0, current_user=Depends(get_current_user)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, created_at, cbc_json, interpretation_json, probability, source
            FROM cbc_reports
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (current_user.user_id, limit, offset))
        reports = cursor.fetchall()
        
        for r in reports:
            if r.get('cbc_json'):
                r['cbc'] = json.loads(r['cbc_json']) if isinstance(r['cbc_json'], str) else r['cbc_json']
            if r.get('interpretation_json'):
                r['interpretation'] = json.loads(r['interpretation_json']) if isinstance(r['interpretation_json'], str) else r['interpretation_json']
            if 'cbc_json' in r: del r['cbc_json']
            if 'interpretation_json' in r: del r['interpretation_json']
            
        return {"reports": reports}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching CBC history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve CBC history")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
