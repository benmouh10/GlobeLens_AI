"""
Hermetic tests for the shared password policy.
"""
import pytest
from pydantic import ValidationError

from app.core.passwords import validate_password_strength
from app.schemas.user import UserRegister


class TestValidatePasswordStrength:
    def test_accepts_strong_password(self):
        assert validate_password_strength("Str0ng!Pass") == "Str0ng!Pass"

    def test_rejects_short_password(self):
        with pytest.raises(ValueError, match="at least 8"):
            validate_password_strength("Ab1!ef")

    def test_rejects_password_over_bcrypt_byte_limit(self):
        with pytest.raises(ValueError, match="72 bytes"):
            validate_password_strength("Aa1!" + "x" * 80)

    @pytest.mark.parametrize(
        "common", ["password", "Password123", "admin123", "adminpass", "changeme"]
    )
    def test_rejects_common_passwords(self, common):
        with pytest.raises(ValueError, match="too common"):
            validate_password_strength(common)

    def test_rejects_low_character_variety(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_password_strength("abcdefgh")

    def test_rejects_two_character_classes(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_password_strength("abcdefg1")


class TestRegistrationSchemaUsesPolicy:
    def test_strong_password_passes(self):
        user = UserRegister(
            name="Jane Doe", email="jane@example.com", password="Str0ng!Pass"
        )
        assert user.password == "Str0ng!Pass"

    def test_weak_password_is_rejected(self):
        with pytest.raises(ValidationError):
            UserRegister(
                name="Jane Doe", email="jane@example.com", password="weakpass"
            )
