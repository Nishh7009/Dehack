from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
import uuid
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class ROLES:
    CUSTOMER = 'customer'
    SERVICE_PROVIDER = 'service_provider'

class NewUser(AbstractUser):
    USER_ROLES = (
    (ROLES.CUSTOMER, "Customer"),
    (ROLES.SERVICE_PROVIDER, "Service Provider"),
    )

    INDIAN_LANGUAGES = (
        ("en", "English"),
        ("hi", "Hindi"),
        ("bn", "Bengali"),
        ("ta", "Tamil"),
        ("te", "Telugu"),
        ("mr", "Marathi"),
        ("gu", "Gujarati"),
        ("kn", "Kannada"),
        ("ml", "Malayalam"),
        ("pa", "Punjabi"),
        ("or", "Odia"),
        ("as", "Assamese"),
        ("ur", "Urdu"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Personal Info?

    first_name = models.CharField(max_length=30)
    middle_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=20)
    phone_number = models.CharField(max_length=20)  # E.164 format: +919876543210
    email = models.EmailField(blank=True, null=True, unique=True)

    # RBAC?
    role = models.CharField(
        max_length=20,
        choices=USER_ROLES
    )

    # Language Pref?
    preferred_language = models.CharField(
        max_length=5,
        choices=INDIAN_LANGUAGES,
        default="en"
    )

    # Tracking their location?
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)

    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    
    # Geospatial location field for PostGIS queries
    location = gis_models.PointField(
        geography=True,  # Use geography for accurate distance calculations in meters
        null=True,
        blank=True,
        srid=4326,  # WGS84 coordinate system (standard for GPS)
        help_text="Geographic location stored as Point(longitude, latitude)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Basic Auth Fields?
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    otp_retries = models.IntegerField(default=3)
    totp_secret = models.CharField(max_length=32, blank=True, null=True)
    profile_completed = models.BooleanField(default=False)
    
    # Telegram Integration
    telegram_chat_id = models.CharField(max_length=50, blank=True, null=True, unique=True)
    telegram_username = models.CharField(max_length=100, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        # Auto-populate location PointField from latitude/longitude
        if self.latitude is not None and self.longitude is not None:
            self.location = Point(float(self.longitude), float(self.latitude), srid=4326)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.phone_number} ({self.role})"

class ServiceProviderProfile(models.Model):
    # You should know your worker
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(NewUser, on_delete=models.CASCADE, related_name='service_provider_profile')
    bio = models.TextField(blank=True)
    years_of_experience = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    services = models.TextField(help_text="Comma-separated list of services offered") # Basically for checkbox
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"Service Provider Profile for {self.user}"
    def update_average_rating(self):
        ratings = ServiceRating.objects.filter(service__service_provider=self.user)
        if ratings.exists():
            total_rating = sum(r.overall_rating for r in ratings)
            self.average_rating = total_rating / ratings.count()
            self.save()
    def update_years_of_experience(self, start_date):
        today = timezone.now().date()
        self.years_of_experience = today.year - start_date.year - ((today.month, today.day) < (start_date.month, start_date.day))
        self.save()
    def get_services_list(self):
        return [service.strip() for service in self.services.split(',') if service.strip()]
    def save(self, *args, **kwargs):
        if self.user.role != ROLES.SERVICE_PROVIDER:
            raise ValueError("User must have role SERVICE_PROVIDER to have a ServiceProviderProfile")
        super().save(*args, **kwargs)

class ServiceRequest(models.Model):
    """
    A customer's request for a service. No longer tied to a single provider.
    Celery task finds nearby providers and AI negotiates with all of them.
    """
    STATUS_CHOICES = (
        ("PENDING", "Pending - Looking for providers"),
        ("NEGOTIATING", "Negotiating with providers"),
        ("OFFERS_READY", "Offers ready for review"),
        ("ACCEPTED", "Offer accepted"),
        ("CANCELLED", "Cancelled"),
        ("EXPIRED", "Expired - no offers"),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='service_requests')
    
    # Service details
    description = models.TextField(help_text="What the customer needs")
    service_types = models.TextField(help_text="Comma-separated service types, e.g. 'plumbing, electrical'")
    
    # Customer's location for finding nearby providers
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Budget (max for all negotiations)
    customer_budget = models.DecimalField(max_digits=10, decimal_places=2,
        help_text="Maximum budget - same limit for all providers")
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Negotiation progress tracking
    providers_contacted = models.PositiveIntegerField(default=0, help_text="Number of providers contacted")
    offers_received = models.PositiveIntegerField(default=0, help_text="Number of offers received")
    
    # Celery task tracking
    task_id = models.CharField(max_length=255, null=True, blank=True,
        help_text="Celery task ID for tracking negotiation progress")
    
    # Final selection
    selected_offer = models.ForeignKey('NegotiationSession', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='selected_for_request',
        help_text="The offer the customer chose")
    
    requested_on = models.DateTimeField(null=True, blank=True,
        help_text="When the customer wants the service")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Service request by {self.customer}: {self.service_types} - {self.status}"
    
    def get_offers(self):
        """Get all completed negotiation sessions for this request"""
        return self.negotiations.filter(status='completed', outcome='agreed')


class Service(models.Model):
    """Service requested by customer from service provider"""
    STATUS_CHOICES = (
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    )
    PAYMENT_CHOICES = (
        ("PENDING", "Payment Pending"),
        ("PAID", "Paid"),
        ("CONFIRMED", "Confirmed by Provider"),
        ("REFUNDED", "Refunded"),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='services_requester')
    service_provider = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='services_provider')
    description = models.TextField()
    agreed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="The negotiated price agreed upon")
    
    service_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IN_PROGRESS')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='PENDING')
    
    # Token for provider to confirm payment receipt (public link)
    payment_confirmation_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    
    completion_verification_from_customer = models.BooleanField(default=False)
    completion_verification_from_provider = models.BooleanField(default=False)
    requested_on = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Service by {self.service_provider} for {self.customer} - {self.service_status}"

