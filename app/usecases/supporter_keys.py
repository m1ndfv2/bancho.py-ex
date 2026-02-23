from __future__ import annotations

import re
import secrets
import time
import uuid
from dataclasses import dataclass

import app.state
from app.constants.privileges import Privileges
from app.logging import log
from app.repositories import supporter_keys as supporter_keys_repo
from app.repositories import users as users_repo

SUPPORTER_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}$")
SUPPORTER_BIT = int(Privileges.SUPPORTER)
MAX_GENERATE_AMOUNT = 500
MAX_DURATION_DAYS = 3650
REDEEM_WINDOW_SECONDS = 60
REDEEM_WINDOW_LIMIT = 5


class SupporterKeyError(ValueError):
    pass


class SupporterRateLimitError(SupporterKeyError):
    pass


class SupporterPermissionError(SupporterKeyError):
    pass


@dataclass
class RedeemResult:
    code: str
    duration_days: int
    donor_end: int


@dataclass
class GenerateResult:
    batch_id: str
    codes: list[str]


def _require_valid_code(code: str) -> None:
    if SUPPORTER_KEY_PATTERN.fullmatch(code) is None:
        raise SupporterKeyError("Invalid key format.")


def _require_valid_generate(amount: int, duration_days: int) -> None:
    if amount < 1 or amount > MAX_GENERATE_AMOUNT:
        raise SupporterKeyError("amount must be in range [1, 500].")
    if duration_days < 1 or duration_days > MAX_DURATION_DAYS:
        raise SupporterKeyError("durationDays must be in range [1, 3650].")


async def ensure_redeem_rate_limit(user_id: int, ip: str) -> None:
    keys = [
        f"supporter_keys:redeem:user:{user_id}",
        f"supporter_keys:redeem:ip:{ip}",
    ]
    for key in keys:
        current = await app.state.services.redis.incr(key)
        if current == 1:
            await app.state.services.redis.expire(key, REDEEM_WINDOW_SECONDS)
        if int(current) > REDEEM_WINDOW_LIMIT:
            raise SupporterRateLimitError("Too many redeem attempts. Try later.")


def generate_supporter_code() -> str:
    parts = [secrets.token_hex(4).upper() for _ in range(3)]
    return "-".join(parts)


async def generate_keys(
    *,
    admin_id: int,
    admin_priv: int,
    amount: int,
    duration_days: int,
    note: str | None,
    batch_id: str | None,
) -> GenerateResult:
    if (admin_priv & int(Privileges.ADMINISTRATOR)) == 0:
        raise SupporterPermissionError("Administrator privileges required.")

    _require_valid_generate(amount, duration_days)

    resolved_batch_id = batch_id or str(uuid.uuid4())
    if batch_id is not None:
        existing = await supporter_keys_repo.fetch_by_batch_id(batch_id)
        if existing:
            log(
                "supporter_keys.generate.idempotent_hit",
                extra={"batch_id": batch_id, "admin_id": admin_id},
            )
            return GenerateResult(
                batch_id=batch_id,
                codes=[row["code"] for row in existing],
            )

    codes = [generate_supporter_code() for _ in range(amount)]
    await supporter_keys_repo.create_many(
        codes=codes,
        duration_days=duration_days,
        created_by=admin_id,
        batch_id=resolved_batch_id,
        note=note,
    )

    log(
        "supporter_keys.generate.success",
        extra={
            "admin_id": admin_id,
            "amount": amount,
            "duration_days": duration_days,
            "batch_id": resolved_batch_id,
        },
    )

    return GenerateResult(batch_id=resolved_batch_id, codes=codes)


async def redeem_key(*, code: str, user_id: int) -> RedeemResult:
    _require_valid_code(code)

    now = int(time.time())

    async with app.state.services.database.transaction():
        key_row = await app.state.services.database.fetch_one(
            "SELECT id, duration_days "
            "FROM supporter_keys "
            "WHERE code = :code AND used_by = 0 "
            "FOR UPDATE",
            {"code": code},
        )
        if key_row is None:
            raise SupporterKeyError("Key is invalid or already redeemed.")

        duration_days = int(key_row["duration_days"])
        if duration_days < 1 or duration_days > MAX_DURATION_DAYS:
            raise SupporterKeyError("Key has invalid duration.")

        updated = await app.state.services.database.execute(
            "UPDATE supporter_keys "
            "SET used_by = :user_id, used_at = NOW() "
            "WHERE id = :id AND used_by = 0",
            {"user_id": user_id, "id": key_row["id"]},
        )
        if updated == 0:
            raise SupporterKeyError("Key is invalid or already redeemed.")

        user_row = await users_repo.fetch_one(id=user_id)
        if user_row is None:
            raise SupporterKeyError("User not found.")

        donor_base = max(now, int(user_row["donor_end"]))
        donor_end = donor_base + (duration_days * 86400)

        await app.state.services.database.execute(
            "UPDATE users "
            "SET priv = (priv | :supporter_bit), donor_end = :donor_end "
            "WHERE id = :user_id",
            {
                "supporter_bit": SUPPORTER_BIT,
                "donor_end": donor_end,
                "user_id": user_id,
            },
        )

    log(
        "supporter_keys.redeem.success",
        extra={
            "user_id": user_id,
            "code": code,
            "duration_days": duration_days,
            "donor_end": donor_end,
        },
    )
    log(
        "audit.supporter_key_redeem",
        extra={"actor_id": user_id, "code": code, "donor_end": donor_end},
    )
    log(
        "events.OnAddDonorEvent",
        extra={"user_id": user_id, "donor_end": donor_end},
    )

    return RedeemResult(code=code, duration_days=duration_days, donor_end=donor_end)
