from datetime import date, datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os
import logging
import hashlib

logger = logging.getLogger(__name__)

# Configuration from Environment Variables
LEGACY_DEVELOPMENT_KEY_SHA256 = "b33d24ac6dc686d4b70684b0f3ce96409c03e6437cf6a80c06d4e66774a8a1c5"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or not SECRET_KEY.strip():
    raise RuntimeError("Set SECRET_KEY to a non-blank signing key before starting MediNexus.")
if IS_PRODUCTION and (
    len(SECRET_KEY) < 32
    or hashlib.sha256(SECRET_KEY.encode()).hexdigest() == LEGACY_DEVELOPMENT_KEY_SHA256
):
    raise RuntimeError("Production requires a unique SECRET_KEY of at least 32 characters.")

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ALLOWED_ALGORITHMS = ["HS256"]
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

if ALGORITHM not in ALLOWED_ALGORITHMS:
    logger.warning("Unsafe JWT algorithm '%s' specified. Forcing HS256.", ALGORITHM)
    ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt", "pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    user_id: Optional[int] = None
    role: Optional[str] = None

class User(BaseModel):
    id: int
    email: Optional[str] = None
    full_name: str
    role: str
    blood_group: Optional[str] = None
    mobile_no: Optional[str] = None
    mrn: Optional[str] = None
    date_of_birth: Optional[date] = None
    email_verified: Optional[int] = 1
    mobile_verified: Optional[int] = 1
    profile_data: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

from src.database import get_db

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        
        if email is None or user_id is None:
            raise credentials_exception
            
        # Verify user still exists and role matches DB
        from src.models import User as DBUser
        user = db.query(DBUser).filter(
            DBUser.id == user_id,
            DBUser.password_hash.is_not(None),
        ).first()
        if not user:
            raise credentials_exception
            
        token_data = TokenData(email=user.email, user_id=user.id, role=user.role or role)
    except JWTError:
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        raise credentials_exception
        
    return token_data

async def get_current_admin(current_user: TokenData = Depends(get_current_user)):
    if current_user.role not in ["admin", "hospital_admin", "department_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


async def require_patient_management_role(current_user: TokenData = Depends(get_current_user)):
    """Patient registry is initially limited to hospital wide administrators."""
    if current_user.role not in {"admin", "hospital_admin"}:
        raise HTTPException(status_code=403, detail="Patient registry administrator privileges required")
    return current_user

async def get_current_doctor(current_user: TokenData = Depends(get_current_user)):
    if current_user.role not in ["doctor", "emergency_doctor", "admin", "hospital_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor authorization required"
        )
    return current_user


