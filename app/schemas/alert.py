from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import re

class AlertCreate(BaseModel):
    target_audience: str = Field(..., max_length=100)
    subject: str = Field(..., max_length=200)
    message: str = Field(..., max_length=1000)
    type: str = Field(default="Notice", max_length=50)
    cnic: Optional[str] = None

    @field_validator("cnic")
    @classmethod
    def validate_cnic(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("CNIC must be in format XXXXX-XXXXXXX-X (e.g., 12345-1234567-1)")
        return v

class AlertResponse(BaseModel):
    id: int
    officer_id: int
    officer_name: Optional[str] = None
    title: str
    message: str
    target_audience: str
    alert_type: str
    created_at: datetime

    class Config:
        from_attributes = True
