from fastapi import APIRouter, Path, Query
from app.services.nadra_service import verify_cnic

router = APIRouter()


@router.get("/cnic/{cnic}", summary="Verify CNIC against Mock NADRA API")
async def verify_citizen_cnic(
    cnic: str = Path(..., description="The CNIC to verify, e.g., 12345-1234567-1"),
    force_refresh: bool = Query(False, description="Bypass cache and fetch fresh data from NADRA")
):
    """
    Verifies the provided CNIC. Checks Upstash Redis cache first.
    If not cached (or force_refresh=true), queries the mock NADRA API and caches the result.
    """
    data = await verify_cnic(cnic, force_refresh=force_refresh)
    return {"status": "success", "data": data}
