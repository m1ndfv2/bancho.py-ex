from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.constants.privileges import Privileges
from app.usecases import supporter_keys as supporter_keys_uc


class FakeDatabase:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.key = {"id": 1, "code": "AAAAAAAA-BBBBBBBB-CCCCCCCC", "duration_days": 30, "used_by": 0}
        self.user = {"id": 10, "donor_end": 0, "priv": int(Privileges.UNRESTRICTED)}

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            yield

    async def fetch_one(self, query: str, params: dict[str, object]):
        if "FROM supporter_keys" in query and "used_by = 0" in query:
            if params["code"] == self.key["code"] and self.key["used_by"] == 0:
                return {"id": self.key["id"], "duration_days": self.key["duration_days"]}
            return None
        raise AssertionError(query)

    async def execute(self, query: str, params: dict[str, object]):
        if query.startswith("UPDATE supporter_keys"):
            if self.key["id"] == params["id"] and self.key["used_by"] == 0:
                self.key["used_by"] = int(params["user_id"])
                return 1
            return 0
        if query.startswith("UPDATE users"):
            self.user["priv"] |= int(params["supporter_bit"])
            self.user["donor_end"] = int(params["donor_end"])
            return 1
        raise AssertionError(query)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key: str, _seconds: int) -> bool:
        return True


@pytest.mark.asyncio
async def test_redeem_success(monkeypatch):
    fake_db = FakeDatabase()

    async def fake_fetch_one(*, id: int):
        assert id == 10
        return fake_db.user

    monkeypatch.setattr("app.state.services.database", fake_db)
    monkeypatch.setattr("app.repositories.users.fetch_one", fake_fetch_one)

    result = await supporter_keys_uc.redeem_key(code=fake_db.key["code"], user_id=10)

    assert result.duration_days == 30
    assert fake_db.key["used_by"] == 10
    assert fake_db.user["priv"] & int(Privileges.SUPPORTER)


@pytest.mark.asyncio
async def test_redeem_same_key_twice(monkeypatch):
    fake_db = FakeDatabase()

    async def fake_fetch_one(*, id: int):
        return fake_db.user

    monkeypatch.setattr("app.state.services.database", fake_db)
    monkeypatch.setattr("app.repositories.users.fetch_one", fake_fetch_one)

    await supporter_keys_uc.redeem_key(code=fake_db.key["code"], user_id=10)
    with pytest.raises(supporter_keys_uc.SupporterKeyError):
        await supporter_keys_uc.redeem_key(code=fake_db.key["code"], user_id=11)


@pytest.mark.asyncio
async def test_parallel_redeem(monkeypatch):
    fake_db = FakeDatabase()

    async def fake_fetch_one(*, id: int):
        return fake_db.user

    monkeypatch.setattr("app.state.services.database", fake_db)
    monkeypatch.setattr("app.repositories.users.fetch_one", fake_fetch_one)

    async def attempt(user_id: int) -> bool:
        try:
            await supporter_keys_uc.redeem_key(code=fake_db.key["code"], user_id=user_id)
            return True
        except supporter_keys_uc.SupporterKeyError:
            return False

    results = await asyncio.gather(attempt(10), attempt(11))
    assert sum(results) == 1


@pytest.mark.asyncio
async def test_donor_end_extends_from_current(monkeypatch):
    fake_db = FakeDatabase()
    fake_db.user["donor_end"] = 2_000_000_000

    async def fake_fetch_one(*, id: int):
        return fake_db.user

    monkeypatch.setattr("app.state.services.database", fake_db)
    monkeypatch.setattr("app.repositories.users.fetch_one", fake_fetch_one)

    result = await supporter_keys_uc.redeem_key(code=fake_db.key["code"], user_id=10)

    assert result.donor_end == 2_000_000_000 + 30 * 86400


@pytest.mark.asyncio
async def test_generate_requires_admin(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr("app.state.services.redis", fake_redis)

    with pytest.raises(supporter_keys_uc.SupporterPermissionError):
        await supporter_keys_uc.generate_keys(
            admin_id=1,
            admin_priv=int(Privileges.UNRESTRICTED),
            amount=1,
            duration_days=30,
            note=None,
            batch_id=None,
        )
