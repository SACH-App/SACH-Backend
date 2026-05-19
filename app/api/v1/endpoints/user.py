from datetime import datetime, timezone
import random
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    get_password_hash, verify_password, create_access_token,
    create_refresh_token, decode_token
)
from app.core.redis import get_redis
from app.core.logging_config import get_logger
from app.models.user import User
from app.models.evidence import Evidence
from app.schemas.user import (
    UserCreate, UserResponse, UserUpdate, ChangePassword,
    PasswordResetRequest, PasswordReset, Token, RefreshTokenRequest,
    OTPRequest, OTPVerify
)
from app.schemas.fir import FIRCreate, FIRResponse, FIRDetailResponse
from app.schemas.evidence import EvidenceResponse
from app.schemas.notification import NotificationResponse
from app.schemas.pagination import PaginatedResponse
from app.services import nadra_service
from app.services import user_service, fir_service, notification_service, storage_service
from app.services.email_service import send_otp_email

logger = get_logger(__name__)
router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/user/login")


# ────────────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new citizen. Role is always 'citizen' — cannot be overridden."""
    # 1. Verify CNIC against Mock NADRA API AND match the name
    await nadra_service.verify_cnic(user_in.cnic, expected_name=user_in.full_name)

    # 2. Check if user already exists
    existing = await user_service.get_user_by_cnic(db, user_in.cnic)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this CNIC already exists.",
        )

    # 3. Check email uniqueness if provided
    if user_in.email:
        existing_email = await user_service.get_user_by_email(db, user_in.email)
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists.",
            )

    # 4. Fetch address from NADRA (best-effort — won't block signup on failure)
    address = await nadra_service.fetch_citizen_address(user_in.cnic)
    logger.info(f"NADRA address for {user_in.cnic}: {address}")

    # 5. Create citizen (role is hardcoded in the service)
    db_user = await user_service.create_citizen(
        db, cnic=user_in.cnic, full_name=user_in.full_name,
        password=user_in.password, phone=user_in.phone, email=user_in.email,
        address=address
    )
    return db_user


@router.post("/login", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """OAuth2 login — returns access + refresh tokens. Use CNIC as 'username'."""
    user = await user_service.get_user_by_cnic(db, form_data.username)

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect CNIC or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact admin."
        )

    # Update last login
    await user_service.update_last_login(db, user)

    access_token = create_access_token(data={"sub": user.cnic})
    refresh_token = create_refresh_token(data={"sub": user.cnic})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/login/otp/request")
async def request_otp(body: OTPRequest, db: AsyncSession = Depends(get_db)):
    """Request an email OTP for login."""
    user = await user_service.get_user_by_cnic(db, body.cnic)
    if not user:
        return {"message": "If the CNIC is registered, an OTP will be sent to the registered email."}
        
    if not user.email:
        logger.warning(f"OTP requested for CNIC {user.cnic} but no email is on file.")
        return {"message": "If the CNIC is registered, an OTP will be sent to the registered email."}
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact admin."
        )

    # Generate 6-digit OTP
    otp_code = str(random.randint(100000, 999999))
    
    # Store in Redis (5 min TTL)
    redis_client = get_redis()
    if redis_client:
        await redis_client.setex(f"otp:{user.cnic}", 300, otp_code)
        
    # Send Email asynchronously
    try:
        await send_otp_email(user.email, otp_code)
    except Exception as e:
        logger.error(f"Failed to send OTP to {user.email}: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email.")
        
    return {"message": "If the CNIC is registered, an OTP will be sent to the registered email."}


@router.post("/login/otp/verify", response_model=Token)
async def verify_otp(body: OTPVerify, db: AsyncSession = Depends(get_db)):
    """Verify an email OTP and return JWT tokens."""
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(status_code=503, detail="Service unavailable")
        
    stored_otp = await redis_client.get(f"otp:{body.cnic}")
    if not stored_otp or stored_otp != body.otp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP."
        )
        
    user = await user_service.get_user_by_cnic(db, body.cnic)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated."
        )
        
    # Delete OTP to prevent reuse
    await redis_client.delete(f"otp:{body.cnic}")
    
    # Update last login
    await user_service.update_last_login(db, user)

    access_token = create_access_token(data={"sub": user.cnic})
    refresh_token = create_refresh_token(data={"sub": user.cnic})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
async def refresh_token(body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Get a new access token using a refresh token."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    cnic = payload.get("sub")
    user = await user_service.get_user_by_cnic(db, cnic)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated"
        )

    access_token = create_access_token(data={"sub": user.cnic})
    refresh_token = create_refresh_token(data={"sub": user.cnic})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    """Log out by blacklisting the current JWT in Redis."""
    payload = decode_token(token)
    if payload:
        exp = payload.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        ttl = int(exp - now)
        if ttl > 0:
            redis_client = get_redis()
            if redis_client:
                await redis_client.setex(f"blacklist:{token}", ttl, "revoked")
    return {"message": "Successfully logged out"}


# ────────────────────────────────────────────────────────────────────
# PASSWORD MANAGEMENT
# ────────────────────────────────────────────────────────────────────

