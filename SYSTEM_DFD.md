# Balloorina System Data Flow Diagram (DFD)

## Scope Used
This DFD is based on the current implemented system in this repository (`Project/app/models.py`, `Project/app/views.py`, `Project/app/urls.py`, and `Project/app/services.py`).

## System Description (Derived from Actual Code)
Balloorina is a web-based event styling platform where customers can register, verify email, log in, create bookings, upload references, save custom design canvases, submit payments (manual GCash and PayMongo checkout), send concerns, write reviews, and chat with an AI assistant. Admin/Staff users manage bookings, payments, users, reviews, concerns, site content, gallery, and design canvas assets. The system stores operational records in database models and sends/receives data through external providers (Email SMTP, PayMongo, AI provider).

---

## Context Diagram (Level 0 DFD)

### A. Text-Based Structure

#### External Entities
- `E1 Customer`
- `E2 Admin/Staff`
- `E3 Email Service (SMTP)`
- `E4 PayMongo Payment Gateway`
- `E5 AI Provider (Hugging Face Inference API)`

#### Process
- `P0 Balloorina Event Booking and Design Management System`

#### Data Flows
- `E1 -> P0`: registration data, login credentials, booking details, design canvas data, payment details, review data, concern tickets, chat messages
- `P0 -> E1`: account verification status, booking status updates, payment status, notifications, saved design records, chat responses
- `E2 -> P0`: booking decisions, payment verification/rejection, user/content/catalog management updates, concern/review moderation actions
- `P0 -> E2`: booking/payment queues, dashboard analytics, concern/review lists, audit logs, admin notifications
- `P0 -> E3`: verification email and password reset email requests
- `E3 -> P0`: email delivery outcome (success/failure)
- `P0 -> E4`: checkout session requests, payment status retrieval, webhook verification/processing
- `E4 -> P0`: checkout URLs, payment status payloads, webhook events
- `P0 -> E5`: chat prompts with system/user context
- `E5 -> P0`: AI response content

### B. Drawable Version (Mermaid)
```mermaid
flowchart LR
    E1[Customer]
    E2[Admin/Staff]
    E3[Email Service SMTP]
    E4[PayMongo Gateway]
    E5[AI Provider Hugging Face]

    P0((P0: Balloorina System))

    E1 -->|Register/Login, Bookings, Payments, Reviews, Concerns, Chat, Designs| P0
    P0 -->|Status updates, Notifications, AI replies, Account results| E1

    E2 -->|Approvals, Verifications, Content and Catalog Updates| P0
    P0 -->|Admin queues, Analytics, Logs, Notifications| E2

    P0 -->|Verification and Reset Emails| E3
    E3 -->|Delivery Result| P0

    P0 -->|Checkout Requests and Payment Queries| E4
    E4 -->|Checkout URL, Payment Status, Webhooks| P0

    P0 -->|Prompt + Context| E5
    E5 -->|AI Response| P0
```

---

## Level 1 DFD

### A. Text-Based Structure

#### External Entities
- `E1 Customer`
- `E2 Admin/Staff`
- `E3 Email Service (SMTP)`
- `E4 PayMongo Payment Gateway`
- `E5 AI Provider (Hugging Face Inference API)`

#### Data Stores
- `D1 User Accounts` (`User`)
- `D2 Booking Records` (`Booking`, `BookingImage`, `Design`)
- `D3 Payment Records` (`Payment`, `GCashConfig`)
- `D4 Feedback and Concerns` (`Review`, `ReviewImage`, `ConcernTicket`)
- `D5 Design Workspace` (`UserDesign`, `CanvasCategory`, `CanvasLabel`, `CanvasAsset`)
- `D6 Content and Catalog` (`Package`, `AddOn`, `AdditionalOnly`, `Service`, `GalleryCategory`, `GalleryImage`, `HomeContent`, `HomeFeatureItem`, `ServiceContent`, `AboutContent`, `AboutValueItem`, `ServiceChargeConfig`)
- `D7 Chat and Moderation` (`ChatSession`, `ChatMessage`, `ChatModerationState`, `ChatModerationEvent`)
- `D8 Notifications and Audit` (`Notification`, `AdminNotification`, `AuditLog`)

#### Processes and Flows

1. `P1 Account and Access Management`
- Inputs: registration form, login credentials, forgot/reset password request (`E1`)
- Reads/Writes: `D1`, `D8`
- External: sends verification/reset emails to `E3`
- Outputs: authentication result, email verification status, login session state (`E1`)

2. `P2 Booking and Scheduling Management`
- Inputs: booking form, schedule details, reference images, booking updates/deletes (`E1`), booking approval/deny/confirm/complete actions (`E2`)
- Reads/Writes: `D2`, `D8`
- Outputs: booking decisions and schedule conflict outcomes to `E1` and `E2`, notifications written to `D8`

3. `P3 Payment Processing and Verification`
- Inputs: manual GCash payment submission (`E1`), PayMongo checkout initiation (`E1`), payment verify/reject actions (`E2`)
- Reads/Writes: `D2`, `D3`, `D8`
- External: checkout/session/status/webhook exchange with `E4`
- Outputs: payment and booking payment-status updates to `E1` and admin payment queues to `E2`

