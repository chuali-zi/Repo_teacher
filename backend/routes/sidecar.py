from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.dto import ExplainSidecarData, ExplainSidecarRequest, success_envelope
from backend.routes._errors import error_response
from backend.sidecar import explainer

router = APIRouter(prefix="/api", tags=["sidecar"])


@router.post("/sidecar/explain")
async def explain_sidecar(request: ExplainSidecarRequest) -> JSONResponse:
    try:
        data = await explainer.explain_question(request.question)
    except UserFacingErrorException as exc:
        return error_response(None, exc.error)
    return JSONResponse(status_code=200, content=success_envelope(None, data))
