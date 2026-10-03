"""
Hermetic tests for the role hierarchy and the require_role dependency factory.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.rbac import has_at_least, require_role, role_rank
from app.entities.models import UserRole


def _user(role):
    return SimpleNamespace(role=role)


class TestRoleRank:
    def test_strict_ordering(self):
        assert role_rank(UserRole.GUEST) < role_rank(UserRole.AUTH_USER)
        assert role_rank(UserRole.AUTH_USER) < role_rank(UserRole.JOURNALIST)
        assert role_rank(UserRole.JOURNALIST) < role_rank(UserRole.ADMIN)

    def test_accepts_string_values(self):
        assert role_rank("ADMIN") == role_rank(UserRole.ADMIN)

    def test_unknown_role_sorts_below_guest(self):
        assert role_rank("WIZARD") == -1

    def test_has_at_least(self):
        assert has_at_least(UserRole.ADMIN, UserRole.AUTH_USER)
        assert has_at_least(UserRole.AUTH_USER, UserRole.AUTH_USER)
        assert not has_at_least(UserRole.GUEST, UserRole.AUTH_USER)


class TestRequireRole:
    def test_dependency_is_tagged_with_minimum(self):
        assert require_role(UserRole.ADMIN).__rbac_min__ == UserRole.ADMIN
        assert require_role(UserRole.GUEST).__rbac_min__ == UserRole.GUEST

    @pytest.mark.asyncio
    async def test_guest_tier_returns_none_for_anonymous(self):
        dep = require_role(UserRole.GUEST)
        assert await dep(current_user=None) is None

    @pytest.mark.asyncio
    async def test_guest_tier_passes_authenticated_user_through(self):
        dep = require_role(UserRole.GUEST)
        user = _user(UserRole.AUTH_USER)
        assert await dep(current_user=user) is user

    @pytest.mark.asyncio
    async def test_member_tier_accepts_equal_or_higher(self):
        dep = require_role(UserRole.JOURNALIST)
        assert (await dep(current_user=_user(UserRole.JOURNALIST))).role == UserRole.JOURNALIST
        assert (await dep(current_user=_user(UserRole.ADMIN))).role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_member_tier_rejects_lower_ranked_account(self):
        dep = require_role(UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc:
            await dep(current_user=_user(UserRole.AUTH_USER))
        assert exc.value.status_code == 403
