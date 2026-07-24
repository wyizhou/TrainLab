from __future__ import annotations
from io import StringIO
import json
import pytest
from trainlab.analysis.cli import exit_code_for, main, parse_request
from trainlab.analysis.contracts import AnalysisContractError, AnalysisError, AnalysisReceipt, AnalysisRequest, build_run_key
from trainlab.analysis.service import AnalysisTool
REQUESTED_AT = "2026-07-23T00:00:00Z"
def payload(mode: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {"schema_version":"1","mode":mode,"subject_id":"subject_1","invocation_id":"invoke_1" if mode!="status" else None,"run_key":None,"summary_local_date":None,"advice_local_date":None,"as_of_local_date":None,"plan_id":None,"reason_event_id":None,"effective_local_date":None,"artifact_id":None,"delivery_id":None,"regeneration_reason_code":None,"requested_at_utc":REQUESTED_AT}
    if mode == "revise_plan": value.update(plan_id="plan_1", reason_event_id="event_1")
    if mode == "regenerate": value.update(artifact_id="artifact_1", regeneration_reason_code="explicit_user_request")
    if mode in {"retry_delivery","reconcile_delivery"}: value.update(delivery_id="delivery_1")
    value.update(changes); return value
@pytest.mark.parametrize("mode", ["daily","weekly","revise_plan","regenerate","retry_delivery","reconcile_delivery","status"])
def test_each_mode_has_a_strict_valid_request(mode: str) -> None:
    request = AnalysisRequest.from_dict(payload(mode)); assert build_run_key(request).startswith(f"analysis:subject_1:{mode}:")
@pytest.mark.parametrize(("mode","changes"), [("daily",{"run_key":"analysis:subject_1:daily:x:y"}),("weekly",{"summary_local_date":"2026-07-22"}),("revise_plan",{"reason_event_id":None}),("regenerate",{"regeneration_reason_code":None}),("retry_delivery",{"delivery_id":None}),("reconcile_delivery",{"artifact_id":"x"}),("status",{"invocation_id":"x"})])
def test_mode_fields_are_mutually_exclusive(mode: str, changes: dict[str, object]) -> None:
    with pytest.raises(AnalysisContractError, match="analysis_request_schema_invalid"): AnalysisRequest.from_dict(payload(mode, **changes))
def test_status_run_key_is_selector_only_and_is_echoed() -> None:
    selected = "analysis:subject_1:daily:2026-07-22:invoke_old"; request = AnalysisRequest.from_dict(payload("status", run_key=selected))
    assert build_run_key(request) == selected and request.invocation_id is None
    assert parse_request(["status","--run-key",selected], subject_id="subject_1", requested_at_utc=REQUESTED_AT).run_key == selected
@pytest.mark.parametrize("mode", ["daily","weekly","revise_plan","regenerate","retry_delivery","reconcile_delivery"])
def test_run_key_is_rejected_for_every_non_status_mode(mode: str) -> None:
    with pytest.raises(AnalysisContractError, match="analysis_request_schema_invalid"):
        AnalysisRequest.from_dict(payload(mode, run_key="analysis:subject_1:daily:2026-07-22:old"))
def test_status_without_run_key_uses_a_stable_read_only_selector() -> None:
    request = AnalysisRequest.from_dict(payload("status"))
    assert build_run_key(request) == "analysis:subject_1:status:current:read_only"
def test_bad_date_id_utc_and_forbidden_controls_are_rejected() -> None:
    for changes in ({"summary_local_date":"2026-02-30"},{"subject_id":"bad subject"},{"requested_at_utc":"2026-07-23T00:00:00+08:00"},{"model":"x"},{"prompt":"x"},{"harness_path":"x"},{"command":"x"},{"recipient":"x"},{"body":"x"}):
        with pytest.raises(AnalysisContractError): AnalysisRequest.from_dict(payload("daily", **changes))
class RecordingService:
    def __init__(self) -> None: self.request: AnalysisRequest | None = None
    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        self.request = request; return AnalysisReceipt(run_key=build_run_key(request),invocation_id=request.invocation_id,mode=request.mode,status="deferred",started_at_utc=request.requested_at_utc,completed_at_utc=REQUESTED_AT,errors=(AnalysisError("service","waiting_for_future_layer","no body"),))
class WrongRunKeyService:
    def execute(self, request: AnalysisRequest) -> AnalysisReceipt:
        return AnalysisReceipt(run_key="analysis:subject_1:daily:other:wrong",invocation_id=request.invocation_id,mode=request.mode,status="deferred",started_at_utc=request.requested_at_utc,completed_at_utc=REQUESTED_AT,errors=(AnalysisError("service","waiting_for_future_layer","safe"),))
@pytest.mark.parametrize("analysis_request", [
    AnalysisRequest.from_dict(payload("daily")),
    AnalysisRequest.from_dict(payload("status", run_key="analysis:subject_1:daily:2026-07-22:selected")),
    AnalysisRequest.from_dict(payload("status")),
])
def test_service_receipt_rejects_a_wrong_run_key_for_write_and_status_selectors(analysis_request: AnalysisRequest) -> None:
    with pytest.raises(ValueError, match="analysis_service_receipt_run_key_mismatch"):
        AnalysisTool(WrongRunKeyService()).execute(analysis_request)
@pytest.mark.parametrize("analysis_request", [
    AnalysisRequest.from_dict(payload("daily")),
    AnalysisRequest.from_dict(payload("status", run_key="analysis:subject_1:daily:2026-07-22:selected")),
    AnalysisRequest.from_dict(payload("status")),
])
def test_service_receipt_accepts_the_exact_expected_run_key(analysis_request: AnalysisRequest) -> None:
    service = RecordingService()
    assert AnalysisTool(service).execute(analysis_request).run_key == build_run_key(analysis_request)
def test_cli_and_python_api_share_one_service_and_stdout_only_has_receipt() -> None:
    service=RecordingService(); output=StringIO(); code=main(["status","--run-key","analysis:subject_1:daily:2026-07-22:old"],tool=AnalysisTool(service),subject_id="subject_1",stdout=output)
    assert code == 11 and service.request is not None and service.request.run_key == "analysis:subject_1:daily:2026-07-22:old"
    receipt=json.loads(output.getvalue()); assert receipt["run_key"] == service.request.run_key and "prompt" not in output.getvalue()
def test_cli_never_generates_an_invocation_id() -> None:
    with pytest.raises(ValueError,match="analysis_invocation_id_required"): parse_request(["daily"],subject_id="subject_1",requested_at_utc=REQUESTED_AT)
    assert parse_request(["daily"],subject_id="subject_1",invocation_id_provider=lambda:"injected_1",requested_at_utc=REQUESTED_AT).invocation_id == "injected_1"
@pytest.mark.parametrize(("status","code"),[("succeeded",0),("unchanged",0),("partial",10),("deferred",11),("lock_busy",12),("rejected",20),("failed",21)])
def test_exit_mapping(status: str, code: int) -> None: assert exit_code_for(status) == code
