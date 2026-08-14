"""Single, side-effect-free A3-02 application-service boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .contracts import AnalysisError, AnalysisReceipt, AnalysisRequest, build_run_key


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AnalysisApplicationService(Protocol):
    def execute(self, request: AnalysisRequest) -> AnalysisReceipt: ...


class UnimplementedAnalysisApplicationService:
    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        return AnalysisReceipt(
            run_key=build_run_key(request),
            invocation_id=request.invocation_id,
            mode=request.mode,
            status="failed",
            started_at_utc=request.requested_at_utc,
            completed_at_utc=_utc_now(),
            errors=(
                AnalysisError(
                    "service",
                    "analysis_route_not_implemented",
                    "analysis route is not implemented",
                ),
            ),
        )


class AnalysisTool:
    def __init__(
        self, application_service: AnalysisApplicationService | None = None
    ) -> None:
        self._service = application_service or UnimplementedAnalysisApplicationService()

    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        request.validate()
        receipt = self._service.execute(request)
        if (
            receipt.mode != request.mode
            or receipt.invocation_id != request.invocation_id
        ):
            raise ValueError("analysis_service_receipt_request_mismatch")
        if receipt.run_key != build_run_key(request):
            raise ValueError("analysis_service_receipt_run_key_mismatch")
        receipt.validate()
        return receipt
