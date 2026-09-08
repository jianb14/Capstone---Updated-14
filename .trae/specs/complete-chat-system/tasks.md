# Balloorina Complete Chat System - Implementation Plan

## Task 1: Update Models (ChatSession & ChatMessage field additions)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Add `status`, `assigned_admin`, `last_client_message_at`, `admin_last_read_at` fields + `has_unread_for_admin` property to ChatSession model.
  - Add `is_read` BooleanField + `read_at` DateTimeField + `is_from_admin` property to ChatMessage model.
  - Keep existing fields and model methods; append new fields at end of each class to preserve migration order.
  - Preserve existing related_names (chat_sessions, messages, sent_messages, received_messages) — do NOT change.
- **Acceptance Criteria Addressed**: AC-1, AC-2, FR-1, FR-9, NFR-4
- **Test Requirements**:
  - `rule` TR-1.1: Django model validation passes (`python manage.py check` returns exit 0).
  - `rule` TR-1.2: `makemigrations` generates a single non-destructive migration that adds the new columns/FK with defaults (no Remove/Rename operations).
  - `rule` TR-1.3: After migrate, shell test: `ChatSession(status='ai').get_status_display()` returns "AI Bot"; `ChatMessage().is_from_admin` is False on a customer sender and True on an admin sender.
  - `rubric` TR-1.4: FK assigned_admin on_delete behavior; scale 1-5; anchors 1=CASCADE breaks data 3=SET_NULL but no related_name 5=SET_NULL + related_name='assigned_chats' matches spec; threshold >=4; evidence=models.py code snippet of FK definition.
- **Notes**: assigned_admin must be nullable (blank=True, null=True) since sessions start as AI-mode.

## Task 2: Run Migration (makemigrations + migrate)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - Run `python manage.py makemigrations` then `python manage.py migrate`.
  - Verify no data loss on existing ChatSession/ChatMessage rows (columns added with defaults/safe).
- **Acceptance Criteria Addressed**: AC-1 (lifecycle), FR-1, NFR-4
- **Test Requirements**:
  - `rule` TR-2.1: Both commands exit 0; migration file created under app/migrations/xxxx_CHAT_STATUS_READ.py naming (auto-name OK).
  - `rule` TR-2.2: After migrate, `PRAGMA table_info(...)` or Django shell `field.name` enumeration shows new fields present on both ChatSession and ChatMessage.
- **Notes**: Take no migration actions for models other than ChatSession/ChatMessage in this task.

## Task 3: Add Views & API Endpoints to views.py
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2 (models migrated; views query new fields)
- **Description**:
  - Implement 8 new view functions (append to views.py, before select_design_type def):
    1. `client_chat_page` — renders `client/client_chat_page.html` with sessions list + ban_status. role=='customer' guard.
    2. `chat_request_admin` — POST JSON, sets status='pending_admin', persists system confirmation ChatMessage, creates Notifications for all admins.
    3. `chat_mark_read` — POST JSON, marks admin-sent messages is_read=True in a given client's session.
    4. `admin_chat_inbox` — renders `admin/admin_chat_inbox.html`. Guard: admin/staff/superuser. Annotated query with last_msg_time Subquery, sorted by status then unread then time. Stats dict: pending/active_admin/ai/unread_total.
    5. `admin_chat_thread` — GET + POST. GET: auto-mark client messages read, render thread template. POST: save admin reply, auto-upgrade pending→active_admin, set assigned_admin. Redirect back to same thread URL.
    6. `admin_chat_accept` — POST only, status 'pending_admin' → 'active_admin', assigned_admin=request.user, saves system ChatMessage.
    7. `admin_chat_close` — POST only, session.status='closed'.
    8. `admin_chat_unread_poll` — GET JSON {unread_total, pending_count}. Admin guard only.
  - Add ALL missing Django imports at top of views.py (json, timezone, Q, Max, OuterRef, Subquery, get_object_or_404, transaction if not present). Reuse existing imports where present.
  - Import Notification, ChatModerationState, ChatModerationEvent in services.py style — already imported in views? Check views.py existing `from .models import (...)` line; add ChatSession/ChatMessage/Notification/etc ONLY if not already imported.
  - All admin guards: `if request.user.role not in ['admin','staff'] and not request.user.is_superuser: return HttpResponseForbidden("Admins only")`.
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-6, AC-7, FR-2, FR-3, FR-4, FR-5, FR-6, FR-9, NFR-3, NFR-4, NFR-5
- **Test Requirements**:
  - `rule` TR-3.1: `python manage.py check` passes (syntax/import OK).
  - `rule` TR-3.2: All 8 new function names present in views.py; grep confirms. HTTP methods decorators (@login_required, @require_POST for POST-only views) applied per spec.
  - `rubric` TR-3.3: Role gating completeness; scale 1-5; anchors 1=no guards anywhere 3=admin inbox guarded but not thread/poll 5=every admin endpoint + customer endpoint role-guarded correctly; threshold >=4; evidence=views.py code regions for each function.
  - `rule` TR-3.4: request_admin view creates at least one Notification for each existing admin user. Verify via Django shell `Notification.objects.filter(title__icontains='New Admin Chat').count()` > 0 after one handoff POST.
