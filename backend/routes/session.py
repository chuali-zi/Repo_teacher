
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.dto import success_envelope
from backend.m5_session import session_service
from backend.routes._errors import error_response

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session")
async def get_session(x_session_id: str | None = Header(default=None)) -> JSONResponse:
    try:
        data = session_service.get_snapshot(x_session_id)
    except UserFacingErrorException as exc:
        return error_response(x_session_id, exc.error)
    return JSONResponse(status_code=200, content=success_envelope(data.session_id, data))


@router.delete("/session")
async def delete_session(x_session_id: str = Header()) -> JSONResponse:
    try:
        data = session_service.clear_session(x_session_id)
    except UserFacingErrorException as exc:
        return error_response(x_session_id, exc.error)
    return JSONResponse(status_code=200, content=success_envelope(None, data))
