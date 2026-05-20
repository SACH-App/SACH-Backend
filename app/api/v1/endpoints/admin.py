from fastapi import APIRouter, Depends, HTTPException, status, Query
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
import random
import json

from app.api.deps import get_current_officer_user, get_current_admin_user, oauth2_scheme
from app.core.database import get_db
from app.core.logging_config import get_logger
from app.core.security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token, decode_token
)
from app.core.redis import get_redis
from app.models.user import User, UserRole
from app.models.fir import FIRStatus, FIRCategory, FIRPriority
from app.models.police_station import PoliceStation
from app.schemas.user import (
    UserResponse, AdminUserUpdate, OfficerCreate, OfficerSignupRequest,
    OfficerSignupVerify, OfficerLoginRequest, Token
)
from app.schemas.fir import (
    FIRResponse, FIRDetailResponse, FIRStatusUpdate, FIRAssignOfficer
)
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.dashboard import DashboardStats
from app.schemas.pagination import PaginatedResponse
from app.services import user_service, fir_service, notification_service
from app.services.nadra_service import verify_cnic, fetch_citizen_address
from app.services.email_service import send_otp_email

logger = get_logger(__name__)
router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# OFFICER AUTHENTICATION & REGISTRATION
# ────────────────────────────────────────────────────────────────────

@router.post("/signup/request", status_code=status.HTTP_200_OK)
async def signup_officer_request(
    body: OfficerSignupRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1 of registration. Verifies identity with NADRA, checks uniqueness,
    generates a 6-digit OTP, caches registration details in Redis, and sends email.
    """
    # 1. Verify CNIC spelling and expected name matches Mock NADRA API
    await verify_cnic(body.cnic, expected_name=body.full_name)

    # Fetch address from NADRA Mock API (best-effort)
    nadra_address = await fetch_citizen_address(body.cnic)

    # 2. Check if a user with this CNIC already exists in the system
    existing_cnic = await user_service.get_user_by_cnic(db, body.cnic)
    if existing_cnic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this CNIC already exists."
        )

    # 3. Check if a user with this Email already exists in the system
    existing_email = await user_service.get_user_by_email(db, body.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists."
        )

    # 4. Validate rank against hierarchical ranks
    valid_ranks = [
        "Constable", "Head Constable", "ASI", "SI", "Inspector",
        "DSP", "SP", "SSP", "DIG", "AIG", "IG"
    ]
    if body.rank not in valid_ranks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid rank. Must be one of: {', '.join(valid_ranks)}"
        )

    # 5. Generate 6-digit numeric OTP
    otp_code = str(random.randint(100000, 999999))
    logger.info(f"Generated registration OTP for CNIC {body.cnic}: {otp_code}")

    # 6. Cache OTP and registration data in Redis (10-minute TTL)
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis service unavailable. Unable to process signup."
        )

    # Save details
    registration_payload = body.model_dump()
    registration_payload["address"] = nadra_address
    await redis_client.setex(f"signup_data:{body.cnic}", 600, json.dumps(registration_payload))
    await redis_client.setex(f"signup_otp:{body.cnic}", 600, otp_code)

    # 7. Send Email via Resend
    try:
        await send_otp_email(body.email, otp_code)
    except Exception as e:
        logger.error(f"Failed to send registration OTP email to {body.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP email. Please try again."
        )

    return {"message": "OTP sent successfully", "cnic": body.cnic}


@router.post("/signup/verify", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup_officer_verify(
    body: OfficerSignupVerify,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2 of registration. Validates OTP from Redis, retrieves cached registration data,
    resolves/creates PoliceStation, creates officer with is_active=False.
    """
    redis_client = get_redis()
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis service unavailable."
        )

    # 1. Retrieve cached OTP
    stored_otp = await redis_client.get(f"signup_otp:{body.cnic}")
    if not stored_otp or stored_otp != body.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP."
        )

    # 2. Retrieve cached signup payload
    stored_payload_str = await redis_client.get(f"signup_data:{body.cnic}")
    if not stored_payload_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration session expired. Please submit the registration form again."
        )

    signup_payload = json.loads(stored_payload_str)

    # 3. Dynamic Police Station Resolution
    station_name = signup_payload["station_name"].strip()
    district = signup_payload["district"].strip()
    city = signup_payload["city"].strip()

    # Query station in database
    result = await db.execute(select(PoliceStation).where(PoliceStation.name == station_name))
    station = result.scalars().first()

    if not station:
        station = PoliceStation(
            name=station_name,
            address=f"{district}, {city}, Pakistan",
            jurisdiction=f"{district}, {city}"
        )
        db.add(station)
        await db.commit()
        await db.refresh(station)
        logger.info(f"Created new Police Station: {station_name}")

    # 4. Hash Password & Create User
    hashed_password = get_password_hash(signup_payload["password"])
    
    new_officer = User(
        cnic=signup_payload["cnic"],
        full_name=signup_payload["full_name"],
        email=signup_payload["email"],
        phone=signup_payload["phone"],
        address=signup_payload.get("address"),
        password_hash=hashed_password,
        role=UserRole.officer,
        badge_number=signup_payload["badge_number"],
        rank=signup_payload["rank"],
        station_id=station.id,
        is_active=False  # Deactivated by default, pending admin review
    )

    db.add(new_officer)
    await db.commit()
    await db.refresh(new_officer)

    # 5. Clean up Redis cache
    await redis_client.delete(f"signup_otp:{body.cnic}")
    await redis_client.delete(f"signup_data:{body.cnic}")

    logger.info(f"Officer registered successfully: {new_officer.cnic} (Badge: {new_officer.badge_number}). Status: PENDING_APPROVAL")

    return new_officer


