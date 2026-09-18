"""In-memory conversation history contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from trainlab.contracts.time import ensure_utc


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    content: str
    created_at_utc: datetime


@dataclass
class InMemoryConversationHistory:
    _turns: list[ConversationTurn] = field(default_factory=list)

    def append(self, role: str, content: str, now_utc: datetime | None = None) -> None:
        created_at = datetime.now(UTC) if now_utc is None else ensure_utc(now_utc)
        self._turns.append(ConversationTurn(role=role, content=content, created_at_utc=created_at))

    def snapshot(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    def clear(self) -> None:
        self._turns.clear()

    @property
    def persistence_target(self) -> None:
        return None
