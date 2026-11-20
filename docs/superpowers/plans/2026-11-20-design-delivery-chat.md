# Design Delivery Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically deliver booking designs into the customer's Admin Chat as one linked card.

**Architecture:** Extend ChatMessage with typed delivery and booking references plus a revision flag. Create the message inside the existing upload transaction; expose its metadata through the shared support API and render it in the shared JavaScript controller. Deleting a delivery clears the reference and removes its preview everywhere.

**Tech Stack:** Django, existing SQLite test settings, vanilla JavaScript/CSS, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-20-design-delivery-chat-design.md`

## Global Constraints

- Preserve booking views, payment gates, image limits, revision validation, and existing email.
- No additional dependencies, duplicate uploads, duplicate sends, or extra chat email.
- Use existing chat theme tokens, image dialog, and safe DOM text rendering.

## Review Focus

- First-ever chat and closed conversations: one accessible support session is created or reopened.
- Multiple bookings, AI conversations and customers: each design reaches only the correct customer support chat.
- Lost response retries and transaction rollback: no orphaned or duplicate delivery messages.
- Delivery deletion: watched messages, pinned previews, shared media and replies cannot retain the removed image.
- Small screens and hostile caption text: readable card, safe text, working image and booking actions.

### Task 1: Atomic delivery messages and support metadata

**Files:** `app/models.py`, new migration, `app/design_delivery_chat.py`, `app/views/bookings.py`, `app/views/chat.py`, `app/views/support_chat.py`, `app/test_design_delivery.py`.

**Interfaces:** `post_design_delivery(delivery, *, revised=False)` creates one support message. `_chat_message_json` returns optional `design_delivery` metadata with booking ID, viewer-specific booking URL, title and removed state, and resolves the linked image without copying it.

- [x] Add integration tests for initial/blank/custom messages, support session reuse/creation/reopening, customer isolation, revision label, unread state, retry, rollback, email count and deletion across state/media/pins/replies.
- [x] Run those tests before implementation; expect failures for missing messages/metadata.
- [x] Add the model references and migration; implement the helper and upload hook; extend chat serialization/media queries and disallow delivery text editing.
- [x] Run `python manage.py test app.test_design_delivery app.test_support_chat --settings=Project.test_settings --noinput`; expect success.

### Task 2: Shared chat delivery card and browser verification

**Files:** `static/js/support_chat.js`, `static/css/support_chat.css`, widget/inbox asset versions, admin delivery form help, new `app/test_design_delivery_chat_browser.py`.

**Interfaces:** Consume Task 1 metadata; render title, booking number, standard/custom text, full-image preview and View booking link in both chat surfaces. Removed cards omit their preview.

- [x] Add a real-browser test covering admin send, customer/admin cards, image dialog, customer feedback, booking link, revisions, deletion updates, safe captions and light/dark mobile layouts.
- [x] Run before renderer changes; expect a missing delivery card assertion.
- [x] Implement the shared card using existing tokens/dialog, extend row signatures and hide ordinary edit for delivery cards; update form help and asset versions.
- [x] Run browser and related backend tests, Django checks, migration drift check and JavaScript syntax check; expect success.
- [x] Obtain a fresh code review, address substantive findings, and record verification results.

## Execution notes

Work proceeds in the user's existing feature checkout; leave unrelated untracked manuals/diagrams intact. Do not commit, push or merge unless requested. Test databases and uploaded test media stay isolated through Project.test_settings.

## Progress and review

Task 1 is complete: 77 backend checks passed with one SQLite skip; two dedicated PostgreSQL concurrency tests passed in an isolated temporary database. The local application migration is applied.

A fresh reviewer identified stale open image/media dialogs, a PostgreSQL lock-order conflict, unauthorized superuser booking links, and a stale removed-delivery inbox preview. Each has a regression test and a fix. The canvas migration test now restores the current migration graph after testing its historical state.

Task 2 is complete: the final 22-test design/email/browser run passed, including the compact greeting and image preview. Screenshots were inspected at desktop/mobile widths. See `docs/superpowers/specs/2026-11-20-design-delivery-chat-verification.md` for evidence and existing repository test failures.
