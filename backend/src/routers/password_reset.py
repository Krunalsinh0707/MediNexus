import re
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database import get_db
from src.models import User, PasswordResetOTP
from src.schemas.password_reset import (
    ForgotPasswordRequest,
    VerifyOTPRequest,
    ResetPasswordRequest,
    PasswordResetResponse
)
from src.services.otp_service import otp_service
from src.services.email_service import email_service
from src.auth import get_password_hash
from src.security.rate_limiter import rate_limit

logger = logging.getLogger("health_analyzer.password_reset_router")

router = APIRouter(tags=["Password Reset System"])

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return False, "Password must contain at least one special character."
    return True, "Password meets strength criteria."

@router.post("/forgot-password", response_model=PasswordResetResponse)
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    _limiter: None = Depends(rate_limit(max_requests=5, window_seconds=600, prefix="forgot_pw"))
):
    """
    Initiate Forgot Password flow. Checks user existence, generates OTP, and dispatches email.
    """
    email_clean = req.email.lower().strip()

    # 1. Check if user exists in database
    user = db.query(User).filter(
        func.lower(func.btrim(User.email)) == email_clean,
        User.password_hash.is_not(None),
    ).first()
    if not user:
        return PasswordResetResponse(success=False, message="Email not registered")

    # Extract request IP and user agent for audit
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # 2. Generate and save OTP
    ok, msg, otp_code = otp_service.create_otp_for_email(
        db=db,
        email=email_clean,
        ip_address=ip_addr,
        user_agent=user_agent
    )
    if not ok:
        return PasswordResetResponse(success=False, message=msg)

    logger.info(f"🔑 Password reset OTP requested and generated for {email_clean}")

    # 3. Send email asynchronously via Gmail SMTP
    try:
        user_name = user.full_name or "User"
        await email_service.send_password_reset_otp(email_clean, otp_code, user_name)
    except Exception as e:
        logger.error(f"Failed to dispatch reset email: {e}")
        return PasswordResetResponse(
            success=False,
            message="Failed to deliver reset email. Please contact hospital support."
        )

    return PasswordResetResponse(success=True, message="OTP Sent Successfully")

@router.post("/verify-otp", response_model=PasswordResetResponse)
async def verify_otp(
    req: VerifyOTPRequest,
    db: Session = Depends(get_db),
    _limiter: None = Depends(rate_limit(max_requests=10, window_seconds=60, prefix="verify_otp"))
):
    """
    Verify 6-digit OTP code for password reset.
    """
    email_clean = req.email.lower().strip()
    otp_clean = req.otp.strip()

    eligible_user = db.query(User.id).filter(
        func.lower(func.btrim(User.email)) == email_clean,
        User.password_hash.is_not(None),
    ).first()
    if not eligible_user:
        return PasswordResetResponse(success=False, message="Email not registered")

    ok, msg = otp_service.verify_otp_for_email(db, email_clean, otp_clean)
    if not ok:
        return PasswordResetResponse(success=False, message=msg)

    return PasswordResetResponse(success=True, message="OTP Verified")

@router.post("/reset-password", response_model=PasswordResetResponse)
async def reset_password(
    req: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _limiter: None = Depends(rate_limit(max_requests=5, window_seconds=600, prefix="reset_pw"))
):
    """
    Reset user password after verifying passwords match, strength rules, and OTP record.
    """
    email_clean = req.email.lower().strip()

    # 1. Check passwords match
    if req.password != req.confirm_password:
        return PasswordResetResponse(success=False, message="Passwords do not match.")

    # 2. Check password strength
    is_strong, strength_msg = validate_password_strength(req.password)
    if not is_strong:
        return PasswordResetResponse(success=False, message=strength_msg)

    # 3. Check OTP record status
    otp_record = db.query(PasswordResetOTP).filter(
        PasswordResetOTP.email == email_clean
    ).order_by(PasswordResetOTP.id.desc()).first()

    if not otp_record or not otp_record.verified:
        return PasswordResetResponse(success=False, message="OTP verification required before resetting password.")

    # 4. Hash new password using bcrypt
    new_pw_hash = get_password_hash(req.password)

    # 5. Update user in MySQL database
    user = db.query(User).filter(
        func.lower(func.btrim(User.email)) == email_clean,
        User.password_hash.is_not(None),
    ).first()
    if not user:
        return PasswordResetResponse(success=False, message="Email not registered")

    user.password_hash = new_pw_hash
    db.commit()

    # 6. Delete OTP
    otp_service.delete_otp_for_email(db, email_clean)

    logger.info(f"🔑 Password successfully reset for user {email_clean}")
    return PasswordResetResponse(success=True, message="Password Updated Successfully")
