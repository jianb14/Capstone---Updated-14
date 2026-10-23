# AI assistant

The guide shows three suggestions at a time from nine theme/color combinations
per occasion. **Help me choose** becomes **Show more ideas**; each click shuffles
the choices and excludes the previous batch. Browsing suggestions preserves
the customer's inputs until they select a style. Choosing one
fills both editable fields. Guide answers and the edited review are saved under
a customer-specific browser key for seven days; **Clear answers** removes them.
Composer drafts and the selected image for editing use customer-specific keys.

Questions such as "What colors suit a wedding?" and "How do I generate a design?"
receive advice without generating an image. Explicit requests, full design
descriptions and **Generate design** can generate images. Advice questions and
negative instructions take precedence over a generation flag. An LLM `[PROMPT]`
block cannot turn an advice request into a paid image operation.

A mixed request such as "What are your packages and can I see a sample backdrop?"
returns the catalog-backed text and an owned, saved image in the same reply.
The text model supplies a separate visual brief; only the worker spends image
credits. Samples are labeled as AI concepts. If generation fails or hits the
image budget, the information remains visible with a clear failure notice.
Numbered replies use one ordered list around nested inclusion bullets, so
package numbers continue even when a model writes every item as `1.`.

## Conversation actions, memory and relevance

Production defaults enable `AI_SMART_ROUTING_ENABLED` and
`AI_RELEVANCE_CHECK_ENABLED`. Clear catalog, date, gallery and booking-help
questions use validated read-only actions. Other messages use a small JSON plan
with a fixed action allowlist; unknown actions, URLs, SQL and supplied account
IDs are never executed. Booking/payment tools always filter by the authenticated
customer. Dates are checked against the literal request; ambiguous dates prompt
for clarification. Ordinary questions and explicit image opt-outs cannot become
paid image operations because a model proposed one.

Topic routing and answer scope are separate. `answer_mode` in the saved plan is
`overview`, `fact`, `focused`, `visual` or `clarify`. Only recognized general
overviews and small factual lookups return a template directly. Specific
questions use a dedicated writer and the relevance check even when the planner
selected only `booking_help`, `payment_help`, `packages` or another tool. This
prevents a form-field question from receiving the entire booking journey.

Focused replies use relevant support facts from `app/ai_support_knowledge.py`,
compatible live tool results, and recent conversation references. Form, canvas,
guide and payment facts are separated to avoid mixing controls from different
pages. Keep those facts aligned with their templates when the UI changes.
Current duration/change policies read SiteSettings. A payment's pending review
and a booking's `pending_payment` status are distinct. Concrete scope checks
request a repair for excessive length, unsolicited estimates, unsupported
color-limit exemptions and invented manual payment instructions.

An uncertain or malformed classification now takes the grounded text-answer path;
it does not automatically display a generic service-category menu. Missing facts
are explained specifically. Availability checks without a complete date ask for
that date, and a short answer continues the same check (including past-date
validation). Choosing **AI image** asks for design details when none are saved;
an ordinary question or an image opt-out never authorizes generation.
Booking-hour questions use the validated event-start window directly, while
identifying an unspecified online-submission cutoff instead of assuming one.

Pending date/image questions are stored in the preceding request's validated
plan, separately from design preferences. Only the immediately preceding
successful reply in the same owned chat can continue a question, for up to one
day. A topic change, failed request, or brief reset prevents stale continuation.
Existing chats that received the previous generic menu/date question can recover
on their next reply. No new migration or environment variable is required for
this routing correction. Messages with identical timestamps also use their
creation IDs to keep the model context and displayed history in the same order.

Each chat stores an explicit design brief (occasion, theme, colors, name,
milestone, budget and selected package). Model-extracted updates require literal
evidence from the current message. Saved details remain available beyond the
recent-message window and are not shared between chats. **Clear saved details**
in the guide clears the server brief. Its version increments so a pending reply
cannot restore details cleared during inference. Guide draft **Clear answers**
remains a separate browser-only action.

Package checks use active package prices and stated numeric panel/color limits.
A conflict asks the customer which limit/package/budget to change before image
budget is consumed. Confirmed details and package constraints are appended to
image and editing prompts. These checks constrain the brief; a generated raster
image is still a concept and does not guarantee an exact physical setup.

Free-form replies are held until a separate relevance check compares the latest
question, confirmed brief and server facts. An off-topic draft gets one repair
and another check; otherwise the assistant asks for clarification. Creative
styling advice is allowed, while business claims require server facts. Pure
styling answers filter unsolicited package/status claims. The real **Checking
the reply** stage is displayed during verification. This reduces mismatches;
it cannot guarantee that a probabilistic model will judge every answer correctly.

Requests for previous/actual work return active Gallery records with **Actual
setup** labels. These cards have no AI edit, booking or feedback controls. New
images remain labeled **AI concepts**. Mixed requests can return both. Deleted
or deactivated gallery images are filtered out of subsequent status/history
responses.

