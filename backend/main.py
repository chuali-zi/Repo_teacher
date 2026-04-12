from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.contracts.domain import UserFacingError
from backend.contracts.dto import error_envelope
from backend.contracts.enums import ErrorCode, SessionStatus
from backend.routes.analysis import router as analysis_router
from backend.routes.chat import router as chat_router
from backend.routes.repo import router as repo_router
from backend.routes.session import router as session_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Repo Tutor",
        version="0.1.0",
        description="Scaffold following docs/CURRENT_SPEC.md v3 contracts.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(repo_router)
    app.include_router(session_router)
    app.include_router(analysis_router)
    app.include_router(chat_router)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    error = UserFacingError(
        error_code=ErrorCode.INVALID_REQUEST,
        message="请求参数不合法，请检查必填字段和格式",
        retryable=True,
        stage=SessionStatus.IDLE,
        input_preserved=True,
        internal_detail=str(exc),
    )
    return JSONResponse(
        status_code=400,
        content=error_envelope(request.headers.get("x-session-id"), error),
    )


app = create_app()
