from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def test_macos_x86_cryptography_dependency_is_exactly_pinned() -> None:
    requirements = [
        line.strip()
        for line in (SOURCE_ROOT / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirements.count("cryptography==47.0.0") == 1
