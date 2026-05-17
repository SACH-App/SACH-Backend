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
        headers={"Content-Type": "application/json"},
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

async def _get_valid_token() -> str:
    """Fetch a valid JWT token from Mock NADRA API, caching it in Redis."""
    redis_client = get_redis()
    cache_key = "nadra_access_token"
    
    # 1. Return cached token if it exists
    if redis_client:
        cached_token = await redis_client.get(cache_key)
        if cached_token:
            return cached_token

    # 2. Otherwise, fetch a new token
    client = get_http_client()
    try:
        response = await client.post("/auth/login", json={
            "username": settings.NADRA_USERNAME,
            "password": settings.NADRA_PASSWORD
        })
        response.raise_for_status()
        token = response.json().get("access_token")
        
        # 3. Cache token for 25 minutes (it expires in 30 on NADRA's end)
        if redis_client and token:
            await redis_client.setex(cache_key, 1500, token)
            
        return token
    except httpx.HTTPStatusError as e:
        logger.error(f"NADRA Auth failed: {e.response.text}")
        raise HTTPException(status_code=502, detail="NADRA API Authentication failed")
    except Exception as e:
        logger.error(f"Failed to fetch NADRA token: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to NADRA API")


async def verify_cnic(cnic: str, expected_name: str = None, force_refresh: bool = False) -> dict:
    redis_client = get_redis()
    cache_key = f"nadra_verification:{cnic}"

    # 1. Check Redis Cache
    if redis_client and not force_refresh:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            data = json.loads(cached_data)
            
            # Check alive status from cache
            if data.get("is_alive") is False:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Registration denied: NADRA records indicate this citizen is deceased."
                )

            if expected_name:
                _verify_name_match(data, expected_name, cnic)
            return data

    # 2. Get active Bearer token and attach to headers
    token = await _get_valid_token()
    client = get_http_client()
    
    # Use /citizens/{cnic} for full partner data
    url = f"/citizens/{cnic}" 

    try:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="CNIC not found in NADRA database")
        raise HTTPException(status_code=502, detail="NADRA API error")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Could not connect to NADRA API")

    # 3. Cache the citizen profile response
    if redis_client:
        await redis_client.setex(cache_key, 86400, json.dumps(data))

    # 4. Verify Identity Rules
    
    # Check if the citizen is alive
    if data.get("is_alive") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration denied: NADRA records indicate this citizen is deceased."
        )

    # Check if the name matches
    if expected_name:
        _verify_name_match(data, expected_name, cnic)

    return data


async def fetch_citizen_address(cnic: str) -> str | None:
    """
    Fetch the citizen's address from NADRA's /citizens/{cnic}/addresses endpoint.
    Prefers PERMANENT address over CURRENT.
    Returns a formatted address string, or None if unavailable.
    This is best-effort — failures are logged but do NOT block signup.
    """
    try:
        token = await _get_valid_token()
        client = get_http_client()
        response = await client.get(
            f"/citizens/{cnic}/addresses",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        data = response.json()

        addresses = data.get("addresses", [])
        if not addresses:
            logger.info(f"No addresses returned by NADRA for CNIC {cnic}")
            return None

        # Prefer PERMANENT address; fall back to CURRENT or whatever is first
        chosen = None
        for addr in addresses:
            if addr.get("address_type", "").upper() == "PERMANENT":
                chosen = addr
                break
        if chosen is None:
            for addr in addresses:
                if addr.get("address_type", "").upper() == "CURRENT":
                    chosen = addr
                    break
        if chosen is None:
            chosen = addresses[0]

        # Build a formatted string from available fields
        # NADRA response format: street, city, district, province, postal_code
        parts = [
            chosen.get("street", ""),
            chosen.get("city", ""),
            chosen.get("province", ""),
            chosen.get("postal_code", ""),
        ]
        formatted = ", ".join(p.strip() for p in parts if p and p.strip())
        logger.info(f"Fetched NADRA address for {cnic}: {formatted}")
        return formatted or None

    except Exception as e:
        logger.error(f"Failed to fetch address from NADRA for {cnic}: {e}")
        return None


def _verify_name_match(nadra_data: dict, expected_name: str, cnic: str) -> None:
    # Combine first and last name from Mock NADRA response
    first_name = nadra_data.get("first_name", "")
    last_name = nadra_data.get("last_name", "")
    nadra_name = f"{first_name} {last_name}".strip()

    normalize = lambda s: " ".join(s.lower().strip().split())

    if normalize(nadra_name) != normalize(expected_name):
        logger.warning(f"Name mismatch for CNIC {cnic}: expected='{expected_name}', nadra='{nadra_name}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name does not match NADRA records. Please enter your name exactly as it appears on your CNIC."
        )
