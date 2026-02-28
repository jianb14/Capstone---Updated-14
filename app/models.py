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

    def __str__(self):
        return f"{self.username} ({self.role})"


class Booking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancel_requested', 'Cancel Requested'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    event_date = models.DateField()
    event_time = models.TimeField(null=True, blank=True)
    event_type = models.CharField(max_length=50)
    event_location = models.CharField(max_length=100)
    number_of_guests = models.PositiveIntegerField()
    package_type = models.CharField(max_length=50, blank=True, null=True)
    special_requests = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # ✅ NEW FIELDS
    edit_requested = models.BooleanField(default=False)
    edit_allowed = models.BooleanField(default=False)

    total_price = models.DecimalField(max_digits=20, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def can_edit(self):
        return self.status == 'pending'

    def __str__(self):
        return f"Booking {self.id} by {self.user.username}"



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
    price_estimate = models.DecimalField(max_digits=20, decimal_places=2)
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
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    )

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='pending')
    transaction_ref = models.CharField(max_length=100, unique=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

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

    def __str__(self):
        return f"Review {self.id} by {self.user.username}"


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
    service_features = models.TextField(help_text="One service feature per line", blank=True, null=True)

    price = models.DecimalField(max_digits=20, decimal_places=2)
    service_charge = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)
    service_notes = models.TextField(blank=True, null=True)

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def feature_list(self):
        return self.features.splitlines()

    def service_feature_list(self):
        if self.service_features:
            return self.service_features.splitlines()
        return []

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



class AddOn(models.Model):
    name = models.CharField(max_length=150)
    image = models.ImageField(upload_to='addons/', blank=True, null=True)
    
    price = models.DecimalField(max_digits=20, decimal_places=2)
    solo_price = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
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
    
    price = models.DecimalField(max_digits=20, decimal_places=2)
    features = models.TextField(help_text="One feature per line")
    notes = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def feature_list(self):
        return self.features.splitlines()

    def __str__(self):
        return self.name
