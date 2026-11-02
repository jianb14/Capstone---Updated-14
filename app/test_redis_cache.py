"""Redis configuration, deployment diagnostics, and cache integration checks."""

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from PIL import Image

from Project.cache_config import build_caches

try:
    # Test-only dependency; the deployed application uses the real redis client.
    from fakeredis import TcpFakeServer
except ImportError:
    TcpFakeServer = None


class CacheConfigurationTests(SimpleTestCase):
    def test_local_development_accepts_missing_or_blank_url(self):
        for env in ({}, {"REDIS_URL": ""}, {"REDIS_URL": "  "}):
            with self.subTest(env=env):
                config = build_caches(env)["default"]
                self.assertTrue(config["BACKEND"].endswith("LocMemCache"))

    def test_authenticated_private_and_tls_urls_select_redis(self):
        for url in (
            "redis://default:password@redis.railway.internal:6379/0",
            "rediss://default:password@redis.example.com:6379/1",
            "redis://[::1]:6379",
        ):
            with self.subTest(url=url):
                config = build_caches({"REDIS_URL": " " + url + " "})["default"]
                self.assertTrue(config["BACKEND"].endswith("RedisCache"))
                self.assertEqual(config["LOCATION"], url)
                self.assertEqual(config["TIMEOUT"], 300)
                self.assertLessEqual(config["OPTIONS"]["socket_timeout"], 5)
                self.assertLessEqual(config["OPTIONS"]["socket_connect_timeout"], 5)

    def test_prefix_can_isolate_shared_redis_environments(self):
        for url in ("", "redis://localhost:6379/0"):
            config = build_caches({"REDIS_URL": url, "CACHE_KEY_PREFIX": " preview "})
            self.assertEqual(config["default"]["KEY_PREFIX"], "preview")

    def test_invalid_urls_fail_without_exposing_credentials(self):
        for url in (
            "${{Redis.REDIS_URL}}", "https://private-password@redis:6379",
            "redis://:private-password@/0", "redis://redis:70000",
            "redis://redis:0", "redis://redis:not-a-port",
            "redis://[broken", "redis://redis:6379#fragment",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ImproperlyConfigured) as error:
                    build_caches({"REDIS_URL": url})
                self.assertNotIn("private-password", str(error.exception))
                self.assertNotIn(url, str(error.exception))


class CacheDiagnosticTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(self.settings(CACHES=build_caches({})))

    def test_local_check_preserves_other_keys_and_removes_its_probe(self):
        backend = caches["default"]
        backend.set("unrelated-test-key", "keep", 30)
        self.addCleanup(backend.delete, "unrelated-test-key")
        output = io.StringIO()
        with patch("app.management.commands.check_cache.uuid4", return_value=Mock(hex="probe")):
            call_command("check_cache", stdout=output)
        self.assertIn("Cache OK: LocMemCache", output.getvalue())
        self.assertEqual(backend.get("unrelated-test-key"), "keep")
        self.assertIsNone(backend.get("cache-check:probe"))

    def test_production_check_rejects_local_memory(self):
        with self.assertRaisesMessage(CommandError, "Redis is required"):
            call_command("check_cache", require_redis=True, stdout=io.StringIO())

    def test_connection_failure_is_actionable_and_does_not_print_secrets(self):
        backend = Mock(spec=RedisCache)
        backend.set.side_effect = ConnectionError("redis://default:private-password@redis:6379")
        backend.delete.side_effect = ConnectionError("private-password")
        output = io.StringIO()
        with patch("app.management.commands.check_cache.caches", {"default": backend}):
            with self.assertRaises(CommandError) as error:
                call_command("check_cache", require_redis=True, stdout=output)
        self.assertIn("Verify REDIS_URL", str(error.exception))
        self.assertNotIn("private-password", str(error.exception))
        self.assertNotIn("Cache OK", output.getvalue())
        backend.delete.assert_called_once()

    def test_silent_failed_write_does_not_report_success(self):
        backend = Mock(spec=RedisCache)
        backend.get.return_value = None
        with patch("app.management.commands.check_cache.caches", {"default": backend}):
            with self.assertRaisesMessage(CommandError, "Cache check failed"):
                call_command("check_cache", require_redis=True, stdout=io.StringIO())


