from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.services.invite_access_service import (
    INVITE_COOKIE,
    InviteAccessService,
)


router = APIRouter(prefix="/access", tags=["access"])


class InviteCodeInput(BaseModel):
    code: str = Field(min_length=4, max_length=128)


@router.get("/status")
def access_status(request: Request) -> dict:
    required = settings.app_env == "production" and bool(
        settings.invite_code
    )
    return {
        "required": required,
        "authorized": (
            not required or InviteAccessService.authorize(request)
        ),
    }


@router.post("/invite")
def authorize_invite(
    payload: InviteCodeInput,
    request: Request,
    response: Response,
):
    if not InviteAccessService.verify_code(payload.code):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "INVALID_INVITE_CODE",
                    "message": "邀请码不正确，请向邀请人确认。",
                }
            },
        )
    response.set_cookie(
        key=INVITE_COOKIE,
        value=InviteAccessService.issue_token(),
        max_age=settings.invite_access_ttl_hours * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/v1",
    )
    return {"authorized": True}
