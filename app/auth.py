import os
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY_PREFIX = "waro_"

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def extract_api_key(request: Request) -> Optional[str]:
    """Extrae API key de Authorization: Bearer o X-API-Key."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:].startswith(API_KEY_PREFIX):
        return auth_header[7:]

    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header.startswith(API_KEY_PREFIX):
        return api_key_header

    return None


def extract_session_token(request: Request) -> Optional[str]:
    """Extrae session token de Authorization: Bearer (non-waro prefix) o cookie."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and not auth_header[7:].startswith(API_KEY_PREFIX):
        return auth_header[7:]

    session_token = request.cookies.get("session-token")
    if session_token:
        return session_token

    return None


async def validate_api_key(api_key: str) -> Optional[dict]:
    """Valida API key contra la misma BD de api_warocol."""
    if not api_key or not api_key.startswith(API_KEY_PREFIX):
        return None

    key_hash = hash_api_key(api_key)
    pool = await get_pool()

    async with pool.acquire() as conn:
        token = await conn.fetchrow(
            """
            SELECT id, tenant_id, scopes, expires_at, is_active
            FROM api_tokens
            WHERE key_hash = $1
            """,
            key_hash,
        )

        if not token:
            return None

        if not token["is_active"]:
            return None

        if token["expires_at"] and token["expires_at"] < datetime.now(timezone.utc):
            return None

        await conn.execute(
            "UPDATE api_tokens SET last_used_at = NOW() WHERE id = $1",
            token["id"],
        )

        return {
            "token_id": str(token["id"]),
            "tenant_id": str(token["tenant_id"]),
            "scopes": token["scopes"],
        }


async def validate_session_token(session_token: str) -> Optional[dict]:
    """Valida session token contra la tabla sessions de api_warocol."""
    if not session_token:
        return None

    pool = await get_pool()

    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            """
            SELECT s.id, s.user_id, s.expires_at, s.is_active,
                   m.tenant_id
            FROM sessions s
            JOIN member m ON m.user_id = s.user_id AND m.is_active = true
            WHERE s.id = $1
            LIMIT 1
            """,
            session_token,
        )

        if not session:
            return None

        if not session["is_active"]:
            return None

        if session["expires_at"] and session["expires_at"] < datetime.now(timezone.utc):
            return None

        return {
            "session_id": str(session["id"]),
            "user_id": str(session["user_id"]),
            "tenant_id": str(session["tenant_id"]),
        }


async def require_auth(request: Request) -> dict:
    """Dependency: requiere API key o session token válido."""
    # Try API key first
    api_key = extract_api_key(request)
    if api_key:
        result = await validate_api_key(api_key)
        if result:
            return result
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    # Try session token
    session_token = extract_session_token(request)
    if session_token:
        result = await validate_session_token(session_token)
        if result:
            return result
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    raise HTTPException(
        status_code=401,
        detail="Authentication required. Use Authorization: Bearer <session_token> or API key"
    )
