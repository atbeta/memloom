"""Bearer auth for /api/admin routes."""
from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from memloom.auth_keys import admin_key

log = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _expected_admin_key() -> str | None:
    """Prefer MEMLOOM_ADMIN_KEY; fall back to MEMLOOM_INGEST_KEY."""
    return admin_key()


def verify_admin_bearer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Reject if Bearer token does not match the admin key."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = _expected_admin_key()
    if not expected:
        log.error("neither MEMLOOM_ADMIN_KEY nor MEMLOOM_INGEST_KEY is set — refusing admin requests")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server misconfiguration: no admin/ingest key set",
        )
    if not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
