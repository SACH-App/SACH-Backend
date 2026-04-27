from fastapi import APIRouter

router = APIRouter()

@router.get("/dashboard")
async def get_admin_dashboard():
    """Placeholder for admin dashboard data"""
    return {"message": "Admin dashboard access"}
