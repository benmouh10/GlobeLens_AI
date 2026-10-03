"""
GlobeLens AI — Password policy.

A single reusable strength check shared by every place a password is accepted
(public registration and admin provisioning). Keeping it here means the rules
cannot drift between schemas.

bcrypt only hashes the first 72 bytes of a password, so longer inputs are
silently truncated. Rejecting more than 72 UTF-8 bytes makes that limit
explicit instead of letting two different passwords share one hash.
"""
from __future__ import annotations

import re

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt's fixed input limit
MIN_CHARACTER_CLASSES = 3

_CLASS_PATTERNS = (
    re.compile(r"[a-z]"),
    re.compile(r"[A-Z]"),
    re.compile(r"[0-9]"),
    re.compile(r"[^A-Za-z0-9]"),
)

# Small denylist of the most-abused passwords. Not a substitute for a breach
# corpus, but it stops the obvious guesses that survive the class rules.
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "p@ssw0rd",
        "123456", "1234567", "12345678", "123456789", "1234567890",
        "qwerty", "qwerty123", "qwertyuiop", "1q2w3e4r", "qazwsx", "zxcvbnm",
        "abc123", "123123", "111111", "000000", "666666", "888888",
        "letmein", "welcome", "monkey", "dragon", "iloveyou", "sunshine",
        "princess", "football", "baseball", "superman", "master", "shadow",
        "admin", "admin123", "adminpass", "adminpass123", "root", "toor",
        "guest", "test", "changeme", "secret", "pass", "asdfgh", "123qwe",
    }
)


def validate_password_strength(password: str) -> str:
    """Return ``password`` unchanged when it is acceptable, else raise ValueError."""
    if not isinstance(password, str):
        raise ValueError("Password must be a string")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes long"
        )

    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common; choose something less predictable")

    classes = sum(1 for pattern in _CLASS_PATTERNS if pattern.search(password))
    if classes < MIN_CHARACTER_CLASSES:
        raise ValueError(
            "Password must include at least "
            f"{MIN_CHARACTER_CLASSES} of: lowercase letters, uppercase letters, "
            "digits, symbols"
        )

    return password