Admins/staff can open `/dashboard/ai-health/` (admins also have an **AI Health**
sidebar link). It reports recorded failures, active jobs, quality repairs,
request trends and token usage when the provider returned it. Latency and usage
are sampled from the latest 500 requests in the selected period. Estimated text
costs require manually configured `AI_TEXT_PRICING_JSON` rates; unreported usage
and image charges are excluded. No paid background health probes run. Customer
messages are not shown on the dashboard. Failures create in-app dashboard alerts;
no external notification or email is sent.

Apply migration `0106_ai_conversation_quality` with the updated code. Defaults
work without new environment overrides; flags can temporarily disable the new
conversation adapter or relevance judge independently for troubleshooting.

The synthetic English/Taglish routing scenarios, including short follow-ups, live in
`app/ai_conversation_cases.json`. To check fast routes without inference:

```shell
python manage.py evaluate_ai_conversations
```

The summary explicitly marks cases requiring a live planner. To evaluate all
cases with real text inference (uses text credits, never creates images):

```shell
python manage.py evaluate_ai_conversations --live
python manage.py test app.test_ai_conversation app.test_ai_text app.test_ai_jobs --settings=Project.test_settings
```

Routing checks alone do not validate the actual reply. Specific questions across
booking, payments, packages, canvas and the guide also have synthetic end-to-end
checks in `app/ai_answer_cases.json`:

```shell
python manage.py evaluate_ai_answers --live
```

This uses text inference credits, public facts and synthetic conversation data;
it never generates images, reads customer account records or saves chat messages.
`--show-replies` prints the generated answers as escaped JSON for inspection.

## Attached photos and editing

An attachment appears inside the composer, above the text controls. **Add
something**, **Change colors** and **Remove something** start an editable
instruction without sending it. After submission, the photo appears above and
outside the customer's text bubble, including when history reloads. **Edit this
photo** selects that original upload; **Edit this design** selects a generated
version. The selected reference also appears inside the composer.

A new upload takes precedence over a previously selected/generated design and
does not inherit its unrelated name, colors or layout. The server resolves
`source_photo_id` only to an undeleted image message owned by the authenticated
customer in the same AI chat. It reads stored image bytes, never a URL supplied
by the customer. A missing source asks the customer to attach it again rather
than silently editing a different image.

An explicit change uses the image-editing provider directly with the source
image and instructions to preserve unmentioned parts. Photo-only messages and
incomplete actions ask what to change before consuming image budget. Opinion
questions use photo analysis without generation. An explicit request for a new
design inspired by the photo uses photo analysis and new-image generation.
Follow-up edits use the latest generated version unless the customer selects an
original photo or another version. Retrying retains the same stored source.

These changes require no additional migration or environment variable. Existing
`AI_IMAGE_EDIT_MODEL_ID` and `AI_IMAGE_EDIT_PROVIDER` settings control editing.
The model determines visual fidelity; instructions do not guarantee pixel-exact
preservation. Region selection/masks are not part of this editor.

## Provider configuration

