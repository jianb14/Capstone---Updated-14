# Admin booking workspace

Open **Bookings** in the admin sidebar. The workspace has three queues:

- **Bookings:** reservations, status, event schedule, setup and approval/completion actions.
- **Design Delivery:** confirmed reservations with a positive, verified payment applied to the booking. Work is ordered by the earliest design deadline. Filter by **Needs design**, **Needs revision** or **Design sent**.
- **Change Requests:** the existing active/history review queues, quotes and payment-resolution workflow.

The Bookings tab opens with Pending selected. Choose All statuses to view the complete list; an explicit empty `status` parameter preserves that choice across reloads and pagination. Clearing filters shows all statuses; returning through the Bookings tab starts with Pending again. The KPI totals cover all dates. Search, status, event-date filters and sorting apply to the queue below them. Date boundaries are inclusive; invalid or reversed ranges show an error. Tables default to eight rows, with four as a smaller page-size option. An empty queue shows an empty state without a table header.

## Deliver a design

1. Open **Design Delivery**, then select **Send design** on the appropriate row. The same shortcut is available in Bookings.
2. Review the customer, event schedule, venue, selected setup, preferences, reference images and design deadline in the modal.
3. Choose or drop one JPG, PNG or WEBP image, optionally enter a **Message to customer**, then select **Send design**.

The customer receives an in-app notification and an automatic email through the existing Brevo backend. The email contains the order number (the booking ID), the admin's short message (or a standard message when blank), and the actual uploaded design as an attachment. There is no email button or link required to access the file. The same message is saved as the design caption. Customers can also view/download the delivered design using their existing booking details. The queue and modal update without a page reload. **Manage design** opens images already sent; reference and delivered images have a larger preview.

Email is attempted only after the upload transaction commits, using the validated upload bytes rather than downloading from storage. A failed or unconfirmed email attempt preserves the design and in-app notification; the admin sees a message to check email settings and provider delivery logs. A successful provider acceptance is not proof of inbox delivery. There are no automatic email retries; replaying a submission ID does not send another email. Sending a new/revised design sends its own attachment email. Deleting a design does not recall an email already sent. No extra email variables, package or migration is needed; use the existing configuration in `docs/email.md`.

Existing limits remain: three delivered images per booking, five MB per image and a caption of up to 255 characters. The server checks image contents as well as extension/type, and rejects images over 40 million pixels. Delete an old image to make room for a replacement. Deleting the latest applicable image can reopen the design task.

The caption shows a live character counter. Missing-image validation focuses the visible Browse Files button and scrolls only the modal body, keeping its header and footer in place. Booking details retain the venue pin and a status-colored history timeline. History shows seven entries initially; from eight entries onward, Show more / Show less expands or collapses the remaining entries without reloading.

An applied design amendment makes a previous delivery out of date. Its row becomes **Needs revision** until a newer image is delivered. If requirements change while the upload modal is open, the server requires reopening and reviewing the latest requirements before submission. Existing deadline alerts continue to work; a missed design deadline does not cancel a paid reservation.

## Async actions and safeguards

Queue tabs, search/clear, dropdown filters, date filters, page size and pagination load asynchronously. Booking/change details and design delivery use modals with independently scrolling content and visible footer actions. Browser history restores queue/modal state. If a list request fails, the previous results remain visible with an error.

Approving, declining, completing, saving a manual logistics fee, reviewing a change request, sending a design and deleting a design use POST requests with CSRF and admin authorization. Destructive or status-changing row actions ask for confirmation; declining a booking requires a selected reason. Booking declines and payment rejections offer preset reasons with optional additional details. The saved reason and any details appear in the existing customer notification and history; the server validates the choice and length before changing a status. Errors are shown below the relevant field or form, and successful mutations use the shared admin feedback toast.

Design uploads take a booking row lock, so simultaneous uploads cannot exceed the three-image limit. Each modal submission also carries a unique submission ID: retrying the same successful upload does not create another design or customer notification. No database migration is required for this workspace.

Booking detail URLs redirect to `/staff/bookings/?open_booking=<id>`; `section=design` is preserved. Payment detail URLs redirect to `/staff/payments/?open_payment=<id>`. Admin notifications use these modal links directly. AJAX requests to the detail endpoints still return modal content. Change request detail URLs redirect to the requests queue with `open_change=<id>`, including historical requests; AJAX requests return the review modal content.

## Verification

`app/test_admin_booking_workspace.py` checks queue classification, filtering, pagination, payment/state guards, image validation, AJAX responses, notifications, repeated submissions, permissions and CSRF. `app/test_booking_design_concurrency.py` checks concurrent uploads using PostgreSQL row locks.

`app/test_admin_booking_workspace_browser.py` runs with `RUN_DESIGN_BROWSER=1`. It exercises search/filter/pagination and design/change actions without reloading, browser history, request-failure recovery, both themes and desktop/mobile layouts, including modal scrolling and footer visibility. It uses local test storage/mail and a disposable test database.

Browser checks also cover row/button hover isolation, compact status badges, a real Leaflet venue marker, expandable history, upload-error focus, the caption counter, and requested-change highlights/dividers in both themes. System-generated history entries and removed authors render without requiring an account username.
