from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    fit_detail,
    fit_sync,
    model_job,
    storage,
    weekly_stages,
)

jobs = importlib.import_module("test_m12_model_job")


def setup(tmp_path):
    root, end, scope, payload, schema, adapter = jobs.setup(tmp_path)
    goal = json.loads(
        (Path(__file__).parents[1] / "fixtures/m12_legacy_goal.json").read_text()
    )
    payload["goal_snapshot"] = {"sha256": model_job.sha(goal), "goal": goal}

    def validate_input(body):
        assert body == payload

    def validate_result(output, body):
        validate_input(body)
        assert output == {"ok": True}

    contract = weekly_stages.StageContract(schema, validate_result, lambda *_: adapter)
    return (
        root,
        end,
        scope,
        payload,
        schema,
        adapter,
        validate_input,
        validate_result,
        contract,
    )


@pytest.mark.parametrize("entry", ["model_job", "weekly_stages"])
def test_old_goal_cannot_create_model_intent(tmp_path, entry):
    root, end, scope, payload, schema, adapter, check_input, check_result, contract = (
        setup(tmp_path)
    )
    before = (root / "trainlab-fit.db").read_bytes()
    with pytest.raises(ValueError, match="^model_legacy_goal_readonly$"):
        if entry == "model_job":
            model_job.run(
                root,
                end,
                scope,
                payload,
                schema,
                adapter,
                stage="plan",
                validate_input=check_input,
                validate_result=check_result,
            )
        else:

            def forbidden(*_):
                raise AssertionError("legacy goal must stop before adapter preparation")

            contract = weekly_stages.StageContract(schema, check_result, forbidden)
            weekly_stages.execute(
                root, end, "plan", payload, scope, contract, check_input
            )
    assert adapter.calls == 0
    assert (root / "trainlab-fit.db").read_bytes() == before
    assert not model_job.capture_path(root, end, stage="plan").parent.exists()


@pytest.mark.parametrize("status", ["succeeded", "unknown"])
def test_old_goal_existing_intent_recovers_with_same_sha_and_budget(tmp_path, status):
    root, end, scope, payload, schema, adapter, check_input, check_result, contract = (
        setup(tmp_path)
    )
    host = fit_detail.DetailHost(root, end, scope, stage="plan")
    host.read(jobs.fixture.request())
    assert host.usage()["requests"] == 1
    request, validator = model_job.prepare_request(
        end,
        scope,
        payload,
        schema,
        adapter.profile,
        stage="plan",
        validate_input=check_input,
        validate_result=check_result,
    )
    key = "model-job:" + end + ":plan"
    with storage.open_store(root) as db:
        fit_detail.put(db, key + ":intent", model_job.sha(request), request)
    path = model_job.capture_path(root, end, stage="plan")
    fit_sync.private_directory(path.parent.parent)
    fit_sync.private_directory(path.parent)
    if status == "succeeded":
        capture = model_job.checked_result(
            request, {"ok": True}, None, validator, check_result
        )
        storage.atomic_file(path, storage.canonical(capture).encode())
        with storage.open_store(root) as db:
            fit_detail.put(db, key + ":result", model_job.sha(request), capture)
    before = (root / "trainlab-fit.db").read_bytes()
    budget = fit_detail.DetailHost(root, end, scope, stage="plan").usage()

    def forbidden(*_):
        raise AssertionError("saved stages must never prepare an adapter")

    contract = weekly_stages.StageContract(schema, check_result, forbidden)
    for _ in range(2):
        result = weekly_stages.execute(
            root, end, "plan", payload, scope, contract, check_input
        )
        assert result["status"] == status
        assert result["invocation_adapter_calls"] == 0
    assert adapter.calls == 0
    assert fit_detail.DetailHost(root, end, scope, stage="plan").usage() == budget
    assert (root / "trainlab-fit.db").read_bytes() == before
