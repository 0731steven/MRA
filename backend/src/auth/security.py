"""Password hashing helpers shared by authentication and account bootstrap."""

import hashlib
import secrets


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify current hashes and transparently support the previous hash format."""

    try:
        if stored.startswith("pbkdf2_sha256$"):
            _, iterations, salt, expected = stored.split("$", 3)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), int(iterations)
            ).hex()
        else:
            # Backward compatibility for accounts created before migrations existed.
            salt, expected = stored.split("$", 1)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 100_000
            ).hex()
    except (TypeError, ValueError):
        return False
    return secrets.compare_digest(actual, expected)
