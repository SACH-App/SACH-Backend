from fastapi import APIRouter

router = APIRouter()

@router.get("/status")
async def get_mobile_status():
    """Placeholder for mobile app specific endpoint"""
    return {"message": "Mobile API status ok"}
