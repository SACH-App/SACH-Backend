from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from typing import Optional

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.logging_config import get_logger
from app.models.user import User
from app.models.fcm_token import FCMToken

logger = get_logger(__name__)
router = APIRouter()


class FCMTokenRegister(BaseModel):
    token: str = Field(..., description="Firebase Cloud Messaging device token")
    device_info: Optional[str] = Field(None, description="Device model/OS info")


@router.get("/status")
async def get_mobile_status():
    """Mobile API health check."""
    return {"message": "Mobile API status ok", "version": "1.0.0"}


@router.post("/fcm-token", status_code=status.HTTP_201_CREATED)
async def register_fcm_token(
    body: FCMTokenRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Register a Firebase Cloud Messaging token for push notifications."""
    # Check if token already exists
    result = await db.execute(select(FCMToken).where(FCMToken.token == body.token))
    existing = result.scalars().first()

    if existing:
        # Update ownership if token already registered
        existing.user_id = current_user.id
        existing.device_info = body.device_info
        db.add(existing)
        await db.commit()
        return {"message": "FCM token updated"}

    fcm = FCMToken(
        user_id=current_user.id,
        token=body.token,
        device_info=body.device_info,
    )
    db.add(fcm)
    await db.commit()
    logger.info(f"FCM token registered for user {current_user.id}")
    return {"message": "FCM token registered"}


@router.delete("/fcm-token")
async def remove_fcm_token(
    body: FCMTokenRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Remove a FCM token (e.g., on logout from mobile)."""
    result = await db.execute(
        select(FCMToken).where(
            FCMToken.token == body.token,
            FCMToken.user_id == current_user.id
        )
    )
    token = result.scalars().first()
    if token:
        await db.delete(token)
        await db.commit()
        return {"message": "FCM token removed"}
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
