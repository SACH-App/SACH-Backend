from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from app.api.deps import get_current_officer_user, get_current_admin_user
from app.core.database import get_db
from app.core.logging_config import get_logger
from app.models.user import User, UserRole
from app.models.fir import FIRStatus, FIRCategory, FIRPriority
from app.schemas.user import UserResponse, AdminUserUpdate, OfficerCreate
from app.schemas.fir import (
    FIRResponse, FIRDetailResponse, FIRStatusUpdate, FIRAssignOfficer
)
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.dashboard import DashboardStats
from app.schemas.pagination import PaginatedResponse
from app.services import user_service, fir_service, notification_service
from app.services.nadra_service import verify_cnic

logger = get_logger(__name__)
router = APIRouter()


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
