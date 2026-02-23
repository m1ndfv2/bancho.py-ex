from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials as HTTPCredentials
from fastapi.security import HTTPBearer

import app.state
from app.constants.privileges import Privileges
from app.repositories import users as users_repo

http_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user_id: int
    priv: int


async def require_logged_in(
    request: Request,
    token: HTTPCredentials | None = Depends(http_bearer_scheme),
) -> AuthContext:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    user_id = app.state.sessions.api_keys.get(token.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    user = await users_repo.fetch_one(id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    request.state.auth_user_id = int(user_id)
    return AuthContext(user_id=int(user_id), priv=int(user["priv"]))


async def require_admin(context: AuthContext = Depends(require_logged_in)) -> AuthContext:
    if (context.priv & int(Privileges.ADMINISTRATOR)) == 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges required.")
    return context
