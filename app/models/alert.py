from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(String(1000), nullable=False)
    target_audience = Column(String(100), nullable=False)
    alert_type = Column(String(50), default="Notice", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    officer = relationship("User", foreign_keys=[officer_id])