- **Notes**: Keep existing chat_api / chat_sessions / chat_history / chat_clear unchanged per NFR-4 (no edits to those 4 functions).

## Task 4: Register URLs in app/urls.py + Add Imports
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3 (all view functions defined)
- **Description**:
  - Add imports of the 8 new views into urls.py's `from .views import ( ... )` block: `client_chat_page, chat_request_admin, chat_mark_read, admin_chat_inbox, admin_chat_thread, admin_chat_accept, admin_chat_close, admin_chat_unread_poll`.
  - Add 8 URL patterns after existing `/api/chat/clear/` line:
    - `path("chat/", client_chat_page, name="client_chat_page")`
    - `path("api/chat/request-admin/", chat_request_admin, name="chat_request_admin")`
    - `path("api/chat/mark-read/", chat_mark_read, name="chat_mark_read")`
    - `path("staff/chat/", admin_chat_inbox, name="admin_chat_inbox")`
    - `path("staff/chat/<int:session_id>/", admin_chat_thread, name="admin_chat_thread")`
    - `path("staff/chat/<int:session_id>/accept/", admin_chat_accept, name="admin_chat_accept")`
    - `path("staff/chat/<int:session_id>/close/", admin_chat_close, name="admin_chat_close")`
    - `path("api/staff/chat/unread/", admin_chat_unread_poll, name="admin_chat_unread_poll")`
- **Acceptance Criteria Addressed**: FR-10, AC-3 (polling URL), AC-6 (guarded views via their own guards)
- **Test Requirements**:
  - `rule` TR-4.1: `python manage.py show_urls` or `python manage.py check` passes.
  - `rule` TR-4.2: `reverse('client_chat_page') == '/chat/'`, `reverse('admin_chat_inbox') == '/staff/chat/'` (run in shell). All 8 names resolve to non-empty paths.
- **Notes**: Do NOT remove or re-order existing URLs (NFR-4).

