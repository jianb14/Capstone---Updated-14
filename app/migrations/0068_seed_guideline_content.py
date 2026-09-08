# Seed migration: copies the previously hard-coded Guidelines / Terms / Privacy
# content into the database so it appears pre-filled in the admin manager.
from django.db import migrations

GUIDELINES_INTRO = (
    "These guidelines explain how booking, payment, and status updates work "
    "inside the Balloorina system."
)

GUIDELINES_ITEMS = [
    ("Complete and Accurate Booking Details", "Make sure your event date, time, location, package selection, and special requests are correct before submitting your booking request."),
    ("Booking Status Flow", "Booking requests are reviewed by admin. Your booking status may update as Pending, Pending Payment, Confirmed, Completed, or Expired based on verification and event timeline."),
    ("Required Initial Payment", "For bookings that proceed to payment, the system may require an initial payment amount before full confirmation, based on current payment settings."),
    ("Payment Verification", "Submitted payments are subject to admin verification. While payment is pending verification, please avoid sending duplicate payments for the same booking."),
    ("Non-Refundable Payment Notice", "Upon checkout, you are required to confirm that completed payments are non-refundable and non-cancellable, except where required by law."),
    ("Track Updates in Your Account", "Always monitor your booking and payment records in My Bookings and My Payments to stay updated on status changes and admin actions."),
    ("Edits and Requests", "If you need to update booking details, use the available system actions as early as possible. Late changes may be limited depending on booking status."),
    ("Account Responsibility", "Keep your profile information updated and secure your account credentials. Actions submitted through your account are treated as your confirmed requests."),
    ("Need Help", "For booking or payment concerns, contact Balloorina support through the channels provided on the website so your concern can be reviewed promptly."),
]

TERMS_INTRO = (
    "Please review these guidelines before your event to keep the setup "
    "smooth, safe, and on schedule."
)

TERMS_ITEMS = [
    ("Balloorina Event Styling", "By proceeding with your booking and settling the required reservation fee, you (the Client) agree to comply with the following service terms established by Balloorina."),
    ("Rental Policy", "All props, backdrops, and decorative materials provided are the exclusive property of Balloorina and are for rental use only. Clients are strictly prohibited from removing, retaining, or transporting any materials from the venue after the event."),
    ("Care and Liability", "Clients are responsible for the safety of all props and backdrops during the event. Any damage incurred whether by the client, guests, or venue conditions will be subject to additional charges based on the repair or replacement cost of the item."),
    ("Design Consistency", "To ensure the high-quality output Balloorina is known for, we adhere strictly to the approved mock-up. Once the decor and balloons are arranged, no modifications or rearrangements are permitted. Furthermore, the backdrop location is finalized during the planning phase. ensure the designated spot is ready to maintain structural stability."),
    ("Workspace Requirements", "Our styling team requires a professional environment to perform their work. Please allow our stylists to work without interference or adjustments by the client or guests. If guests arrive early, we appreciate your cooperation in providing our team the space needed to complete the setup without distraction."),
    ("Scheduling and Ingress", "Setup duration begins only once all materials have been successfully brought into the venue (ingress). A basic backdrop setup requires approximately two (2) hours. Please note that elaborate designs may require additional time, which will be communicated during the planning stage."),
    ("Booking and Payment Policy", "A date is considered \"Locked-in\" only after the 100% reservation fee has been received and verified. This serves as a reservation fee and not a partial downpayment. Given the nature of event styling and resource allocation, all reservation fees are strictly non-refundable."),
]

PRIVACY_INTRO = (
    "We respect your privacy and protect your personal information in line with the"
)

PRIVACY_ITEMS = [
    ("Information We Collect", "We may collect your name, email address, mobile number, event details, venue information, payment details, and account activity when you book or communicate with us."),
    ("How We Use Your Data", "Your information is used to process bookings, prepare event proposals, provide customer support, verify payments, and send booking-related updates."),
    ("Data Sharing", "We do not sell your personal data. We only share information with trusted service providers (such as payment processors) when needed to complete your transaction."),
    ("Data Protection", "We use reasonable administrative, technical, and physical safeguards to protect your data from unauthorized access, loss, or misuse."),
    ("Data Retention", "We keep your information only as long as necessary for business operations, legal compliance, and record-keeping, then securely delete or anonymize it."),
    ("Your Rights", "You may request access, correction, or deletion of your personal data, or raise concerns about how your data is handled, subject to applicable laws."),
    ("Contact for Privacy Concerns", "For any data privacy requests, please email us at balloorina.ph@gmail.com."),
]


def seed_policy(apps, page_key, title, intro, items, attachment_label="", attachment_url=""):
    GuidelinePageContent = apps.get_model("app", "GuidelinePageContent")
    GuidelineItem = apps.get_model("app", "GuidelineItem")

    page, created = GuidelinePageContent.objects.get_or_create(
        page_key=page_key,
        defaults={
            "title": title,
            "intro": intro,
            "attachment_label": attachment_label,
            "attachment_url": attachment_url,
        },
    )
    if not created:
        return
    if not page.items.exists():
        for order, (heading, body) in enumerate(items, start=1):
            GuidelineItem.objects.create(
                page_content=page,
                heading=heading,
                body=body,
                display_order=order,
                is_active=True,
            )


def seed_all(apps, schema_editor):
    seed_policy(apps, "guidelines", "Booking Guidelines", GUIDELINES_INTRO, GUIDELINES_ITEMS)
    seed_policy(apps, "terms", "Terms & Conditions", TERMS_INTRO, TERMS_ITEMS)
    seed_policy(
        apps,
        "privacy",
        "Privacy Policy",
        PRIVACY_INTRO,
        PRIVACY_ITEMS,
        attachment_label="Data Privacy Act of 2012 (Republic Act No. 10173).",
        attachment_url="/static/docs/DataPrivacy.pdf",
    )


def unseed_all(apps, schema_editor):
    GuidelinePageContent = apps.get_model("app", "GuidelinePageContent")
    GuidelinePageContent.objects.filter(
        page_key__in=["guidelines", "terms", "privacy"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0067_guidelinepagecontent_guidelineitem'),
    ]

    operations = [
        migrations.RunPython(seed_all, unseed_all),
    ]
