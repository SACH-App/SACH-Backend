from fastapi import APIRouter, Path
from app.services.nadra_service import verify_cnic

router = APIRouter()

@router.get("/cnic/{cnic}", summary="Verify CNIC against Mock NADRA API")
async def verify_citizen_cnic(
    cnic: str = Path(..., description="The CNIC to verify, e.g., 12345-1234567-1")
):
    """
    Verifies the provided CNIC. Checks Upstash Redis cache first.
    If not cached, queries the mock NADRA API and caches the result.
    """
    data = await verify_cnic(cnic)
    return {"status": "success", "data": data}