## Task 5: Create admin_chat.css (Shared styles for Client + Admin Chat UI)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None (CSS is independent artifact; will be linked in base templates later under Task 8)
- **Description**:
  - New file: `static/css/admin_chat.css`.
  - Sections (in order):
    1. ADMIN CHAT LAYOUT — `.admin-chat-wrap` grid 320px 1fr, min-height, sidebar header.
    2. SESSION LIST — `.session-card`, `.sc-avatar`, `.unread-dot` (pulseGlow keyframe), `.has-unread` highlight, `.active` selected state, grouped labels.
    3. STATS CHIPS — `.stat-chip` pending/active/ai/unread color variants.
    4. ADMIN THREAD HEADER — `.admin-thread-header` flex, `.thread-user` avatar, `.thread-actions` buttons (Accept green, Close muted, Back link).
    5. MESSAGE BUBBLES — `.admin-msg-row` (client left, admin right/reversed). `.am-bubble` with tail-radius (top-left vs top-right). `.am-meta` with ADMIN/CLIENT tag pills.
    6. REPLY BOX — `.thread-reply-box textarea` dark input, `.btn-send-reply`.
    7. CLIENT CHAT PAGE — `.chat-page-wrap` grid 280px 1fr, session sidebar, chat-header with status badge and action buttons (Talk-to-Admin, Clear).
    8. CLIENT MSG BUBBLES — `.msg-row.user` right, `.msg-row.assistant` left, `.msg-bubble.typing` bouncing 3-dots (typingBounce keyframes).
    9. FLOATING WIDGET (⭐ critical) — `.float-chat-bubble` fixed bottom:24px right:24px 56px circle with shadow, z-index:9990. `.float-chat-popover` 320px panel shows status pill + smart-hint card + 2 action buttons. `.float-chat-unread-badge` red 18-22px circle +1 offset with pulse. entrancePulse keyframe on load. `.float-chat-close` X in popover corner.
    10. RESPONSIVE — @media max-width 900px: grid collapses to 1fr, sidebar <= 220px, bubbles max-width:90%, thread header wraps. @media max-width 480px: bubble font 0.78rem, floating bubble 50px, popover 280px bottom:80px right:12px.
  - ALL styles reference CSS variables from existing admin_dashboard.css: `--card-bg`, `--card-bdr`, `--t1/--t2/--t3/--t4`, `--r/--rx/--rs`, `--blue/--blue-d`, `--teal/--teal-d`, `--gold/--gold-d`, `--red/--red-d`.
  - Classes are NAMESPACED — prefix floating widget with `.float-chat-*` to avoid colliding with any existing `.chat-` classes used elsewhere.
- **Acceptance Criteria Addressed**: AC-4, AC-5, AC-8, FR-7, NFR-1, NFR-2
- **Test Requirements**:
  - `rule` TR-5.1: CSS file parses (`@keyframes`, `@media`) validatable via `python manage.py runserver` loading it with no 404 and browser DevTools CSS Errors panel empty.
  - `rubric` TR-5.2: Glassmorphism theme matching; scale 1-5; anchors 1=plain white bg 3=dark bg but different radii/spacing vs dashboard panels 5=all --vars used, radii var(--r)/var(--rx) consistent, hover transitions same curve (0.2s ease) as dashboard; threshold >=4; evidence=grep for --card-bg and var(--r) in the CSS file.
  - `rule` TR-5.3: All 4 responsive breakpoints in AC-8 covered by @media rules in the file (≥1024 default; ≤900; ≤768; ≤480).
- **Notes**: The filename is `admin_chat.css` even though client uses it — avoids creating two files. Name matches spec NFR-6.

