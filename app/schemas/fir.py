from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Optional, List
from datetime import datetime
from app.models.fir import FIRStatus, FIRCategory, FIRPriority
import re


class FIRBase(BaseModel):
    title: str = Field(..., max_length=200, description="Short title for the FIR")
    description: str = Field(..., description="Detailed description of the incident")


class FIRCreate(FIRBase):
    incident_date: Optional[datetime] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    category: FIRCategory = FIRCategory.other
    priority: FIRPriority = FIRPriority.medium
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class OfficerFIRCreate(FIRBase):
    """Officer files a FIR on behalf of a citizen."""
    # Citizen identity
    citizen_cnic: str = Field(..., max_length=15, description="Citizen's CNIC: XXXXX-XXXXXXX-X")
    citizen_name: str = Field(..., max_length=100)
    citizen_phone: Optional[str] = Field(None, max_length=20)
    citizen_email: str = Field(..., max_length=255, description="Citizen's email address (required)")
    citizen_gender: Optional[str] = Field(None, max_length=10)
    citizen_dob: Optional[str] = Field(None, max_length=20)  # ISO date string
    # Incident info
    incident_date: Optional[datetime] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    category: FIRCategory = FIRCategory.other
    priority: FIRPriority = FIRPriority.medium
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("citizen_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("citizen_email must be a valid email address")
        return v.lower().strip()

    @field_validator("citizen_cnic")
    @classmethod
    def validate_cnic(cls, v: str) -> str:
        if not re.match(r"^\d{5}-\d{7}-\d{1}$", v):
            raise ValueError("citizen_cnic must be in format XXXXX-XXXXXXX-X")
        return v


class FIRResponse(FIRBase):
    id: int
    tracking_number: str
    citizen_id: int
    status: str
    category: FIRCategory
    priority: FIRPriority
    incident_date: Optional[datetime] = None
    incident_location: Optional[str] = None
    assigned_officer_id: Optional[int] = None
    officer_name: Optional[str] = None
    officer_notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def resolve_status(self) -> 'FIRResponse':
        if self.assigned_officer_id is not None and str(self.status).lower().strip() in ("pending", "filed"):
            self.status = "under_review"
        return self


class FIRDetailResponse(FIRResponse):
    """Extended response with nested comments and evidence."""
    comments: List["CommentResponse"] = []
    evidence: List["EvidenceResponse"] = []
    citizen_name: Optional[str] = None
    officer_name: Optional[str] = None


class FIRStatusUpdate(BaseModel):
    status: FIRStatus
    officer_notes: Optional[str] = None


class FIRAssignOfficer(BaseModel):
    officer_id: int


class FIRSearch(BaseModel):
    """Query parameters for searching FIRs."""
    status: Optional[FIRStatus] = None
    category: Optional[FIRCategory] = None
    priority: Optional[FIRPriority] = None
    assigned_officer_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None  # Search in title/description


# Avoid circular import — import these at the bottom
from app.schemas.comment import CommentResponse
from app.schemas.evidence import EvidenceResponse

# Rebuild the model to resolve forward references
FIRDetailResponse.model_rebuild()
