from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import status
from fastapi.param_functions import Query

from app.api.v2.common import responses
from app.api.v2.common.auth import AuthContext
from app.api.v2.common.auth import require_admin
from app.api.v2.common.auth import require_logged_in
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.api.v2.models.supporter_keys import GenerateSupporterKeysRequest
from app.api.v2.models.supporter_keys import RedeemSupporterKeyRequest
from app.api.v2.models.supporter_keys import SupporterKeyItem
from app.repositories import supporter_keys as supporter_keys_repo
from app.usecases import supporter_keys as supporter_keys_uc

router = APIRouter()


@router.get("/supporter-keys")
async def supporter_keys_page(
    _: AuthContext = Depends(require_logged_in),
) -> Success[dict[str, str]]:
    return responses.success(
        {
            "message": "Submit your key with POST /v2/supporter-keys/redeem.",
        },
    )


@router.post("/supporter-keys/redeem")
async def redeem_supporter_key(
    payload: RedeemSupporterKeyRequest,
    request: Request,
    context: AuthContext = Depends(require_logged_in),
) -> Success[dict[str, int | str]] | Failure:
    try:
        await supporter_keys_uc.ensure_redeem_rate_limit(
            user_id=context.user_id,
            ip=request.client.host if request.client else "unknown",
        )
        result = await supporter_keys_uc.redeem_key(
            code=payload.code,
            user_id=context.user_id,
        )
    except supporter_keys_uc.SupporterRateLimitError as exc:
        return responses.failure(str(exc), status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    except supporter_keys_uc.SupporterKeyError as exc:
        return responses.failure(str(exc), status_code=status.HTTP_409_CONFLICT)

    return responses.success(
        {
            "message": "Supporter key redeemed successfully.",
            "code": result.code,
            "duration_days": result.duration_days,
            "donor_end": result.donor_end,
        },
        status_code=status.HTTP_200_OK,
    )


@router.get("/admin/supporter-keys")
async def admin_supporter_keys_page(
    _: AuthContext = Depends(require_admin),
) -> Success[dict[str, str]] | Failure:
    return responses.success({"message": "Supporter keys admin page."})


@router.post("/admin/supporter-keys/generate")
async def generate_supporter_keys(
    payload: GenerateSupporterKeysRequest,
    context: AuthContext = Depends(require_admin),
) -> Success[dict[str, object]] | Failure:
    try:
        result = await supporter_keys_uc.generate_keys(
            admin_id=context.user_id,
            admin_priv=context.priv,
            amount=payload.amount,
            duration_days=payload.duration_days,
            note=payload.note,
            batch_id=payload.batch_id,
        )
    except supporter_keys_uc.SupporterPermissionError as exc:
        return responses.failure(str(exc), status_code=status.HTTP_403_FORBIDDEN)
    except supporter_keys_uc.SupporterKeyError as exc:
        return responses.failure(str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    return responses.success(
        {
            "message": "Keys generated.",
            "batch_id": result.batch_id,
            "codes": result.codes,
        },
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/admin/supporter-keys/list")
async def list_supporter_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    _: AuthContext = Depends(require_admin),
) -> Success[list[SupporterKeyItem]] | Failure:
    rows, total = await supporter_keys_repo.fetch_paginated(page, page_size)
    items = [SupporterKeyItem.from_mapping(row) for row in rows]
    return responses.success(
        items,
        meta={
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )
