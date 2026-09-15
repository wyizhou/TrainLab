from pathlib import Path

import pytest

from skills._shared.fit_weekly import (
    email_config,
    gmail_auth,
    gmail_scopes,
    publication,
)


def private(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    "text",
    [
        "owner@example.invalid",
        "# 默认邮箱\n填写自己的 Gmail，用于发送和接收。\nowner@example.invalid\n",
    ],
)
def test_single_mail_with_prose(tmp_path, text):
    assert (
        email_config.read(tmp_path, str(private(tmp_path / "Email.md", text.encode())))
        == "owner@example.invalid"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"owner@example.invalid owner@example.invalid",
        b"owner@example.invalid\nother@example.invalid",
        b"Owner <owner@example.invalid>",
        b"owner@example.invalid\r\nBcc: other",
        b"owner@example.invalid,",
        b"owner@@example.invalid",
        b"\xff",
    ],
)
def test_email_rejects_ambiguous_or_invalid(tmp_path, raw):
    with pytest.raises(ValueError):
        email_config.read(tmp_path, str(private(tmp_path / "Email.md", raw)))


def test_email_permissions_and_symlink(tmp_path):
    path = private(tmp_path / "Email.md", b"owner@example.invalid")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        email_config.read(tmp_path, str(path))
    path.chmod(0o600)
    link = tmp_path / "alias.md"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        email_config.read(tmp_path, str(link))


def test_scope_source_and_capabilities():
    assert gmail_auth.SCOPES == gmail_scopes.SCOPES
    assert gmail_scopes.SCOPES == {"https://www.googleapis.com/auth/gmail.modify"}
    assert gmail_scopes.valid(gmail_scopes.LEGACY_SCOPES, labels=False)
    assert not gmail_scopes.valid(gmail_scopes.LEGACY_SCOPES, labels=True)
    assert not gmail_scopes.valid(
        gmail_scopes.SCOPES | {"https://mail.google.com/"}, labels=True
    )


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        (
            "2026-08-09T07:00:00Z",
            "TrainLab｜每周训练报告｜回顾2026年8月2日—2026年8月9日｜计划2026年8月10日—2026年8月16日",
        ),
        (
            "2027-01-03T07:00:00Z",
            "TrainLab｜每周训练报告｜回顾2026年12月27日—2027年1月3日｜计划2027年1月4日—2027年1月10日",
        ),
    ],
)
def test_original_hong_kong_subject(end, expected):
    assert publication.weekly_subject(end) == expected


@pytest.mark.parametrize("repository", [False, True])
def test_private_token_boundary_follows_repository_or_standalone_source(
    tmp_path, monkeypatch, repository
):
    from skills._shared.fit_weekly import run_config

    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(run_config, "SOURCE", source)
    if repository:
        (tmp_path / ".git").write_text("synthetic git marker")
    with pytest.raises(ValueError, match="in_repository"):
        email_config.outside_repository(source / "token.json")
    if repository:
        with pytest.raises(ValueError, match="in_repository"):
            email_config.outside_repository(tmp_path / "private" / "token.json")
    else:
        email_config.outside_repository(tmp_path / "private" / "token.json")
