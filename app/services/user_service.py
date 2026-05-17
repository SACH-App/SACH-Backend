from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timezone

from app.models.user import User, UserRole
from app.core.security import get_password_hash, verify_password
from app.core.logging_config import get_logger

logger = get_logger(__name__)


async def get_user_by_cnic(db: AsyncSession, cnic: str) -> User | None:
    result = await db.execute(select(User).where(User.cnic == cnic))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def create_citizen(db: AsyncSession, cnic: str, full_name: str, password: str,
                         phone: str = None, email: str = None) -> User:
    """Create a new citizen user (role is hardcoded)."""
    hashed = get_password_hash(password)
    user = User(
        cnic=cnic,
        full_name=full_name,
        phone=phone,
        email=email,
        role=UserRole.citizen,
        password_hash=hashed,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Created citizen user: {cnic}")
    return user


async def create_officer(db: AsyncSession, cnic: str, full_name: str, password: str,
                         phone: str = None, email: str = None,
                         badge_number: str = None, rank: str = None,
                         station_id: int = None) -> User:
    """Create a new officer user (admin action)."""
    hashed = get_password_hash(password)
    user = User(
        cnic=cnic,
        full_name=full_name,
        phone=phone,
        email=email,
        role=UserRole.officer,
        password_hash=hashed,
        badge_number=badge_number,
        rank=rank,
        station_id=station_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Created officer user: {cnic}")
    return user


async def update_user_profile(db: AsyncSession, user: User, **kwargs) -> User:
    """Update user profile fields."""
    for key, value in kwargs.items():
        if value is not None and hasattr(user, key):
            setattr(user, key, value)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(db: AsyncSession, user: User, new_password: str) -> User:
    """Change a user's password."""
    user.password_hash = get_password_hash(new_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Password changed for user: {user.cnic}")
    return user


async def update_last_login(db: AsyncSession, user: User) -> None:
    """Update the last_login timestamp."""
    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()


async def get_users_paginated(db: AsyncSession, offset: int, limit: int,
                              role: UserRole = None, search: str = None):
    """Get users with pagination and optional filters."""
    query = select(User)
    count_query = select(func.count(User.id))

    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if search:
        search_filter = User.full_name.ilike(f"%{search}%")
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    # Get total
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return users, total


async def deactivate_user(db: AsyncSession, user: User) -> User:
    """Soft-delete by deactivating the user."""
    user.is_active = False
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Deactivated user: {user.cnic}")
    return user


async def get_user_counts(db: AsyncSession) -> dict:
    """Get count of users by role."""
    total_result = await db.execute(select(func.count(User.id)))
    citizen_result = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.citizen)
    )
    officer_result = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.officer)
    )
    return {
        "total_users": total_result.scalar(),
        "total_citizens": citizen_result.scalar(),
        "total_officers": officer_result.scalar(),
    }
