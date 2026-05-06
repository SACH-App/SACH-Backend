"""
Pydantic schemas package.
Contains data validation, serialization, and deserialization models.
"""
from app.schemas.user import (
    UserCreate, UserResponse, UserUpdate, AdminUserUpdate,
    OfficerCreate, ChangePassword, PasswordResetRequest, PasswordReset,
    Token, TokenData, RefreshTokenRequest
)
from app.schemas.fir import (
    FIRCreate, FIRResponse, FIRDetailResponse,
    FIRStatusUpdate, FIRAssignOfficer, FIRSearch
)
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.evidence import EvidenceResponse
from app.schemas.notification import NotificationResponse
from app.schemas.dashboard import DashboardStats
from app.schemas.pagination import PaginationParams, PaginatedResponse
