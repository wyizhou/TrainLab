from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[3]


def _load(name: str, relative: str) -> Any:
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COMMON = _load(
    "trainlab_gmail_common_m11_test",
    "skills/gmail-sender/scripts/gmail_rest_common.py",
)


def _asset() -> dict[str, Any]:
    data = b"\x89PNG\r\n\x1a\n" + b"synthetic-chart"
    return {
        "role": "daily_activity_heart_rate",
        "cid": "trainlab-chart-123@trainlab.invalid",
        "filename": "daily-activity-heart-rate.png",
        "media_type": "image/png",
        "width_px": 1248,
        "height_px": 520,
        "sha256": COMMON.sha256_bytes(data),
        "byte_size": len(data),
        "alt": "活动心率图：三个真实采样点",
        "data": data,
    }


def _kwargs() -> dict[str, Any]:
    asset = _asset()
    subject = "TrainLab · 每日训练简报 · 2026-08-21"
    return {
        "recipient": "owner@example.com",
        "subject": subject,
        "plain": "今天可以轻松训练。",
        "html": f'<html><head><title>{subject}</title></head><body><h1>{subject}</h1><img src="cid:{asset["cid"]}" alt="图"></body></html>',
        "source_sha256": "a" * 64,
        "date_value": datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        "inline_assets": [asset],
    }


def test_mime_v2_is_deterministic_exact_and_v1_golden_is_unchanged() -> None:
    first = COMMON.deterministic_mime_v2(**_kwargs())
    second = COMMON.deterministic_mime_v2(**_kwargs())
    assert first == second
    raw, message_id, digest = first
    assert digest == COMMON.sha256_bytes(raw)
    assert (
        COMMON.verify_mime_v2_with_actual_message_id(
            raw,
            recipient=_kwargs()["recipient"],
            subject=_kwargs()["subject"],
            plain=_kwargs()["plain"],
            html=_kwargs()["html"],
            inline_assets=_kwargs()["inline_assets"],
        )
        == message_id
    )
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    assert parsed.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in parsed.iter_parts()] == [
        "text/plain",
        "multipart/related",
    ]

    old = COMMON.deterministic_mime(
        recipient="athlete@example.com",
        subject="TrainLab daily",
        plain="plain report",
        html="<p>html report</p>",
        source_sha256="a" * 64,
        date_value=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )
    assert (
        old[1]
        == "<trainlab.92ec700b9d9d20ec5a0eae1c585c86501e1c8b2ee07193960cbf051e601177a0@trainlab.invalid>"
    )
    assert old[2] == "efb65e65025903ed9b38a833aea72aab3e1fb116712371a5f238cd98a5d7352f"


def test_mime_v2_keeps_related_container_without_charts() -> None:
    kwargs = _kwargs()
    kwargs["html"] = (
        "<html><head><title>TrainLab · 每日训练简报 · 2026-08-21</title></head>"
        "<body><h1>TrainLab · 每日训练简报 · 2026-08-21</h1></body></html>"
    )
    kwargs["inline_assets"] = []
    raw, message_id, _digest = COMMON.deterministic_mime_v2(**kwargs)
    assert (
        COMMON.verify_mime_v2_with_actual_message_id(
            raw,
            recipient=kwargs["recipient"],
            subject=kwargs["subject"],
            plain=kwargs["plain"],
            html=kwargs["html"],
            inline_assets=[],
        )
        == message_id
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_reference",
        "remote_image",
        "data_uri",
        "duplicate_cid",
        "wrong_sha",
        "orphan_asset",
    ],
)
def test_mime_v2_rejects_unsafe_or_unclosed_assets(mutation: str) -> None:
    values = _kwargs()
    asset = dict(values["inline_assets"][0])
    values["inline_assets"] = [asset]
    if mutation == "missing_reference":
        values["html"] = values["html"].replace("cid:", "cid:missing-")
    elif mutation == "remote_image":
        values["html"] += '<img src="https://example.com/private.png">'
    elif mutation == "data_uri":
        values["html"] += '<img src="data:image/png;base64,AA==">'
    elif mutation == "duplicate_cid":
        values["inline_assets"].append(dict(asset))
    elif mutation == "wrong_sha":
        asset["sha256"] = "0" * 64
    elif mutation == "orphan_asset":
        extra = dict(asset)
        extra["cid"] = "orphan@trainlab.invalid"
        extra["filename"] = "orphan.png"
        values["inline_assets"].append(extra)
    with pytest.raises(COMMON.GmailRestError):
        COMMON.deterministic_mime_v2(**values)


