"""
GlobeLens AI — AuthService
==========================
Handles password hashing, credential verification, and JWT issuance.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import uuid

from fastapi import HTTPException, status
import bcrypt
from jose import jwt

from app.core.config import settings
from app.entities.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserLogin, UserRegister


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    plain_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(plain_bytes, hashed_bytes)



class AuthService:
    """Business logic service for user authentication and session tokens."""

    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def register_user(self, data: UserRegister) -> User:
        """
        Register a new user in the system.
        Raises 400 Bad Request if the email is already in use.
        """
        existing_user = await self._user_repo.get_by_email(data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered"
            )

        hashed = hash_password(data.password)
        return await self._user_repo.create(data, hashed)

    async def authenticate_user(self, data: UserLogin) -> User:
        """
        Authenticate a user by verifying their credentials.
        Raises 401 Unauthorized if verification fails.
        """
        user = await self._user_repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account has been blocked"
            )

        return user

    def create_access_token(self, data: Dict[str, Any]) -> str:
        """
        Generate a signed HS256 JWT access token.
        Token expiration is determined by ACCESS_TOKEN_EXPIRE_MINUTES.
        """
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        # iat records issuance time; jti gives every token a unique id so it can
        # be referenced individually (auditing now, targeted revocation later).
        to_encode.update({
            "exp": expire,
            "iat": now,
            "jti": uuid.uuid4().hex,
        })

        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        return encoded_jwt
