"""Password hashing behaviour."""

import pytest

from app.core.security import hash_password, needs_rehash, verify_password


def test_hash_is_not_the_plaintext() -> None:
    assert hash_password("correct horse battery staple") != "correct horse battery staple"


def test_verify_accepts_the_correct_password() -> None:
    password = "correct horse battery staple"
    assert verify_password(password, hash_password(password))


def test_verify_rejects_a_wrong_password() -> None:
    assert not verify_password("wrong", hash_password("correct horse battery staple"))


def test_same_password_hashes_differently_each_time() -> None:
    """A per-hash salt is what stops one leaked rainbow table cracking every account."""
    assert hash_password("same input") != hash_password("same input")


def test_uses_argon2id() -> None:
    """argon2id is the variant that resists both GPU and side-channel attacks."""
    assert hash_password("x").startswith("$argon2id$")


def test_verify_rejects_a_malformed_hash_instead_of_raising() -> None:
    """A corrupted stored hash must fail the login, not 500 the endpoint."""
    assert not verify_password("anything", "not-a-hash")


def test_needs_rehash_is_false_for_a_freshly_created_hash() -> None:
    assert not needs_rehash(hash_password("x"))


@pytest.mark.parametrize("password", ["", " ", "a" * 1024])
def test_handles_boundary_length_passwords(password: str) -> None:
    assert verify_password(password, hash_password(password))
