"""Check the configured cache without clearing application data or logging secrets."""

from uuid import uuid4

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify cache writes, reads, atomic add, and deletion using a temporary key."

    def add_arguments(self, parser):
        parser.add_argument(
            "--require-redis", action="store_true",
            help="Fail if the default cache is not Redis (used by Railway startup).",
        )

    def handle(self, *args, **options):
        backend = caches["default"]
        name = type(backend).__name__
        if options["require_redis"] and not isinstance(backend, RedisCache):
            raise CommandError(
                f"Redis is required, but the default cache uses {name}. "
                "Set REDIS_URL on the Django service to the Redis service reference "
                "and redeploy."
            )

        key = "cache-check:" + uuid4().hex
        value = {"bytes": b"\x00\xff", "items": ["cache", 1]}
        missing = object()
        try:
            backend.set(key, value, timeout=30)
            if backend.get(key) != value:
                raise ValueError("Cache did not return the written value.")
            if backend.add(key, "must-not-overwrite", timeout=30):
                raise ValueError("Cache add replaced an existing key.")
            if backend.get(key) != value:
                raise ValueError("Cache add modified an existing value.")
            backend.delete(key)
            if backend.get(key, missing) is not missing:
                raise ValueError("Cache delete did not remove the key.")
            if not backend.add(key, value, timeout=30):
                raise ValueError("Cache add could not create a new key.")
        except Exception:
            # Redis exceptions can contain hosts/credentials from the URL.
            # Keep deployment logs useful without exposing connection secrets.
            raise CommandError(
                f"Cache check failed ({name}). Verify REDIS_URL, Redis health, "
                "credentials, and that both Railway services are in the same "
                "project/environment. Run this inside the deployed Django "
                "container; private Railway addresses cannot be reached locally."
            ) from None
        finally:
            # Delete only our unique probe, even if verification failed.
            try:
                backend.delete(key)
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(
            f"Cache OK: {name} (write/read, atomic add, delete)."
        ))
