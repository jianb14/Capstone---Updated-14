# Customer support chat

The admin inbox (`/staff/chat/`) and the customer's floating Admin Support panel use the same scoped interface and controller. The AI assistant is separate.

- Conversations, inbox filters/search, earlier messages, sending, edits, deletes, reactions, pins, shared photos and closing/reopening conversations use JSON requests without page reloads.
- The admin's Full screen button expands the same inbox into a viewport-filling modal workspace. Exit full screen or Escape returns to the page, preserving the conversation, draft/attachments and reading position. Nested dialogs and message menus close before Escape exits the workspace; background navigation cannot receive keyboard focus while expanded. This is an in-page view, not the browser's F11 mode, and does not persist after a reload.
- The inbox searches customer identity and the full message history. Message search searches the selected conversation. History loads 50 messages at a time; shared media shows the latest 100 images.
- Polling runs every 4.5 seconds while open, every 15 seconds for the closed customer badge, and pauses in hidden tabs. Polls never submit or clear drafts. Older messages visible in the viewport also receive updated edits, deletions and reactions.
- Reading is recorded separately from fetching. Only messages up to the last displayed message are marked read while the conversation is focused and scrolled to the bottom. Searching or viewing a dialog does not mark the remaining conversation read.
- Opening the customer widget does not create an empty conversation. The first successful send creates or restores their support conversation. Sending to a closed conversation reopens it.
- Each send supports 4,000 characters and up to four JPG/PNG/GIF/WEBP images, each at most 5 MB and 40 megapixels. The server verifies actual image content before saving the batch.
- A UUID submission receipt prevents duplicate messages after a lost response and retry (receipts retained for 24 hours). A retry with changed content must use a new token. Sending failures keep the draft and selected photos. Drafts are held in memory per conversation, not persisted to browser storage.
- Only participants and administrators can access support conversations; customers cannot edit another sender's messages or access AI conversations through these endpoints. The existing chat send rate budget applies.
- Administrators receive an inbox notification for a new support conversation. Offline customers receive an in-app chat notification and a best-effort email for admin replies. Mail failure does not lose a saved message. The customer's chat notification link opens the support panel.

No database migration is needed; deduplication reuses the existing `SubmissionReceipt` table. Routes are in `app/views/support_chat.py`, templates in `components/support_chat_*`, and styling/controller in `static/css/support_chat.css` and `static/js/support_chat.js`.

Verification: `app.test_support_chat` exercises isolation, validation, retries, receipts, notification failures, read positions, reactions/pins and pagination. Set `RUN_SUPPORT_CHAT_BROWSER=1` to run `app.test_support_chat_browser` with two signed-in Chrome contexts, themes and mobile layouts. Use a disposable test database and temporary media storage.
