# User-facing error message review

Date: November 19, 2026. Status: proposals for discussion; application code has not been changed.

**Implementation update:** The user subsequently approved the English replacements. Application changes and regression tests are now implemented; see `docs/user-error-message-verification.md` for results. Statements below about “review only” describe the original audit stage.

## Correction after the Report Concern report

The first review was incomplete: Report Concern appeared only in the parsing-error discussion, and the main findings did not clearly identify its raw-message display paths. Its ordinary network-error handling was not enough evidence to consider the screen covered.

Report Concern is a priority finding. `static/js/report_concern.js:193` translates an `AbortError` or a same-realm `TypeError`, but otherwise returns `error.message` at `:196`. Submission displays that value in both the inline status and the toast at `:226` and `:227`; cancellation does the same at `:333` and `:334`.

There are two important paths beyond an ordinary network failure:

- `:212` and `:325` turn a server-provided message into `new Error(...)`. If it contains technical text, it is displayed directly, including “Failed to fetch.”
- JSON parsing at `:190` can throw a `SyntaxError`. The UI displays the browser's raw “Unexpected token … is not valid JSON” text.

Controlled Chrome tests drove the real submit/cancel handlers and confirmed both inline and toast exposure. A second probe also loaded the full page from Django with an isolated test database. An injected technical server response reproduced “Failed to fetch”; malformed JSON reproduced the parsing diagnostic. These establish the exposure paths, not which response or script version caused the user's particular occurrence. A native fetch failure alone was translated into the existing friendly fallback in the tested Chrome environment.

Proposed submission text: **“We couldn't confirm your submission. Check My Concerns before trying again.”** Keep the entered details and attachments available in the form.

Proposed cancellation text: **“We couldn't confirm the cancellation. Check your concern's status before trying again.”**

If using Filipino instead: **“Hindi namin makumpirma kung naipadala ang concern mo. Nandito pa ang mga inilagay mo. Tingnan muna ang My Concerns bago subukang muli.”**

The expanded source scan covers **77 JavaScript files, 214 templates, and 91 Python modules: 382 files**. The [coverage CSV](error-message-audit-coverage.csv) lists every scanned file, matching failure/message locations, and whether it was individually browser-tested. A scan is not a claim that every page/action was browser-tested. Candidate matches include internal errors and logs, which need the source-to-display distinctions below.

Reproduction artifacts are in `.booking-followup-check/error-copy-audit/`: `report_concern_probe.py`, `report-concern-results.json`, `live_concern_probe.py`, and the full-page screenshot `live-report-concern-failed-to-fetch.png`. These are local audit fixtures, not application changes. Responses were deliberately injected; no customer concern was submitted or cancelled in the development database.

Verified results:

- `report_concern_probe.py`: 14 isolated real-handler scenarios completed; 8 displayed raw technical messages. This probe uses the actual concern template markup and source scripts, with a minimal page shell.
- `live_concern_probe.py`, with `ERROR_AUDIT_ENTRIES=account_navigation`: 8 full Django-page scenarios passed their observation assertions; 4 displayed raw technical messages. These cover submit/cancel after entering Report Concern from the account sidebar. Results are recorded in `live-concern-results.json`.
- The full-page probe used `Project.test_settings`, a temporary SQLite test database, test-only login cookies, local email/cache backends, and intercepted failure responses. It verified that the fixture concern remained New and no additional concern was created.
- “Passed” means the audit reproduced the recorded outcomes. It does not mean the raw-message problems have been fixed. No application fix was made.

## Scope and confidence

Reviewed first-party JavaScript in `static/js`, inline scripts and visible text in `app/templates`, Django views, and the supporting validation/error-handling modules in `app`. Followed important messages from their source to the code that displays them. Excluded generated `staticfiles`, dependencies, migrations, tests, logs, manuals, and backup data from the message inventory.

