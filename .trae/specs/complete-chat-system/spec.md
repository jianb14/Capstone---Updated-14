# Balloorina Complete Chat System - Product Requirements Document

## Overview
- **Summary**: Complete end-to-end chat system supporting three modes: (1) Client ↔ AI Assistant (existing, upgraded), (2) Client ↔ Human Admin Handoff (new), (3) Admin Inbox for managing all client chats (new). Includes upgraded floating bottom-right chat widget on client-side with status indicators, unread badges, mini popover, and smart trigger hints. Integrated with existing ChatSession/ChatMessage models, moderation system, and Notification infrastructure.
- **Purpose**: Currently only Client↔AI chat exists via API. Clients have no way to request human help for booking/payment issues, and admins have no inbox to see/reply to client messages. The floating widget in the bottom-right of client pages is a static bubble without status, unread indicators, or mini-popover preview.
- **Target Users**:
  - **Clients (role=customer)**: Browse Balloorina, book events, need quick answers via AI or human support when AI is insufficient.
  - **Admins (role=admin / is_superuser) & Staff (role=staff)**: Manage operations, handle client concerns via chat inbox, view AI-mode chats for context.

## Goals
1. **Model Layer**: Extend existing `ChatSession` with status lifecycle (ai → pending_admin → active_admin → closed) and `ChatMessage` with read-tracking (is_read/read_at). Add assigned_admin, last_client_message_at, admin_last_read_at for inbox UX.
2. **Client Chat Page**: Full dedicated page at `/chat/` with sidebar session list, main message area, "Talk to Admin" handoff button, typing indicators, read/unread marking, ban-state UI from existing moderation.
3. **Admin Chat Inbox**: Page at `/staff/chat/` with grouped session list (Pending → Active → AI mode), unread dots, assigned-admin chips, stats summary chips.
4. **Admin Chat Thread**: Page at `/staff/chat/<id>/` with full message history, Accept/Close actions, reply form, sender badges (ADMIN/CLIENT), read receipts.
5. **AJAX & Polling APIs**: `chat_request_admin`, `chat_mark_read`, `admin_chat_unread_poll`. Reuse existing `chat_api`, `chat_history`, `chat_sessions`, `chat_clear`.
6. **Upgraded Floating Widget**: Bottom-right fixed-position bubble on ALL client-facing pages, with: online status, unread-count badge, mini-popover on hover/click preview, shortcuts to full chat page, context-aware smart hints based on current page.
7. **Navigation Integration**: "💬 Chat Support" link in client navbar. Client chat badge in admin sidebar/topbar with live unread polling.
8. **Admin Notifications**: On handoff request, create Notification entries for all admin users so they see it via their existing notification dropdown.

## Non-Goals
- **NOT building WebSockets/Channels**: Use short-poll AJAX (5s client, 15s admin badge) — Balloorina has real-time volume compatible with polling and no Django Channels configured.
- **NOT reworking moderation/ban system**: Reuse existing `get_chatbot_response`, `evaluate_chat_moderation`, `ChatModerationState`, profanity filter & image-generation logic unchanged.
- **NOT file attachments in chat**: Text + HTML-rendered AI-generated images only, matching existing ChatMessage.TextField schema.
- **NOT group chat / multi-admin**: One assigned admin per session (displayed in sidebar); others can still open and reply via the shared inbox.
- **NOT rewriting the existing AI text/image generator**: Call existing `get_chatbot_response()` verbatim.

