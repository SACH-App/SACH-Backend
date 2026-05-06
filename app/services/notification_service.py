from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.notification import Notification, NotificationType
from app.core.logging_config import get_logger

logger = get_logger(__name__)


async def create_notification(db: AsyncSession, user_id: int, title: str, message: str,
                              notification_type: NotificationType = NotificationType.general,
                              reference_id: int = None) -> Notification:
    """Create an in-app notification for a user."""
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        reference_id=reference_id,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    logger.info(f"Notification created for user {user_id}: {title}")
    return notification


async def get_user_notifications(db: AsyncSession, user_id: int, offset: int, limit: int):
    """Get paginated notifications for a user."""
    query = select(Notification).where(Notification.user_id == user_id)
    count_query = select(func.count(Notification.id)).where(Notification.user_id == user_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    notifications = result.scalars().all()

    return notifications, total


async def mark_notification_read(db: AsyncSession, notification_id: int, user_id: int) -> Notification | None:
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id
        )
    )
    notification = result.scalars().first()
    if notification:
        notification.is_read = True
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, user_id: int) -> int:
    """Mark all notifications as read for a user. Returns count updated."""
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read == False
        )
    )
    notifications = result.scalars().all()
    for n in notifications:
        n.is_read = True
        db.add(n)
    await db.commit()
    return len(notifications)


async def notify_fir_status_change(db: AsyncSession, citizen_id: int, fir_id: int,
                                    tracking_number: str, new_status: str) -> None:
    """Send notification when FIR status changes."""
    await create_notification(
        db=db,
        user_id=citizen_id,
        title="FIR Status Updated",
        message=f"Your FIR {tracking_number} status has been changed to: {new_status}",
        notification_type=NotificationType.fir_status_update,
        reference_id=fir_id,
    )


async def notify_fir_assigned(db: AsyncSession, officer_id: int, fir_id: int,
                               tracking_number: str) -> None:
    """Send notification when a FIR is assigned to an officer."""
    await create_notification(
        db=db,
        user_id=officer_id,
        title="New FIR Assigned",
        message=f"FIR {tracking_number} has been assigned to you.",
        notification_type=NotificationType.fir_assigned,
        reference_id=fir_id,
    )


async def notify_fir_comment(db: AsyncSession, user_id: int, fir_id: int,
                              tracking_number: str, commenter_name: str) -> None:
    """Send notification when someone comments on a FIR."""
    await create_notification(
        db=db,
        user_id=user_id,
        title="New Comment on FIR",
        message=f"{commenter_name} added a comment on FIR {tracking_number}.",
        notification_type=NotificationType.fir_comment,
        reference_id=fir_id,
    )


async def send_push_notification(db: AsyncSession, user_id: int, title: str, body: str) -> None:
    """
    STUB: Send a push notification via Firebase Cloud Messaging.
    TODO: Integrate with Firebase Admin SDK when ready.
    """
    from app.models.fcm_token import FCMToken
    result = await db.execute(select(FCMToken).where(FCMToken.user_id == user_id))
    tokens = result.scalars().all()

    if tokens:
        logger.info(f"[PUSH STUB] Would send to {len(tokens)} device(s) for user {user_id}: {title} - {body}")
        # In production:
        # from firebase_admin import messaging
        # for t in tokens:
        #     msg = messaging.Message(notification=messaging.Notification(title=title, body=body), token=t.token)
        #     messaging.send(msg)
    else:
        logger.info(f"[PUSH STUB] No FCM tokens for user {user_id}, skipping push notification")
