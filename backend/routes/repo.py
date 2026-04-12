from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.dto import (
    SubmitRepoRequest,
    ValidateRepoRequest,
    error_envelope,
    success_envelope,
)
from backend.m5_session import session_service
from backend.routes._errors import error_response

router = APIRouter(prefix="/api", tags=["repo"])


@router.post("/repo/validate")
async def validate_repo(request: ValidateRepoRequest) -> dict:
    data = session_service.validate_repo_input(request.input_value)
    return success_envelope(None, data)


@router.post("/repo")
async def submit_repo(request: SubmitRepoRequest) -> JSONResponse:
    try:
        data = session_service.create_repo_session(request.input_value)
    except UserFacingErrorException as exc:
        return error_response(None, exc.error)
    return JSONResponse(
        status_code=202,
        content=success_envelope(session_service.store.active_session.session_id, data)
        if session_service.store.active_session
        else error_envelope(None, session_service.invalid_request_error("会话创建失败")),
    )
