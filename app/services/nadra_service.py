import json
import httpx
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.redis import get_redis
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Shared httpx.AsyncClient — managed by the app lifespan in main.py
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get the shared HTTP client. Must be initialized via init_client()."""
    if _http_client is None:
        raise RuntimeError("HTTP client not initialized. Call init_client() first.")
    return _http_client


async def init_client() -> None:
    """Initialize the shared httpx.AsyncClient (called on app startup)."""
    global _http_client
    _http_client = httpx.AsyncClient(
        base_url=settings.NADRA_API_URL,
        headers={
            "Authorization": f"Bearer {settings.NADRA_PARTNER_KEY}",
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )
    logger.info("NADRA HTTP client initialized")


async def close_client() -> None:
    """Close the shared httpx.AsyncClient (called on app shutdown)."""
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
        logger.info("NADRA HTTP client closed")


async def verify_cnic(cnic: str, expected_name: str = None, force_refresh: bool = False) -> dict:
    """
    Verifies a CNIC against the external Mock NADRA API.

    Args:
        cnic: The CNIC to verify.
        expected_name: If provided, the name returned by NADRA is compared against this.
                       Raises 400 if they don't match (identity verification).
        force_refresh: If True, bypasses the Redis cache and fetches fresh data.

    Returns:
        dict: The NADRA verification data.
    """
    redis_client = get_redis()
    cache_key = f"nadra_verification:{cnic}"

    # 1. Check Redis Cache (unless force_refresh)
    if redis_client and not force_refresh:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info(f"NADRA cache hit for {cnic}")
            data = json.loads(cached_data)
            # Still validate name even on cache hit
            if expected_name:
                _verify_name_match(data, expected_name, cnic)
            return data

    # 2. Make external HTTP call using the shared client
    client = get_http_client()
    url = f"/verify/{cnic}"

    try:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CNIC not found in NADRA database"
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="NADRA API error"
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to NADRA API"
        )

    # 3. Cache the successful response for 24 hours (86400 seconds)
    if redis_client:
        await redis_client.setex(cache_key, 86400, json.dumps(data))
        logger.info(f"NADRA data cached for {cnic}")

    # 4. Verify identity — match name against NADRA records
    if expected_name:
        _verify_name_match(data, expected_name, cnic)

    return data


def _verify_name_match(nadra_data: dict, expected_name: str, cnic: str) -> None:
    """
    Compare the name provided by the user against what NADRA has on file.
    Uses case-insensitive comparison with whitespace normalization.
    """
    # NADRA may return name in different field names — try common ones
    nadra_name = (
        nadra_data.get("full_name")
        or nadra_data.get("name")
        or nadra_data.get("fullName")
        or ""
    )

    # Normalize: lowercase, strip, collapse whitespace
    normalize = lambda s: " ".join(s.lower().strip().split())

    if normalize(nadra_name) != normalize(expected_name):
        logger.warning(
            f"Name mismatch for CNIC {cnic}: "
            f"expected='{expected_name}', nadra='{nadra_name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name does not match NADRA records. Please enter your name exactly as it appears on your CNIC."
        )
