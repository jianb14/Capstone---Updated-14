import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator


# -----------------------------
# 1️⃣ User
# -----------------------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('admin', 'Admin'),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email_verified = models.BooleanField(
        default=False,
        help_text="New accounts must verify their email before logging in.",
    )

    def __str__(self):
        return f"{self.username} ({self.role})"


class EmailOTPChallenge(models.Model):
    """Session-bound email verification/recovery; never stores the plaintext code."""
    SIGNUP = 'signup'
    RESET = 'reset'
    PURPOSES = ((SIGNUP, 'Account verification'), (RESET, 'Password recovery'))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_otp_challenges')
    purpose = models.CharField(max_length=10, choices=PURPOSES)
    email_snapshot = models.EmailField(help_text='Email address that received this challenge.')
    code_digest = models.CharField(max_length=64, blank=True, default='')
    session_digest = models.CharField(max_length=64)
    password_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    grant_expires_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=['user', 'purpose', 'consumed_at'], name='email_otp_user_purpose_idx')]


class Booking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('pending_payment', 'Pending Payment'),
        ('confirmed', 'Confirmed'),
        ('cancel_requested', 'Cancel Requested'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('partial', 'Partial Payment'),
        ('paid', 'Paid'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    event_date = models.DateField()
    event_time = models.TimeField(null=True, blank=True)
    event_type = models.CharField(max_length=50, default='')
    event_location = models.CharField(max_length=255)
    package_type = models.CharField(max_length=500, blank=True, null=True)
    special_requests = models.TextField(blank=True, null=True)
    reference_image = models.ImageField(upload_to='booking_references/', blank=True, null=True)

    # 📍 Step 3 — Location (interactive map). Text location stays required;
    # coords/landmark are optional so booking never blocks when the map fails.
    event_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Latitude pin from the Step 3 location map.',
    )
    event_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Longitude pin from the Step 3 location map.',
    )
    # 🚚 Logistics snapshot — kinukuha sa create/edit at hindi na binabago
    # pag nagbago ang admin config (para stable ang binayaran ng customer).
    logistics_distance_km = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Straight-line km (Haversine) from shop to venue pin at booking time.',
    )
    logistics_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Computed logistics fee (base + distance) stored at booking time.',
    )
    logistics_fee_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Admin manual logistics fee — overrides the computed fee when set.',
    )

    # ⏱️ Duration & overtime snapshot — kinukuha sa create/edit at hindi na
    # binabago pag nagbago ang SiteSettings overtime config mamaya.
    event_end_date = models.DateField(
        null=True, blank=True,
        help_text='Actual end date (next day kapag umabot ng midnight / overnight).',
    )
    event_end_time = models.TimeField(
        null=True, blank=True,
        help_text='End time of the event. Falls back to the legacy "(End Time: HH:MM)" tag sa special_requests kapag blank.',
    )
    duration_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Total booked duration in minutes (start → end, +1 day kapag overnight).',
    )
    overtime_hours = models.PositiveIntegerField(
        default=0,
        help_text='Billable overtime hours beyond the included hours.',
    )
    overtime_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Overtime fee charged (overtime_hours × SiteSettings.booking_overtime_rate at booking time).',
    )
    fee_policy_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text='Logistics base, notes, included hours and overtime rate used for the saved booking quote.',
    )

    venue_landmark = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Nearest landmark / floor / gate hint shown to the styling crew.',
    )

    # 🎨 Step 4 — Design Preferences (all optional; Tier 1 scope).
    design_theme = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Chosen theme/decor style (e.g. Spiderman, Princess) or custom text.',
    )
    color_palette = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Preferred color palette (preset swatches or custom colors).',
    )
    motto_text = models.CharField(
        max_length=150, blank=True, default='',
        help_text='Text requested on the backdrop/signage (e.g. "Happy 18th, Maria!").',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # ✅ NEW FIELDS
    edit_requested = models.BooleanField(default=False)
    edit_allowed = models.BooleanField(default=False)
    edit_request_reason = models.TextField(blank=True, null=True)
    cancel_request_reason = models.TextField(blank=True, null=True)
    admin_denial_reason = models.TextField(blank=True, null=True)
    edit_original_snapshot = models.JSONField(blank=True, null=True)
    admin_notified = models.BooleanField(default=False)
    admin_notif_hidden = models.BooleanField(default=False)

    payment_status = models.CharField(max_length=15, choices=PAYMENT_STATUS_CHOICES, default='pending')
    approved_at = models.DateTimeField(null=True, blank=True)
    payment_due_at = models.DateTimeField(null=True, blank=True, help_text='Saved initial payment deadline; never later than the event start.')
    design_due_at = models.DateTimeField(null=True, blank=True, help_text='Saved deadline for the team to deliver the event design.')

    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def can_edit(self):
        return self.status == 'pending'

    def __str__(self):
        return f"Booking {self.id} by {self.user.username}"


class BookingChangeRequest(models.Model):
    ACTIVE_STATUSES = ('pending_review', 'quoted', 'awaiting_payment', 'manual_review')
    STATUS_CHOICES = tuple((key, label) for key, label in (
        ('pending_review', 'Awaiting team review'), ('quoted', 'Quote ready for your approval'),
        ('awaiting_payment', 'Awaiting additional payment'), ('manual_review', 'Needs manual review'),
        ('applied', 'Changes applied'), ('rejected', 'Request declined'),
        ('withdrawn', 'Request withdrawn'), ('expired', 'Quote expired')))
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='change_requests')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='pending_review')
    reason = models.TextField()
    original = models.JSONField(default=dict)
    proposed = models.JSONField(default=dict)
    quote = models.JSONField(default=dict)
    admin_notes = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='booking_changes_reviewed')
    downgrade_acknowledged = models.BooleanField(default=False)
    original_total = models.DecimalField(max_digits=10, decimal_places=2)
    quoted_total = models.DecimalField(max_digits=10, decimal_places=2)
    additional_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hold_start = models.DateTimeField(null=True, blank=True)
    hold_end = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['booking'], condition=models.Q(status__in=('pending_review', 'quoted', 'awaiting_payment', 'manual_review')), name='one_active_booking_change')]


class BookingChangeImage(models.Model):
    change_request = models.ForeignKey(BookingChangeRequest, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='booking_change_references/')


class BookingImage(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='booking_references/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for Booking {self.booking.id}"


class BookingDeadlineNotice(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='deadline_notices')
    key = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['booking', 'key'], name='unique_booking_deadline_notice')]


# -----------------------------
# 2️⃣a Booking Design Delivery (admin → client backdrop design)
# -----------------------------
class BookingDesignDelivery(models.Model):
    """Backdrop/mock-up design na ina-upload ng admin PAGKATAPOS ng bayad
    (status == 'confirmed'). Ito ang actual na susundin sa event — magkaiba
    sa BookingImage (reference mula sa client) at sa Design (canvas asset).
    """
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name='design_deliveries'
    )
    image = models.ImageField(
        upload_to='booking_design_deliveries/',
        help_text='Backdrop design delivered to the customer (JPG/PNG/WEBP, max 5MB).',
    )
    caption = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='design_deliveries_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"Design delivery for Booking {self.booking.id}"


# -----------------------------
# 2️⃣b Booking Status Log (status history timeline)
# -----------------------------
class BookingStatusLog(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='status_logs')
    old_status = models.CharField(max_length=20, blank=True, default='')
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='booking_status_changes')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Booking Status Log'
        verbose_name_plural = 'Booking Status Logs'

    @property
    def new_status_label(self):
        """Human-readable new status (e.g. 'pending_payment' -> 'Pending Payment')."""
        return (self.new_status or "").replace("_", " ").title()

    @property
    def old_status_label(self):
        """Human-readable old status (e.g. 'pending_payment' -> 'Pending Payment')."""
        return (self.old_status or "").replace("_", " ").title()

    def __str__(self):
        return f"Booking #{self.booking_id}: {self.old_status or '—'} → {self.new_status}"


# -----------------------------
# 2️⃣c Blocked Date (blockout dates — dates clients cannot book)
# -----------------------------
class BlockedDate(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blocked_dates'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'Blocked Date'
        verbose_name_plural = 'Blocked Dates'

    def __str__(self):
        return f"{self.date.strftime('%B %d, %Y')} — {self.reason or 'Unavailable'}"


# -----------------------------
# 2️⃣d Site Settings (singleton — central admin configuration)
# -----------------------------
class SiteSettings(models.Model):
    max_saved_designs = models.PositiveIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(2147483647)],
        help_text='Maximum saved designs per customer, including drafts and ready-to-book designs.',
    )
    site_name = models.CharField(max_length=150, default='Balloorina')
    contact_email = models.CharField(max_length=255, blank=True, default='')
    contact_phone = models.CharField(max_length=50, blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    facebook_link = models.URLField(blank=True, default='')
    instagram_link = models.URLField(blank=True, default='')
    booking_lead_time_days = models.PositiveIntegerField(
        default=0,
        help_text='Minimum number of days between today and a booking date. 0 = no lead time requirement.',
    )
    booking_payment_window_hours = models.PositiveIntegerField(default=24, help_text='Initial payment window after approval, capped at event start.')
    booking_design_lead_hours = models.PositiveIntegerField(default=24, help_text='Hours before the event when a missing design becomes urgent.')
    booking_change_cutoff_hours = models.PositiveIntegerField(default=48, help_text='Minimum hours before the event for a customer change request.')
    admin_emails_for_notifications = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Comma-separated email addresses that receive admin alert emails. Leave empty to disable.',
    )
    email_notifications_enabled = models.BooleanField(
        default=True,
        help_text='Send email alerts to admin when new bookings, payments, or concerns come in.',
    )

    # ⏱️ Booking duration & overtime policy (admin-configurable).
    booking_min_duration_hours = models.PositiveIntegerField(
        default=2,
        help_text='Minimum booking duration in hours (client cannot book shorter than this).',
    )
    booking_included_hours = models.PositiveIntegerField(
        default=3,
        help_text='Hours included in the base package price. Overtime starts after this.',
    )
    booking_overtime_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=500,
        help_text='Overtime charge per hour (or fraction) beyond the included hours.',
    )
    booking_max_duration_hours = models.PositiveIntegerField(
        default=24,
        help_text='Maximum booking duration in hours (allows overnight / 24-hour bookings).',
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='site_settings_updates'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'
        constraints = [models.CheckConstraint(check=models.Q(max_saved_designs__gte=1), name='saved_design_limit_at_least_one')]

    def __str__(self):
        return f"Site Settings ({self.site_name})"

    @classmethod
    def load(cls):
        """Singleton loader — always returns exactly one settings row."""
        settings_obj = cls.objects.first()
        if settings_obj is None:
            settings_obj = cls.objects.create()
        return settings_obj

    def admin_notification_emails(self):
        """Return the parsed list of admin alert emails."""
        if not self.email_notifications_enabled:
            return []
        return [
            email.strip()
            for email in (self.admin_emails_for_notifications or "").split(",")
            if email.strip()
        ]



# -----------------------------
# 3️⃣ Design
# -----------------------------
class Design(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('finalized', 'Finalized'),
    )

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='designs')
    style = models.CharField(max_length=50)
    color_palette = models.CharField(max_length=50)
    image = models.ImageField(upload_to='designs/')
    generated_by_ai = models.BooleanField(default=False)
    price_estimate = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Design {self.id} for Booking {self.booking.id}"


# -----------------------------
# 4️⃣ Payment
# -----------------------------
class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = (
        ('gcash', 'GCash'),
        ('card', 'Card'),
        ('paypal', 'PayPal'),
        ('paymongo_card', 'PayMongo Card'),
        ('paymongo_gcash', 'PayMongo GCash'),
        ('paymongo_grabpay', 'PayMongo GrabPay'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    )

    PAYMENT_TYPE_CHOICES = (
        ('downpayment', 'Downpayment'),
        ('full', 'Full Payment'),
        ('balance', 'Balance'),
        ('change_balance', 'Booking change payment'),
    )

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    change_request = models.ForeignKey('BookingChangeRequest', on_delete=models.RESTRICT, null=True, blank=True, related_name='payments')
    applied_to_booking = models.BooleanField(default=True, help_text='False for change payments until the approved change is applied.')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='full')
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='pending')
    transaction_ref = models.CharField(max_length=100, unique=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(blank=True, null=True, help_text='When manual proof was submitted or a successful provider payment was received; not checkout creation.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)
    gcash_reference_number = models.CharField(max_length=100, blank=True, default='')
    gcash_sender_name = models.CharField(max_length=255, blank=True, default='')
    receipt_image = models.ImageField(upload_to='payment_receipts/', blank=True, null=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='verified_payments')
    admin_notified = models.BooleanField(default=False)
    
    # PayMongo specific fields
    paymongo_checkout_session_id = models.CharField(max_length=100, blank=True, default='')
    paymongo_payment_id = models.CharField(max_length=100, blank=True, default='')
    paymongo_contact_number = models.CharField(max_length=30, blank=True, default='')
    paymongo_checkout_url = models.URLField(blank=True, default='')

    def __str__(self):
        return f"Payment {self.id} for Booking {self.booking.id}"


# -----------------------------
# 5️⃣ Review
# -----------------------------
class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(User, related_name='liked_reviews', blank=True)
    is_testimonial = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    admin_notified = models.BooleanField(default=False)

    def total_likes(self):
        return self.likes.count()

    def __str__(self):
        return f"Review {self.id} by {self.user.username}"


class ReviewImage(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='review_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for Review {self.review.id}"


class ReviewReply(models.Model):
    """Official admin response to a customer review, shown publicly."""
    review = models.OneToOneField(Review, on_delete=models.CASCADE, related_name='reply')
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='review_replies')
    reply_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Review Reply'
        verbose_name_plural = 'Review Replies'

    def __str__(self):
        return f"Reply to Review {self.review_id} by {self.admin.username if self.admin else 'Admin'}"


# -----------------------------
# 6️⃣ ChatSession & ChatMessage
# -----------------------------
class ChatSession(models.Model):
    STATUS_CHOICES = (
        ('ai', 'AI Bot'),
        ('pending_admin', 'Pending Admin Handoff'),
        ('active_admin', 'Active with Admin'),
        ('closed', 'Closed'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ai')
    is_admin_support = models.BooleanField(default=False, db_index=True)
    assigned_admin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='assigned_chats',
        null=True,
        blank=True,
    )
    last_client_message_at = models.DateTimeField(null=True, blank=True)
    admin_last_read_at = models.DateTimeField(null=True, blank=True)
    client_typing_until = models.DateTimeField(null=True, blank=True)
    admin_typing_until = models.DateTimeField(null=True, blank=True)
    client_last_active_at = models.DateTimeField(null=True, blank=True)
    admin_last_active_at = models.DateTimeField(null=True, blank=True)
    design_brief = models.JSONField(default=dict, blank=True)
    design_brief_version = models.PositiveIntegerField(default=0)

    @property
    def has_unread_for_admin(self):
        if not self.last_client_message_at:
            return False
        if not self.admin_last_read_at:
            return True
        return self.last_client_message_at > self.admin_last_read_at

    def __str__(self):
        return f"{self.title} - {self.user.username} ({self.get_status_display()})"

class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    message = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='chat_attachments/%Y/%m/', null=True, blank=True)
    image_original_name = models.CharField(max_length=255, blank=True, default='')
    is_flagged = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )
    # Pinned messages (Messenger-style) — either side (client or admin) can
    # pin a message so both instantly see the important ones.
    is_pinned = models.BooleanField(default=False, db_index=True)
    pinned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="pinned_chat_messages",
        null=True,
        blank=True,
    )
    pinned_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_from_admin(self):
        return (
            getattr(self.sender, 'role', None) in ['admin', 'staff']
            or getattr(self.sender, 'is_superuser', False)
        )

    def __str__(self):
        return f"Message {self.id} from {self.sender.username} to {self.receiver.username}"


class MessageReaction(models.Model):
    message = models.ForeignKey(
        ChatMessage, on_delete=models.CASCADE, related_name="reactions"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_reactions")
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user", "emoji")


class AiRequest(models.Model):
    """Durable AI work, keyed by a customer-generated idempotency UUID."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_requests')
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='ai_requests', null=True)
    user_message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, related_name='ai_requests')
    assistant_message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, related_name='ai_responses')
    retry_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='retries')
    reference = models.ForeignKey('AiGeneratedImage', on_delete=models.SET_NULL, null=True, blank=True, related_name='revisions')
    fingerprint = models.CharField(max_length=64)
    input_text = models.TextField()
    kind = models.CharField(max_length=16, default='advice')
    state = models.CharField(max_length=16, default='queued', db_index=True,
        choices=[(value, value.title()) for value in ('queued', 'running', 'succeeded', 'failed')])
    stage = models.CharField(max_length=32, default='queued')
    partial_text = models.TextField(blank=True)
    result = models.JSONField(default=dict)
    plan = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    seed = models.PositiveBigIntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    provider_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user'], condition=models.Q(state__in=['queued', 'running']),
                                                name='one_active_ai_request_per_user')]
        indexes = [models.Index(fields=['state', 'created_at'], name='ai_request_queue_idx')]


class AiGeneratedImage(models.Model):
    """An owned image artifact; revisions read this file, never a client-supplied URL."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(AiRequest, on_delete=models.CASCADE, related_name='images')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    image = models.ImageField(upload_to='ai_generated/')
    prompt = models.TextField()
    seed = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class AiImageFeedback(models.Model):
    """Like/dislike feedback on AI-generated design images from the chat."""

    RATING_CHOICES = (
        (1, "Like"),
        (-1, "Dislike"),
    )

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_image_feedback"
    )
    image_url = models.CharField(max_length=500)
    prompt = models.TextField(blank=True, default="")
    rating = models.SmallIntegerField(choices=RATING_CHOICES, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "image_url")
        ordering = ["-created_at"]

    def __str__(self):
        feeling = "liked" if self.rating > 0 else "disliked"
        return f"{self.user.username} {feeling} {self.image_url[:40]}"

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji}"