Most entries are source findings; Report Concern additionally has the controlled browser verification described above. This is not a browser reproduction of every failure. “Can display” means the inspected error path forwards that message to the interface. Network errors such as “Failed to fetch,” “Load failed,” and “NetworkError when attempting to fetch resource” depend on the browser; they need not exist as literal strings in the repository. JSON parsing errors also vary by browser and response.

The inventory below groups repeated instances by screen and message family. API-only and older paths are identified separately so that they are not mistaken for confirmed messages on current screens. This review cannot guarantee every possible runtime or third-party validation message.

## Suggested wording rules

- Say what the user was trying to do: load a booking, save a design, send a message, or verify a code.
- Give a useful next step. For a connection failure, ask the user to check their connection. A general error should not automatically blame their internet.
- Keep exception text, JSON, API keys, database details, HTTP diagnostics, and internal identifiers in developer logs.
- Preserve helpful field errors, such as “Passwords do not match.” Do not replace them all with the same generic error.
- When a submission's outcome is uncertain, say “We couldn't confirm…” and ask the user to check its status before retrying. Do not claim that it failed, succeeded, or was never charged without evidence.
- Say “Your changes are still here” only when the interface actually retains them. Do not tell users to reload a page with unsaved work without a way to preserve it.
- Keep any real wait time dynamic. Keep payment amounts, booking rules, and limits unchanged.
- Proposed copy is simple English to match the existing interface. Filipino/Taglish is an alternative for discussion.

## 1. Screens that can expose browser error text

The main problem in these rows is displaying `error.message` without translating browser errors first. `error.message || 'Friendly message'` does not fix this: “Failed to fetch” is nonempty, so it wins over the fallback.