class ServiceRating(models.Model):
    # Guess
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='ratings')
    quality_of_service = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(5)])
    punctuality = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(5)])
    professionalism = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(5)])
    overall_rating = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(5)])
    review = models.TextField(blank=True)
    rated_on = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Rating for {self.service} - {self.overall_rating} stars rated on {self.rated_on.strftime('%Y-%m-%d %H:%M:%S')}"

class ChatSession(models.Model):
    # Idk Session?
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='chat_sessions')
    max_creds = models.IntegerField(default=100, help_text="Maximum credits allocated for this chat session")
    creds_counter = models.IntegerField(default=0, help_text="Credits used in this chat session")
    session_started_on = models.DateTimeField(auto_now_add=True)
    session_validity = models.DurationField(default=timezone.timedelta(hours = 3))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Chat session for {self.user} started on {self.session_started_on.strftime('%Y-%m-%d %H:%M:%S')}"
    def is_active(self):
        return timezone.now() < self.session_started_on + self.session_validity
    def remaining_credits(self):
        return self.max_creds - self.creds_counter
    
class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='sent_chat_messages', null=True)
    receiver = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='received_chat_messages', null=True)
    
    original_message = models.TextField(null=True, blank=True)  # What sender typed
    original_language = models.CharField(max_length=5, null=True, blank=True)
    
    translated_message = models.TextField(null=True, blank=True)  # What receiver sees
    translated_language = models.CharField(max_length=5, null=True, blank=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['timestamp']

class Notifications(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=100, null=True, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notification_type = models.CharField(max_length=50, null=True, blank=True)

    def form_message(self, context):
        # Form the message based on the context provided. Context can be a dictionary containing relevant information about the event that triggered the notification.
        # For example, if the notification is about a new service request, the context might contain details about the service provider, customer, and service description.
        if context.get('event') == 'new_service_request':
            self.message = f"You have a new service request from {context.get('customer_name')} for {context.get('service_description')}."
        elif context.get('event') == 'service_request_accepted':
            self.message = f"Your service request for {context.get('service_description')} has been accepted by {context.get('service_provider_name')}."
        elif context.get('event') == 'service_request_rejected':
            self.message = f"Your service request for {context.get('service_description')} has been rejected by {context.get('service_provider_name')}."
        elif context.get('event') == 'service_completed':
            self.message = f"Your service request for {context.get('service_description')} has been marked as completed by {context.get('service_provider_name')}."
        elif context.get('event') == 'negotiated_offer':
            self.message = context.get('negotiated_offer')
        else:
            self.message = "You have a new notification."
    def __str__(self):
        return f"Notification for {self.user} - {'Read' if self.is_read else 'Unread'} created on {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

class SOSRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='sos_requests')
    culprit = models.ForeignKey(NewUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='sos_as_culprit')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    is_resolved = models.BooleanField(default=False)
    requested_on = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SOS Request by {self.user} - {'Resolved' if self.is_resolved else 'Unresolved'} requested on {self.requested_on.strftime('%Y-%m-%d %H:%M:%S')}"

class Blacklist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='blacklist_entries')
    blocked_user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} has blocked {self.blocked_user}"

class EmergencyContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Emergency Contact {self.name} for {self.user}"

class WebhookSubscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='webhook_subscriptions')
    url = models.URLField(help_text="URL to send webhook notifications")
    event_type = models.CharField(max_length=50, default='notification_count')  # notification_count, new_message, etc.
    is_active = models.BooleanField(default=True)
    secret = models.CharField(max_length=64, blank=True)  # For webhook signature verification
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.secret:
            import secrets
            self.secret = secrets.token_hex(32)
        super().save(*args, **kwargs)

class VoiceCall(models.Model):
    status_bits = (
        ("initiated", "Initiated"),
        ("ringing", "Ringing"),
        ("in-progress", "In Progress"),
        ("completed", "Completed"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    caller = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='outgoing_calls')
    receiver = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='incoming_calls')
    
    caller_language = models.CharField(max_length=5, choices=NewUser.INDIAN_LANGUAGES)
    receiver_language = models.CharField(max_length=5, choices=NewUser.INDIAN_LANGUAGES)
    
    twilio_call_sid = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=50, default='initiated')  # initiated, ringing, in-progress, completed
    
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(default=0)  # in seconds
    
    class Meta:
        ordering = ['-started_at']

class CallTranscript(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(VoiceCall, on_delete=models.CASCADE, related_name='transcripts')
    speaker = models.ForeignKey(NewUser, on_delete=models.CASCADE)
    
    original_text = models.TextField()  # What speaker said in their language
    original_language = models.CharField(max_length=5)
    
    translated_text = models.TextField()  # Translation for other person
    translated_language = models.CharField(max_length=5)
    
    timestamp = models.DateTimeField(auto_now_add=True)


class NegotiationSession(models.Model):
    """
    Tracks AI negotiation conversations with service providers via WhatsApp.
    Each session represents one negotiation attempt for a ServiceRequest.
    """
    NEGOTIATION_STATUS = (
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    )
    
    OUTCOME_CHOICES = (
        ('agreed', 'Deal Agreed'),
        ('no_deal', 'No Deal'),
        ('timeout', 'Timeout'),
        ('cancelled', 'Cancelled'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='negotiations')
    provider_phone = models.CharField(max_length=20, help_text="Provider's WhatsApp number in E.164 format")
    
    # Conversation state for Sarvam AI context
    conversation_history = models.JSONField(default=list, help_text="Message history for AI context")
    
    # Price tracking
    current_offer = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Provider's current price offer")
    counter_offer = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="AI's last counter-offer")
    
    # Negotiation constraints
    max_price = models.DecimalField(max_digits=10, decimal_places=2,
        help_text="Customer's maximum budget - never exceed this")
    min_acceptable = models.DecimalField(max_digits=10, decimal_places=2,
        help_text="Auto-accept threshold - accept immediately if offer is at or below")
    
    # Session state
    status = models.CharField(max_length=20, choices=NEGOTIATION_STATUS, default='active')
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, null=True, blank=True)
    message_count = models.IntegerField(default=0, help_text="Number of messages exchanged")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(help_text="Session timeout - negotiation fails after this")
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Negotiation for {self.service_request} - {self.status}"
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def add_message(self, role: str, content: str):
        """Add a message to conversation history"""
        self.conversation_history.append({
            'role': role,
            'content': content,
            'timestamp': timezone.now().isoformat()
        })
        self.message_count += 1
        self.save()

