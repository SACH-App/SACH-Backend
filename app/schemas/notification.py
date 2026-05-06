from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.notification import NotificationType


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    is_read: bool
    notification_type: NotificationType
    reference_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
