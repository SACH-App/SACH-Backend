import enum
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class FIRStatus(str, enum.Enum):
    pending = "pending"
    under_investigation = "under_investigation"
    resolved = "resolved"
    closed = "closed"

class FIR(Base):
    __tablename__ = "firs"

    id = Column(Integer, primary_key=True, index=True)
    tracking_number = Column(String(50), unique=True, index=True, nullable=False)
    citizen_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String, nullable=False)
    status = Column(Enum(FIRStatus), default=FIRStatus.pending, nullable=False)
    assigned_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
