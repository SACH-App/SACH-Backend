from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.models.fir import FIR, FIRStatus, FIRCategory, FIRPriority
from app.models.fir_comment import FIRComment
from app.models.evidence import Evidence
from app.schemas.fir import FIRDetailResponse
from app.core.utils import generate_tracking_number
from app.core.logging_config import get_logger
from app.services import user_service

logger = get_logger(__name__)


async def build_fir_detail(db: AsyncSession, fir: FIR) -> FIRDetailResponse:
    """Helper to build a detailed FIR response with comments and evidence."""
    comments = await get_fir_comments(db, fir.id)
    result = await db.execute(select(Evidence).where(Evidence.fir_id == fir.id))
    evidence_list = result.scalars().all()

    response = FIRDetailResponse.model_validate(fir)
    response.comments = [
        {
            "id": c.id, "fir_id": c.fir_id, "user_id": c.user_id,
            "content": c.content, "created_at": c.created_at,
            "author_name": (await user_service.get_user_by_id(db, c.user_id)).full_name if c.user_id else None
        }
        for c in comments
    ]
    response.evidence = evidence_list
    response.citizen_name = (await user_service.get_user_by_id(db, fir.citizen_id)).full_name if fir.citizen_id else None
    
    if fir.assigned_officer_id:
        officer = await user_service.get_user_by_id(db, fir.assigned_officer_id)
        response.officer_name = officer.full_name if officer else None

    return response


async def create_fir(db: AsyncSession, citizen_id: int, title: str, description: str,
                     incident_date: datetime = None, incident_location: str = None,
                     category: FIRCategory = FIRCategory.other,
                     priority: FIRPriority = FIRPriority.medium) -> FIR:
    """Create a new FIR with a unique tracking number."""
    tracking_number = generate_tracking_number()
    fir = FIR(
        tracking_number=tracking_number,
        title=title,
        description=description,
        citizen_id=citizen_id,
        incident_date=incident_date,
        incident_location=incident_location,
        category=category,
        priority=priority,
    )
    db.add(fir)
    await db.commit()
    await db.refresh(fir)
    logger.info(f"FIR created: {tracking_number} by citizen {citizen_id}")
    return fir


async def get_fir_by_id(db: AsyncSession, fir_id: int) -> FIR | None:
    result = await db.execute(select(FIR).where(FIR.id == fir_id))
    return result.scalars().first()


async def get_fir_by_tracking_number(db: AsyncSession, tracking_number: str) -> FIR | None:
    result = await db.execute(select(FIR).where(FIR.tracking_number == tracking_number))
    return result.scalars().first()


async def get_citizen_firs(db: AsyncSession, citizen_id: int, offset: int, limit: int):
    """Get paginated FIRs for a citizen."""
    query = select(FIR).where(FIR.citizen_id == citizen_id)
    count_query = select(func.count(FIR.id)).where(FIR.citizen_id == citizen_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(FIR.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    firs = result.scalars().all()

    return firs, total


async def get_all_firs_paginated(db: AsyncSession, offset: int, limit: int,
                                 status: FIRStatus = None,
                                 category: FIRCategory = None,
                                 priority: FIRPriority = None,
                                 assigned_officer_id: int = None,
                                 date_from: datetime = None,
                                 date_to: datetime = None,
                                 search: str = None):
    """Get all FIRs with pagination and filters."""
    query = select(FIR)
    count_query = select(func.count(FIR.id))

    filters = []
    if status:
        filters.append(FIR.status == status)
    if category:
        filters.append(FIR.category == category)
    if priority:
        filters.append(FIR.priority == priority)
    if assigned_officer_id:
        filters.append(FIR.assigned_officer_id == assigned_officer_id)
    if date_from:
        filters.append(FIR.created_at >= date_from)
    if date_to:
        filters.append(FIR.created_at <= date_to)
    if search:
        filters.append(
            FIR.title.ilike(f"%{search}%") | FIR.description.ilike(f"%{search}%")
        )

    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(FIR.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    firs = result.scalars().all()

    return firs, total


async def update_fir_status(db: AsyncSession, fir: FIR, status: FIRStatus,
                            officer_id: int, officer_notes: str = None) -> FIR:
    """Update FIR status and optionally add officer notes."""
    fir.status = status
    fir.assigned_officer_id = officer_id
    if officer_notes:
        fir.officer_notes = officer_notes
    db.add(fir)
    await db.commit()
    await db.refresh(fir)
    logger.info(f"FIR {fir.tracking_number} status updated to {status.value}")
    return fir


async def assign_fir_officer(db: AsyncSession, fir: FIR, officer_id: int) -> FIR:
    """Assign an officer to a FIR."""
    fir.assigned_officer_id = officer_id
    db.add(fir)
    await db.commit()
    await db.refresh(fir)
    logger.info(f"FIR {fir.tracking_number} assigned to officer {officer_id}")
    return fir


async def add_comment(db: AsyncSession, fir_id: int, user_id: int, content: str) -> FIRComment:
    """Add a comment/note to a FIR."""
    comment = FIRComment(fir_id=fir_id, user_id=user_id, content=content)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


async def get_fir_comments(db: AsyncSession, fir_id: int):
    """Get all comments for a FIR."""
    result = await db.execute(
        select(FIRComment).where(FIRComment.fir_id == fir_id).order_by(FIRComment.created_at.asc())
    )
    return result.scalars().all()


async def delete_fir(db: AsyncSession, fir: FIR) -> None:
    """Hard delete a FIR (admin only)."""
    await db.delete(fir)
    await db.commit()
    logger.info(f"FIR {fir.tracking_number} deleted")


async def get_fir_stats(db: AsyncSession) -> dict:
    """Get FIR statistics for the dashboard."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    total = (await db.execute(select(func.count(FIR.id)))).scalar()
    pending = (await db.execute(
        select(func.count(FIR.id)).where(FIR.status == FIRStatus.pending)
    )).scalar()
    under_inv = (await db.execute(
        select(func.count(FIR.id)).where(FIR.status == FIRStatus.under_investigation)
    )).scalar()
    resolved = (await db.execute(
        select(func.count(FIR.id)).where(FIR.status == FIRStatus.resolved)
    )).scalar()
    closed = (await db.execute(
        select(func.count(FIR.id)).where(FIR.status == FIRStatus.closed)
    )).scalar()

    firs_today = (await db.execute(
        select(func.count(FIR.id)).where(FIR.created_at >= today_start)
    )).scalar()
    firs_week = (await db.execute(
        select(func.count(FIR.id)).where(FIR.created_at >= week_start)
    )).scalar()
    firs_month = (await db.execute(
        select(func.count(FIR.id)).where(FIR.created_at >= month_start)
    )).scalar()

    # FIRs by category
    cat_result = await db.execute(
        select(FIR.category, func.count(FIR.id)).group_by(FIR.category)
    )
    firs_by_category = {str(row[0].value): row[1] for row in cat_result.all()}

    # FIRs by priority
    pri_result = await db.execute(
        select(FIR.priority, func.count(FIR.id)).group_by(FIR.priority)
    )
    firs_by_priority = {str(row[0].value): row[1] for row in pri_result.all()}

    return {
        "total_firs": total,
        "pending_firs": pending,
        "under_investigation_firs": under_inv,
        "resolved_firs": resolved,
        "closed_firs": closed,
        "firs_today": firs_today,
        "firs_this_week": firs_week,
        "firs_this_month": firs_month,
        "firs_by_category": firs_by_category,
        "firs_by_priority": firs_by_priority,
    }
