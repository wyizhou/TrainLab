"""Public synthetic, real R2/R3 pipeline used by R4 offline checks."""

import importlib
import json
from copy import deepcopy

coaching_fixture = importlib.import_module("m12_coaching_factory")
contexts = importlib.import_module("test_m12_weekly_context")
END = contexts.fixture.END


def setup(
    tmp_path,
    monkeypatch,
    *,
    activities=None,
    transform=None,
    activity_name=None,
    with_cadence=False,
):
    from skills._shared.fit_weekly import coaching, model_job, weekly_stages

    if with_cadence:
        original_record = contexts.fixture.factory.record

        def cadence_record(t, distance, hr, *, extra=()):
            return original_record(t, distance, hr, extra=(*extra, (4, 2, 88)))

        monkeypatch.setattr(contexts.fixture.factory, "record", cadence_record)
    if activity_name is not None:
        original_call = contexts.fixture.FakeSDK.call_tool

        async def named_call(self, name, arguments):
            result = await original_call(self, name, arguments)
            if name == "get_activities_by_date":
                value = json.loads(result.content[0].text)
                for activity in value["activities"]:
                    activity["name"] = activity_name
                result.content[0].text = json.dumps(value)
            return result

        monkeypatch.setattr(contexts.fixture.FakeSDK, "call_tool", named_call)
    root, evidence, _ = contexts.setup(
        tmp_path, monkeypatch, activities, parser_version="fit-summary-2"
    )
    calls = []

    def prepare(stage):
        def factory(payload, scope):
            output = (
                coaching_fixture.plan()
                if stage == "plan"
                else coaching_fixture.summary(payload)
            )
            if transform:
                transform(stage, output, payload)
            adapter = model_job.FakeAdapter(output, [])
            calls.append(adapter)
            return adapter

        return factory

    result = weekly_stages.run(
        root,
        END,
        plan=coaching.stage_contract(root, "plan", prepare("plan")),
        summary=coaching.stage_contract(root, "summary", prepare("summary")),
        validate_history=coaching.validator(root),
    )
    assert result["publishable"]
    return root, evidence, calls


def edited_summary(revision):
    value = deepcopy(revision["summary_content"])
    value["core_conclusions"][0]["text"] = "现有资料不足，暂不作进一步判断。"
    return value


def supported_content(stage, output, payload):
    """Known source values and complete repeated easy steps for report QA."""
    if stage == "plan":
        running = payload["running_activities"][0]
        output["rationale"] = coaching_fixture.claim(
            "依据现有跑步记录安排轻松课程，负荷变化仍有不确定性。",
            [coaching_fixture.reference(running)],
        )
        w = output["days"][0]["workout"]
        w["steps"][0]["repeat"] = 2
        w["steps"][0]["steps"][0]["value"] = 600
    else:
        running = next(
            a
            for a in payload["current_week"]["activities"]
            if a["sessions"][0]["sport"] == "running"
        )
        output["core_conclusions"] = [
            coaching_fixture.claim(
                "本期跑步记录保留了可核验距离，采样局限见活动清单。",
                [coaching_fixture.reference(running)],
            )
        ]
        output["running_analysis"]["technique"] = [
            coaching_fixture.claim(
                "设备记录节律可供观察；单次平均值不能证明动作质量，也不换算为单脚步数。",
                [
                    coaching_fixture.reference(
                        running, ["summary", "metrics", "cadence_rpm", "mean"]
                    )
                ],
            )
        ]
