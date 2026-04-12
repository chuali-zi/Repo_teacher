from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.dto import SendMessageRequest, success_envelope
from backend.contracts.sse import encode_sse_stream
from backend.m5_session import session_service
from backend.m5_session.event_streams import iter_chat_events
from backend.routes._errors import error_response
from backend.routes._sse import error_sse_response

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def send_message(request: SendMessageRequest, x_session_id: str = Header()) -> JSONResponse:
    try:
        data = session_service.accept_chat_message(x_session_id, request.message)
    except UserFacingErrorException as exc:
        return error_response(x_session_id, exc.error)
    return JSONResponse(status_code=202, content=success_envelope(x_session_id, data))


@router.get("/chat/stream")
async def chat_stream(session_id: str = Query()) -> StreamingResponse:
    try:
        session_service.assert_session_matches(session_id)
    except UserFacingErrorException as exc:
        return error_sse_response(session_id, exc.error)
    return StreamingResponse(
        encode_sse_stream(iter_chat_events(session_id)),
        media_type="text/event-stream; charset=utf-8",
    )
