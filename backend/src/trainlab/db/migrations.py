from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory


@lru_cache
def migration_head() -> str:
    backend_root = Path(__file__).resolve().parents[3]
    head = ScriptDirectory(str(backend_root / "migrations")).get_current_head()
    if head is None:
        raise RuntimeError("migration history has no head")
    return head
