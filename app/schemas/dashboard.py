from pydantic import BaseModel
from typing import Optional, Dict


class DashboardStats(BaseModel):
    total_firs: int = 0
    pending_firs: int = 0
    under_investigation_firs: int = 0
    resolved_firs: int = 0
    closed_firs: int = 0
    total_users: int = 0
    total_citizens: int = 0
    total_officers: int = 0
    firs_today: int = 0
    firs_this_week: int = 0
    firs_this_month: int = 0
    firs_by_category: Dict[str, int] = {}
    firs_by_priority: Dict[str, int] = {}
