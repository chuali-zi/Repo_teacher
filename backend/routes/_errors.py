from fastapi.responses import JSONResponse

from backend.contracts.domain import UserFacingError
from backend.contracts.dto import error_envelope
from backend.contracts.enums import ErrorCode


def status_for_error(error: UserFacingError) -> int:
    if error.error_code == ErrorCode.INVALID_REQUEST:
        return 400
    if error.error_code == ErrorCode.INVALID_STATE:
        return 409
    return 500


def error_response(session_id: str | None, error: UserFacingError) -> JSONResponse:
    return JSONResponse(
        status_code=status_for_error(error),
        content=error_envelope(session_id, error),
    )

