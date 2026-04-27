from pydantic import BaseModel, Field
from typing import Optional
from app.models.user import UserRole

class UserBase(BaseModel):
    cnic: str = Field(..., max_length=15, description="Citizen National Identity Card number")
    full_name: str = Field(..., max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    role: UserRole = UserRole.citizen

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserResponse(UserBase):
    id: int

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    cnic: Optional[str] = None