4. `P4 Reviews and Concern Ticket Handling`
- Inputs: review submission/likes/edits/deletes, concern ticket submission (`E1`), testimonial toggle and concern status updates (`E2`)
- Reads/Writes: `D2`, `D4`, `D8`
- Outputs: published feedback views for customers, moderation/work queues for admins

5. `P5 Design Canvas and User Design Management`
- Inputs: canvas JSON, thumbnail, design save/rename/delete requests, package-linked design selection (`E1`), canvas asset/category/label administration (`E2`)
- Reads/Writes: `D5`, `D6`, `D8`, and design references in `D2`
- Outputs: user design library, canvas asset feeds, booking-linked design artifacts

6. `P6 Content, Catalog, and Media Administration`
- Inputs: package/add-on/additional/service/home/about/gallery/content updates (`E2`)
- Reads/Writes: `D6`, `D8`
- Outputs: updated public-facing content and catalog data consumed by customers (`E1`)

7. `P7 AI Chat and Moderation`
- Inputs: chat messages and session requests (`E1`)
- Reads/Writes: `D7`, context reads from `D1/D2/D3/D4/D5/D6`, audit writes to `D8`
- External: sends prompts/context to `E5`, receives AI replies
- Outputs: moderated AI replies, warnings, temporary ban enforcement responses (`E1`)

8. `P8 Notification and Reporting Services`
- Inputs: system events from `P1-P7`, admin analytics/report requests (`E2`)
- Reads/Writes: `D8` and aggregated reads from `D2/D3/D4`
- Outputs: customer/admin notification feeds, dashboard analytics, exported reports

### B. Drawable Version (Mermaid)
```mermaid
flowchart TB
    %% External Entities
    E1[Customer]
    E2[Admin/Staff]
    E3[Email Service SMTP]
    E4[PayMongo Gateway]
    E5[AI Provider Hugging Face]

    %% Processes
    P1((P1 Account and Access))
    P2((P2 Booking and Scheduling))
    P3((P3 Payment Processing))
    P4((P4 Reviews and Concerns))
    P5((P5 Design Canvas Management))
    P6((P6 Content and Catalog Admin))
    P7((P7 AI Chat and Moderation))
    P8((P8 Notification and Reporting))

    %% Data Stores
    D1[(D1 User Accounts)]
    D2[(D2 Booking Records)]
    D3[(D3 Payment Records)]
    D4[(D4 Feedback and Concerns)]
    D5[(D5 Design Workspace)]
    D6[(D6 Content and Catalog)]
    D7[(D7 Chat and Moderation)]
    D8[(D8 Notifications and Audit)]

    %% P1
    E1 -->|Register/Login/Reset| P1
    P1 -->|Auth/Verification Result| E1
    P1 -->|Verification/Reset Email| E3
    E3 -->|Delivery Result| P1
    P1 <--> D1
    P1 --> D8

    %% P2
    E1 -->|Booking Data and Updates| P2
    E2 -->|Approve/Deny/Confirm/Complete| P2
    P2 -->|Booking Status and Schedule Outcome| E1
    P2 -->|Booking Queue and Details| E2
    P2 <--> D2
    P2 --> D8

    %% P3
    E1 -->|GCash Submit/PayMongo Checkout Request| P3
    E2 -->|Verify/Reject Payment| P3
    P3 -->|Payment Status| E1
    P3 -->|Payment Queue| E2
    P3 <--> D2
    P3 <--> D3
    P3 --> D8
    P3 -->|Checkout/Status Request| E4
    E4 -->|Checkout URL/Webhook/Status| P3

    %% P4
    E1 -->|Reviews and Concern Tickets| P4
    E2 -->|Review and Concern Actions| P4
    P4 -->|Feedback and Concern Updates| E1
    P4 -->|Moderation Queues| E2
    P4 <--> D2
    P4 <--> D4
    P4 --> D8

    %% P5
    E1 -->|Save/Edit/Delete Design| P5
    E2 -->|Canvas Asset Admin Updates| P5
    P5 -->|Design Library and Canvas Assets| E1
    P5 <--> D5
    P5 <--> D6
    P5 --> D2
    P5 --> D8

    %% P6
    E2 -->|Content/Catalog CRUD| P6
    P6 -->|Updated Public Content| E1
    P6 <--> D6
    P6 --> D8

    %% P7
    E1 -->|Chat Message| P7
    P7 -->|AI Reply/Warning/Ban Notice| E1
    P7 <--> D7
    P7 -->|Prompt + Context| E5
    E5 -->|AI Response| P7
    P7 --> D8

    %% P8
    E2 -->|Analytics/Report Request| P8
    P8 -->|Dashboard and Reports| E2
    P8 <--> D8
    P8 -->|Notification Feed| E1
    P8 -->|Admin Notification Feed| E2
    P8 -->|Aggregated Reads| D2
    P8 -->|Aggregated Reads| D3
    P8 -->|Aggregated Reads| D4
```

---

## Notes for Accuracy
- Booking approval flow in code transitions `pending -> pending_payment`, then payment verification transitions booking to `confirmed`.
- Payment supports both manual GCash submission and PayMongo checkout/webhook ingestion.
- AI chat includes moderation state/events and may return warning/ban payloads without saving normal chat messages.
- Admin and Staff share many management pages, while some actions (for example concern status update endpoint) are restricted to `admin` role.