class ChatNotification(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="chat_notifications"
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Chat notification for {self.user.username}: {self.message[:40]}"


class QuickReply(models.Model):
    text = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text[:50]


class ChatModerationState(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_moderation_state')
    banned_until = models.DateTimeField(blank=True, null=True, db_index=True)
    last_ban_ended_at = models.DateTimeField(blank=True, null=True)
    total_violations = models.PositiveIntegerField(default=0)
    total_bans = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Chat Moderation State'
        verbose_name_plural = 'Chat Moderation States'

    def __str__(self):
        return f"Moderation state for {self.user.username}"


class ChatModerationEvent(models.Model):
    VIOLATION_TYPE_CHOICES = (
        ('profanity', 'Profanity'),
        ('toxicity', 'Toxicity'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_moderation_events')
    violation_type = models.CharField(max_length=20, choices=VIOLATION_TYPE_CHOICES, default='profanity')
    matched_terms = models.CharField(max_length=255, blank=True, default='')
    message_excerpt = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Chat Moderation Event'
        verbose_name_plural = 'Chat Moderation Events'

    def __str__(self):
        return f"{self.user.username} {self.violation_type} @ {self.created_at:%Y-%m-%d %H:%M}"


# -----------------------------
# 7️⃣ Package
# -----------------------------
class Package(models.Model):
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to='packages/', blank=True, null=True)

    description = models.TextField(
        blank=True,
        null=True,
        help_text="Short line shown under the package name on the Packages page"
    )

    features = models.TextField(help_text="One feature per line")

    price = models.DecimalField(max_digits=10, decimal_places=2)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def feature_list(self):
        return self.features.splitlines()

    def __str__(self):
        return self.name


# Booking Step 2 preview photos (max 2) — ang mga larawang ito ang
# lumalabas sa "Preview" step ng booking kapag package ang napili.
class PackagePreviewImage(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='preview_images')
    image = models.ImageField(upload_to='package_previews/')
    order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Preview {self.id} ({self.package.name})"


# -----------------------------
# 8️⃣ Audit Log
# -----------------------------
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username if self.user else "Anonymous"} - {self.action} on {self.created_at.strftime("%Y-%m-%d %H:%M")}'

    class Meta:
        ordering = ['-created_at']


# -----------------------------
# 9️⃣ Admin Notification
# -----------------------------
class AdminNotification(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='admin_notifications', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='caused_admin_notifications', null=True, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Admin Notif: {self.message[:30]}..."


class AddOn(models.Model):
    name = models.CharField(max_length=150)
    image = models.ImageField(upload_to='addons/', blank=True, null=True)
    
    price = models.DecimalField(max_digits=10, decimal_places=2)
    solo_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    features = models.TextField(help_text="One feature per line")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def feature_list(self):
        return self.features.splitlines()

    def __str__(self):
        return self.name



# Booking Step 2 preview photos (max 2) para sa add-on combos.
class AddOnPreviewImage(models.Model):
    addon = models.ForeignKey(AddOn, on_delete=models.CASCADE, related_name='preview_images')
    image = models.ImageField(upload_to='addon_previews/')
    order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Preview {self.id} ({self.addon.name})"


class AdditionalOnly(models.Model):
    name = models.CharField(max_length=150)
    image = models.ImageField(upload_to='additional/', blank=True, null=True)
    
    price = models.DecimalField(max_digits=10, decimal_places=2)
    features = models.TextField(help_text="One feature per line")
    notes = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def feature_list(self):
        return self.features.splitlines()

    def __str__(self):
        return self.name


# Booking Step 2 preview photos (max 2) para sa additional-only items.
class AdditionalOnlyPreviewImage(models.Model):
    additional = models.ForeignKey(AdditionalOnly, on_delete=models.CASCADE, related_name='preview_images')
    image = models.ImageField(upload_to='additional_previews/')
    order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Preview {self.id} ({self.additional.name})"


class ServiceChargeConfig(models.Model):
    # Base fee na dati rati — ngayon ito ay ang CAVITE BASE logistics fee
    # (sakop ng free radius sa ibaba).
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # 📏 Distance-based logistics (admin-configurable).
    shop_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Shop/base latitude for distance computation (blank uses the business address in Site Settings).',
    )
    shop_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Shop/base longitude for distance computation.',
    )
    free_radius_km = models.DecimalField(
        max_digits=6, decimal_places=2, default=15,
        help_text='Included straight-line distance from the shop for outside-Cavite venues. Cavite venues always use the base fee.',
    )
    per_km_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=30,
        help_text='Outside-Cavite additional fee per kilometer beyond the included distance (minimum one billable kilometer).',
    )
    max_fee_cap = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Maximum total logistics fee (0 = no cap). Applied after base + distance fee.',
    )

    notes = models.TextField(
        blank=True,
        default="Includes styling fee, toll fees, fuel, crew meals, and ingress/egress logistics.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Service Charge Configuration"
        verbose_name_plural = "Service Charge Configuration"

    def __str__(self):
        return f"Service Charge: {self.amount}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user.username}: {self.message[:30]}..."



class ConcernTicket(models.Model):
    CATEGORY_CHOICES = (
        ('bug', 'Bug Report'),
        ('account', 'Account Issue'),
        ('payment', 'Payment Concern'),
        ('booking', 'Booking Concern'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='concern_tickets')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    subject = models.CharField(max_length=150)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    admin_notes = models.TextField(blank=True, null=True)
    admin_notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Concern #{self.id} - {self.subject}"


class ConcernImage(models.Model):
    concern = models.ForeignKey(ConcernTicket, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='concern_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for Concern #{self.concern.id}"


# -----------------------------
# 10?? User Designs (Custom Canvas)
# -----------------------------
class UserDesign(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='custom_designs')
    name = models.CharField(max_length=255, default='Untitled Design')
    canvas_json = models.TextField(help_text="Fabric.js JSON state of the canvas")
    thumbnail = models.ImageField(upload_to='user_designs/thumbnails/', blank=True, null=True)
    base_package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True, related_name='derived_designs')
    design_offer = models.ForeignKey('DesignOffer', on_delete=models.SET_NULL, null=True, blank=True, related_name='designs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} by {self.user.username}"


# -----------------------------
# 11️⃣ Gallery
# -----------------------------
class GalleryCategory(models.Model):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Gallery Categories'

    def __str__(self):
        return self.name


class GalleryImage(models.Model):
    category = models.ForeignKey(GalleryCategory, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='gallery/')
    caption = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caption or 'Image'} ({self.category.name})"


class CanvasCategory(models.Model):
    builtin_key = models.CharField(max_length=40, null=True, blank=True, unique=True, editable=False)
    name = models.CharField(max_length=120, unique=True)
    order = models.PositiveIntegerField(default=1, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
    available_package = models.BooleanField(default=True)
    available_entrance = models.BooleanField(default=False)
    available_stand = models.BooleanField(default=False)
    is_balloon = models.BooleanField(default=False, help_text='Use the shared balloon color limit for this category.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Canvas Categories'

    def __str__(self):
        return self.name


class CanvasLabel(models.Model):
    category = models.ForeignKey(CanvasCategory, on_delete=models.CASCADE, related_name='labels')
    name = models.CharField(max_length=120)
    order = models.PositiveIntegerField(default=1, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'order', 'name']
        unique_together = ('category', 'name')

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class CanvasAsset(models.Model):
    builtin_key = models.CharField(max_length=40, null=True, blank=True, unique=True, editable=False)
    category = models.ForeignKey(CanvasCategory, on_delete=models.CASCADE, related_name='assets')
    label_ref = models.ForeignKey(CanvasLabel, on_delete=models.SET_NULL, related_name='assets', null=True, blank=True)
    label = models.CharField(max_length=150)
    subgroup = models.CharField(max_length=120, blank=True, default='')
    image = models.ImageField(upload_to='canvas_assets/', blank=True, null=True)
    static_path = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Optional static path (e.g. images/canvas/premium/frames/round_arch.svg)",
    )
    item_type = models.CharField(max_length=20, default='image')
    width = models.PositiveIntegerField(default=150)
    height = models.PositiveIntegerField(default=150)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
    available_package = models.BooleanField(default=True)
    available_entrance = models.BooleanField(default=False)
    available_stand = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'label_ref__order', 'subgroup', 'sort_order', 'id']

    def __str__(self):
        return f"{self.label} ({self.category.name})"


class DesignOffer(models.Model):
    TYPES = [('package', 'Package'), ('entrance', 'Entrance Arch'), ('stand', 'Welcome Stand')]
    kind = models.CharField(max_length=12, choices=TYPES)
    package = models.OneToOneField(Package, on_delete=models.CASCADE, null=True, blank=True, related_name='design_configuration')
    entrance = models.OneToOneField(AddOn, on_delete=models.CASCADE, null=True, blank=True, related_name='design_configuration')
    stand = models.OneToOneField(AdditionalOnly, on_delete=models.CASCADE, null=True, blank=True, related_name='design_configuration')
    is_enabled = models.BooleanField(default=False)
    max_balloon_colors = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(check=(
            models.Q(kind='package', package__isnull=False, entrance__isnull=True, stand__isnull=True) |
            models.Q(kind='entrance', package__isnull=True, entrance__isnull=False, stand__isnull=True) |
            models.Q(kind='stand', package__isnull=True, entrance__isnull=True, stand__isnull=False)
        ), name='design_offer_one_matching_owner')]

    @property
    def item(self):
        return getattr(self, self.kind)

    @property
    def name(self):
        return self.item.name

    @property
    def price(self):
        return self.item.solo_price if self.kind == 'entrance' else self.item.price

    @property
    def booking_label(self):
        return f'{self.name} (Solo)' if self.kind == 'entrance' else self.name


class DesignRequirement(models.Model):
    offer = models.ForeignKey(DesignOffer, on_delete=models.CASCADE, related_name='requirements')
    category = models.ForeignKey(CanvasCategory, on_delete=models.PROTECT, related_name='design_requirements')
    required = models.BooleanField(default=False)
    minimum = models.PositiveIntegerField(default=0)
    maximum = models.PositiveIntegerField(null=True, blank=True)
    display_name = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['category__order', 'category__name']
        constraints = [
            models.UniqueConstraint(fields=['offer', 'category'], name='one_design_rule_per_category'),
            models.CheckConstraint(check=(models.Q(required=True, minimum__gte=1) | models.Q(required=False, minimum=0)), name='design_rule_required_minimum'),
            models.CheckConstraint(check=(models.Q(maximum__isnull=True) | models.Q(maximum__gte=models.F('minimum'))), name='design_rule_minimum_lte_maximum'),
        ]


class OfferInclusion(models.Model):
    ROW_TYPES = [('item', 'Canvas item'), ('service', 'Service')]
    offer = models.ForeignKey(DesignOffer, on_delete=models.CASCADE, related_name='inclusions')
    row_type = models.CharField(max_length=10, choices=ROW_TYPES, default='item')
    name = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    category = models.ForeignKey(CanvasCategory, on_delete=models.PROTECT, null=True, blank=True, related_name='offer_inclusions')
    required_minimum = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['offer', 'category'], condition=models.Q(category__isnull=False), name='one_inclusion_per_offer_category'),
            models.CheckConstraint(check=models.Q(quantity__isnull=True) | models.Q(quantity__gte=1), name='positive_inclusion_quantity'),
            models.CheckConstraint(check=models.Q(quantity__isnull=True) | models.Q(required_minimum__lte=models.F('quantity')), name='inclusion_minimum_lte_quantity'),
            models.CheckConstraint(check=models.Q(row_type='item') | models.Q(row_type='service', category__isnull=True, required_minimum=0), name='valid_inclusion_row_type'),
        ]


