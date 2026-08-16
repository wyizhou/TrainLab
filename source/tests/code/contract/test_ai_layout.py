from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ai_evaluation_layout_and_privacy_boundaries() -> None:
    ai_root = ROOT / "tests/ai"
    for name in ("cases", "rubrics", "schemas", "templates", "results"):
        assert (ai_root / name).is_dir()
    assert not (ROOT / "skills/_tests").exists()
    for path in (ai_root / "cases").glob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert "expected" in content.lower()
        assert "verdict" in content.lower()
        assert "goal.md" not in content
        assert "credentials" not in content.lower()
    results = ai_root / "results"
    assert any(results.iterdir())
    assert not (results / "live").exists()
