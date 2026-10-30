"""Password hashing and sign-in throttling, from the standard library only. No secret lives in the repo."""
import hashlib
import hmac
import os
import time

SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
MAX_TRIES, LOCK_SECONDS = 5, 300


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
        return hmac.compare_digest(got.hex(), digest)
    except ValueError:
        return False


class Throttle:
    """Too many wrong passwords for one address locks it for a few minutes. In memory: fine for a demo."""

    def __init__(self, tries: int = MAX_TRIES, lock: int = LOCK_SECONDS):
        self.tries, self.lock = tries, lock
        self.fails: dict[str, tuple[int, float]] = {}

    def locked(self, key: str) -> bool:
        count, at = self.fails.get(key, (0, 0.0))
        if count >= self.tries and time.time() - at < self.lock:
            return True
        if count >= self.tries:
            self.fails.pop(key, None)
        return False

    def fail(self, key: str) -> None:
        count, _ = self.fails.get(key, (0, 0.0))
        self.fails[key] = (count + 1, time.time())

    def ok(self, key: str) -> None:
        self.fails.pop(key, None)


throttle = Throttle()
# One address may create 10 accounts an hour. It reuses Throttle: every account made counts as a "fail".
signups = Throttle(tries=10, lock=3600)
