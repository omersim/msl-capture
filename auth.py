"""
HMAC authentication — identical scheme to msl-kitchen.
Headers: X-API-Key, X-Signature, X-Timestamp
Signature: hash_hmac('sha256', timestamp + sha256(body), secret)
"""
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

API_KEY = os.environ.get("MSL_TOOLS_API_KEY", "")
HMAC_SECRET = os.environ.get("MSL_TOOLS_HMAC_SECRET", "")
TIMESTAMP_TOLERANCE_SEC = 300  # 5 minutes


def _compute_signature(timestamp: str, body: bytes, secret: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    message = timestamp + body_hash
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


async def require_hmac(request: Request) -> None:
    """FastAPI dependency — raises 401 if HMAC is missing or invalid."""
    api_key = request.headers.get("X-API-Key", "")
    signature = request.headers.get("X-Signature", "")
    timestamp = request.headers.get("X-Timestamp", "")

    if not api_key or not signature or not timestamp:
        raise HTTPException(status_code=401, detail="missing_auth_headers")

    if not API_KEY or not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="server_not_configured")

    if not hmac.compare_digest(api_key, API_KEY):
        raise HTTPException(status_code=401, detail="invalid_api_key")

    try:
        ts_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_timestamp")

    if abs(time.time() - ts_int) > TIMESTAMP_TOLERANCE_SEC:
        raise HTTPException(status_code=401, detail="timestamp_expired")

    body = await request.body()
    expected = _compute_signature(timestamp, body, HMAC_SECRET)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid_signature")