def test_mime_v2_verifier_rejects_tampered_png_and_html() -> None:
    raw, _message_id, _digest = COMMON.deterministic_mime_v2(**_kwargs())
    expected = _kwargs()
    expected["inline_assets"][0] = dict(expected["inline_assets"][0])
    expected["inline_assets"][0]["data"] += b"tampered"
    expected["inline_assets"][0]["byte_size"] = len(
        expected["inline_assets"][0]["data"]
    )
    expected["inline_assets"][0]["sha256"] = COMMON.sha256_bytes(
        expected["inline_assets"][0]["data"]
    )
    with pytest.raises(COMMON.GmailRestError, match="gmail_rest_mime_mismatch"):
        COMMON.verify_mime_v2_with_actual_message_id(
            raw,
            **{
                key: expected[key]
                for key in ("recipient", "subject", "plain", "html", "inline_assets")
            },
        )


def test_mime_v2_accepts_frozen_brand_and_status_cid_dimensions() -> None:
    values = _kwargs()
    assets = []
    for role, width, height in (
        ("email_brand_mark", 96, 96),
        ("email_status_caution", 64, 64),
    ):
        data = b"\x89PNG\r\n\x1a\n" + role.encode()
        assets.append(
            {
                "role": role,
                "cid": f"{role}@trainlab.invalid",
                "filename": f"{role}.png",
                "media_type": "image/png",
                "width_px": width,
                "height_px": height,
                "sha256": COMMON.sha256_bytes(data),
                "byte_size": len(data),
                "alt": "TrainLab" if role == "email_brand_mark" else "需要谨慎",
                "data": data,
            }
        )
    values["inline_assets"] = assets
    values["html"] = (
        f"<html><head><title>{values['subject']}</title></head><body>"
        f"<h1>{values['subject']}</h1>"
        + "".join(
            f'<img src="cid:{item["cid"]}" alt="{item["alt"]}">' for item in assets
        )
        + "</body></html>"
    )
    raw, message_id, _digest = COMMON.deterministic_mime_v2(**values)
    assert (
        COMMON.verify_mime_v2_with_actual_message_id(
            raw,
            recipient=values["recipient"],
            subject=values["subject"],
            plain=values["plain"],
            html=values["html"],
            inline_assets=assets,
        )
        == message_id
    )
    invalid = dict(assets[0])
    invalid["width_px"] = 64
    values["inline_assets"] = [invalid, assets[1]]
    with pytest.raises(COMMON.GmailRestError, match="gmail_rest_inline_asset_invalid"):
        COMMON.deterministic_mime_v2(**values)


@pytest.mark.parametrize("mutation", ["missing", "wrong", "duplicate"])
def test_mime_v2_requires_one_title_equal_to_subject(mutation: str) -> None:
    values = _kwargs()
    subject = values["subject"]
    title = f"<title>{subject}</title>"
    if mutation == "missing":
        values["html"] = values["html"].replace(title, "")
    elif mutation == "wrong":
        values["html"] = values["html"].replace(title, "<title>错误标题</title>")
    else:
        values["html"] = values["html"].replace(title, title + title)
    with pytest.raises(
        COMMON.GmailRestError, match="gmail_rest_subject_heading_mismatch"
    ):
        COMMON.deterministic_mime_v2(**values)