class HomeContent(models.Model):
    hero_label = models.CharField(max_length=255, blank=True, default='')
    hero_title = models.CharField(max_length=255, blank=True, default='')
    hero_subheadline = models.TextField(blank=True, default='')
    stat_events_styled = models.CharField(max_length=50, blank=True, default='')
    stat_rating = models.CharField(max_length=50, blank=True, default='')
    stat_satisfaction = models.CharField(max_length=50, blank=True, default='')
    stat_response_time = models.CharField(max_length=50, blank=True, default='')
    why_choose_title = models.CharField(max_length=255, blank=True, default='')
    why_choose_subtitle = models.TextField(blank=True, default='')
    occasion_chips = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text="Comma-separated list, e.g. Birthdays, Weddings, Corporate Events",
    )
    how_it_works_label = models.CharField(max_length=100, blank=True, default='')
    how_it_works_title = models.CharField(max_length=255, blank=True, default='')
    how_it_works_title_accent = models.CharField(max_length=255, blank=True, default='')
    faq_title = models.CharField(max_length=255, blank=True, default='')
    faq_subtitle = models.TextField(blank=True, default='')
    cta_title = models.CharField(max_length=255, blank=True, default='')
    cta_subtitle = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Home Content'

    def __str__(self):
        return 'Home Page Content'


