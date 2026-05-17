from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from app.models.user import UserRole
import re


class UserBase(BaseModel):
    cnic: str = Field(..., max_length=15, description="CNIC in format XXXXX-XXXXXXX-X")
    full_name: str = Field(..., max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X (e.g., 12345-1234567-1)")
        return v


class UserCreate(UserBase):
    """Signup schema — role is always 'citizen', cannot be overridden."""
    password: str = Field(..., min_length=8)
    # NOTE: 'role' is intentionally NOT here. Citizens cannot set their own role.


class UserResponse(BaseModel):
    id: int
    cnic: str
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    profile_picture: Optional[str] = None
    role: UserRole
    is_active: bool
    badge_number: Optional[str] = None
    rank: Optional[str] = None
    station_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Profile update — citizens can update these fields."""
    full_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)


class AdminUserUpdate(BaseModel):
    """Admin can update role, active status, and officer fields."""
    full_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    badge_number: Optional[str] = None
    rank: Optional[str] = None
    station_id: Optional[int] = None


class OfficerCreate(BaseModel):
    """Admin creates an officer account."""
    cnic: str = Field(..., max_length=15)
    full_name: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    badge_number: Optional[str] = None
    rank: Optional[str] = None
    station_id: Optional[int] = None

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class PasswordResetRequest(BaseModel):
    cnic: str = Field(..., max_length=15)


class PasswordReset(BaseModel):
    cnic: str = Field(..., max_length=15)
    otp: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    cnic: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str

class OTPRequest(BaseModel):
    cnic: str = Field(..., max_length=15)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v

class OTPVerify(BaseModel):
    cnic: str = Field(..., max_length=15)
    otp: str = Field(..., min_length=6, max_length=6)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v
