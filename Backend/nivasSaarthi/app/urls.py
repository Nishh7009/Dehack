from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register_user'),
    path('verify-totp/', views.verify_totp, name='verify_totp'),
    path('resend-totp/', views.resend_totp, name='resend_totp'),
    path('profile-completion/', views.profile_completion, name='profile_completion'),
    path('speech-to-text/', views.speech_to_text_server, name='speech_to_text_server'),
    path('text-to-speech/', views.text_to_speech_server, name='text_to_speech_server'),
    ]
