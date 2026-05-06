from datetime import timedelta
from math import ceil
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
from app.core.utils import generate_reset_token
from app.core.logging_config import get_logger
from app.models.user import User
from app.models.fir import FIR
from app.models.evidence import Evidence
from app.schemas.user import (
    UserCreate, UserResponse, UserUpdate, ChangePassword,
    PasswordResetRequest, PasswordReset, Token, RefreshTokenRequest
)
from app.schemas.fir import FIRCreate, FIRResponse, FIRDetailResponse
from app.schemas.evidence import EvidenceResponse
from app.schemas.notification import NotificationResponse
from app.schemas.pagination import PaginatedResponse
from app.services import nadra_service
from app.services import user_service, fir_service, notification_service, storage_service

logger = get_logger(__name__)
router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/user/login")


# ────────────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new citizen. Role is always 'citizen' — cannot be overridden."""
    # 1. Verify CNIC against Mock NADRA API
    await nadra_service.verify_cnic(user_in.cnic)

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

    # 4. Create citizen (role is hardcoded in the service)
    db_user = await user_service.create_citizen(
        db, cnic=user_in.cnic, full_name=user_in.full_name,
        password=user_in.password, phone=user_in.phone, email=user_in.email
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
        from datetime import datetime, timezone
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
    """Request a password reset. Generates a token stored in Redis (15 min TTL)."""
    user = await user_service.get_user_by_cnic(db, body.cnic)
    if not user:
        # Don't reveal if user exists — always return success
        return {"message": "If the CNIC is registered, a reset token has been generated."}

    token = generate_reset_token()

    # Store token in Redis with 15-minute TTL
    redis_client = get_redis()
    if redis_client:
        await redis_client.setex(f"reset:{token}", 900, user.cnic)

    # STUB: Log the token instead of emailing it
    logger.info(f"[PASSWORD RESET] Token for {user.cnic}: {token}")
    # TODO: Replace with actual email sending (e.g., Resend, SendGrid)

    return {"message": "If the CNIC is registered, a reset token has been generated."}


@router.post("/reset-password")
async def reset_password(body: PasswordReset, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid reset token."""
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service unavailable")

    cnic = await redis_client.get(f"reset:{body.token}")
    if not cnic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    user = await user_service.get_user_by_cnic(db, cnic)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await user_service.change_password(db, user, body.new_password)
    await redis_client.delete(f"reset:{body.token}")

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
        category=fir_in.category, priority=fir_in.priority
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
    return {
        "items": firs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ceil(total / page_size) if total > 0 else 0,
    }


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

    # Build detailed response
    comments = await fir_service.get_fir_comments(db, fir_id)
    result = await db.execute(select(Evidence).where(Evidence.fir_id == fir_id))
    evidence_list = result.scalars().all()

    response = FIRDetailResponse.model_validate(fir)
    response.comments = [
        {"id": c.id, "fir_id": c.fir_id, "user_id": c.user_id,
         "content": c.content, "created_at": c.created_at,
         "author_name": (await user_service.get_user_by_id(db, c.user_id)).full_name if c.user_id else None}
        for c in comments
    ]
    response.evidence = evidence_list
    response.citizen_name = (await user_service.get_user_by_id(db, fir.citizen_id)).full_name if fir.citizen_id else None
    if fir.assigned_officer_id:
        officer = await user_service.get_user_by_id(db, fir.assigned_officer_id)
        response.officer_name = officer.full_name if officer else None

    return response


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
    return {
        "items": notifications,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ceil(total / page_size) if total > 0 else 0,
    }


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
