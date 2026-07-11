from src.auth.security import hash_password, verify_password


def test_password_hash_round_trip_and_random_salt():
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")

    assert first != second
    assert verify_password("correct-horse-battery-staple", first)
    assert not verify_password("wrong-password", first)


def test_legacy_password_hash_is_still_accepted():
    import hashlib

    salt = "0123456789abcdef"
    digest = hashlib.pbkdf2_hmac(
        "sha256", b"legacy-password", salt.encode(), 100_000
    ).hex()
    assert verify_password("legacy-password", f"{salt}${digest}")