| Screen / action | Display location | Suggested user-facing text |
| --- | --- | --- |
| **Report Concern: submit** | `static/js/report_concern.js:196`, `:212`, `:226`, `:227` | “We couldn't confirm your submission. Check My Concerns before trying again.” Confirmed raw-message exposure in controlled browser tests. |
| **Report Concern: cancel** | `static/js/report_concern.js:196`, `:325`, `:333`, `:334` | “We couldn't confirm the cancellation. Check your concern's status before trying again.” Confirmed raw-message exposure in controlled browser tests. |
| My Designs: rename | `static/js/my_designs.js:208` | “We couldn't confirm the new name. Check your designs before trying again.” |
| My Designs: delete | `static/js/my_designs.js:227` | “We couldn't confirm whether this design was deleted. Check My Designs before trying again.” |
| Reviews: create/edit | `static/js/review_page.js:152` | “We couldn't confirm whether your review was saved. Check My Reviews before trying again.” |
| Reviews: delete | `static/js/review_page.js:174` | “We couldn't confirm whether your review was deleted. Check My Reviews before trying again.” |
| Reviews: like/unlike | `static/js/review_page.js:232` | “We couldn't update your like. Please try again.” |
| Customer booking details | `static/js/customer_booking_details.js:145` | “We couldn't load this booking. Check your connection and try again.” when a connection error is detected |
| Customer notifications list | `static/js/customer_notifications.js:164` | “We couldn't load your notifications. Check your connection and try again.” when a connection error is detected |
| Customer password code verification | `static/js/profile_password_otp.js:48` | “We couldn't confirm the password change. Try signing in with your new password before trying again.” for a submitted password change; use “We couldn't load password verification. Please try again.” for loading |
| Account deletion: resend verification code | `static/js/profile_deletion.js:163` | “We couldn't confirm whether a new code was sent. Check your email, then try again when the resend button is available.” |
| AI recent chats: delete | `app/templates/client/base.html:2177` | “We couldn't confirm whether this chat was deleted. Check your recent chats before trying again.” |
| Admin bookings: list, details, changes | `static/js/admin_booking_workspace.js:66`, `:131`, `:215` | Loading: “We couldn't load the bookings. Please try again.” Saving: “We couldn't confirm the update. Check the booking's latest status before trying again.” |
| Admin payment list, settings, details, approval/rejection | `static/js/admin_payment_workspace.js:91`, `:143`, `:179`, `:222`, `:351`, `:377` | Loading: “We couldn't load the payments. Please try again.” Saving: “We couldn't confirm the update. Check the latest payment status before submitting again.” |
| Admin catalog: list, details, save, delete | `static/js/admin_catalog.js:73`, `:136`, `:217`, `:286` | Loading: “We couldn't load these items. Please try again.” Saving/deletion: “We couldn't confirm the change. Check the item list before trying again.” |
| Admin calendar: block/unblock dates, refresh | `static/js/admin_calendar.js:161`, `:185`, `:195`, `:203` | “We couldn't confirm the calendar change. Check whether the date is blocked before trying again.” For a known successful save followed by a failed refresh: “Your change was saved, but we couldn't refresh the calendar. Refresh it to see the latest schedule.” |
| Admin reviews: list, details, reply actions | `static/js/admin_reviews.js:84`, `:167`, `:214` | Loading: “We couldn't load the reviews. Please try again.” Reply: “We couldn't confirm whether your reply was saved. Check the review before trying again.” |
| Admin concerns: list, details, update | `static/js/admin_concerns.js:77`, `:130`, `:162` | Loading: “We couldn't load the concerns. Please try again.” Update: “We couldn't confirm the change. Check this concern's latest status before trying again.” |
| Admin users: list, details, access changes | `static/js/admin_users.js:56`, `:72`, `:107` | “We couldn't load this account. Please try again.” Access change: “We couldn't confirm the access change. Check the account's current access before trying again.” |
| Admin dashboard filters/refresh | `static/js/admin_dashboard.js:135` | “We couldn't update the dashboard. The previous figures are still shown. Please try again.” |
| Admin global search | `static/js/admin_navigation.js:89` | “We couldn't search right now. Check your connection and try again.” when a connection error is detected |
| Admin activity history | `static/js/admin_audit_log.js:90` | “We couldn't load the activity history. Your current list is still shown. Please try again.” |
| Admin profile/password verification | `static/js/admin_profile_workspace.js:87`, `:125`, `:148` | Loading: “We couldn't load password verification. Please try again.” Code sending: “We couldn't confirm whether the code was sent. Check your email before requesting another.” Verification: “We couldn't confirm the password change. Try signing in with your new password before trying again.” |
| Admin security/invitations | `static/js/admin_security.js:213`, `:214`, `:383` | Loading: “We couldn't load the invitations. Please try again.” Submission: “We couldn't confirm this change. Check the current account or invitation details before trying again.” |
| Accept admin invitation | `static/js/admin_invitation_accept.js:92` | “We couldn't confirm whether your account was created. Try signing in before submitting again.” |
| Admin canvas asset deletion | `app/templates/admin/canvas/admin_canvas_assets.html:408` | “We couldn't confirm whether this item was deleted. Check the item list before trying again.” |

These replacements are contextual proposals, not instructions to overwrite specific validation messages. Connection-specific copy should be used only for a detected connection failure.

## 2. Paths that hide network failures but can still expose parsing errors

| Location | Current handling | Suggested text for an unreadable response |
| --- | --- | --- |
| `static/js/admin_configuration.js:64`, `:85` | Converts `TypeError`, but forwards a `SyntaxError` from `response.json()` through `error.message`. | “We couldn't confirm whether your settings were saved. Check the current settings before trying again.” |
| `static/js/admin_analytics.js:229`, `:248` | Converts connection errors/timeouts, but forwards JSON parsing errors. | “We couldn't update the report. The previous report is still shown. Please try again.” |
| `static/js/report_concern.js:190`, `:193` | Converts connection errors/timeouts, but forwards JSON parsing errors. | Submission: “We couldn't confirm whether your concern was submitted. Check My Concerns before trying again.” Cancellation: “We couldn't confirm the cancellation. Check this concern's status before trying again.” |
| `static/js/support_chat.js:62`, `:66` | Converts connection errors/timeouts, but a malformed JSON response is rethrown and can reach `setError(error.message)`. | Loading: “We couldn't load your messages. Please try again.” Sending: “We couldn't confirm whether your message was sent. Check the conversation before sending again.” |
| `static/js/admin_security.js:173` | Checks content type but does not translate malformed JSON; the error can reach the locations in section 1. | Use the invitation/security action-specific message in section 1. |
| `static/js/admin_profile_workspace.js:71` | Parses JSON directly; parsing errors can reach `tell(error.message)`. | Use the loading, sending, or password-change message in section 1. |

