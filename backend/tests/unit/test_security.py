from trainlab.core.security import (
    hash_password,
    hash_token,
    new_token,
    normalize_username,
    verify_password,
)


def test_username_normalization_is_casefolded_and_trimmed() -> None:
    assert normalize_username("  OwnerUSER  ") == "owneruser"


def test_password_hash_round_trip_and_rejection() -> None:
    stored = hash_password("correct-password")
    assert verify_password("correct-password", stored)
    assert not verify_password("wrong-password", stored)
    assert "correct-password" not in stored


def test_tokens_are_random_and_only_digests_need_persistence() -> None:
    first = new_token()
    second = new_token()
    assert first != second
    assert len(hash_token(first)) == 64
    assert first not in hash_token(first)
