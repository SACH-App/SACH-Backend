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
    station_name: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
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
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X (e.g., 12345-1234567-1)")
        return v


class OfficerSignupRequest(BaseModel):
    cnic: str = Field(..., max_length=15, description="CNIC in format XXXXX-XXXXXXX-X")
    full_name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    badge_number: str = Field(..., max_length=50)
    rank: str = Field(..., max_length=50)
    city: str = Field(..., max_length=100)
    district: str = Field(..., max_length=100)
    station_name: str = Field(..., max_length=200)
    password: str = Field(..., min_length=8)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("badge_number")
    @classmethod
    def validate_badge(cls, v: str) -> str:
        if not re.match(r"^PK-\d{5}$", v):
            raise ValueError("Badge number must be in format PK-XXXXX (e.g. PK-12345)")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() != "":
            if not re.match(r"^\+92\s3\d{9}$", v):
                raise ValueError("Phone number must be in format +92 3XXXXXXXXX")
        return v


class OfficerSignupVerify(BaseModel):
    cnic: str = Field(..., max_length=15)
    otp: str = Field(..., min_length=6, max_length=6)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v


class OfficerLoginRequest(BaseModel):
    cnic: str = Field(..., max_length=15)
    password: str = Field(...)
    badge_number: Optional[str] = Field(None, max_length=50)

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X")
        return v