## Task 6: Create Client Chat Page Template (client_chat_page.html)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5 (CSS named), Task 4 (URL names exist; template uses {% url ... %} tags)
- **Description**:
  - New file: `app/templates/client/client_chat_page.html`.
  - `{% extends 'client/base.html' %}` + `{% load static %}`.
  - Layout: `<div class="chat-page-wrap">` → `.chat-sidebar` (head + new-chat btn + session list) + `.chat-main` (header: title + status badge + handoff/clear actions; then `.chat-messages` scroll area; then `.chat-input-wrap` with ban-warning div + textarea+send button).
  - Inline <script> at bottom of {% block content %}:
    - CSRF cookie helper `getCookie(name)`.
    - State: currentSessionId, isBanned, banSeconds, pollTimer.
    - `loadSessions()` → GET {% url 'chat_sessions' %} → render `.session-item` list.
    - `loadSession(sid)` → GET {% url 'chat_history' %} → append messages + POST mark-read + startPolling.
    - `sendMessage()` → append user msg → show typing indicator → POST {% url 'chat_api' %} JSON {message, session_id} → handle response, append reply, check ban.
    - `requestAdminBtn.onclick` → POST {% url 'chat_request_admin' %} → UI update to ⏳ Waiting status badge.
    - `startAdminReplyPolling()` → setInterval 5000ms → GET chat_history → compare content-hash (btoa(sent_at + first50chars)) deduplication → append new only → POST mark-read if new.
    - `clearChatBtn.onclick` → POST {% url 'chat_clear' %} → reset.
    - Enter=send, Shift+Enter=newline on textarea.
    - Ban countdown if isBanned (from Django template vars: `{{ is_banned|yesno:"true,false" }}`, `{{ ban_remaining_seconds }}`).
  - Welcome bubble in empty chat messages box: "👋 Hi! I'm Balloorina AI. Ask me about packages, pricing, or even generate a design concept! If you need human help, click 'Talk to Admin' above."
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-6, AC-7, AC-8, FR-2, FR-3, NFR-1, NFR-2
- **Test Requirements**:
  - `rule` TR-6.1: Django template syntax parses without error (load check + runserver browse /chat/ → HTTP 200 not 500).
  - `rubric` TR-6.2: Message UX quality; scale 1-5; anchors 1=text only no timings/indicators 3=send works but no typing indicator or dedup 5=all features present: typing indicator, enter/shift+enter, content-hash dedup on poll, mark-read POST, ban countdown, warning UI; threshold >=4; evidence=JS block inline audit.
  - `rule` TR-6.3: All 6 API URLs in the script use {% url %} tag (never hardcoded paths), CSRF token included in all POSTs.
- **Notes**: Inline script keeps this template self-contained; no separate JS file needed per spec scope.

## Task 7: Create Admin Chat Inbox Template (admin_chat_inbox.html)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5 (CSS classes), Task 4 (url names)
- **Description**:
  - New file: `app/templates/admin/admin_chat_inbox.html`.
  - `{% extends 'admin/admin_base.html' %}` + `{% load static %}`.
  - Layout: `.admin-chat-wrap` → sidebar (`session-group-label` grouped via `{% regroup sessions by status as status_groups %}` with labels "⏳ PENDING ADMIN", "👥 ACTIVE CHATS", "🤖 AI MODE") plus empty state.
  - Each session card: `.sc-avatar` (first letter), `.sc-name` + `{% if s.has_unread_for_admin %}<span class="unread-dot">{% endif %}`, `.sc-title` (truncate 40), `.sc-assigned` first-2-letters chip if `s.assigned_admin`.
  - Main area empty-select placeholder with 💬 icon + "Select a conversation" + 3 quick-tips bullet list explaining Pending/Active/AI semantics.
- **Acceptance Criteria Addressed**: AC-2, AC-5, AC-8, FR-4, NFR-1, NFR-2
- **Test Requirements**:
  - `rule` TR-7.1: Browse /staff/chat/ as admin → HTTP 200; template renders without TemplateSyntaxError.
  - `rule` TR-7.2: `{% regroup %}` produces at least 1 group-label div when sessions exist; verified by HTML output grep.
- **Notes**: Session card `<a href="{% url 'admin_chat_thread' s.id %}">`.

