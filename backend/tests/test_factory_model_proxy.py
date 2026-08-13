import base64
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException


def test_factory_analysis_token_round_trip(monkeypatch):
    from app.config import get_settings
    from app.routers import factory

    settings = get_settings().model_copy(update={"credential_secret": "unit-test-secret-that-is-long-enough"})
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    token = factory._analysis_token(42, int(time.time()) + 60)
    assert factory._analysis_token_user(f"Bearer {token}") == 42


def test_factory_analysis_token_rejects_tampering(monkeypatch):
    from app.config import get_settings
    from app.routers import factory

    settings = get_settings().model_copy(update={"credential_secret": "unit-test-secret-that-is-long-enough"})
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    payload = base64.urlsafe_b64encode(f"7:{int(time.time()) + 60}".encode()).decode().rstrip("=")
    bad = hmac.new(b"different", f"factory-analysis:{payload}".encode(), hashlib.sha256).hexdigest()
    with pytest.raises(HTTPException) as error:
        factory._analysis_token_user(f"Bearer {payload}.{bad}")
    assert error.value.status_code == 401


def test_proxy_analyzer_restricts_origin():
    from app.routers import factory

    with pytest.raises(HTTPException) as error:
        factory._proxy_analyzer("https://malicious.example", "token")
    assert error.value.status_code == 422
