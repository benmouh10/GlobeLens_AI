"""
GlobeLens AI — Role-based access control.

Roles form a strict hierarchy, and an anonymous request is ranked as GUEST, so
an endpoint declares a single minimum tier instead of each controller keeping
its own tuple of allowed roles:

    GUEST (0) < AUTH_USER (1) < JOURNALIST (2) < ADMIN (3)

``require_role(AUTH_USER)`` is the explicit equivalent of
``Depends(get_current_user)``; ``require_role(ADMIN)`` replaces the old
``require_admin``. Both now reject under-ranked callers the same way: 401 when
nobody is authenticated, 403 when an authenticated account is too low.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status

from app.controllers.auth_controller import get_current_user, get_current_user_optional
from app.entities.models import User, UserRole

# Student note: the ranking is data, not code, so has_at_least stays a pure
# function that is trivial to unit-test.
ROLE_RANK = {
    UserRole.GUEST: 0,
    UserRole.AUTH_USER: 1,
    UserRole.JOURNALIST: 2,
    UserRole.ADMIN: 3,
}


def role_rank(role) -> int:
    """Rank for a role enum/value; anything unrecognised sorts below GUEST."""
    if isinstance(role, str):
        try:
            role = UserRole(role)
        except ValueError:
            return -1
    return ROLE_RANK.get(role, -1)


def has_at_least(role, minimum: UserRole) -> bool:
    """True when ``role`` ranks at or above ``minimum``."""
    return role_rank(role) >= role_rank(minimum)


def require_role(minimum: UserRole):
    """Build a FastAPI dependency that admits callers of at least ``minimum``.

    GUEST is the floor, so a GUEST-gated route is effectively public but still
    receives the optional user object (None for anonymous visitors). Any higher
    tier authenticates first, then checks the rank.
    """
    if role_rank(minimum) <= role_rank(UserRole.GUEST):
        async def _guest(
            current_user: Optional[User] = Depends(get_current_user_optional),
        ) -> Optional[User]:
            return current_user

        _guest.__rbac_min__ = UserRole.GUEST
        return _guest

    async def _member(current_user: User = Depends(get_current_user)) -> User:
        if not has_at_least(current_user.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{minimum.value} role required",
            )
        return current_user

    # Tagged so the API-policy test can classify the route without guessing by
    # function name.
    _member.__rbac_min__ = minimum
    return _member
