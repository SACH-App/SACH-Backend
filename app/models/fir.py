import enum
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, DateTime, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class FIRStatus(str, enum.Enum):
    pending = "pending"
    under_investigation = "under_investigation"
    resolved = "resolved"
    closed = "closed"


class FIRCategory(str, enum.Enum):
    theft = "theft"
    assault = "assault"
    fraud = "fraud"
    cybercrime = "cybercrime"
    harassment = "harassment"
    robbery = "robbery"
    murder = "murder"
    kidnapping = "kidnapping"
    domestic_violence = "domestic_violence"
    other = "other"


class FIRPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FIR(Base):
    __tablename__ = "firs"

    id = Column(Integer, primary_key=True, index=True)
    tracking_number = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    citizen_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Incident details
    incident_date = Column(DateTime(timezone=True), nullable=True)
    incident_location = Column(String(500), nullable=True)
    category = Column(Enum(FIRCategory), default=FIRCategory.other, nullable=False)
    priority = Column(Enum(FIRPriority), default=FIRPriority.medium, nullable=False)

    # Status & Assignment
    status = Column(Enum(FIRStatus), default=FIRStatus.pending, nullable=False, index=True)
    assigned_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    officer_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    citizen = relationship("User", back_populates="submitted_firs", foreign_keys=[citizen_id])
    assigned_officer = relationship("User", back_populates="assigned_firs", foreign_keys=[assigned_officer_id])
    comments = relationship("FIRComment", back_populates="fir", cascade="all, delete-orphan", order_by="FIRComment.created_at")
    evidence = relationship("Evidence", back_populates="fir", cascade="all, delete-orphan")
