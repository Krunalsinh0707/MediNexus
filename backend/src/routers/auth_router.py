from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta, datetime
import random
import re
import json
import logging

from src.database import get_db_connection
from src.auth import (
    Token, User, get_current_user, get_password_hash,
    verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
)
from src.sms_service import send_otp_sms
from src.security.rate_limiter import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])

ALLOWED_BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
SAFE_USER_COLUMNS = "id, email, full_name, role, blood_group, mobile_no, mrn, date_of_birth, email_verified, mobile_verified, profile_data, created_at, updated_at"

class UserCreate(BaseModel):
    email: str
    mobile_no: str
    blood_group: str
    password: str
    full_name: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    blood_group: Optional[str] = None
    mobile_no: Optional[str] = None
    profile_data: Optional[dict] = None

class ForgotPasswordRequest(BaseModel):
    email: str
    mobile_no: str
    full_name: str
    blood_group: str

class ResetPasswordRequest(BaseModel):
    mobile_no: str
    otp: str
    new_password: str

def _is_valid_email(email: str) -> bool:
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

def _normalize_mobile(mobile_no: str) -> str:
    return re.sub(r"\D", "", mobile_no or "")

def _is_valid_mobile(mobile_no: str) -> bool:
    normalized = _normalize_mobile(mobile_no)
    return 10 <= len(normalized) <= 15

