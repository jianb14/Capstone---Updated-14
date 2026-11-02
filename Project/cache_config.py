"""Cache settings without opening connections during imports or builds."""

from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def build_caches(environ):
    redis_url = (environ.get("REDIS_URL") or "").strip()
    prefix = (environ.get("CACHE_KEY_PREFIX") or "balloorina").strip() or "balloorina"

    if not redis_url:
        # Local development needs no Redis server. Railway's startup command
        # requires Redis explicitly so production cannot silently use this.
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "balloorina-local",
                "KEY_PREFIX": prefix,
                "TIMEOUT": 300,
            }
        }

    try:
        parsed = urlsplit(redis_url)
        valid = (
            parsed.scheme in {"redis", "rediss"}
            and bool(parsed.hostname)
            and (parsed.port is None or parsed.port > 0)
            and not parsed.fragment
            and "${{" not in redis_url
        )
    except ValueError:
        valid = False
    if not valid:
        # Never include the URL: it contains the Redis password.
        raise ImproperlyConfigured(
            "REDIS_URL must be a valid redis:// or rediss:// connection URL. "
            "On Railway, reference the Redis service's REDIS_URL variable."
        )

    return {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
            "KEY_PREFIX": prefix,
            "TIMEOUT": 300,
            "OPTIONS": {
                "socket_connect_timeout": 3,
                "socket_timeout": 3,
            },
        }
    }
