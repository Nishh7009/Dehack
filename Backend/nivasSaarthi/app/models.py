from django.db import models
from django.contrib.auth.models import AbstractBaseUser
import uuid
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class NewUser(AbstractBaseUser):
    USER_ROLES = (
    ("CUSTOMER", "Customer"),
    ("SERVICE_PROVIDER", "Service Provider"),
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
    phone_number = models.CharField(max_length=10)
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Basic Auth Fields?
    is_verified = models.BooleanField(default=False)
    otp_retries = models.IntegerField(default=3)
    totp_secret = models.CharField(max_length=16, blank=True, null=True)
    profile_completed = models.BooleanField(default=False)
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
        if self.user.role != Role.SERVICE_PROVIDER:
            raise ValueError("User must have role SERVICE_PROVIDER to have a ServiceProviderProfile")
        super().save(*args, **kwargs)

class ServiceRequest(models.Model):
    status_choices = (
        ("PENDING", "Pending"),
        ("ACCEPTED", "Accepted"),
        ("REJECTED", "Rejected"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='service_requests')
    service_provider = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='service_offers')
    description = models.TextField()
    service_acceptance = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default='PENDING') # PENDING, ACCEPTED, REJECTED
    requested_on = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Service request by {self.customer} for {self.service_provider} on {self.requested_on.strftime('%Y-%m-%d %H:%M:%S')}"

class Service(models.Model):
    # Service requested by customer from service provider
    choices = (
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='services_requester')
    service_provider = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='services_provider')
    description = models.TextField()
    service_status = models.CharField(max_length=20, choices=choices, default='IN_PROGRESS') # IN_PROGRESS, COMPLETED, CANCELLED
    completion_verification_from_customer = models.BooleanField(default=False)
    completion_verification_from_provider = models.BooleanField(default=False)
    requested_on = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Service requested by {self.customer} from {self.service_provider} requested on {self.requested_on.strftime('%Y-%m-%d %H:%M:%S')}"

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
    chat_session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(NewUser, on_delete=models.CASCADE, related_name='sent_messages')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Message from {self.sender} in session {self.chat_session} sent on {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    def save(self, *args, **kwargs):
        # Some logic to update the counter according to credits used. Budget maxxing
        message_length = len(self.message)
        creds_used = message_length // 100 
        self.chat_session.creds_counter += creds_used
        self.chat_session.save()
        super().save(*args, **kwargs)
