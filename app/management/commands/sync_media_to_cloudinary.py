"""Upload local media/ files to Cloudinary so deployed URLs stop 404ing.

Production serves media through ``MediaCloudinaryStorage`` (Project/settings.py),
but the database was seeded from ``backup.json`` with relative paths such as
``gallery/r1.png`` whose files only exist in this repository's ``media/`` folder.
Cloudinary never received those uploads, so every rendered URL -- which the
storage layer builds as
``https://res.cloudinary.com/<cloud>/image/upload/v1/media/<path>`` -- returned
404 and the site showed broken images / alt text.

This command uploads each file under ``MEDIA_ROOT`` using the public ID that
Django's storage layer derives (``media/<relative path>``, with Cloudinary
tracking the format separately), then verifies the exact rendered URL over
HTTP -- the same check ``MediaCloudinaryStorage.exists()`` performs.

Usage (Cloudinary credentials must be present in the environment, e.g. copied
from the Railway service variables):

    python manage.py sync_media_to_cloudinary --dry-run
    python manage.py sync_media_to_cloudinary --limit 3
    python manage.py sync_media_to_cloudinary
    python manage.py sync_media_to_cloudinary --verify-only
"""

import os
from pathlib import Path

import cloudinary
import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

try:
    from cloudinary_storage import app_settings as cloudinary_app_settings

    MEDIA_PREFIX = cloudinary_app_settings.PREFIX
    MEDIA_TAG = cloudinary_app_settings.MEDIA_TAG
except Exception:  # pragma: no cover - Cloudinary not configured at all
    cloudinary_app_settings = None
    MEDIA_PREFIX = getattr(settings, "MEDIA_URL", "/media/")
    MEDIA_TAG = "media"

IMAGE_EXTENSIONS = {
    "jpg", "jpe", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "ico",
}


