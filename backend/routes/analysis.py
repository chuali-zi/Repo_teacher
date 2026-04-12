from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.sse import encode_sse_stream
from backend.m5_session import session_service
from backend.m5_session.event_streams import iter_analysis_events
from backend.routes._sse import error_sse_response

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/analysis/stream")
async def analysis_stream(session_id: str = Query()) -> StreamingResponse:
    try:
        session_service.assert_session_matches(session_id)
    except UserFacingErrorException as exc:
        return error_sse_response(session_id, exc.error)
    return StreamingResponse(
        encode_sse_stream(iter_analysis_events(session_id)),
        media_type="text/event-stream; charset=utf-8",
    )
