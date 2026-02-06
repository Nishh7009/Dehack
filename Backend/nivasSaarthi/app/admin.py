from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    NewUser, ServiceProviderProfile, ServiceRequest, Service, ServiceRating,
    ChatSession, ChatMessage, Notifications, SOSRequest, Blacklist,
    EmergencyContact, WebhookSubscription, VoiceCall, CallTranscript
)


# Inline Admin Classes
class ServiceProviderProfileInline(admin.StackedInline):
    model = ServiceProviderProfile
    can_delete = False
    verbose_name_plural = 'Service Provider Profile'
    extra = 0


class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 0


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('id', 'sender', 'message', 'timestamp', 'created_at')


class ServiceRatingInline(admin.StackedInline):
    model = ServiceRating
    extra = 0


class CallTranscriptInline(admin.TabularInline):
    model = CallTranscript
    extra = 0
    readonly_fields = ('id', 'speaker', 'original_text', 'original_language', 'translated_text', 'translated_language', 'timestamp')


# Main Admin Classes
@admin.register(NewUser)
class NewUserAdmin(UserAdmin):
    list_display = ('username', 'phone_number', 'first_name', 'last_name', 'role', 'city', 'is_active', 'is_verified', 'created_at')
    list_filter = ('role', 'is_active', 'is_verified', 'is_staff', 'preferred_language', 'city', 'state')
    search_fields = ('phone_number', 'email', 'first_name', 'last_name', 'city')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'location')
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'middle_name', 'last_name', 'phone_number', 'email')}),
        ('Role & Preferences', {'fields': ('role', 'preferred_language')}),
        ('Location', {'fields': ('address', 'city', 'state', 'pincode', 'latitude', 'longitude', 'location')}),
        ('Status', {'fields': ('is_active', 'is_staff', 'is_verified', 'profile_completed')}),
        ('Authentication', {'fields': ('otp_retries', 'totp_secret')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'phone_number', 'password1', 'password2', 'role'),
        }),
    )
    
    inlines = [ServiceProviderProfileInline, EmergencyContactInline]


@admin.register(ServiceProviderProfile)
class ServiceProviderProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'years_of_experience', 'average_rating', 'created_at')
    list_filter = ('years_of_experience', 'average_rating')
    search_fields = ('user__phone_number', 'user__first_name', 'user__last_name', 'services', 'bio')
    readonly_fields = ('id', 'created_at', 'updated_at', 'average_rating')
    raw_id_fields = ('user',)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'service_provider', 'status', 'service_acceptance', 'requested_on')
    list_filter = ('status', 'service_acceptance', 'requested_on')
    search_fields = ('customer__phone_number', 'service_provider__phone_number', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at', 'requested_on')
    raw_id_fields = ('customer', 'service_provider')
    date_hierarchy = 'requested_on'
    
    actions = ['mark_accepted', 'mark_rejected']
    
    @admin.action(description='Mark selected requests as Accepted')
    def mark_accepted(self, request, queryset):
        queryset.update(status='ACCEPTED', service_acceptance=True)
    
    @admin.action(description='Mark selected requests as Rejected')
    def mark_rejected(self, request, queryset):
        queryset.update(status='REJECTED', service_acceptance=False)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'service_provider', 'service_status', 'completion_verification_from_customer', 'completion_verification_from_provider', 'requested_on')
    list_filter = ('service_status', 'completion_verification_from_customer', 'completion_verification_from_provider', 'requested_on')
    search_fields = ('customer__phone_number', 'service_provider__phone_number', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at', 'requested_on')
    raw_id_fields = ('customer', 'service_provider')
    date_hierarchy = 'requested_on'
    inlines = [ServiceRatingInline]
    
    actions = ['mark_completed', 'mark_cancelled']
    
    @admin.action(description='Mark selected services as Completed')
    def mark_completed(self, request, queryset):
        queryset.update(service_status='COMPLETED')
    
    @admin.action(description='Mark selected services as Cancelled')
    def mark_cancelled(self, request, queryset):
        queryset.update(service_status='CANCELLED')


@admin.register(ServiceRating)
class ServiceRatingAdmin(admin.ModelAdmin):
    list_display = ('id', 'service', 'overall_rating', 'quality_of_service', 'punctuality', 'professionalism', 'rated_on')
    list_filter = ('overall_rating', 'rated_on')
    search_fields = ('service__customer__phone_number', 'service__service_provider__phone_number', 'review')
    readonly_fields = ('id', 'created_at', 'updated_at', 'rated_on')
    raw_id_fields = ('service',)
    date_hierarchy = 'rated_on'


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'creds_counter', 'max_creds', 'session_started_on', 'session_validity')
    list_filter = ('session_started_on',)
    search_fields = ('user__phone_number', 'user__first_name', 'user__last_name')
    readonly_fields = ('id', 'created_at', 'updated_at', 'session_started_on')
    raw_id_fields = ('user',)
    date_hierarchy = 'session_started_on'
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat_session', 'sender', 'message_preview', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('sender__phone_number', 'message')
    readonly_fields = ('id', 'created_at', 'updated_at', 'timestamp')
    raw_id_fields = ('chat_session', 'sender')
    date_hierarchy = 'timestamp'
    
    @admin.display(description='Message Preview')
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message


