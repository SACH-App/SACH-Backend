import enum
from sqlalchemy import Column, Integer, String, Enum, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserRole(str, enum.Enum):
    citizen = "citizen"
    admin = "admin"
    officer = "officer"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    cnic = Column(String(15), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=True, index=True)
    phone = Column(String(20), nullable=True)
    address = Column(String(500), nullable=True)
    profile_picture = Column(String(500), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.citizen, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Officer-specific fields
    badge_number = Column(String(50), nullable=True)
    rank = Column(String(50), nullable=True)
    station_id = Column(Integer, ForeignKey("police_stations.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    station = relationship("PoliceStation", back_populates="officers")
    submitted_firs = relationship("FIR", back_populates="citizen", foreign_keys="FIR.citizen_id")
    assigned_firs = relationship("FIR", back_populates="assigned_officer", foreign_keys="FIR.assigned_officer_id")
    comments = relationship("FIRComment", back_populates="author")
    notifications = relationship("Notification", back_populates="user")
    fcm_tokens = relationship("FCMToken", back_populates="user")
