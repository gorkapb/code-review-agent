from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from src.api import security


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeDb:
    def __init__(self, value: Any) -> None:
        self._value = value

    async def execute(self, _stmt: Any) -> FakeResult:
        return FakeResult(self._value)


def test_hash_api_key_is_deterministic_and_hides_plaintext():
    raw = "cra_secret-token"
    digest = security.hash_api_key(raw)

    assert digest == security.hash_api_key(raw)  # deterministic -> indexable lookup
    assert raw not in digest
    assert len(digest) == 64  # sha256 hex
    assert security.hash_api_key("other") != digest


def test_generate_api_key_is_prefixed_and_unique():
    a = security.generate_api_key()
    b = security.generate_api_key()

    assert a.startswith("cra_")
    assert a != b


@pytest.mark.asyncio
async def test_missing_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        await security.get_current_tenant(credentials=None, db=FakeDb(None))

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        await security.get_current_tenant(
            credentials=_bearer("cra_nope"), db=FakeDb(None)
        )

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert 'error="invalid_token"' in exc.value.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_valid_token_returns_tenant():
    tenant = SimpleNamespace(id="tenant-1")

    result = await security.get_current_tenant(
        credentials=_bearer("cra_ok"), db=FakeDb(tenant)
    )

    assert result is tenant