@router.post("/register", response_model=Token)
async def register(
    user: UserCreate,
    _limiter: None = Depends(rate_limit(max_requests=5, window_seconds=600, prefix="register"))
):
    email = (user.email or "").strip().lower()
    mobile_no = _normalize_mobile(user.mobile_no)
    full_name = (user.full_name or "").strip()
    blood_group = (user.blood_group or "").strip().upper()

    if not _is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    if not _is_valid_mobile(mobile_no):
        raise HTTPException(status_code=400, detail="Valid mobile number is required")

    if blood_group not in ALLOWED_BLOOD_GROUPS:
        raise HTTPException(status_code=400, detail=f"Invalid blood group. Allowed values: {', '.join(sorted(ALLOWED_BLOOD_GROUPS))}")

    if len(full_name) < 2 or len(full_name) > 100:
        raise HTTPException(status_code=400, detail="Full name must be between 2 and 100 characters")

    if len(user.password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE lower(btrim(email)) = %s", (email,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    cursor.execute("SELECT id FROM users WHERE regexp_replace(mobile_no, '[^0-9]', '', 'g') = %s", (mobile_no,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Mobile number already registered")

    hashed_password = get_password_hash(user.password)

    cursor.execute(
        """
        INSERT INTO users (email, mobile_no, blood_group, password_hash, full_name, role)
        VALUES (%s, %s, %s, %s, %s, 'user') RETURNING id
        """,
        (email, mobile_no, blood_group, hashed_password, full_name)
    )
    inserted_user = cursor.fetchone()
    if not inserted_user or inserted_user.get("id") is None:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail="Could not retrieve the registered user ID")
    user_id = int(inserted_user["id"])
    conn.commit()

    access_token = create_access_token(
        data={"sub": email, "user_id": user_id, "role": "user"},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    cursor.close()
    conn.close()

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/token", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    _limiter: None = Depends(rate_limit(max_requests=10, window_seconds=60, prefix="login"))
):
    login_id_raw = (form_data.username or "").strip()
    login_id_email = login_id_raw.lower()
    login_id_mobile = _normalize_mobile(login_id_raw)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if "@" in login_id_raw:
        cursor.execute("SELECT id, email, password_hash, role FROM users WHERE lower(btrim(email)) = %s AND password_hash IS NOT NULL", (login_id_email,))
    else:
        cursor.execute("SELECT id, email, password_hash, role FROM users WHERE regexp_replace(mobile_no, '[^0-9]', '', 'g') = %s AND password_hash IS NOT NULL", (login_id_mobile,))
    user = cursor.fetchone()

    if not user or not verify_password(form_data.password, user["password_hash"]):
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    access_token = create_access_token(
        data={"sub": user["email"], "user_id": user["id"], "role": user["role"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    cursor.close()
    conn.close()

    return {"access_token": access_token, "token_type": "bearer"}





@router.get("/users/me", response_model=User)
async def read_users_me(current_user=Depends(get_current_user)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT {SAFE_USER_COLUMNS} FROM users WHERE id = %s", (current_user.user_id,))
        user = cursor.fetchone()
        
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Ensure profile_data is parsed as dict if returned as string
        if user.get("profile_data") and isinstance(user["profile_data"], str):
            try:
                user["profile_data"] = json.loads(user["profile_data"])
            except Exception:
                user["profile_data"] = {}
        elif not user.get("profile_data"):
            user["profile_data"] = {}
            
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user profile")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()


@router.put("/users/me", response_model=User)
async def update_user_me(user_update: UserUpdate, current_user=Depends(get_current_user)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        ALLOWED_COLUMNS = {"full_name", "blood_group", "mobile_no", "profile_data"}
        update_data = {k: v for k, v in user_update.dict(exclude_unset=True).items() if k in ALLOWED_COLUMNS}
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")
        
        if "mobile_no" in update_data:
            update_data["mobile_no"] = _normalize_mobile(update_data["mobile_no"])
            if not _is_valid_mobile(update_data["mobile_no"]):
                raise HTTPException(status_code=400, detail="Invalid mobile number format")

        # Serialize profile_data if provided
        if "profile_data" in update_data and isinstance(update_data["profile_data"], dict):
            update_data["profile_data"] = json.dumps(update_data["profile_data"])

        columns = ", ".join([f"{k} = %s" for k in update_data.keys()])
        values = list(update_data.values())
        values.append(current_user.user_id)
        
        query = f"UPDATE users SET {columns}, updated_at = NOW() WHERE id = %s"
        cursor.execute(query, tuple(values))
        
        # Record audit log
        try:
            audit_details = json.dumps({"updated_fields": list(update_data.keys())})
            cursor.execute(
                "INSERT INTO audit_logs (user_id, action, details, status) VALUES (%s, %s, %s, %s)",
                (current_user.user_id, "Patient Profile Information Updated", audit_details, "Success")
            )
        except Exception as audit_err:
            print("Audit log error:", audit_err)

        conn.commit()
        
        cursor.execute(f"SELECT {SAFE_USER_COLUMNS} FROM users WHERE id = %s", (current_user.user_id,))
        updated_user = cursor.fetchone()

        if updated_user and updated_user.get("profile_data") and isinstance(updated_user["profile_data"], str):
            try:
                updated_user["profile_data"] = json.loads(updated_user["profile_data"])
            except Exception:
                updated_user["profile_data"] = {}
        elif updated_user and not updated_user.get("profile_data"):
            updated_user["profile_data"] = {}

        return updated_user
        
    except HTTPException:
        raise
    except Exception as e:
        if "duplicate" in str(e).lower():
            raise HTTPException(status_code=400, detail="Mobile number already registered by another user")
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user profile")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()


@router.get("/users/me/activity")
async def get_user_activity(current_user=Depends(get_current_user)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, action, details, created_at, status FROM audit_logs WHERE user_id = %s ORDER BY created_at DESC LIMIT 10",
            (current_user.user_id,)
        )
        logs = cursor.fetchall() or []
        result = []
        for log in logs:
            dt = log.get("created_at")
            result.append({
                "id": log.get("id"),
                "action": log.get("action"),
                "details": log.get("details"),
                "status": log.get("status", "Success"),
                "timestamp": dt.isoformat() if hasattr(dt, 'isoformat') else str(dt) if dt else None
            })
        return result
    except Exception as e:
        print("Error fetching activity logs:", e)
        return []
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
