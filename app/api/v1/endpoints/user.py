from fastapi import APIRouter

router = APIRouter()

@router.get("/profile")
async def get_user_profile():
    """Placeholder for React user website profile"""
    return {"message": "User profile data"}