## Background & Context
- Existing codebase: Django project, `ChatSession`/`ChatMessage` models in [models.py:192-248](file:///C:/Users/Christian%20R/OneDrive/Desktop/Capstone---Updated-14/app/models.py#L192-L248).
- Existing 4 chat APIs in [views.py:3878-4088](file:///C:/Users/Christian%20R/OneDrive/Desktop/Capstone---Updated-14/app/views.py#L3878-L4088) and URLs at [urls.py:356-359](file:///C:/Users/Christian%20R/OneDrive/Desktop/Capstone---Updated-14/app/urls.py#L356-L359).
- HuggingFace-based AI with text chat + SDXL image generation + Taglish support in `services.py:get_chatbot_response`.
- Existing profanity/toxicity moderation with strike/ban system in services.py.
- `Notification` model already exists and is used for admin notification dropdown in topbar.
- Client base template `app/templates/client/base.html`, Admin base `app/templates/admin/admin_base.html`, Navbars in `components/navbar.html` and `components/admin_navbar.html`, topbar in `components/admin_topbar.html`.
- User preference: bottom-right floating chat widget (confirmed by user in this session) is the BEST placement; NOT moving it, only upgrading UX.

## Functional Requirements
- **FR-1 Model Updates**: ChatSession.status (choices ai/pending_admin/active_admin/closed), assigned_admin FK, last_client_message_at, admin_last_read_at. ChatMessage.is_read + read_at. Add computed `has_unread_for_admin` property and `is_from_admin` property.
- **FR-2 Client Chat Page**: `/chat/` page renders session sidebar, message window, input bar, status badge (AI/Pending/Active), "Talk to Admin" handoff button, clear/new chat buttons, typing indicator, ban countdown UI.
- **FR-3 Client API Extensions**: `/api/chat/request-admin/` (POST) updates ChatSession, sends system confirmation message, creates admin Notifications. `/api/chat/mark-read/` (POST) marks admin-sent messages read in current session.
- **FR-4 Admin Inbox**: `/staff/chat/` — grouped sessions by status, per-session card with avatar, client name, unread dot, assigned chip. Stats chips at top: pending / active_admin / ai / unread_total.
- **FR-5 Admin Thread**: `/staff/chat/<id>/` — full message history with role tags, Accept button (pending→active_admin + assign admin + system message), Close button (status=closed), POST reply form, auto-scroll to bottom, Enter-to-send. Opening thread auto marks unread client messages as read.
- **FR-6 Admin Polling API**: `/api/staff/chat/unread/` returns JSON `{unread_total, pending_count}` for badge updates.
- **FR-7 Floating Client Widget**: Fixed bottom-right bubble on all client pages. Click toggles mini popover showing (a) status pill "🤖 AI · 👤 Admin Available", (b) "Need help booking?" contextual smart hint, (c) two buttons: [Quick Chat (mini)] and [Open Full Chat]. Red unread badge when user has unread admin replies. Bubble pulses on first page load for 3s to draw attention. Smart hint text changes per page: home/package/booking/design/gallery.
- **FR-8 Nav Links**: Client navbar adds "💬 Chat Support" → /chat/. Admin sidebar/topbar badge uses polling endpoint to show count and hyperlink to /staff/chat/.
- **FR-9 Handoff Notifications**: On `request_admin`, create `Notification` row for every user with role=admin or is_superuser=True so their bell icon updates in real-time after next refresh.
- **FR-10 URL Registration**: All 6 new endpoints registered in app/urls.py, names matching the names referenced in templates/JS.

## Non-Functional Requirements
- **NFR-1 Responsiveness**: Client chat page, admin inbox, and floating widget must render correctly at 480px / 768px / 1024px+ breakpoints (sidebar stacks on mobile, message bubbles max-width adjustments per breakpoint). Styles in admin_chat.css.
- **NFR-2 Glassmorphism Theme Matching**: All chat UI cards, bubbles, and sidebars must match existing "Pure Charcoal · Glass Panel" design in admin_base.css / admin_dashboard.css — same --card-bg, --card-bdr, --teal, --blue, --gold, --r CSS variables, same border radii and hover transitions.
- **NFR-3 Security & Roles**: Admin-only views protected by `role in ['admin','staff'] or is_superuser` guard. Customer-only chat page enforces `role=='customer'`. Session access scoped: clients can only read/write their own sessions, admins see all. CSRF tokens sent in all AJAX POSTs.
- **NFR-4 No Breaking Changes**: Existing 4 APIs (`chat_api`, `chat_sessions`, `chat_history`, `chat_clear`) continue to function unchanged for backward compatibility. AI response path, moderation path, image save path in services.py untouched.
- **NFR-5 Performance**: Polling intervals must not spam DB — 5s for client chat history dedup (only appends new messages via content hash compare), 15s for admin badge count, 30s auto-refresh on admin thread page only.
- **NFR-6 Code Co-Location**: All new views → append to views.py before select_design_type function. All new URLs → append to urlpatterns after existing /api/chat/clear/. Styles → new static/css/admin_chat.css (single shared file imported by BOTH client base AND admin base). Templates → standard locations under templates/client and templates/admin.

## Constraints
- **Technical**: No Django Channels; polling only. SQLite/Postgres via existing ORM. Use only installed libs already in venv (requests, Pillow, huggingface_hub installed — no new pip installs).
- **Business**: Taglish-fluent text copy (mix of English and Filipino) matching current site tone. Admin chat must remain useful at low volume — typical Balloorina is ~2-10 concurrent chats.
- **Dependencies**: Existing `User.role` field (admin/staff/customer), `Notification` model, `ChatSession.user`, `ChatMessage.sender/receiver`, `get_chatbot_response`, `get_current_ban_status`, `evaluate_chat_moderation`.

## Assumptions
- Assumption A: At least 1 admin user exists in the DB (handled in existing chat_api already — returns 500 with clear message otherwise).
- Assumption B: `MEDIA_URL` / `MEDIA_ROOT` already configured for existing AI image uploads and are reused unchanged.
- Assumption C: Floating widget CSS class names don't collide with existing styles — namespaced under `.float-chat-*`.
- Assumption D: CSRF token cookie name matches Django default (`csrftoken`).
- Assumption E: Existing admin notification dropdown (rendered in admin_topbar.html via Notification model) will correctly surface new chat-handoff notifications without schema changes.

## Acceptance Criteria

### AC-1: ChatSession.status lifecycle transitions correctly
- **Type**: `rule`
- **Given**: A ChatSession exists with user=customer, initial status='ai'
- **When**: Client POSTs valid session_id to /api/chat/request-admin/ → Admin opens /staff/chat/<id>/ and clicks Accept → Admin clicks Close
- **Then**: Status transitions 'ai'→'pending_admin'→'active_admin'→'closed' in strict order. Re-requesting admin while pending does not duplicate notifications.
- **Pass Condition**: Three separate manual tests each produce the correct transition AND DB reflects same values. No duplicate Notification rows on repeat request_admin POSTs (check count before/after via /api/staff/chat/unread/).
- **Evidence**: Shell session + DB query output for each transition.

### AC-2: Unread messages surface in admin inbox correctly
- **Type**: `rule`
- **Given**: Admin inbox loaded, 2 sessions where session A has new client messages after admin_last_read_at, session B does not
- **When**: Admin visits /staff/chat/
- **Then**: Session A shows red unread-dot badge + counted in `unread_total` stat chip. Session B has no dot. Opening session A marks A's unread client messages is_read=True + session.admin_last_read_at set to now.
- **Pass Condition**: Visual + DB check: before open → `SELECT COUNT(*) FROM chatmessage WHERE is_read=False AND session_id=A` >0; after thread open → 0 AND session.admin_last_read_at is NOT NULL.
- **Evidence**: Inbox screenshot with red dots visible. SQL query output before/after.

### AC-3: Client can see admin replies within 6 seconds of send
- **Type**: `rule`
- **Given**: Client has /chat/ open on session_id=1 (in active_admin state). Admin sends reply via /staff/chat/1/ POST form.
- **When**: 6 seconds elapse on client side (polling).
- **Then**: Client's message pane shows new admin message bubble with correct sender avatar and meta, no duplicate append of existing messages (content-hash dedup works).
- **Pass Condition**: New message appears in client DOM within 6 seconds and previous messages in DOM count do not increase.
- **Evidence**: DOM MutationObserver count or DOM child-count comparison + network tab request log showing /api/chat/history/ fetch at 5s interval.

### AC-4: Floating widget renders on all client pages with page-aware hints
- **Type**: `rubric`
- **Dimension**: Floating widget UX completeness on client-facing pages (home, packages, booking, gallery, design canvas, profile).
- **Scale**: 1-5
- **Anchors**: 1 = Widget missing on most pages, no badge, no popover. 3 = Widget on 3+ pages, click opens full chat, static text hint. 5 = Widget present and correctly positioned (bottom-right, fixed, z-index above footer) on ALL six listed pages; shows page-aware smart hint text (e.g., booking page → "Need booking help?"); unread badge updates on admin reply; popover has working Quick/Full chat buttons; subtle entrance pulse animation on first paint.
- **Pass Threshold**: >= 4
- **Evidence**: Six screenshots (one per page type) each showing widget + current smart hint text.

### AC-5: Admin inbox layout matches Balloorina charcoal-glass theme
- **Type**: `rubric`
- **Dimension**: Visual design fidelity (colors, spacing, radii, typography) relative to existing dashboard panels in admin_dashboard.css.
- **Scale**: 1-5
- **Anchors**: 1 = White/unstyled raw HTML, no cards. 3 = Uses dark bg but mismatched borders/radii vs glass-panel theme. 5 = sidebar session cards, thread header, message bubbles, reply box all reuse --card-bg, --card-bdr, --t1/--t2/--t3/--blue/--teal/--gold variables correctly; same border-radius as existing glass-panel; avatar pill badges, unread dots, stat chips have identical shadow/hover treatments to dashboard mod-badges; message-bubble tails consistent with standard chat pattern.
- **Pass Threshold**: >= 4
- **Evidence**: Side-by-side screenshot of admin chat inbox AND existing data-modules row from /dashboard/ demonstrating shared visual language.

### AC-6: Role/permission gating enforced
- **Type**: `rule`
- **Given**: Session user role=customer only
- **When**: Logged in as customer → visits /staff/chat/ OR admin user (role=admin) → POST /chat with session_id belonging to a different user's session
- **Then**: Customer receives 403 Forbidden. Admin's /chat API cannot send messages to arbitrary other users' sessions (session filter by user enforced). Conversely, admins CAN open any session via /staff/chat/<id>/.
- **Pass Condition**: Two manual curl / browser tests: customer hits 403 on /staff/chat/; admin opens all inbox sessions successfully.
- **Evidence**: HTTP response codes (403 / 200) captured in network tab or curl output.

### AC-7: Existing AI chat flow + moderation + image gen remain working
- **Type**: `rule`
- **Given**: Clean client chat session (status=ai). User types a normal Taglish question ("magkano ang wedding package?"), then types a profanity test word, then types "gawa ka ng birthday design pink and gold".
- **When**: Each message sends via existing /api/chat/ POST route.
- **Then**: (a) AI responds with package pricing text unchanged, (b) profanity → warning/banned UI shown via existing evaluate_chat_moderation integration, (c) image request → AI returns <img> tag with data-ai-prompt attribute and file saved to /media/ai_generated/.
- **Pass Condition**: All three sub-conditions produce outputs matching pre-existing behaviour of the codebase (verified by running through the same prompts before/after or via code inspection confirming chat_api calls `get_chatbot_response` unchanged).
- **Evidence**: Screenshots of three message types with AI replies visible in chat UI.

### AC-8: Responsive breakpoints render without horizontal scroll
- **Type**: `rule`
- **Given**: Three viewport widths: 420px (mobile), 820px (tablet), 1440px (desktop).
- **When**: Client /chat/, admin /staff/chat/, admin /staff/chat/<id>/, and home with floating widget are loaded in each.
- **Then**: No horizontal scrollbar appears; sidebar collapses to stacked layout <900px; text never overflows its bubble; floating widget never overlaps footer links. Admin thread at 420px still shows sender/meta readably with 90% max-width on bubbles.
- **Pass Condition**: Four pages × three viewports = 12 measurements. Every one has document.body.scrollWidth <= window.innerWidth (allowing 1px fuzz).
- **Evidence**: DevTools ruler overlay screenshots at each breakpoint for client chat and admin thread.

## Open Questions
- [x] Q1: Floating widget placement → **Answered**: bottom-right, keep it (user confirmed in same session). Smart page-aware hints included as FR-7.
- [x] Q2: WebSockets vs polling → **Answered**: polling only per constraints (no Channels).
- [x] Q3: Admin topbar badge in existing navbar → **Answered**: use existing sidebar nav link + topbar script poll; reuse Notification for handoff events in admin bell.
