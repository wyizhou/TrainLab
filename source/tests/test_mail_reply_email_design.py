from __future__ import annotations

import pytest

from src.mail_agent.renderer import MailRenderError, render_mail_response


def render(**changes: object):
    value: dict[str, object] = {
        "response_artifact_id": 23,
        "response_kind": "mail_reply",
        "user_visible_text": "已收到你的请求。",
        "delivery_run_id": "mail:response:23:thread-7",
        "original_subject": "Re: [TrainLab idempotency: old] Re: 本周训练",
        "structured_content": {
            "title": "训练安排回复",
            "subject_intent": "调整训练时间",
            "recommendations": ["先保持轻松活动"],
            "safety_note": "如有不适，请停止运动。",
        },
    }
    value.update(changes)
    return render_mail_response(**value)  # type: ignore[arg-type]


def test_reply_design_binds_only_published_values_and_removes_unset_optional_blocks() -> (
    None
):
    value = render()
    assert value.subject == "Re: 本周训练"
    assert "已收到你的请求。" in value.plain_text
    assert "先保持轻松活动" in value.plain_text
    assert "如有不适，请停止运动。" in value.plain_text
    assert "mail:response:23:thread-7" not in value.subject
    assert "mail:response:23:thread-7" not in value.plain_text
    assert "训练安排回复" in value.html and "已收到你的请求。" in value.html
    assert "调整训练时间" in value.html and "先保持轻松活动" in value.html
    assert "安全说明" in value.html
    assert "计划修改" not in value.html and "数据说明：" not in value.html
    assert "data-" not in value.html
    assert "待分析结果写入" not in value.html and "已生成修订建议" not in value.html


@pytest.mark.parametrize(
    "structured",
    (
        [],
        {"recommendations": "not a list"},
        {"safety_note": ["not text"]},
    ),
)
def test_design_fails_closed_for_structured_content_type_errors(
    structured: object,
) -> None:
    with pytest.raises(
        MailRenderError, match="mail_response_structured_content_invalid"
    ):
        render(structured_content=structured)


def test_subject_removes_crlf_replies_and_internal_markers() -> None:
    value = render(
        original_subject="Re: RE: [TrainLab idempotency: x] run-id: old \r\n  训练安排"
    )
    assert value.subject == "Re: 训练安排"
    assert "\r" not in value.subject and "\n" not in value.subject