class Command(BaseCommand):
    help = (
        "Upload the repository's local media/ files to Cloudinary so existing "
        "database records (relative paths) render instead of returning 404."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the files and target public IDs without uploading.",
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Skip uploads; only HTTP-verify the URLs Django generates.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Process only the first N files (smoke test).",
        )

    def handle(self, *args, **options):
        cloud_name, api_key, api_secret = self._cloudinary_config()
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_dir():
            raise CommandError(f"MEDIA_ROOT does not exist: {media_root}")

        files = sorted(path for path in media_root.rglob("*") if path.is_file())
        if options["limit"]:
            files = files[: options["limit"]]

        prefix = self._prefix()
        self.stdout.write(f"Cloudinary cloud : {cloud_name or '(not configured)'}")
        self.stdout.write(f"Media root       : {media_root}")
        self.stdout.write(f"Public ID prefix : {prefix}")
        self.stdout.write(f"Files to process : {len(files)}")

        if options["dry_run"]:
            for path in files:
                relative = path.relative_to(media_root).as_posix()
                self.stdout.write(f"  {relative} -> {prefix}{relative}")
            self.stdout.write(self.style.WARNING("\nDry run: nothing was uploaded."))
            return

        if not (cloud_name and api_key and api_secret):
            raise CommandError(
                "Cloudinary credentials are missing. Set CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET (Railway -> your "
                "service -> Variables) in the environment before running this "
                "command."
            )

        cloudinary.config(
            cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True
        )
        session = requests.Session()
        try:
            existing = (
                set() if options["verify_only"] else self._list_existing(prefix)
            )
        except cloudinary.exceptions.AuthorizationRequired as exc:
            raise CommandError(
                "Cloudinary rejected the credentials (HTTP 401). Double-check "
                f"CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET. Original error: {exc}"
            )

        uploaded = verified = skipped = 0
        failures = []
        total = len(files)

        for index, path in enumerate(files, start=1):
            relative = path.relative_to(media_root).as_posix()
            extension = path.suffix.lower().lstrip(".")

            if extension not in IMAGE_EXTENSIONS:
                skipped += 1
                self.stdout.write(f"  [{index}/{total}] skip (not an image): {relative}")
                continue

            public_id = prefix + relative
            base_id = public_id.rsplit(".", 1)[0] if "." in relative else public_id
            url = self._rendered_url(relative, cloud_name)

            if options["verify_only"]:
                status = self._head(session, url)
                if status == 200:
                    verified += 1
                else:
                    failures.append((relative, status))
                    self.stderr.write(
                        self.style.ERROR(
                            f"  [{index}/{total}] FAIL {relative}: HTTP {status}"
                        )
                    )
                continue

            already_present = base_id in existing
            if not already_present:
                self._upload(path, base_id)

            status = self._head(session, url)
            if status != 200:
                # Some formats (e.g. .jpe) may not resolve through the inferred
                # format; retry with the extension inside the public ID so the
                # asset ID matches the rendered URL exactly.
                self._upload(path, public_id)
                status = self._head(session, url)

            if status == 200:
                if already_present:
                    verified += 1
                else:
                    uploaded += 1
                existing.add(base_id)
                self.stdout.write(
                    self.style.SUCCESS(f"  [{index}/{total}] OK {relative}")
                )
            else:
                failures.append((relative, status))
                self.stderr.write(
                    self.style.ERROR(f"  [{index}/{total}] FAIL {relative}: HTTP {status}")
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {uploaded} uploaded, {verified} already reachable, "
                f"{skipped} skipped, {len(failures)} failed."
            )
        )
        if failures:
            self.stderr.write(
                self.style.ERROR("Files whose URL still does not resolve:")
            )
            for relative, status in failures:
                self.stderr.write(self.style.ERROR(f"  - {relative} (HTTP {status})"))
            raise CommandError(f"{len(failures)} file(s) could not be verified.")

    # --- helpers --------------------------------------------------------

    def _cloudinary_config(self):
        config = getattr(settings, "CLOUDINARY_STORAGE", None) or {}
        cloud_name = config.get("CLOUD_NAME") or os.getenv("CLOUDINARY_CLOUD_NAME", "")
        api_key = config.get("API_KEY") or os.getenv("CLOUDINARY_API_KEY", "")
        api_secret = config.get("API_SECRET") or os.getenv("CLOUDINARY_API_SECRET", "")
        return cloud_name, api_key, api_secret

    def _prefix(self):
        """Public ID prefix ("media/"), matching _prepend_prefix in the storage."""
        return (MEDIA_PREFIX or "media").strip("/") + "/"

    def _rendered_url(self, relative_path, cloud_name):
        """Return the exact URL the website renders for a stored path."""
        try:
            url = default_storage.url(relative_path)
        except Exception:
            url = ""
        if isinstance(url, str) and "res.cloudinary.com" in url:
            return url
        return (
            f"https://res.cloudinary.com/{cloud_name}/image/upload/v1/"
            f"{self._prefix()}{relative_path}"
        )

    def _head(self, session, url):
        """HTTP status of the rendered URL (None when the request fails)."""
        try:
            return session.head(url, allow_redirects=True, timeout=30).status_code
        except requests.RequestException:
            return None

    def _list_existing(self, prefix):
        """Public IDs already stored in the cloud under the media prefix."""
        existing = set()
        next_cursor = None
        while True:
            params = {
                "resource_type": "image",
                "type": "upload",
                "prefix": prefix,
                "max_results": 500,
            }
            if next_cursor:
                params["next_cursor"] = next_cursor
            result = cloudinary.api.resources(**params)
            existing.update(
                item.get("public_id", "") for item in result.get("resources", [])
            )
            next_cursor = result.get("next_cursor")
            if not next_cursor:
                return existing

    def _upload(self, path, public_id):
        return cloudinary.uploader.upload(
            str(path),
            public_id=public_id,
            resource_type="image",
            overwrite=True,
            unique_filename=False,
            tags=MEDIA_TAG,
        )
