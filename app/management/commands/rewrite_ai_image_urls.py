"""Rewrite legacy "/media/ai_generated/..." image srcs in chat messages.

Older AI chat replies embedded a hardcoded local ``/media/...`` URL produced
by the former ``_save_generated_image`` implementation. Production mounts no
``/media/`` route when Cloudinary is configured, so those images 404'd and
the chat showed alt text instead.

This command rewrites each occurrence to the URL Django's storage layer
produces for the same file -- but only when the file actually exists in the
current storage (files committed under ``media/ai_generated/`` were backfilled
to Cloudinary by ``sync_media_to_cloudinary``). Unresolvable files are
reported and left untouched.

Usage:

    python manage.py rewrite_ai_image_urls           # dry run (report only)
    python manage.py rewrite_ai_image_urls --apply   # write the changes
"""

import re

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from app.models import ChatMessage

AI_IMAGE_PATTERN = re.compile(r"/media/ai_generated/([A-Za-z0-9._\-]+)")


class Command(BaseCommand):
    help = (
        "Rewrite legacy /media/ai_generated/... image references in chat "
        "messages to storage-backed URLs (Cloudinary in production)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the rewrites (default is a dry run that only reports).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        messages_scanned = messages_changed = 0
        resolved_names = set()
        missing_names = set()

        for message in ChatMessage.objects.filter(
            message__contains="/media/ai_generated/"
        ).iterator():
            messages_scanned += 1
            original = message.message

            resolved_urls = {}
            for filename in set(AI_IMAGE_PATTERN.findall(original)):
                name = f"ai_generated/{filename}"
                try:
                    exists = default_storage.exists(name)
                except Exception:
                    exists = False
                if exists:
                    resolved_urls[filename] = default_storage.url(name)
                    resolved_names.add(filename)
                else:
                    missing_names.add(filename)

            new_text = AI_IMAGE_PATTERN.sub(
                lambda match: resolved_urls.get(match.group(1)) or match.group(0),
                original,
            )
            if new_text == original:
                continue
            messages_changed += 1
            if apply_changes:
                ChatMessage.objects.filter(pk=message.pk).update(message=new_text)

        mode = "APPLIED" if apply_changes else "DRY RUN (nothing written)"
        self.stdout.write(f"Mode               : {mode}")
        self.stdout.write(f"Messages scanned   : {messages_scanned}")
        self.stdout.write(f"Messages rewritten : {messages_changed}")
        self.stdout.write(f"Files resolved     : {len(resolved_names)}")
        if missing_names:
            self.stdout.write(
                self.style.WARNING(
                    f"Files missing (left as-is, unrecoverable): {len(missing_names)}"
                )
            )
            for name in sorted(missing_names):
                self.stdout.write(self.style.WARNING(f"  - ai_generated/{name}"))
        elif messages_scanned and not apply_changes:
            self.stdout.write(self.style.SUCCESS("All referenced files resolve."))