@skipUnless(TcpFakeServer is not None, "Install fakeredis>=2.28,<3 for Redis TCP integration checks.")
class RedisIntegrationTests(SimpleTestCase):
    """Use Django RedisCache and redis-py over TCP against a disposable emulator."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = TcpFakeServer(("127.0.0.1", 0), server_version=(7, 0))
        cls.server.daemon_threads = True
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()

        def stop_server():
            cls.server.shutdown()
            cls.server.server_close()
            thread.join(timeout=3)

        cls.addClassCleanup(stop_server)
        cls.url = f"redis://127.0.0.1:{cls.server.server_address[1]}/0"

    def setUp(self):
        self.config = build_caches({"REDIS_URL": self.url, "CACHE_KEY_PREFIX": uuid4().hex})
        self.enterContext(self.settings(CACHES=self.config))
        self.first = self.new_connection()
        self.second = self.new_connection()

    def new_connection(self):
        config = self.config["default"]
        backend = RedisCache(config["LOCATION"], config)
        self.addCleanup(self.disconnect, backend)
        return backend

    @staticmethod
    def disconnect(backend):
        for pool in backend._cache._pools.values():
            pool.disconnect()

    def test_independent_connections_share_data_and_invalidation(self):
        self.first.set("shared", {"bytes": b"\x00\xff", "rows": [1, 2]}, 30)
        self.assertEqual(self.second.get("shared"), {"bytes": b"\x00\xff", "rows": [1, 2]})
        self.second.delete("shared")
        self.assertIsNone(self.first.get("shared"))

    def test_simultaneous_add_has_exactly_one_winner(self):
        backends = [self.new_connection() for _ in range(8)]
        barrier = threading.Barrier(len(backends))

        def reserve(backend):
            barrier.wait(timeout=5)
            return backend.add("quiz-throttle", "reserved", 30)

        with ThreadPoolExecutor(max_workers=len(backends)) as executor:
            results = list(executor.map(reserve, backends))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.second.get("quiz-throttle"), "reserved")

    def test_expired_data_is_not_returned(self):
        self.first.set("short-lived", "value", timeout=1)
        self.assertEqual(self.second.get("short-lived"), "value")
        time.sleep(1.1)
        self.assertIsNone(self.second.get("short-lived"))

    def test_diagnostic_runs_against_redis_and_keeps_existing_data(self):
        self.first.set("unrelated", "keep", 30)
        output = io.StringIO()
        backend = caches["default"]
        self.addCleanup(self.disconnect, backend)
        call_command("check_cache", require_redis=True, stdout=output)
        self.assertIn("Cache OK: RedisCache", output.getvalue())
        self.assertEqual(self.second.get("unrelated"), "keep")

    def test_geocoding_second_lookup_uses_shared_redis(self):
        from app.geocoding import search_places

        response = Mock()
        response.json.return_value = {"features": [{
            "properties": {"name": "Bacoor", "countrycode": "PH"},
            "geometry": {"coordinates": [120.95, 14.45]},
        }]}
        self.addCleanup(self.disconnect, caches["default"])
        with patch("app.geocoding.requests.get", return_value=response) as lookup:
            first = search_places("Bacoor")
            second = search_places("Bacoor")
        lookup.assert_called_once()
        self.assertEqual(first, second)
        self.assertEqual(first[0]["lat"], 14.45)

    def test_design_preview_round_trips_binary_data_through_redis(self):
        from app.design_previews import preview_bytes

        image = io.BytesIO()
        Image.new("RGB", (1280, 720), "purple").save(image, "PNG")
        thumbnail = ContentFile(image.getvalue(), name="test-preview.png")
        self.addCleanup(self.disconnect, caches["default"])
        first = preview_bytes(thumbnail)
        with patch.object(thumbnail, "open", side_effect=AssertionError("Preview was not cached")):
            self.assertEqual(preview_bytes(thumbnail), first)
        with Image.open(io.BytesIO(first)) as result:
            self.assertEqual(result.size, (640, 360))

    def test_prefixes_isolate_environments(self):
        other_config = {**self.config["default"], "KEY_PREFIX": "other-" + uuid4().hex}
        other = RedisCache(self.url, other_config)
        self.addCleanup(self.disconnect, other)
        self.first.set("shared", "original-environment", 30)
        other.set("shared", "other-environment", 30)
        self.assertEqual(self.second.get("shared"), "original-environment")
        self.assertEqual(other.get("shared"), "other-environment")