@router.post("/login", response_model=Token)
async def login_officer(
    body: OfficerLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Secure officer/admin login. Checks role (must be officer or admin), 
    checks badge validation, and checks activation status (returns HTTP 403 if pending review).
    """
    user = await user_service.get_user_by_cnic(db, body.cnic)

    # 1. Verify user exists and password is correct
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect CNIC or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Verify role is authorized (officer or admin only)
    if user.role not in [UserRole.admin, UserRole.officer]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only officers and admins can access the admin portal."
        )

    # 3. If badge number is entered, verify it
    if body.badge_number and user.badge_number != body.badge_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Badge number does not match registered details."
        )

    # 4. Check activation status (Inactive accounts are pending review)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending administrative verification. You will be notified via email once approved."
        )

    # 5. Update last login
    await user_service.update_last_login(db, user)

    # 6. Issue tokens
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


@router.get("/me", response_model=UserResponse)
async def get_current_officer_profile(
    current_officer: User = Depends(get_current_officer_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve current logged-in officer profile details.
    """
    station_name = None
    city = None
    district = None

    if current_officer.station_id:
        result = await db.execute(select(PoliceStation).where(PoliceStation.id == current_officer.station_id))
        station = result.scalars().first()
        if station:
            station_name = station.name
            if station.jurisdiction and "," in station.jurisdiction:
                parts = [p.strip() for p in station.jurisdiction.split(",")]
                if len(parts) >= 2:
                    district = parts[0]
                    city = parts[1]

    response_data = UserResponse.model_validate(current_officer)
    response_data.station_name = station_name
    response_data.city = city
    response_data.district = district
    return response_data



# ────────────────────────────────────────────────────────────────────
# DASHBOARD
# ────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Get dashboard statistics. Accessible by officers and admins."""
    fir_stats = await fir_service.get_fir_stats(db)
    user_counts = await user_service.get_user_counts(db)
    return {**fir_stats, **user_counts}


# ────────────────────────────────────────────────────────────────────
# FIR MANAGEMENT
# ────────────────────────────────────────────────────────────────────

@router.get("/firs", response_model=PaginatedResponse[FIRResponse])
async def get_all_firs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[FIRStatus] = Query(None, alias="status"),
    category: Optional[FIRCategory] = None,
    priority: Optional[FIRPriority] = None,
    assigned_officer_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Get all FIRs with pagination and filters. Accessible by officers and admins."""
    offset = (page - 1) * page_size
    firs, total = await fir_service.get_all_firs_paginated(
        db, offset, page_size,
        status=status_filter, category=category, priority=priority,
        assigned_officer_id=assigned_officer_id, search=search
    )
    return PaginatedResponse.create(firs, total, page, page_size)


@router.get("/firs/{fir_id}", response_model=FIRDetailResponse)
async def get_fir_detail(
    fir_id: int,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Get detailed FIR info including comments and evidence."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")

    return await fir_service.build_fir_detail(db, fir)


@router.put("/firs/{fir_id}/status", response_model=FIRResponse)
async def update_fir_status(
    fir_id: int,
    body: FIRStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Update FIR status. Sends notification to the citizen."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")

    updated_fir = await fir_service.update_fir_status(
        db, fir, body.status, current_officer.id, body.officer_notes
    )

    # Notify the citizen
    await notification_service.notify_fir_status_change(
        db, fir.citizen_id, fir.id, fir.tracking_number, body.status.value
    )

    return updated_fir


@router.put("/firs/{fir_id}/assign", response_model=FIRResponse)
async def assign_fir_officer(
    fir_id: int,
    body: FIRAssignOfficer,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Assign an officer to a FIR (admin only)."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")

    # Verify the officer exists and is actually an officer
    officer = await user_service.get_user_by_id(db, body.officer_id)
    if not officer or officer.role not in [UserRole.officer, UserRole.admin]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid officer ID")

    updated_fir = await fir_service.assign_fir_officer(db, fir, body.officer_id)

    # Notify the officer
    await notification_service.notify_fir_assigned(
        db, body.officer_id, fir.id, fir.tracking_number
    )

    return updated_fir


@router.post("/firs/{fir_id}/comment", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def add_fir_comment(
    fir_id: int,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Add an investigation note/comment to a FIR."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")

    comment = await fir_service.add_comment(db, fir_id, current_officer.id, body.content)

    # Notify the citizen about the new comment
    await notification_service.notify_fir_comment(
        db, fir.citizen_id, fir.id, fir.tracking_number, current_officer.full_name
    )

    response = CommentResponse.model_validate(comment)
    response.author_name = current_officer.full_name
    return response


@router.delete("/firs/{fir_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fir(
    fir_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Delete a FIR permanently (admin only)."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")
    await fir_service.delete_fir(db, fir)
    return None


# ────────────────────────────────────────────────────────────────────
# USER MANAGEMENT
# ────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def get_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    role: Optional[UserRole] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """List all users with pagination and filters (admin only)."""
    offset = (page - 1) * page_size
    users, total = await user_service.get_users_paginated(db, offset, page_size, role=role, search=search)
    return PaginatedResponse.create(users, total, page, page_size)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_detail(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Get a specific user's details (admin only)."""
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Update a user's profile, role, or active status (admin only)."""
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updated = await user_service.update_user_profile(
        db, user, **body.model_dump(exclude_none=True)
    )
    return updated


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Deactivate a user account — soft delete (admin only)."""
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    await user_service.deactivate_user(db, user)
    return {"message": f"User {user.full_name} has been deactivated"}


# ────────────────────────────────────────────────────────────────────
# OFFICER MANAGEMENT
# ────────────────────────────────────────────────────────────────────

@router.post("/officers", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_officer(
    body: OfficerCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """Create a new officer account (admin only). Verifies CNIC with NADRA."""
    # Verify CNIC
    await verify_cnic(body.cnic)

    # Check if already exists
    existing = await user_service.get_user_by_cnic(db, body.cnic)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CNIC already registered")

    officer = await user_service.create_officer(
        db, cnic=body.cnic, full_name=body.full_name, password=body.password,
        phone=body.phone, email=body.email, badge_number=body.badge_number,
        rank=body.rank, station_id=body.station_id
    )
    return officer


@router.get("/officers", response_model=PaginatedResponse[UserResponse])
async def get_officers(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user)
):
    """List all officers (admin only)."""
    offset = (page - 1) * page_size
    officers, total = await user_service.get_users_paginated(db, offset, page_size, role=UserRole.officer)
    return PaginatedResponse.create(officers, total, page, page_size)


# ────────────────────────────────────────────────────────────────────
# ANALYTICS
# ────────────────────────────────────────────────────────────────────

@router.get("/analytics")
async def get_analytics(
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Get analytics data for charts and reports."""
    fir_stats = await fir_service.get_fir_stats(db)
    user_counts = await user_service.get_user_counts(db)

    return {
        "fir_stats": fir_stats,
        "user_counts": user_counts,
    }
