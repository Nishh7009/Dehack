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
]
