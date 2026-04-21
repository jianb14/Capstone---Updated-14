from django.db import models
from django.contrib.auth.models import AbstractUser


# -----------------------------
# 1️⃣ User
# -----------------------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('customer', 'Customer'),
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email_verified = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.username} ({self.role})"


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

    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def can_edit(self):
        return self.status == 'pending'

    def __str__(self):
        return f"Booking {self.id} by {self.user.username}"


class BookingImage(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='booking_references/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for Booking {self.booking.id}"



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
    )

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='full')
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='pending')
    transaction_ref = models.CharField(max_length=100, unique=True)
    paid_at = models.DateTimeField(blank=True, null=True)
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


# -----------------------------
# 6️⃣ ChatSession & ChatMessage
# -----------------------------
class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.user.username}"

class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    message = models.TextField()
    is_flagged = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message {self.id} from {self.sender.username} to {self.receiver.username}"
    
    
    
# -----------------------------
# 7️⃣ Package
# -----------------------------
class Package(models.Model):
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to='packages/', blank=True, null=True)

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


class ServiceChargeConfig(models.Model):
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Concern #{self.id} - {self.subject}"


# -----------------------------
# 10?? User Designs (Custom Canvas)
# -----------------------------
class UserDesign(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='custom_designs')
    name = models.CharField(max_length=255, default='Untitled Design')
    canvas_json = models.TextField(help_text="Fabric.js JSON state of the canvas")
    thumbnail = models.ImageField(upload_to='user_designs/thumbnails/', blank=True, null=True)
    base_package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True, related_name='derived_designs')
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
    name = models.CharField(max_length=120, unique=True)
    order = models.PositiveIntegerField(default=1, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'label_ref__order', 'subgroup', 'sort_order', 'id']

    def __str__(self):
        return f"{self.label} ({self.category.name})"


class HomeContent(models.Model):
    hero_title = models.CharField(max_length=255, blank=True, default='')
    hero_subheadline = models.TextField(blank=True, default='')
    hero_primary_cta_text = models.CharField(max_length=100, blank=True, default='')
    hero_secondary_cta_text = models.CharField(max_length=100, blank=True, default='')
    hero_main_image = models.ImageField(upload_to='home_content/', blank=True, null=True)
    hero_float_top_image = models.ImageField(upload_to='home_content/', blank=True, null=True)
    hero_float_bottom_image = models.ImageField(upload_to='home_content/', blank=True, null=True)
    stat_events_styled = models.CharField(max_length=50, blank=True, default='')
    stat_rating = models.CharField(max_length=50, blank=True, default='')
    stat_satisfaction = models.CharField(max_length=50, blank=True, default='')
    stat_response_time = models.CharField(max_length=50, blank=True, default='')
    why_choose_title = models.CharField(max_length=255, blank=True, default='')
    why_choose_subtitle = models.TextField(blank=True, default='')
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


class AboutContent(models.Model):
    hero_title = models.CharField(max_length=255, blank=True, default='')
    hero_subtitle = models.TextField(blank=True, default='')
    story_label = models.CharField(max_length=255, blank=True, default='')
    story_title = models.CharField(max_length=255, blank=True, default='')
    story_paragraph_1 = models.TextField(blank=True, default='')
    story_paragraph_2 = models.TextField(blank=True, default='')
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
    features = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='services/', blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def feature_list(self):
        return self.features.splitlines()

    def __str__(self):
        return self.title


