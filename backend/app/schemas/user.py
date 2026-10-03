"""
GlobeLens AI — User Pydantic Schemas
=====================================
Validates incoming registration/login payloads and filters API serialization.
"""
import uuid
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.passwords import validate_password_strength
from app.entities.models import UserRole


class UserRegister(BaseModel):
    """Payload to register a new User account."""
    name: str = Field(..., min_length=2, max_length=255, description="Full name of the user")
    email: EmailStr = Field(..., description="Unique email address")
    password: str = Field(..., min_length=8, max_length=128, description="Secure account password")

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserLogin(BaseModel):
    """Payload to request user authentication."""
    email: EmailStr = Field(..., description="Account email address")
    password: str = Field(..., description="Account password")


class UserResponse(BaseModel):
    """Sanitized User details returned in public API responses (excludes password_hash)."""
    id: uuid.UUID
    name: str
    email: EmailStr
    role: UserRole
    is_blocked: bool

    model_config = {
        "from_attributes": True
    }


class TokenResponse(BaseModel):
    """Token payload returned upon successful authentication."""
    access_token: str
    token_type: str = "bearer"
