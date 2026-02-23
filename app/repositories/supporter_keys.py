from __future__ import annotations

from typing import TypedDict

import app.state


class SupporterKey(TypedDict):
    id: int
    code: str
    duration_days: int
    created_by: int
    used_by: int
    created_at: str
    used_at: str | None
    batch_id: str | None
    note: str | None


async def create_many(
    *,
    codes: list[str],
    duration_days: int,
    created_by: int,
    batch_id: str,
    note: str | None,
) -> None:
    await app.state.services.database.execute_many(
        "INSERT INTO supporter_keys "
        "(code, duration_days, created_by, batch_id, note) "
        "VALUES (:code, :duration_days, :created_by, :batch_id, :note)",
        [
            {
                "code": code,
                "duration_days": duration_days,
                "created_by": created_by,
                "batch_id": batch_id,
                "note": note,
            }
            for code in codes
        ],
    )


async def fetch_by_batch_id(batch_id: str) -> list[SupporterKey]:
    rows = await app.state.services.database.fetch_all(
        "SELECT id, code, duration_days, created_by, used_by, created_at, used_at, "
        "batch_id, note "
        "FROM supporter_keys "
        "WHERE batch_id = :batch_id "
        "ORDER BY id ASC",
        {"batch_id": batch_id},
    )
    return rows  # type: ignore[return-value]


async def fetch_paginated(page: int, page_size: int) -> tuple[list[SupporterKey], int]:
    rows = await app.state.services.database.fetch_all(
        "SELECT id, code, duration_days, created_by, used_by, created_at, used_at, "
        "batch_id, note "
        "FROM supporter_keys "
        "ORDER BY created_at DESC "
        "LIMIT :limit OFFSET :offset",
        {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        },
    )
    total = await app.state.services.database.fetch_val(
        "SELECT COUNT(*) FROM supporter_keys",
    )
    return rows, int(total)


async def fetch_one_by_code(code: str) -> SupporterKey | None:
    row = await app.state.services.database.fetch_one(
        "SELECT id, code, duration_days, created_by, used_by, created_at, used_at, "
        "batch_id, note "
        "FROM supporter_keys WHERE code = :code",
        {"code": code},
    )
    return row  # type: ignore[return-value]
