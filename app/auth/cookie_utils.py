"""
HttpOnly 세션 쿠키 set/clear — domain·secure·path를 set/delete 간 동일하게 유지.
"""
from __future__ import annotations

from typing import Any

from starlette.responses import Response

from app.config import get_cookie_domain, get_cookie_secure
from app.auth.dependencies import COOKIE_KEY
from app.core.auth_admin import ADMIN_COOKIE_KEY

GUEST_COOKIE_KEY = "flairy_guest_token"


def _base_cookie_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": get_cookie_secure(),
    }
    domain = get_cookie_domain()
    if domain:
        kwargs["domain"] = domain
    return kwargs


def set_access_token_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(key=COOKIE_KEY, value=token, max_age=max_age, **_base_cookie_kwargs())


def clear_access_token_cookie(response: Response) -> None:
    kwargs = _base_cookie_kwargs()
    response.set_cookie(key=COOKIE_KEY, value="", max_age=0, **kwargs)


def set_guest_token_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(key=GUEST_COOKIE_KEY, value=token, max_age=max_age, **_base_cookie_kwargs())


def set_admin_token_cookie(response: Response, token: str, max_age: int = 86400) -> None:
    response.set_cookie(key=ADMIN_COOKIE_KEY, value=token, max_age=max_age, **_base_cookie_kwargs())


def clear_admin_token_cookie(response: Response) -> None:
    kwargs = _base_cookie_kwargs()
    response.set_cookie(key=ADMIN_COOKIE_KEY, value="", max_age=0, **kwargs)
