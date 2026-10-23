from fastapi import FastAPI, Depends
from sqlalchemy import func
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


from src.config.version_config import VERSION_CONFIG

# Internal Module Imports
from src.database import get_db_connection, init_db, require_current_schema, SessionLocal
from src.auth import IS_PRODUCTION, get_password_hash
from src.models import User as DBUser, PasswordResetOTP

# Router Imports
from src.routers import (
    auth_router,
    reports_router,
    cbc_router,
    admin_router,
    chatbot_router,
    password_reset,
    departments_router,
    doctors_router,
    appointments_router,
    medical_reports_router,
    emergency_router,
    communication_router,
    analytics_router,
    notifications_router,
    clinical_chat_router,
    patients_router,
    encounters_router,
    medical_history_router,
    clinical_orders_router,
    medication_orders_router,
    pharmacy_router,
    laboratory_router,
    radiology_router,
    inpatient_router,
    nursing_router,
    billing_router,
    insurance_router,
    inventory_router,
    workforce_router
)

def configured_default_admin_password():
    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD")
    if not admin_password or not admin_password.strip():
        raise RuntimeError(
            "Set DEFAULT_ADMIN_PASSWORD before enabling default-admin creation."
        )
    if IS_PRODUCTION and len(admin_password) < 16:
        raise RuntimeError(
            "Production default-admin creation requires an explicit "
            "DEFAULT_ADMIN_PASSWORD of at least 16 characters."
        )
    return admin_password


def create_default_admin():
    admin_password = configured_default_admin_password()
    db = SessionLocal()
    try:
        admin_email = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@gmail.com")
        admin = db.query(DBUser).filter(
            func.lower(func.btrim(DBUser.email)) == admin_email.strip().lower(),
            DBUser.password_hash.is_not(None),
        ).first()
        if not admin:
            hashed_password = get_password_hash(admin_password)
            new_admin = DBUser(
                email=admin_email,
                mobile_no=os.getenv("DEFAULT_ADMIN_PHONE", "0000000000"),
                blood_group="O+",
                password_hash=hashed_password,
                full_name="System Admin",
                role="hospital_admin"
            )
            db.add(new_admin)
            db.commit()
            print("✅ Default admin user created successfully.")
        else:
            print("ℹ️ Default admin user already exists. Skipping creation.")
    except Exception:
        db.rollback()
        print("❌ Error creating default admin user.")
        raise
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_defaults = os.getenv("HMS_SEED_DEFAULTS", "false").lower() == "true"
    if seed_defaults:
        configured_default_admin_password()
    require_current_schema()
    # Explicit opt-in retains the existing department/routing/admin seed behavior.
    if seed_defaults:
        init_db()
        create_default_admin()
    yield

# Schema initialization is explicit; importing the API never creates tables.

# ---------------- APP CONFIG ----------------
app = FastAPI(
    title=VERSION_CONFIG["project_name"],
    description=VERSION_CONFIG["description"],
    version=VERSION_CONFIG["version"],
    lifespan=lifespan
)

# ---------------- CORS ----------------
def _get_allowed_origins() -> List[str]:
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    extra_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return list(dict.fromkeys(default_origins + extra_origins))

ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
ALLOWED_CORS_HEADERS = ["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=ALLOWED_CORS_METHODS,
    allow_headers=ALLOWED_CORS_HEADERS,
)

from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("health_analyzer.api")

# ---------------- SECURITY HEADERS MIDDLEWARE ----------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ---------------- GLOBAL UNHANDLED EXCEPTION HANDLER ----------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact hospital administrator."}
    )

# ---------------- INCLUDE API ROUTERS ----------------
app.include_router(auth_router.router)
app.include_router(reports_router.router)
app.include_router(cbc_router.router)
app.include_router(admin_router.router)
app.include_router(chatbot_router.router)
app.include_router(password_reset.router)
app.include_router(departments_router.router)
app.include_router(doctors_router.router)
app.include_router(appointments_router.router)
app.include_router(medical_reports_router.router)
app.include_router(emergency_router.router)
app.include_router(communication_router.router)
app.include_router(analytics_router.router)
app.include_router(notifications_router.router)
app.include_router(clinical_chat_router.router)
app.include_router(patients_router.router)
app.include_router(encounters_router.router)
app.include_router(medical_history_router.router)
app.include_router(clinical_orders_router.router)
app.include_router(medication_orders_router.router)
app.include_router(pharmacy_router.router)
app.include_router(laboratory_router.router)
app.include_router(radiology_router.router)
app.include_router(inpatient_router.router)
app.include_router(nursing_router.router)
app.include_router(billing_router.router)
app.include_router(insurance_router.router)
app.include_router(inventory_router.router)
app.include_router(workforce_router.router)

from sqlalchemy import text
from src.database import get_db

# ---------------- BASIC ROOT ROUTE ----------------
@app.get("/")
def root():
    return {
        "message": f"{VERSION_CONFIG['project_name']} running successfully",
        "version": VERSION_CONFIG["version"],
        "build": VERSION_CONFIG["build_number"],
        "status": "online"
    }

@app.get("/health")
def health_check(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "PostgreSQL",
            "connected": True
        }
    except Exception as e:
        logger.error(f"Health check database ping failed: {e}")
        return {
            "status": "unhealthy",
            "database": "PostgreSQL",
            "connected": False
        }


