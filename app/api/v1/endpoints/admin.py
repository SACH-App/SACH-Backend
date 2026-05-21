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
    OfficerSignupVerify, OfficerLoginRequest, Token, UserUpdate
)
from app.schemas.fir import (
    FIRResponse, FIRDetailResponse, FIRStatusUpdate, FIRAssignOfficer, OfficerFIRCreate
)
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.dashboard import DashboardStats
from app.schemas.pagination import PaginatedResponse
from app.schemas.alert import AlertCreate, AlertResponse
from app.models.alert import Alert
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


@router.put("/me", response_model=UserResponse)
async def update_current_officer_profile(
    body: UserUpdate,
    current_officer: User = Depends(get_current_officer_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update current logged-in officer profile details.
    """
    if body.full_name is not None:
        current_officer.full_name = body.full_name
    if body.phone is not None:
        current_officer.phone = body.phone
    if body.email is not None:
        current_officer.email = body.email
    if body.address is not None:
        current_officer.address = body.address

    db.add(current_officer)
    await db.commit()
    await db.refresh(current_officer)

    # We fetch station info to populate the response properly just like in GET /me
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
    
    # Auto Audit: Log this action as an Alert for the Audit Log
    from app.models.alert import Alert
    auto_alert = Alert(
        officer_id=current_officer.id,
        title=f"Profile Updated: {current_officer.full_name}",
        message=f"Officer updated their profile information.",
        target_audience="Specific User",
        alert_type="Update"
    )
    db.add(auto_alert)
    await db.commit()

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

@router.post("/firs", response_model=FIRResponse, status_code=status.HTTP_201_CREATED)
async def file_fir_on_behalf(
    body: OfficerFIRCreate,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """
    Officer files a FIR on behalf of a citizen.
    Looks up citizen by CNIC; if not found, creates a new citizen account
    with a temporary password equal to their CNIC digits (no dashes).
    Email is required so the citizen can later access their account.
    """
    from app.models.user import UserRole as UR

    # 1. Find or create the citizen by CNIC
    citizen = await user_service.get_user_by_cnic(db, body.citizen_cnic)
    if not citizen:
        # New citizen — create account with temp password = CNIC without dashes
        temp_password = body.citizen_cnic.replace("-", "")
        citizen = await user_service.create_citizen(
            db,
            cnic=body.citizen_cnic,
            full_name=body.citizen_name,
            phone=body.citizen_phone,
            email=body.citizen_email,
            password=temp_password,
        )
        logger.info(f"Auto-created citizen account for CNIC {body.citizen_cnic}")
    else:
        # Existing user — ensure they are a citizen (not an officer/admin CNIC)
        if citizen.role not in (UR.citizen,):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CNIC {body.citizen_cnic} belongs to a {citizen.role.value} account, not a citizen."
            )
        # If citizen has no email on record, update it with the provided one
        if not citizen.email and body.citizen_email:
            await user_service.update_user_profile(db, citizen, email=body.citizen_email)

    # 2. Create the FIR linked to the citizen
    fir = await fir_service.create_fir(
        db,
        citizen_id=citizen.id,
        title=body.title,
        description=body.description,
        incident_date=body.incident_date,
        incident_location=body.incident_location,
        category=body.category,
        priority=body.priority,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return fir


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

    # Auto Audit: Log this action as an Alert for the Audit Log
    from app.models.alert import Alert
    auto_alert = Alert(
        officer_id=current_officer.id,
        title=f"FIR Status Updated: {fir.tracking_number}",
        message=f"Status changed to {body.status.value}" + (f" - Notes: {body.officer_notes}" if body.officer_notes else ""),
        target_audience="Specific User",
        alert_type="Update"
    )
    db.add(auto_alert)
    await db.commit()

    return updated_fir


@router.put("/firs/{fir_id}/assign", response_model=FIRResponse)
async def assign_fir_officer(
    fir_id: int,
    body: FIRAssignOfficer,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_officer_user)  # Any officer can try to assign, but rank logic restricts it
):
    """Assign an officer to a FIR (Requires rank ASI or above, and can only assign lower ranking officers)."""
    fir = await fir_service.get_fir_by_id(db, fir_id)
    if not fir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FIR not found")

    # Verify the officer to be assigned exists
    officer = await user_service.get_user_by_id(db, body.officer_id)
    if not officer or officer.role not in [UserRole.officer, UserRole.admin]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid officer ID")

    # Rank Hierarchy Logic
    RANK_HIERARCHY = {
        "IG": 10, "IGP": 10, "DIG": 9, "SSP": 8, "SP": 7, "ASP": 6, "DSP": 6,
        "Inspector": 5, "Sub-Inspector": 4, "SI": 4, 
        "Assistant Sub-Inspector": 3, "ASI": 3,
        "Head Constable": 2, "Constable": 1
    }

    def get_rank_val(rank_str: str) -> int:
        if not rank_str:
            return 0
        for k, v in RANK_HIERARCHY.items():
            if k.lower() in rank_str.lower():
                return v
        return 0

    current_val = get_rank_val(current_admin.rank)
    target_val = get_rank_val(officer.rank)

    # Admin bypasses rank check
    if current_admin.role != UserRole.admin:
        if current_val < 3: # Less than ASI
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be rank ASI or above to assign cases.")
        if target_val >= current_val:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only assign cases to lower ranking officers.")

    updated_fir = await fir_service.assign_fir_officer(db, fir, body.officer_id)

    # Notify the officer
    await notification_service.notify_fir_assigned(
        db, body.officer_id, fir.id, fir.tracking_number
    )

    # Auto Audit: Log this action as an Alert for the Audit Log
    from app.models.alert import Alert
    auto_alert = Alert(
        officer_id=current_admin.id,
        title=f"Officer Assigned: {fir.tracking_number}",
        message=f"Officer {officer.full_name} (ID: {body.officer_id}) was assigned to this FIR.",
        target_audience="Specific User",
        alert_type="Update"
    )
    db.add(auto_alert)
    await db.commit()

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

    # Auto Audit: Log this action as an Alert for the Audit Log
    from app.models.alert import Alert
    auto_alert = Alert(
        officer_id=current_officer.id,
        title=f"Investigation Note Added: {fir.tracking_number}",
        message=f"{current_officer.full_name} added an investigation note.",
        target_audience="Specific User",
        alert_type="Update"
    )
    db.add(auto_alert)
    await db.commit()

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
    current_admin: User = Depends(get_current_officer_user)
):
    """List all officers."""
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


# ────────────────────────────────────────────────────────────────────
# ALERTS & BROADCASTS
# ────────────────────────────────────────────────────────────────────

@router.post("/alerts", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def send_broadcast_alert(
    body: AlertCreate,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Send alert to targeted audiences."""
    district = None
    city = None
    if current_officer.station_id:
        result = await db.execute(select(PoliceStation).where(PoliceStation.id == current_officer.station_id))
        station = result.scalars().first()
        if station and station.jurisdiction and "," in station.jurisdiction:
            parts = [p.strip() for p in station.jurisdiction.split(",")]
            if len(parts) >= 2:
                district = parts[0]
                city = parts[1]

    user_ids = []

    if body.target_audience == 'All Officers':
        query = select(User.id).where(User.role == UserRole.officer)
        result = await db.execute(query)
        user_ids = result.scalars().all()

    elif body.target_audience == 'District Officers':
        if not district:
            raise HTTPException(status_code=400, detail="Officer has no assigned district jurisdiction")
        query = select(User.id).join(PoliceStation, User.station_id == PoliceStation.id).where(
            User.role == UserRole.officer,
            PoliceStation.jurisdiction.ilike(f"%{district}%")
        )
        result = await db.execute(query)
        user_ids = result.scalars().all()

    elif body.target_audience == 'Citizens – City-wide':
        if not city:
            raise HTTPException(status_code=400, detail="Officer has no assigned city jurisdiction")
        query = select(User).where(User.role == UserRole.citizen)
        result = await db.execute(query)
        citizens = result.scalars().all()
        for c in citizens:
            if c.address:
                parts = [p.strip() for p in c.address.split(",")]
                if len(parts) >= 3:
                    # Based on the format: ..., City, Province, PostalCode
                    user_city = parts[-3]
                    if user_city.lower() == city.lower():
                        user_ids.append(c.id)

    elif body.target_audience == 'All Users':
        query = select(User.id)
        result = await db.execute(query)
        user_ids = result.scalars().all()
        
    elif body.target_audience == 'Specific User':
        if not body.cnic:
            raise HTTPException(status_code=400, detail="CNIC is required for Specific User")
        query = select(User.id).where(User.cnic == body.cnic)
        result = await db.execute(query)
        user_id = result.scalar_one_or_none()
        if user_id:
            user_ids.append(user_id)
        else:
            raise HTTPException(status_code=404, detail="User with provided CNIC not found")

    else:
        raise HTTPException(status_code=400, detail="Invalid target audience")

    # Create the alert record
    new_alert = Alert(
        officer_id=current_officer.id,
        title=body.subject,
        message=body.message,
        target_audience=body.target_audience,
        alert_type=body.type
    )
    db.add(new_alert)
    await db.flush()

    if user_ids:
        from app.models.notification import Notification, NotificationType
        notifications = []
        for uid in user_ids:
            notifications.append(
                Notification(
                    user_id=uid,
                    title=body.subject,
                    message=body.message,
                    notification_type=NotificationType.general,
                    reference_id=new_alert.id
                )
            )
        db.add_all(notifications)

    await db.commit()
    await db.refresh(new_alert)
    return new_alert


@router.get("/alerts", response_model=PaginatedResponse[AlertResponse])
async def get_recent_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """Get history of alerts sent."""
    from sqlalchemy.orm import joinedload
    from sqlalchemy import func

    count_query = select(func.count(Alert.id))
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * page_size
    query = select(Alert).options(joinedload(Alert.officer)).order_by(Alert.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    alerts = result.scalars().all()

    response_list = []
    for alert in alerts:
        response_list.append(AlertResponse(
            id=alert.id,
            officer_id=alert.officer_id,
            officer_name=alert.officer.full_name if alert.officer else "Unknown",
            title=alert.title,
            message=alert.message,
            target_audience=alert.target_audience,
            alert_type=alert.alert_type,
            created_at=alert.created_at
        ))

    return PaginatedResponse.create(response_list, total, page, page_size)
