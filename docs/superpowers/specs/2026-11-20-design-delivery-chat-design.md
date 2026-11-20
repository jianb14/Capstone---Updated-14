# Design delivery in Admin Chat

Approved by the user on 2026-11-20 after reviewing the chat proposal.

Sending a design must also post one linked delivery card in the customer's existing Admin Support conversation, creating or reopening that conversation when necessary. The card contains the booking number, a friendly standard message, the optional existing admin caption, the design preview, and a View booking link. Revised designs say “Updated design ready”. Customers reply through the existing conversation.

## Approaches

Ordinary text and image messages are smaller but lose the clear booking context. The approved approach is a single design delivery card linked to the existing delivery, using the shared support chat renderer and existing styling.

## Constraints

- Preserve booking design views, verified-payment gates, three-image limit, revision validation, and design email.
- Save delivery and chat message atomically; an existing submission replay cannot duplicate either or send extra email.
- Reuse the uploaded design file rather than create a second attachment. Deletion leaves a readable “This design was removed” card without an image URL.
- Keep booking links authorized for the viewer and retain normal chat read receipts, replies, pins and reactions.
- No new approval or revision workflow, dependencies, or historical message backfill.

## Implementation choices

Chat messages have a nullable one-to-one delivery reference, a nullable booking reference, and a revision flag. The booking reference identifies a removed delivery card after its delivery reference is cleared. Standard text and optional caption are captured in the message when sent. Delivery cards cannot be edited or deleted as ordinary chat messages, so the record cannot diverge from the delivered design. Both chat mutation endpoints enforce this restriction, including for removed-design history cards. Booking design replacement remains managed through the booking workspace.
