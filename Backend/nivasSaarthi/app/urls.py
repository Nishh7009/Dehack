from django.urls import path
from . import views

urlpatterns = [
    # Auth endpoints
    path('register/', views.register, name='register_user'),
    path('verify-totp/', views.verify_totp, name='verify_totp'),
    path('resend-totp/', views.resend_totp, name='resend_totp'),
    path('profile-completion/', views.profile_completion, name='profile_completion'),
    
    # Sarvam AI endpoints
    path('speech-to-text/', views.speech_to_text_server, name='speech_to_text_server'),
    path('text-to-speech/', views.text_to_speech_server, name='text_to_speech_server'),
    
    # Geospatial endpoints
    path('nearby-providers/', views.get_nearby_providers, name='nearby_providers'),
    
    # Service management endpoints
    path('services/', views.get_services_for_customer, name='services_for_customer'),
    path('services/provider/', views.get_services_for_provider, name='services_for_provider'),
    path('services/details/', views.get_service_details, name='service_details'),
    path('services/complete/', views.complete_service, name='complete_service'),
    path('services/request/', views.request_service, name='request_service'),
    path('services/requests/incoming/', views.get_incoming_requests, name='incoming_requests'),
    path('services/requests/outgoing/', views.get_outgoing_requests, name='outgoing_requests'),
    path('services/requests/accept/', views.accept_service_request, name='accept_request'),
    path('services/requests/reject/', views.reject_service_request, name='reject_request'),
    
    # Notifications endpoints
    path('notifications/', views.get_notifications, name='get_notifications'),
    path('notifications/mark-read/<uuid:notification_id>/', views.mark_notification_as_read, name='mark_notification_as_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_as_read, name='mark_all_notifications_as_read'),
    path('notifications/unread-count/', views.get_unread_notification_count, name='unread_notifications_count'),

    # SOS endpoints
    path('emergency/report/<uuid:service_id>/', views.report_emergency, name='report_emergency'),
    path('emergency/resolve/<uuid:emergency_id>/', views.resolve_emergency, name='resolve_emergency'),

    # Webhook management endpoints
    path('webhooks/register/', views.register_webhook, name='register_webhook'),
    path('webhooks/<uuid:webhook_id>/', views.delete_webhook, name='delete_webhook'),
]
