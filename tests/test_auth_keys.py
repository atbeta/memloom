"""Tests for Hub key split."""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from memloom import auth_keys
from memloom.ingest_server import _check_bearer, _verify_ingest_bearer, _verify_read_bearer


@pytest.fixture(autouse=True)
def _reset_warning_flag():
    auth_keys._warned_read_fallback = False
    yield
    auth_keys._warned_read_fallback = False


def test_read_key_fallback(monkeypatch):
    monkeypatch.delenv("MEMLOOM_READ_KEY", raising=False)
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest-only")
    assert auth_keys.read_key() == "ingest-only"


def test_read_key_preferred(monkeypatch):
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest")
    monkeypatch.setenv("MEMLOOM_READ_KEY", "read")
    assert auth_keys.read_key() == "read"
    assert auth_keys.ingest_key() == "ingest"


def test_admin_key_preferred(monkeypatch):
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest")
    monkeypatch.setenv("MEMLOOM_ADMIN_KEY", "admin")
    assert auth_keys.admin_key() == "admin"


def test_ingest_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest")
    monkeypatch.setenv("MEMLOOM_READ_KEY", "read")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="read")
    with pytest.raises(HTTPException) as ei:
        _check_bearer(creds, auth_keys.ingest_key(), "missing")
    assert ei.value.status_code == 401


def test_read_rejects_ingest_when_split(monkeypatch):
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest")
    monkeypatch.setenv("MEMLOOM_READ_KEY", "read")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="ingest")
    with pytest.raises(HTTPException) as ei:
        _check_bearer(creds, auth_keys.read_key(), "missing")
    assert ei.value.status_code == 401


def test_read_accepts_read_key(monkeypatch):
    monkeypatch.setenv("MEMLOOM_INGEST_KEY", "ingest")
    monkeypatch.setenv("MEMLOOM_READ_KEY", "read")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="read")
    _check_bearer(creds, auth_keys.read_key(), "missing")