class HomeFeatureItem(models.Model):
    home_content = models.ForeignKey(HomeContent, on_delete=models.CASCADE, related_name='features')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    icon_class = models.CharField(max_length=100, blank=True, default='fas fa-star')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title


class HomeHowItWorksStep(models.Model):
    home_content = models.ForeignKey(
        HomeContent, on_delete=models.CASCADE, related_name='how_it_works_steps'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    icon_class = models.CharField(max_length=100, blank=True, default='fas fa-star')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name_plural = 'Home How It Works Steps'

    def __str__(self):
        return self.title


class HomeFaqItem(models.Model):
    home_content = models.ForeignKey(HomeContent, on_delete=models.CASCADE, related_name='faqs')
    question = models.CharField(max_length=255)
    answer = models.TextField(blank=True, default='')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name_plural = 'Home FAQ Items'

    def __str__(self):
        return self.question


# -----------------------------
# 13️⃣ Service Page Content
# -----------------------------
class ServiceContent(models.Model):
    hero_label = models.CharField(max_length=255, blank=True, default='')
    hero_title = models.CharField(max_length=255, blank=True, default='')
    hero_subtitle = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Service Content'

    def __str__(self):
        return 'Service Page Content'


class AboutContent(models.Model):
    hero_label = models.CharField(max_length=255, blank=True, default='')
    hero_title = models.CharField(max_length=255, blank=True, default='')
    hero_subtitle = models.TextField(blank=True, default='')
    story_label = models.CharField(max_length=255, blank=True, default='')
    story_title = models.CharField(max_length=255, blank=True, default='')
    story_paragraph_1 = models.TextField(blank=True, default='')
    story_paragraph_2 = models.TextField(blank=True, default='')
    story_stat_number = models.CharField(max_length=50, blank=True, default='')
    story_stat_text = models.CharField(max_length=255, blank=True, default='')
    story_points = models.TextField(blank=True, default='')
    story_image = models.ImageField(upload_to='about_content/', blank=True, null=True)
    stat_events_styled = models.CharField(max_length=50, blank=True, default='')
    stat_year_founded = models.CharField(max_length=50, blank=True, default='')
    stat_satisfaction = models.CharField(max_length=50, blank=True, default='')
    mission_label = models.CharField(max_length=255, blank=True, default='')
    mission_title = models.CharField(max_length=255, blank=True, default='')
    mission_paragraph_1 = models.TextField(blank=True, default='')
    mission_paragraph_2 = models.TextField(blank=True, default='')
    mission_image = models.ImageField(upload_to='about_content/', blank=True, null=True)
    values_title = models.CharField(max_length=255, blank=True, default='')
    values_subtitle = models.TextField(blank=True, default='')
    journey_title = models.CharField(max_length=255, blank=True, default='')
    journey_subtitle = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'About Content'

    def __str__(self):
        return 'About Page Content'


class AboutValueItem(models.Model):
    about_content = models.ForeignKey(AboutContent, on_delete=models.CASCADE, related_name='values')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    icon_class = models.CharField(max_length=100, blank=True, default='fas fa-star')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title


class AboutJourneyItem(models.Model):
    """Timeline step for the About page "Our Journey" section (max 4 shown)."""
    about_content = models.ForeignKey(AboutContent, on_delete=models.CASCADE, related_name='journey_items')
    caption = models.CharField(max_length=255, blank=True, default='')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.caption or self.title


class RequestRateBucket(models.Model):
    """Shared, atomic request counters; keys contain HMACs, never raw identities."""
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveBigIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class SubmissionReceipt(models.Model):
    """Short-lived response receipts for identical booking/payment submissions."""
    key = models.CharField(max_length=64, primary_key=True)
    expires_at = models.DateTimeField(db_index=True)
    status_code = models.PositiveSmallIntegerField(default=0)
    body = models.TextField(blank=True)
    headers = models.JSONField(default=dict)


class GuidelinePageContent(models.Model):
    PAGE_GUIDELINES = "guidelines"
    PAGE_TERMS = "terms"
    PAGE_PRIVACY = "privacy"
    PAGE_CHOICES = (
        (PAGE_GUIDELINES, "Booking Guidelines"),
        (PAGE_TERMS, "Terms & Conditions"),
        (PAGE_PRIVACY, "Privacy Policy"),
    )
    page_key = models.CharField(max_length=20, choices=PAGE_CHOICES, unique=True)
    title = models.CharField(max_length=255, blank=True, default='')
    intro = models.TextField(blank=True, default='')
    attachment_label = models.CharField(max_length=255, blank=True, default='')
    attachment_url = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Guideline Page Content'
        verbose_name_plural = 'Guideline Page Contents'

    def __str__(self):
        return f"{self.get_page_key_display()} Content"


class GuidelineItem(models.Model):
    page_content = models.ForeignKey(
        GuidelinePageContent, on_delete=models.CASCADE, related_name='items'
    )
    heading = models.CharField(max_length=255, blank=True, default='')
    body = models.TextField(blank=True, default='')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.heading or f'Guideline Item #{self.pk}'


class GCashConfig(models.Model):
    downpayment_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    gcash_number = models.CharField(max_length=100, blank=True, default='')
    gcash_name = models.CharField(max_length=255, blank=True, default='')
    instructions = models.TextField(blank=True, default='')
    qr_code_image = models.ImageField(upload_to='gcash_config/', blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'GCash Configuration'
        verbose_name_plural = 'GCash Configuration'

    def __str__(self):
        return f"GCash Config: {self.downpayment_percent}% DP"


class Service(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    features = models.TextField(
        blank=True,
        default='',
        help_text="One feature per line. Shown as a checklist under the service on the Services page.",
    )
    best_for = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Short text used in the Services page comparison table, e.g. 'Kids parties and milestones'.",
    )
    image = models.ImageField(upload_to="services/", blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "id"]

    def feature_list(self):
        return [line.strip() for line in self.features.splitlines() if line.strip()]

    def __str__(self):
        return self.title


