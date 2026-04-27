import enum
from sqlalchemy import Column, Integer, String, Enum
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
    phone = Column(String(20), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.citizen, nullable=False)
    password_hash = Column(String, nullable=False)