## 3. Fixed messages and backend responses worth rewriting

Some responses below are normally reached only when a request is malformed or an old link is used. They still need safe copy if they are returned to a user. Repeated source locations are grouped.

| Where | Current text / issue | Suggested text |
| --- | --- | --- |
| Design saving, `static/js/design_canvas.js:4163` | “Error saving design: …” / “Unknown error”; server details are appended. | “We couldn't confirm whether your design was saved. Check My Designs before trying again.” |
| Design saving, `static/js/design_canvas.js:4166` | “Network error. Could not save design.” Also catches errors unrelated to the network. | “We couldn't confirm whether your design was saved. Keep this page open and check My Designs in another tab before trying again.” |
| Save/rename/delete design, `app/views/designs.py:254`, `:280`, `:298` | Returns `str(e)` for unexpected exceptions. Can expose database, storage, parsing, or framework wording. | Return a safe action-specific message; log the exception privately. Use the design-saving/rename/delete proposals above, according to the action. |
| Design save/evaluate, `app/views/designs.py:146`, `:170`, `:241`, `:758`, `:764`; `app/design_validation.py:162` | “Invalid design data.” / “Canvas data is invalid.” | “We couldn't read this design. Try reopening it from My Designs.” For a new unsaved design, do not instruct a reload that would discard it; offer retry/support while keeping the page open. |
| Design validation, `app/design_validation.py:175` | “A canvas item is invalid.” | “We couldn't read one of the items in your design. Remove and add that item again.” If possible, identify the affected item. |
| Design validation, `app/design_validation.py:182`; `static/js/design_rules.js:11` | “Re-add an unrecognized catalog item from the asset list so it can be counted.” / “Re-add unrecognized catalog items so they can be counted.” | “Some items in this design are no longer recognized. Remove and add them again from the item list.” |
| Design save, `app/views/designs.py:239` | “Design or offer not found.” | “This design or package is no longer available. Open My Designs or choose another package.” |
| Design endpoints, `app/views/designs.py:141`, `:261`, `:287`, `:754` | “Not allowed” | “You don't have permission to change this design. Sign in with the account that owns it.” Use “open” instead of “change” for read-only access. |
| Password verification and general request protection, `app/views/auth.py:591`, `:595`; `app/request_limits.py:83` | “Request protection is temporarily unavailable. Please try again in 5 seconds.” | General: “We can't complete this action right now. Please try again in 5 seconds.” Password code: “We can't verify your code right now. Please try again in 5 seconds.” |
| Rate limit, `app/request_protection.py:25`; `static/js/admin_booking_workspace.js:31` | “Too many requests.” | “Please wait {seconds} seconds before trying again.” Keep the actual retry time when supplied; otherwise “Please wait a moment before trying again.” |
| Password reset, `app/views/auth.py:705` | “Your reset authorization has expired or already been used.” | “This password reset has expired or was already used. Request a new code to continue.” |
| Customer password request, `app/templates/client/my_profile.html:359` | “Update failed. Please check your inputs.” | “We couldn't send a verification code. Check the highlighted fields and try again.” Keep any specific validation error returned for a field. |
| Booking edit, `app/views/bookings.py:1158` | “Invalid event date format.” | “Choose your event date using the date picker.” |
| Booking time validation, `app/views/bookings.py:1166`; `app/views/common.py:420` | “Invalid time format.” | “Choose the start and end times using the time fields.” |
| Booking price, `app/views/bookings.py:1172`, `:1174` | “Invalid price format.” The customer should not have to repair a calculated price. | “We couldn't confirm the booking total. Review your selected package and extras, then try again.” |
| Admin catalog prices, `app/views/admin.py:290`, `:334`, `:444`, `:500`, `:549`, `:593` | “Invalid price format.” | “Enter a price using numbers, for example 1500.00.” |
| Admin calendar date, `app/views/bookings.py:410` | “Invalid date format.” | “Choose a date using the date picker.” |
| Admin booking fee, `app/views/bookings.py:1503` | “Invalid logistics fee.” | “Enter the delivery and setup fee using numbers, for example 1500.00.” Keep the actual limits and decimal precision checks. |
| Admin booking action fallback, `app/views/booking_workspace.py:47` | “Unknown booking action.” | “We couldn't complete this booking action. Reopen the booking and check its latest status before trying again.” |
| Booking details endpoint, `app/views/bookings.py:1024` | “Unknown booking section.” | “We couldn't open this part of your booking. Reopen the booking details and try again.” The current modal translates the non-OK response before displaying it; this source text is primarily relevant to direct or older callers. |
| Map request, `app/views/bookings.py:35` | “Invalid map coordinates.” | “We couldn't read the selected location. Place the pin on the map again.” |
| Booking delivery calculation, `app/templates/client/booking/booking_page.html:2817`; `app/templates/client/customer_profile.html:833`, `:1129` | “We couldn't calculate logistics…” / “Logistics quote is unavailable…” | “We couldn't calculate the delivery and setup fee for this venue. Please contact our team before continuing.” Confirm this wording covers the business's actual fee. |
| Map fallback, `app/templates/client/booking/booking_page.html:1429`; `app/templates/client/customer_profile.html:1202` | “Map unavailable — pin optional…” can conflict with later validation requiring an exact pin. | “We couldn't load the map. Try again to pin your venue, or contact our team for help.” The actual ability to continue without a pin needs a separate behavior decision. |
| Payment configuration, `app/views/payments.py:836`; `app/views/changes.py:249` | “GCash QR payments are not configured.” | “GCash payment is unavailable right now. Please contact our team before sending money.” |
| Customer payment amount, `app/views/payments.py:903` | “Invalid amount for selected option. Expected PHP …” | “The amount for your selected payment option is PHP {amount}. Review your payment details before continuing.” |
| Admin payment reconciliation, `app/views/payments.py:1348` | “The previous checkout is unresolved. Check its provider status…” | “The earlier payment attempt still needs review. Check its status with the payment service before approving another payment.” |
| Legacy payment return/cancel, `app/views/payments.py:1811` | “Check the provider status before making another payment.” | “We haven't confirmed the previous payment attempt yet. Check its payment status or contact our team before paying again.” |
| Concern image validation, `app/views/profiles.py:112` | “Please attach valid image files.” Does not explain accepted formats. | “Upload a JPG, PNG, or WebP image. If the photo won't open, try another file.” Keep the separate existing size/count errors. |
| Payment proof image, `app/payment_forms.py:50` | “…up to 5 MB and 12 megapixels.” The resolution limit may be unfamiliar. | “Upload a JPG or PNG screenshot under 5 MB. If it is too large, crop it or choose a smaller image.” Keep a precise resolution limit available in help text if needed. |
| AI access, `app/views/ai.py:24`, `:94`, `:111` | “Authentication required.” | “Please sign in again to use the assistant.” |
| AI chat/request lookup, `app/views/ai.py:27`, `:97`; `app/ai_jobs.py:119` | “Chat not found.” / “Request not found.” | “This chat is no longer available. Start a new chat.” / “We couldn't find this message request. Reopen the chat and check its latest messages.” |
| AI request creation, `app/ai_jobs.py:111`, `:121` | “A valid request ID is required.” / “This request ID is already attached to a different message.” | “We couldn't send this message. Reopen the chat, check whether it was sent, and try again if needed.” |
| AI image feedback/save, `app/ai_images.py:14`, `:17`; `app/views/chat.py:1411` | “Invalid image reference.” | “We couldn't find this image. Reopen it from your chat and try again.” |
| Services theme quiz, `app/views/public.py:172`, `:174` | “Invalid request body.” | “We couldn't read your selections. Choose your event type and preferred style again.” |
| Services theme quiz, `app/services.py:2940`, `:2946`, called by `app/views/public.py:218` | “System Error: AI library missing. Please install huggingface_hub.” / “Configuration Error: API key missing.” The quiz returns nonempty text as a result, so these can appear as a supposed successful recommendation. | “We couldn't create a theme suggestion right now. Please try again later or contact our team for help.” Return/display it as an unavailable/error result. |
| AI image helper, `app/services.py:1714`, `:1721`, `:1727` | Image provider, Hugging Face credits, and API-key explanations. Helper is used in older generation paths; it is not the main async job failure mapping. | “We couldn't create the sample image right now. Please try again later.” For a configuration problem, offer contacting the team instead of promising a retry will fix it. |
| Admin offer validation, `app/offer_editor.py:72` | “This row is invalid.” | “We couldn't read this inclusion. Remove it and add it again.” |
| Admin offer image selection, `app/offer_editor.py:130` | “Invalid image selection.” | “We couldn't read the selected images. Choose the images again.” |
| Admin design category, `app/design_admin.py:43` | “Invalid design category.” | “Choose a category from the list.” |
| Admin design quantities, `app/design_admin.py:58` | “Use non-negative minimums and positive maximums.” | “The minimum must be 0 or higher. The maximum must be at least 1.” |
| Admin design color limit, `app/design_admin.py:68` | “Balloon color limit must be a positive whole number.” | “Enter at least 1 balloon color, using a whole number.” |
| Admin catalog/reviews, `static/js/admin_catalog.js:122`; `static/js/admin_reviews.js:37` | “The server returned an incomplete response.” | “We couldn't load these details. Please try again.” |
| Admin dashboard, `static/js/admin_dashboard.js:126` | “The server returned an incomplete dashboard.” | “We couldn't update the dashboard. The previous figures are still shown. Please try again.” |
| Admin bookings, `static/js/admin_booking_workspace.js:32`, `:33` | “The server could not load this information.” / “The server returned an unexpected response.” | “We couldn't load this information. Please try again.” |
| Admin payment workspace, `static/js/admin_payment_workspace.js:38` | “The request could not be completed (${response.status}).” | “We couldn't load this payment information. Please try again.” For submissions, use the status-checking message in section 1. |
| Admin calendar, `static/js/admin_calendar.js:85` | “This action could not be authorized.” | “We couldn't confirm permission for this change. Reopen the calendar and try again.” A definite permission denial should instead say that the account cannot make the change. |
| Admin calendar/payment timeouts, `static/js/admin_calendar.js:91`; `static/js/admin_payment_workspace.js:43`, `:122` | “The request timed out.” | “This is taking longer than expected. Check the latest calendar/payment status before trying again.” |
| Booking change actions, `app/views/changes.py:136`, `:206`, `:284` | “Unknown change request action.” / “Unknown request action.” / “Unknown payment action.” | “We couldn't complete this action. Reopen the booking and try again.” Preserve any warning about submitted payments and check the latest status before repeating a payment action. |
| Admin payment action fallback, `app/views/payments.py:1493` | “Unknown action: '{action}'…” exposes an internal action name. | “We couldn't complete this payment action. Reopen the payment and check its latest status before trying again.” |
| Admin email blast, `app/views/admin.py:1992` | “…email(s) failed to send. Please check the email configuration.” | “{count} emails could not be sent. Review the delivery details before sending again.” Account for partially successful delivery. |