@admin.register(Notifications)
class NotificationsAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'message_preview', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__phone_number', 'message')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('user',)
    date_hierarchy = 'created_at'
    
    actions = ['mark_as_read', 'mark_as_unread']
    
    @admin.display(description='Message Preview')
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    
    @admin.action(description='Mark selected notifications as Read')
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)
    
    @admin.action(description='Mark selected notifications as Unread')
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)


@admin.register(SOSRequest)
class SOSRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'culprit', 'is_resolved', 'latitude', 'longitude', 'requested_on')
    list_filter = ('is_resolved', 'requested_on')
    search_fields = ('user__phone_number', 'culprit__phone_number')
    readonly_fields = ('id', 'created_at', 'updated_at', 'requested_on')
    raw_id_fields = ('user', 'culprit')
    date_hierarchy = 'requested_on'
    
    actions = ['mark_resolved', 'mark_unresolved']
    
    @admin.action(description='Mark selected SOS requests as Resolved')
    def mark_resolved(self, request, queryset):
        queryset.update(is_resolved=True)
    
    @admin.action(description='Mark selected SOS requests as Unresolved')
    def mark_unresolved(self, request, queryset):
        queryset.update(is_resolved=False)


@admin.register(Blacklist)
class BlacklistAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'blocked_user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__phone_number', 'blocked_user__phone_number')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('user', 'blocked_user')
    date_hierarchy = 'created_at'


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'name', 'phone_number', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__phone_number', 'name', 'phone_number')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('user',)


@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'url', 'event_type', 'is_active', 'created_at')
    list_filter = ('is_active', 'event_type', 'created_at')
    search_fields = ('user__phone_number', 'url', 'event_type')
    readonly_fields = ('id', 'created_at', 'secret')
    raw_id_fields = ('user',)
    
    actions = ['activate', 'deactivate']
    
    @admin.action(description='Activate selected subscriptions')
    def activate(self, request, queryset):
        queryset.update(is_active=True)
    
    @admin.action(description='Deactivate selected subscriptions')
    def deactivate(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(VoiceCall)
class VoiceCallAdmin(admin.ModelAdmin):
    list_display = ('id', 'caller', 'receiver', 'caller_language', 'receiver_language', 'status', 'duration', 'started_at')
    list_filter = ('status', 'caller_language', 'receiver_language', 'started_at')
    search_fields = ('caller__phone_number', 'receiver__phone_number', 'twilio_call_sid')
    readonly_fields = ('id', 'started_at')
    raw_id_fields = ('caller', 'receiver')
    date_hierarchy = 'started_at'
    inlines = [CallTranscriptInline]


@admin.register(CallTranscript)
class CallTranscriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'call', 'speaker', 'original_language', 'translated_language', 'text_preview', 'timestamp')
    list_filter = ('original_language', 'translated_language', 'timestamp')
    search_fields = ('speaker__phone_number', 'original_text', 'translated_text')
    readonly_fields = ('id', 'timestamp')
    raw_id_fields = ('call', 'speaker')
    date_hierarchy = 'timestamp'
    
    @admin.display(description='Text Preview')
    def text_preview(self, obj):
        return obj.original_text[:50] + '...' if len(obj.original_text) > 50 else obj.original_text