The text model is configurable through `HUGGINGFACE_MODEL_ID` (default
`Qwen/Qwen3-Next-80B-A3B-Instruct`) and `HUGGINGFACE_TEXT_PROVIDER` (`auto`).
`HUGGINGFACE_TEXT_FALLBACK_MODELS` is a comma-separated list (default
`Qwen/Qwen3-4B-Instruct-2507`). A fallback is attempted only for an unsupported
model, before any output. Authentication, credits, timeouts and partial streams
never start an automatic second inference call. Image model settings are separate.
Provider routing follows the [Hugging Face documentation](https://huggingface.co/docs/inference-providers/index).

Text transport timeout is `HUGGINGFACE_TEXT_TIMEOUT=25` seconds. A wall-clock
deadline of `AI_TEXT_RESPONSE_TIMEOUT_SECONDS=45` covers the text response and
any continuation together. A bounded producer prevents a stalled transport from
blocking the saved request indefinitely. At most two inference producers run per
process. `AI_TEXT_JOB_TIMEOUT_SECONDS=60` lets the status endpoint and worker
recover stalled text jobs even with a live heartbeat. Image generation retains
the separate `AI_JOB_TIMEOUT_SECONDS=900` limit.

Simple catalog requests such as **Our packages** read all active packages,
current prices, service charges and complete inclusions directly from the
database, without an inference call. Mixed questions that also request an image
still follow the text-and-image workflow.

Permanent failures (`model_unavailable`, `provider_auth`, `provider_credits`,
`provider_request`, `provider_config`) do not offer a retry button. Temporary
failures (`provider_busy`, `provider_timeout`, `provider_unavailable`) offer a
retry after a short delay, honoring numeric provider `Retry-After` values.
Error categories are stored on the saved request and logged without provider
credentials or raw responses; customers see a short English message.

Local `.env` and Railway Variables override the defaults. When deploying, remove
an obsolete `HUGGINGFACE_MODEL_ID=Qwen/Qwen2.5-72B-Instruct` override or replace it
with the verified model above; no API key change is required for that migration.

## Saved requests

`POST /api/ai/requests/` accepts a UUID `request_id`, `message`, optional
`session_id`, `image`, `reference_id`, `source_photo_id`, `intent` (`auto`, `generate`, `advice`,
`revise`) and `retry_of`. Poll the returned status URL or
`GET /api/ai/requests/<uuid>/`. `GET /api/ai/requests/active/` finds a customer's
active request. Ownership is checked server-side; status responses are not cached.

The browser saves the UUID before submitting and temporarily keeps attached
photos in IndexedDB. If a POST response is lost, it looks up that same UUID
before resubmitting the same payload. It never falls back to a second generation.
Repeated submission replays the saved operation; changing its payload is rejected.
Only one queued or running request is allowed per customer, across browser tabs
and all AI routes.

Input text/photos are saved to chat at admission and the result is saved once at
completion. Photo history includes the inspiration image and AI response. The
legacy chat, streaming and photo-analysis endpoints share the queue, moderation
and budgets. Non-streaming legacy calls can return HTTP 202 with a request ID and
status URL while processing.

Warnings/bans run before enqueueing; duplicate requests do not add extra strikes.
Active bans are checked again before provider work. Default shared budgets:

| Policy | Default per customer |
| --- | --- |
| `ai_chat` | 30 accepted attempts / minute |
| `ai_chat_cooldown` | 4 seconds between accepted attempts |
| `ai_analysis` | 5 photo requests / minute |
| `ai_image_cooldown` | 15 seconds between image operations |
| `ai_image_daily` | 30 image attempts / rolling 24 hours |

Each image in a multiple-option request reserves one unit before provider work.
Failed image attempts count, since the provider may already have done work.
Advice uses no image quota. Quota failures include a retry time. Polling and
replaying an existing request do not consume AI budgets. General HTTP/upload
budgets still apply to submissions.

## Image revisions

**Edit this design** selects an owned image. Short edits such as "Change only the
balloons to pink" use the last image in the current chat when none was selected.
The server reads the original file from Django storage and submits its bytes to
an image editor, with instructions to preserve the composition and change only
the requested elements. This improves consistency; it is not pixel-exact editing.

Defaults are `AI_IMAGE_EDIT_MODEL_ID=black-forest-labs/FLUX.1-Kontext-dev` and
`AI_IMAGE_EDIT_PROVIDER=auto`. The Hugging Face token needs access, permissions
and credits for the selected editor/provider. Configure another supported model
if needed; see the official [image-to-image API](https://huggingface.co/docs/inference-providers/tasks/image-to-image).
Editing failures keep the original and never silently switch to a fresh
text-to-image layout. Customer-supplied image URLs are not fetched.
Save/feedback actions also resolve owned storage objects, including cloud images;
client-provided filesystem paths are not opened.

## Workers and Railway

Apply `0105_durable_ai_requests` before starting the updated app. The existing
`railway.toml` runs migrations before deployment. Deploy the updated code, static
assets and migration together.

Each development server/Gunicorn worker automatically starts one background AI
worker. PostgreSQL row locks and a unique constraint coordinate the shared queue.
No Redis or separate Railway service is needed with these defaults:

```dotenv
AI_WORKER_AUTOSTART=True
AI_JOB_LEASE_SECONDS=60
AI_JOB_TIMEOUT_SECONDS=900
AI_IMAGE_DAILY_LIMIT=30
AI_IMAGE_COOLDOWN_SECONDS=15
AI_CHAT_COOLDOWN_SECONDS=4
```

`RATE_LIMIT_<POLICY>_COUNT` / `WINDOW_SECONDS` overrides are also supported. For a
dedicated worker, disable autostart on the web service and run
`python manage.py run_ai_worker` in a service with the same database, storage and
AI credentials. `--once` processes at most one request.

Workers heartbeat during processing. Expired leases or requests exceeding the
runtime limit are marked interrupted and never automatically executed again.
**Try again** starts an explicit new attempt using the saved description/photo,
preserving the original input bubble. The app cannot guarantee exactly one
external provider charge if a worker dies after provider success but before saving
its result; it avoids automatically retrying that ambiguous operation.

The UI reports real stages and partial text, without fabricated percentages.
Tests mock providers and spend no AI credits:

```shell
python manage.py test app.test_ai_jobs app.test_ai_image_save app.test_request_protection --settings=Project.test_settings
```

Optional browser tests require Playwright and Edge on Windows. Set
`RUN_DESIGN_BROWSER=1` and run `app.test_ai_design_guide_browser` and
`app.test_ai_recovery_browser` with `Project.test_settings`.