## 4. Other API messages and older paths

These are present in the source. Their existence alone does not establish that a normal interaction in the current UI displays them.

| Source / current message family | Suggested user-facing wording / treatment |
| --- | --- |
| `app/views/chat.py:262`: “Invalid JSON body” | “We couldn't read your message. Please try sending it again.” Check the conversation first if the send result is uncertain. |
| `app/views/chat.py:295`, `:1299`: “System misconfiguration (no admin found)” | “We can't connect you to our team right now. Please try again later.” The current support chat uses `app/views/support_chat.py`, which already returns safer unavailable messages. |
| `app/views/chat.py:539`, `:653`, `:709`, `:740`, `:803`, `:886`, `:1200`, `:1219`: “session_id required” | “We couldn't open this conversation. Reopen the chat and try again.” |
| `app/views/chat.py:680`, `:930`, `:1137`: “message_id required”; `:844`: “message_id and emoji required” | “We couldn't find the selected message. Reopen the conversation and try again.” |
| `app/views/chat.py:125`, `:1143`: “Session not found” / “Message has no session” | “This conversation is no longer available. Reopen the chat or start a new conversation.” |
| `app/views/chat.py:127`, `:714`, `:745`, `:778`, `:808`, `:852`, `:882`, `:1119`, `:1146`, `:1235`: “Forbidden” | “You don't have permission to open or change this conversation.” Tailor open/change to the action. |
| `app/views/chat.py:272`: “Authentication required” | “Please sign in again to send a message.” |
| `app/views/chat.py:846`, `:932`: “Invalid emoji” | “Choose a reaction from the available options.” |
| `app/views/chat.py:1393`, `:1446`: “Something went wrong.” | “We couldn't save your feedback. Please try again.” / “We couldn't confirm whether this image was saved. Check My Designs before trying again.” |
| `static/js/client_admin_chat_widget.js:632`, `:658`, `:717`, `:730`, `:754`: raw `error.message` and “Action failed” | Use send/edit/reaction-specific messages. No current template reference to this older script was found; current widgets include `support_chat.js`. Check whether the old script is still served anywhere before spending implementation effort on it. |
| `static/js/admin_chat_thread.js:438`, `:530`, `:801`, `:1044`: `alert(data.error)` | Direct server text can become a browser alert for reaction, deletion, editing, and pinning. Use “We couldn't update your reaction. Please try again,” or an action-specific confirmation/status-check message for edit/delete. No current template script reference was found in this scan; classify this separately from the current `support_chat.js` inbox. |
| `app/views/chat.py:357`, `:541`, `:639`, `:665`, `:695`, `:729`, `:787`, `:828`, `:871`, `:950`, `:1188`: “Something went wrong. Please try again later.” and its variants | Understandable but vague. Use messages specific to sending, opening, deleting, editing, reacting, or pinning. On an uncertain send/delete/edit, direct the user to check the conversation before repeating the action. |
| `app/views/notifications.py:11`, `:33`, `:52`, `:70`, `:119`, `:166`: “Not allowed”; `:36`, `:73`: “Invalid notification.” | “Please sign in again to view your notifications.” only for an expired login; otherwise “This notification is no longer available. Refresh your notifications.” Respect actual permission failures. |
| `app/admin_notifications.py:31`; `app/views/notifications.py:146`; `app/customer_updates.py:89`, `:113`; `app/views/notifications.py:170`: cursor, update-position, or delivery-receipt errors | “We couldn't update your notifications. Refresh the list and try again.” Some polling paths already recover silently; do not introduce popups for background retries. |
| `app/views/support_chat.py:174`, `:229`, `:334`, `:344`, `:399`: invalid update/send/read/delivery request or action | “We couldn't update this conversation. Reopen the chat and try again.” Use the uncertain-send wording when appropriate. Some read/delivery actions run in the background and should recover quietly. |
| `app/services.py:2233`, `:2237`: monthly AI credits / “AI authentication failed. Please verify the HUGGINGFACE_API_KEY in .env.” | Older non-strict photo-analysis fallback. The current job calls photo analysis with `strict=True` at `app/ai_jobs.py:433`, bypassing these return strings. Keep developer setup instructions out of any path reused for customers. |
| `app/catalog_admin.py:161`, `:200`, `:214`; `app/content_admin.py:158`, `:181`: “Not allowed” | For JSON permission responses: “You don't have permission to make this change.” HTML 403 responses already receive the shared error page. |
| HTML “Not allowed”, “Admins only”, “Customers only” across Django views | Do not blindly treat every source occurrence as visible verbatim. `app/error_pages.py:58` replaces direct HTML 403 bodies for normal page navigation. JSON responses still need their own wording. |