## Task 8: Create Admin Chat Thread Template (admin_chat_thread.html)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5, Task 4, Task 7 (same sidebar code reused)
- **Description**:
  - New file: `app/templates/admin/admin_chat_thread.html`.
  - Same sidebar as Task 7 (copied inline) with ALL_SIDEBAR context from `all_sessions` and `stats`.
  - Header: `.thread-user` (avatar + client name/email), `.thread-status` status badge (⏳/👥/🤖/✅), `.thread-actions` (Accept form POST to admin_chat_accept if pending; Close form POST to admin_chat_close with confirm if not closed; Back link to admin_chat_inbox).
  - Messages area `.thread-messages`: for msg in messages → `.admin-msg-row` + `{% if msg.is_from_admin %}admin{% else %}client{% endif %}` class. `.am-meta` shows sender first name, ADMIN/CLIENT `.meta-tag`, timestamp "M d, h:i A", and "✅" if msg.is_read.
  - Reply box (if session.status != 'closed'): `<form method="POST">` with {% csrf_token %} textarea + submit button.
  - Inline <script>: auto scrollTop to bottom on load, Enter submits form (Shift+Enter newline), 30-second setInterval location.reload() for auto-refresh of thread page only.
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-5, AC-6, AC-8, FR-5
- **Test Requirements**:
  - `rule` TR-8.1: `/staff/chat/<valid_id>/` renders HTTP 200. Form POST saves new ChatMessage → DB row count increments by 1 (verified by shell query).
  - `rubric` TR-8.2: Message thread readability; scale 1-5; anchors 1=msgs stacked without sender markers 3=left/right present but no role-tag or timestamp 5=left/right positioning with correct tails, ADMIN/CLIENT tags, timestamps, ✅ read-receipt check marks, auto-scroll to newest msg on load; threshold >=4; evidence=HTML output of message loop + script block.
- **Notes**: The `is_from_admin` property is used here — must exist per Task 1.

## Task 9: Integrate CSS Link + Floating Widget into Client & Admin Base Templates
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5 (admin_chat.css written), Task 4 (URLs named)
- **Description**:
  - **A. admin_base.html**: In {% block extra_css %} or <head> block, add `<link rel="stylesheet" href="{% static 'css/admin_chat.css' %}">` (if extra_css block exists, use that; else add near other css <link>s before closing head). No floating widget for admin.
  - **B. client/base.html**: Add same `<link rel="stylesheet" href="{% static 'css/admin_chat.css' %}">`. Then, BEFORE closing `</body>` or inside `{% block content %}` wrapper (outside any blocks so appears on every page), add the FLOATING WIDGET HTML:
    ```
    <div class="float-chat-container">
      <button class="float-chat-bubble" id="floatChatBubble" aria-label="Open chat">
        <span class="float-chat-icon">💬</span>
        {% if request.user.is_authenticated %}<span class="float-chat-unread-badge" id="floatChatBadge" style="display:none;">0</span>{% endif %}
      </button>
      <div class="float-chat-popover" id="floatChatPopover" style="display:none;">
        <button class="float-chat-close" id="floatChatClose" aria-label="Close">×</button>
        <div class="float-chat-status">
          <span class="status-pill online">🤖 AI Online</span>
          <span class="status-pill admin-avail">👤 Admin Avail</span>
        </div>
        <div class="float-chat-hint" id="floatChatHint">
          💡 Need help with booking or packages?
        </div>
        <div class="float-chat-actions">
          <a href="{% url 'client_chat_page' %}" class="float-chat-btn primary">💬 Open Full Chat</a>
        </div>
      </div>
    </div>
    ```
  - **C. Add inline <script> after widget (client base only)**:
    - Toggle popover on bubble click.
    - Smart hint detection: if window.location.pathname contains "/package/" → "💡 Which package is right for your event?"; "/booking/" → "💡 Stuck filling out the booking form?"; "/design/" OR "/canvas/" → "💡 Want design ideas or AI-generated concepts?"; "/gallery/" → "💡 Like a photo? Ask how to recreate that look!"; else (home, etc) → default above.
    - For authenticated users: poll `/api/chat/sessions/` every 30s → IF any session has messages where last msg is from admin AND we can detect via history endpoint that new msgs exist, show unread badge count. Simplified version: GET chat_sessions and count sessions with status in ['pending_admin','active_admin'] to show notification of active threads.
    - Entrance: bubble.classList.add('pulse') → setTimeout 3s → remove class.
