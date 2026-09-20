import asyncio

import pytest
from fastapi import HTTPException

from app.config import settings
from app.security.auth import require_operator, require_step_up


def test_require_operator_rejects_missing_header():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_operator(None))
    assert exc.value.status_code == 401


def test_require_operator_accepts_valid_bearer():
    ctx = asyncio.run(require_operator(f"Bearer {settings.operator_auth_secret}"))
    assert ctx.authenticated is True
    assert ctx.step_up is False


def test_require_step_up_rejects_wrong_second_secret():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            require_step_up(
                f"Bearer {settings.operator_auth_secret}",
                "wrong",
            )
        )
    assert exc.value.status_code == 403


def test_require_step_up_accepts_valid_pair():
    ctx = asyncio.run(
        require_step_up(
            f"Bearer {settings.operator_auth_secret}",
            settings.operator_step_up_secret,
        )
    )
    assert ctx.authenticated is True
    assert ctx.step_up is True
