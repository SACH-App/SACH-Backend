import json
import httpx
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.redis import get_redis

async def verify_cnic(cnic: str) -> dict:
    """
    Verifies a CNIC against the external Mock NADRA API.
    Utilizes Upstash Redis for caching to avoid redundant calls.
    """
    redis_client = get_redis()
    cache_key = f"nadra_verification:{cnic}"
    
    # 1. Check Redis Cache
    if redis_client:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    # 2. Make external HTTP call if not in cache
    headers = {
        "Authorization": f"Bearer {settings.NADRA_PARTNER_KEY}",
        "Content-Type": "application/json"
    }
    # Note: Ensure the URL structure matches your actual mock API
    url = f"{settings.NADRA_API_URL}/verify/{cnic}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CNIC not found in NADRA database")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="NADRA API error")
        except httpx.RequestError:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not connect to NADRA API")

    # 3. Cache the successful response for 24 hours (86400 seconds)
    if redis_client:
        await redis_client.setex(cache_key, 86400, json.dumps(data))

    return data
