"""
Hermetic tests for JWT claim hardening (iat / jti).
"""
import uuid

from jose import jwt

from app.core.config import settings
from app.services.auth_service import AuthService


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def _issue(**extra) -> dict:
    service = AuthService(user_repo=None)
    token = service.create_access_token({"sub": "user-123", **extra})
    return _decode(token)


def test_token_carries_sub_exp_iat_jti():
    claims = _issue()
    assert claims["sub"] == "user-123"
    assert "exp" in claims
    assert "iat" in claims
    assert claims["exp"] > claims["iat"]


def test_jti_is_a_valid_uuid():
    uuid.UUID(_issue()["jti"])


def test_jti_is_unique_per_token():
    service = AuthService(user_repo=None)
    first = _decode(service.create_access_token({"sub": "x"}))
    second = _decode(service.create_access_token({"sub": "x"}))
    assert first["jti"] != second["jti"]