- **Acceptance Criteria Addressed**: AC-4, AC-8, FR-7, FR-8, NFR-1
- **Test Requirements**:
  - `rule` TR-9.1: Load / (homepage) as guest + as customer → floating bubble bottom-right visible; click opens popover with correct hint. Browse /package/ → hint changes to package copy (4 tests).
  - `rubric` TR-9.2: Floating widget polish; scale 1-5; anchors 1=static bubble no popover 3=popover works but static text, no entrance anim, no unread badge 5=all features: 3s entrance pulse, 4 page-aware hints, status pills visible, unread badge logic runs on auth, close X works, z-index keeps it above all content including footer; threshold >=4; evidence=widget HTML + script block audit.
- **Notes**: This task is the highest-impact "visible" feature. Keep JS minimal — no frameworks, pure vanilla DOM + fetch only.

## Task 10: Add Chat Navbar Links + Admin Badge Polling
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 4 (URLs)
- **Description**:
  - **A. Client navbar** (`app/templates/components/navbar.html`): Add one `<a>` to `/chat/` inside the main nav `<ul>` or nav-links div, between existing links. Text: `<span>💬</span> Chat Support`. Match styling of sibling nav links (same class, hover, active state). If mobile-menu present add same link to mobile nav section too (consistency).
  - **B. Admin sidebar** (`app/templates/components/admin_navbar.html`): Add a new `<li>` / nav-link block for "Client Chats" pointing to `/staff/chat/`. Add an inline `<span class="nav-badge" id="adminSidebarChatBadge" style="display:none;background:var(--red);color:#fff;font-size:0.6rem;padding:0.08rem 0.4rem;border-radius:999px;margin-left:auto;"></span>` at end of nav link content (flex align).
  - **C. Admin topbar** (`app/templates/components/admin_topbar.html`): Append to the END of the existing <script> block (before closing </script>):
    - 15-second interval → fetch `{% url 'admin_chat_unread_poll' %}` → update `#adminSidebarChatBadge` textContent to (unread_total + pending_count) → if >0 show badge else hide. Also optionally update a topbar inline badge if present (sidebar badge sufficient per spec).
- **Acceptance Criteria Addressed**: AC-3, FR-6, FR-8
- **Test Requirements**:
  - `rule` TR-10.1: Client navbar HTML contains anchor with href='/chat/'. Admin sidebar contains anchor with href='/staff/chat/' + a badge span with id adminSidebarChatBadge.
  - `rule` TR-10.2: Admin topbar script block contains setInterval call with URL to admin_chat_unread_poll (grep).
- **Notes**: If admin sidebar already uses a flex layout, `margin-left:auto` on `<span class="nav-badge">` will correctly right-align the badge next to the label.

## Task 11: Integration Smoke Test (Runserver + Manual 3-Flow Walkthrough)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Tasks 1-10 ALL completed
- **Description**:
  - `python manage.py runserver`.
  - Three flows tested in browser:
    - Flow A (AI Chat): login as customer → /chat/ → send 3 messages → AI replies → ban word check.
    - Flow B (Admin Handoff): In same session → click "Talk to Admin" → confirm → pending status. In separate Chrome profile (or different browser) login as admin → visit /staff/chat/ → see ⏳ PENDING row with unread dot → click → Accept → type reply → customer browser sees reply within 6s.
    - Flow C (Floating Widget): Browse home, /package/, /booking/, /design-canvas/, /gallery/ → widget present + smart hint changes per page. Unread badge on bubble appears after admin sends message while customer is on home.
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4, AC-6, AC-7 (all product flows)
- **Test Requirements**:
  - `rule` TR-11.1: Flow A: All 3 messages responded, no 500 errors.
  - `rule` TR-11.2: Flow B: status changes verified in admin DB session table; customer sees admin message within 2 polling cycles (10 seconds max).
  - `rule` TR-11.3: Flow C: 5 pages × correct hint text.
- **Notes**: If issues found in this smoke test → fix immediately in-place (this task is single pass + final verification).
