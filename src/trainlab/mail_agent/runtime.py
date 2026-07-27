"""Production composition root for the one-shot fourth-layer mail tool.

There is intentionally no daemon, timer, background thread, or provider
fallback here.  Each ``execute`` call verifies the initialized Foundation
environment, opens one SQLite connection, builds the requested stages and
closes every owned resource before returning its receipt.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from trainlab.foundation import FoundationConfig, FoundationRequest, FoundationTool
from trainlab.util import project_root

from .application import MailApplicationService, MailApplicationStages
from .context import MailContextBuilder
from .contracts import MailCounts, MailReceipt, MailRequest, utc_now
from .delivery import MailResponseDeliveryService
from .delivery_repository import MailDeliveryRepository
from .fact_gate import FactGate
from .locks import MailLockBusyError, MailWriteLock
from .poll import MailPollConfig, MailPollService
from .publisher import MailResponsePublisher
from .repository import MailRepository
from .runner import MailCodexRunner
from .stages import (
    DeliveryStage, MissingDependencyStage, PollStage, PreparedStage, ProcessStage, QueueStage,
    ReconcileStage, StatusStage,
)

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_LOCAL_TZ = ZoneInfo("Asia/Singapore")


class MailEnvironmentFactory(Protocol):
    """Narrow seam implemented by the current-environment Gmail adapter.

    The adapter factory must use only the current Codex ``gmail`` MCP binding.
    It must not accept a credential path, executable path, arbitrary recipient,
    or host-specific configuration.
    """

    def __call__(self, foundation: FoundationConfig, *, recipient_address: str) -> Any: ...


@dataclass(frozen=True)
class MailRuntimeDependencies:
    environment_factory: MailEnvironmentFactory | None = None
    runner_factory: Callable[[], Any] = MailCodexRunner
    repository_factory: Callable[[sqlite3.Connection], MailRepository] = MailRepository
    context_factory: Callable[[sqlite3.Connection], Any] = MailContextBuilder
    gate_factory: Callable[[], Any] = FactGate
    clock: Callable[[], str] = utc_now


def _receipt(request: MailRequest, code: str) -> MailReceipt:
    run_key = request.run_key if request.mode == "status" and request.run_key else request.stable_run_key
    return MailReceipt(
        run_key=run_key, invocation_id=request.invocation_id, mode=request.mode,
        status="failed", counts=MailCounts(failed=1),
        errors=({"stage": "prepare", "code": code, "summary": "mail environment is not ready"},),
        started_at_utc=request.requested_at_utc, completed_at_utc=utc_now(),
    )


def _recipient_email(root: Path) -> str:
    """Read the sole fixed recipient authority from the ignored local config."""
    try:
        value = json.loads((root / "config" / "trainlab.json").read_text(encoding="utf-8"))
        email = value["mail"]["recipient_email"]
    except (OSError, TypeError, ValueError, KeyError):
        raise ValueError("mail_runtime_configuration_invalid") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("mail"), dict)
        or not isinstance(email, str)
        or email != email.strip()
        or not _EMAIL.fullmatch(email)
    ):
        raise ValueError("mail_runtime_configuration_invalid")
    return email.lower()


def _default_environment_factory() -> MailEnvironmentFactory | None:
    """Late import prevents status from importing or starting an MCP adapter."""
    try:
        from .environment_adapter import create_environment_adapter
    except ImportError:
        return None
    return create_environment_adapter  # type: ignore[return-value]


class _LockedStage:
    """Give each mutable non-poll stage the same fail-closed write boundary."""

    def __init__(self, stage: Any, lock_path: Path) -> None:
        self._stage = stage
        self._lock_path = lock_path

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            with MailWriteLock(self._lock_path, request.stable_run_key):
                return self._stage.execute(request)
        except MailLockBusyError:
            return MailReceipt(
                run_key=request.stable_run_key, invocation_id=request.invocation_id,
                mode=request.mode, status="lock_busy",
                errors=({"stage": "lock", "code": "lock_busy", "summary": "mail writer is active"},),
                next_action="continue_poll", started_at_utc=request.requested_at_utc,
                completed_at_utc=utc_now(),
            )


class RuntimeMailApplicationService:
    """Owns runtime resources for precisely one public request."""

    def __init__(
        self, *, root: Path | None = None,
        dependencies: MailRuntimeDependencies = MailRuntimeDependencies(),
    ) -> None:
        self._root = root
        self._dependencies = dependencies

    def execute(self, request: MailRequest) -> MailReceipt:
        try:
            root = project_root(self._root)
            foundation = FoundationConfig.load(root)
            status = FoundationTool(foundation).execute(
                FoundationRequest("status", "mail-runtime-status", request.requested_at_utc)
            )
            if not status.ready:
                return _receipt(request, "mail_foundation_not_ready")
            connection = sqlite3.connect(foundation.database_path)
        except Exception:
            return _receipt(request, "mail_runtime_configuration_invalid")
        adapter: Any | None = None
        try:
            repository = self._dependencies.repository_factory(connection)
            # Status is intentionally constructed before adapter/runner and
            # remains a zero-Gmail, zero-Codex database read.
            if request.mode == "status":
                return StatusStage(repository).execute(request)
            try:
                recipient_email = _recipient_email(root)
            except ValueError:
                return _receipt(request, "mail_runtime_configuration_invalid")
            factory = self._dependencies.environment_factory or _default_environment_factory()
            if factory is None:
                return _receipt(request, "mail_environment_adapter_unavailable")
            adapter = factory(foundation, recipient_address=recipient_email)
            if adapter is None:
                return _receipt(request, "mail_environment_adapter_unavailable")
            app = self._compose(request, foundation, repository, adapter)
            return app.execute(request)
        except Exception:
            return _receipt(request, "mail_runtime_initialization_failed")
        finally:
            try:
                if adapter is not None:
                    adapter.close()
            except Exception:
                pass
            connection.close()

    def _compose(
        self, request: MailRequest, foundation: FoundationConfig,
        repository: MailRepository, adapter: Any,
    ) -> MailApplicationService:
        poll = PollStage(MailPollService(
            repository, adapter,
            MailPollConfig(foundation.raw_root, foundation.state_root / "locks" / "mail.lock"),
            clock=self._dependencies.clock,
        ))
        # Only process uses Codex.  A poll, delivery, reconcile or queue call
        # never constructs a runner.
        if request.mode in {"process", "run"}:
            process: Any = ProcessStage(
                repository, self._dependencies.context_factory(repository.connection),
                self._dependencies.runner_factory(), self._dependencies.gate_factory(),
                MailResponsePublisher(repository), self._local_today,
            )
        else:
            process = MissingDependencyStage("mail_process_not_requested")
        delivery_repository = MailDeliveryRepository(repository)
        delivery = PreparedStage(
            DeliveryStage(MailResponseDeliveryService(delivery_repository, adapter)),
            repository, adapter, delivery_repository,
        )
        reconcile = PreparedStage(
            ReconcileStage(repository, delivery_repository, adapter),
            repository, adapter, delivery_repository,
        )
        lock_path = foundation.state_root / "locks" / "mail.lock"
        return MailApplicationService(MailApplicationStages(
            poll=poll,
            process=_LockedStage(process, lock_path),
            deliver=_LockedStage(delivery, lock_path),
            reconcile=_LockedStage(reconcile, lock_path),
            status=StatusStage(repository), queue=QueueStage(repository),
        ), clock=self._dependencies.clock)

    @staticmethod
    def _local_today() -> str:
        return datetime.now(_LOCAL_TZ).date().isoformat()


def create_mail_application(
    *, root: Path | None = None,
    dependencies: MailRuntimeDependencies = MailRuntimeDependencies(),
) -> RuntimeMailApplicationService:
    """Return the single public production composition root."""
    return RuntimeMailApplicationService(root=root, dependencies=dependencies)