## 5. Technical text that should not be counted as a current user error

- `console.error`, `console.warn`, Python logging, internal error codes, and comments can retain technical details.
- `static/js/admin_booking_requests.js:48` throws “Request failed,” but its catch displays “Could not update requests.” at `:58`. The thrown text does not reach the user in this path.
- `static/js/account_navigation.js:38`, `:67`, `:102` and `static/js/account_tables.js:90`, `:93` throw internal loading errors; their catch paths already use separate friendly text.
- `static/js/customer_notifications.js:211` throws “Invalid update payload” in background polling; the catch recovers without displaying that string.
- `app/templates/client/booking/booking_page.html:2016`, `:3000`, `:3395` contain library/fetch/non-JSON diagnostics, but the inspected catch paths use separate friendly messages. The calendar guard displays recovery text at `static/js/booking_calendar_guard.js:45`.
- `static/js/booking_changes.js:15`, `static/js/booking_location_map.js:212`, `:299`, `static/js/ai_request_ui.js:59`, and `static/js/services_widgets.js:159`, `:160` similarly translate their internal thrown messages in the display path.
- `app/views/profiles.py:105`, `:110` throws “Unsupported image format” / “Invalid image” internally, but the customer receives `:112` instead.
- `app/views/payments.py:1826`, `:1895` returns signature/webhook errors to a payment callback, not a normal customer screen.
- AI health monitoring intentionally exposes diagnostic categories to administrators (`app/views/ai_health.py:29` and `app/templates/admin/ai_health/_summary.html:29`). If business staff also use this page, use plain labels such as “AI service unavailable,” “AI account access problem,” or “AI response took too long,” with technical codes in secondary details. This is a separate audience decision.
- `static/js/ai_health.js:105` compares `error.message` with an internal marker to choose fixed recovery text; it does not display the raw exception message.
- The shared 403/404/500 pages in `app/error_pages.py:8` already explain the problem and next steps. Their `HTTP {status}` label in `app/templates/errors/http_error.html:29` is secondary; changing that label is lower priority than stopping raw exceptions.
- Existing safe patterns worth keeping: `static/js/offer_editor.js:459` handles both `SyntaxError` and `TypeError`; `static/js/account_forms.js:50` handles connection/timeout uncertainty; `app/ai_text.py:30` translates provider failures; `app/payment_forms.py:134` warns users not to pay again when proof saving cannot be confirmed.
- `static/js/ai_requests.js:61`, `:114`, `:192` translates unreadable responses and uncertain network outcomes into assistant-specific feedback rather than directly rendering the browser exception. Technical server strings still need safe wording at their backend source.
- Admin gallery filtering at `app/templates/admin/gallery/admin_gallery.html:210` silently restores the table's opacity after a failed load. It does not expose a technical error, but it also does not explain that the filter results were not updated. Suggested added feedback: “We couldn't update the gallery. Your previous results are still shown. Please try again.”

The final network-call cross-check found 42 frontend files with fetch/AJAX requests. Every one is represented in this review, including the customer profile's ordinary password request, the current AI request controller, and the admin gallery's silent failure.

## Recommended discussion order

1. Agree on language and tone: simple English throughout, or Filipino/Taglish for customer errors.
2. Prioritize customer-facing raw browser errors and raw design exceptions.
3. Agree on messages for uncertain booking, review, payment, password, deletion, and chat outcomes.
4. Apply the same rules to admin screens; business staff should not need programming knowledge.
5. Clean up the remaining validation wording and any older endpoints that are still used.

No product code or behavior has been changed. The original review did not include browser failure simulations; the recheck adds controlled Report Concern probes and exact source-scan coverage. Other screens remain source-reviewed rather than individually browser-tested.
