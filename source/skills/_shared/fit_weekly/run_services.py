from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    email_config,
    gmail_auth,
    gmail_message,
    gmail_rest,
    run_config,
)


@dataclass(frozen=True)
class Garmin:
    token_root: Path
    is_cn: bool


@dataclass(frozen=True)
class Gmail:
    token_file: Path
    account: str
    recipient: str

    def client(self) -> gmail_rest.Client:
        return gmail_rest.Client(gmail_auth.Auth(self.token_file, self.account))


def garmin(config: run_config.Config) -> Garmin:
    value = config.service("garmin")
    if set(value) != {"token_root", "is_cn"} or type(value["is_cn"]) is not bool:
        raise ValueError("garmin_config_invalid")
    token = run_config.private_path(config.root, value["token_root"], directory=True)
    return Garmin(token, value["is_cn"])


def gmail_envelope(config: run_config.Config) -> dict[str, Any]:
    value = config.service("gmail")
    if set(value) != {"token_file", "email_file"}:
        raise ValueError("gmail_config_invalid")
    account = email_config.read(config.root, value["email_file"])
    return {"token_file": value["token_file"], "account": account, "recipient": account}


def gmail(config: run_config.Config) -> Gmail:
    value = gmail_envelope(config)
    token = run_config.private_path(config.root, value["token_file"])
    email_config.outside_repository(token)
    return Gmail(
        token,
        gmail_message.address(value["account"]),
        gmail_message.address(value["recipient"]),
    )
