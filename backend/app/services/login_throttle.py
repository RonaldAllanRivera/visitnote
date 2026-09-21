"""Login attempt throttling, backed by Redis.

argon2 makes each guess expensive; this caps how many guesses are possible at all.
State lives in Redis rather than the database because it is high-write, short-lived,
and losing it on a restart is harmless -- the worst case is an attacker gets their
counter reset, which a database row would also allow after any lockout expiry.

Counters are keyed by email address, including addresses that do not exist. Throttling
only known accounts would turn the login endpoint into an address oracle: unlimited
attempts for unregistered addresses, throttling for registered ones.
"""

import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import get_settings


def _key(prefix: str, email: str) -> str:
    # Hashed so that a dump of Redis keys is not a list of customer email addresses.
    digest = hashlib.sha256(email.lower().encode()).hexdigest()[:32]
    return f"login:{prefix}:{digest}"


@dataclass(slots=True)
class LoginThrottle:
    redis: Redis

    async def seconds_until_unlocked(self, email: str) -> int:
        """Remaining lockout in seconds, or 0 when the address is not locked."""
        # redis-py types ttl() as Any. The protocol guarantees an integer: the
        # remaining seconds, -1 for a key with no expiry, -2 when absent.
        ttl = int(await self.redis.ttl(_key("lock", email)))
        return max(ttl, 0)

    async def record_failure(self, email: str) -> None:
        settings = get_settings()
        key = _key("fail", email)

        failures = await self.redis.incr(key)
        if failures == 1:
            # Window starts at the first failure, so scattered typos across a day
            # never accumulate into a lockout.
            await self.redis.expire(key, settings.login_failure_window_seconds)

        if failures >= settings.login_max_attempts:
            await self.redis.set(_key("lock", email), "1", ex=settings.login_lockout_seconds)

    async def reset(self, email: str) -> None:
        """Clear on success, so an occasional mistype never compounds."""
        await self.redis.delete(_key("fail", email), _key("lock", email))