@router.put("/change-password")
async def change_password(
    body: ChangePassword,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Change password (must know current password)."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    await user_service.change_password(db, current_user, body.new_password)
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(body: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset OTP. Sends a 6-digit OTP to the user's registered email."""
    user = await user_service.get_user_by_cnic(db, body.cnic)
    if not user:
        # Don't reveal if user exists — always return success
        return {"message": "If the CNIC is registered, a reset OTP will be sent to the registered email."}

    if not user.email:
        logger.warning(f"Password reset requested for CNIC {user.cnic} but no email is on file.")
        return {"message": "If the CNIC is registered, a reset OTP will be sent to the registered email."}

    # Generate 6-digit OTP
    otp_code = str(random.randint(100000, 999999))

    # Store in Redis with 10-minute TTL (separate key from login OTP)
    redis_client = get_redis()
    if redis_client:
        await redis_client.setex(f"reset_otp:{user.cnic}", 600, otp_code)

    # Send Email via Resend
    try:
        await send_otp_email(user.email, otp_code)
    except Exception as e:
        logger.error(f"Failed to send password reset OTP to {user.email}: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reset OTP email.")

    return {"message": "If the CNIC is registered, a reset OTP will be sent to the registered email."}


@router.post("/reset-password")
async def reset_password(body: PasswordReset, db: AsyncSession = Depends(get_db)):
    """Reset password using CNIC + 6-digit OTP."""
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable")

    stored_otp = await redis_client.get(f"reset_otp:{body.cnic}")
    if not stored_otp or stored_otp != body.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP."
        )

    user = await user_service.get_user_by_cnic(db, body.cnic)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await user_service.change_password(db, user, body.new_password)
    await redis_client.delete(f"reset_otp:{body.cnic}")

    return {"message": "Password has been reset successfully"}


# ────────────────────────────────────────────────────────────────────
# PROFILE ENDPOINTS
# ────────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_active_user)):
    """Get current user's profile."""
    return current_user


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update current user's profile (name, phone, email, address)."""
    # Check email uniqueness if changing email
    if body.email and body.email != current_user.email:
        existing = await user_service.get_user_by_email(db, body.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )

    updated = await user_service.update_user_profile(
        db, current_user,
        full_name=body.full_name, phone=body.phone,
        email=body.email, address=body.address
    )
    return updated


# ────────────────────────────────────────────────────────────────────
# FIR ENDPOINTS (Citizen)
# ────────────────────────────────────────────────────────────────────

@router.post("/fir", response_model=FIRResponse, status_code=status.HTTP_201_CREATED)
async def submit_fir(
    fir_in: FIRCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Submit a new FIR."""
    fir = await fir_service.create_fir(
        db, citizen_id=current_user.id,
        title=fir_in.title, description=fir_in.description,
        incident_date=fir_in.incident_date,
        incident_location=fir_in.incident_location,
        category=fir_in.category, priority=fir_in.priority,
        latitude=fir_in.latitude, longitude=fir_in.longitude
    )
    return fir


@router.get("/firs", response_model=PaginatedResponse[FIRResponse])
async def get_my_firs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all FIRs submitted by the current citizen (paginated)."""
    offset = (page - 1) * page_size
    firs, total = await fir_service.get_citizen_firs(db, current_user.id, offset, page_size)
    return PaginatedResponse.create(firs, total, page, page_size)


@router.get("/fir/track/{tracking_number}", response_model=FIRResponse)
async def track_fir(tracking_number: str, db: AsyncSession = Depends(get_db)):
    """Track a FIR by its tracking number (public — no auth required)."""
    fir = await fir_service.get_fir_by_tracking_number(db, tracking_number)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")
    return fir


@router.get("/fir/{fir_id}", response_model=FIRDetailResponse)
async def get_fir_detail(
    fir_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get detailed FIR info (only if the citizen owns it)."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")
    if fir.citizen_id != current_user.id and current_user.role == "citizen":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return await fir_service.build_fir_detail(db, fir)


# ────────────────────────────────────────────────────────────────────
# EVIDENCE UPLOAD
# ────────────────────────────────────────────────────────────────────

@router.post("/fir/{fir_id}/evidence", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    fir_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Upload evidence (image/pdf) to a FIR."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")
    if fir.citizen_id != current_user.id and current_user.role == "citizen":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Upload to Supabase Storage
    file_data = await storage_service.upload_evidence(file)

    # Save metadata to database
    evidence = Evidence(
        fir_id=fir_id,
        uploaded_by=current_user.id,
        file_url=file_data["file_url"],
        file_name=file_data["file_name"],
        file_type=file_data["file_type"],
        file_size=file_data["file_size"],
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)

    return evidence


# ────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ────────────────────────────────────────────────────────────────────

@router.get("/notifications", response_model=PaginatedResponse[NotificationResponse])
async def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get current user's notifications (paginated)."""
    offset = (page - 1) * page_size
    notifications, total = await notification_service.get_user_notifications(
        db, current_user.id, offset, page_size
    )
    return PaginatedResponse.create(notifications, total, page, page_size)


@router.put("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Mark a notification as read."""
    notification = await notification_service.mark_notification_read(db, notification_id, current_user.id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return {"message": "Notification marked as read"}


@router.put("/notifications/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Mark all notifications as read."""
    count = await notification_service.mark_all_read(db, current_user.id)
    return {"message": f"{count} notifications marked as read"}
