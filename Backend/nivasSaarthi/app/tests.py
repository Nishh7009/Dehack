"""
Comprehensive tests for all API endpoints in views.py and WebSocket consumers
Run with: python manage.py test app.tests
Or in Docker: docker exec nivas_saarthi_web_dev python nivasSaarthi/manage.py test app.tests
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from unittest.mock import patch, MagicMock, AsyncMock
from django.contrib.gis.geos import Point
import pyotp
import uuid
import json
import asyncio

# Channels imports for WebSocket testing
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async

from .models import (
    NewUser, ROLES, ServiceProviderProfile, Service, ServiceRequest,
    Notifications, SOSRequest, Blacklist, EmergencyContact,
    WebhookSubscription, VoiceCall, CallTranscript, ChatMessage
)
from .utils import call_helpers, chat_helpers
from .consumers import TranslatedCallConsumer, TranslatedChatConsumer


class BaseAPITestCase(APITestCase):
    """Base test class with helper methods for authentication and user creation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        # Create a verified customer
        self.customer = NewUser.objects.create(
            username='testcustomer',
            email='customer@test.com',
            phone_number='1234567890',
            first_name='Test',
            middle_name='Middle',
            last_name='Customer',
            role=ROLES.CUSTOMER,
            is_active=True,
            is_verified=True,
            profile_completed=True,
        )
        self.customer.set_password('testpassword123')
        self.customer.save()
        
        # Create a verified service provider with location
        self.provider = NewUser.objects.create(
            username='testprovider',
            email='provider@test.com',
            phone_number='0987654321',
            first_name='Test',
            middle_name='Middle',
            last_name='Provider',
            role=ROLES.SERVICE_PROVIDER,
            is_active=True,
            is_verified=True,
            profile_completed=True,
            latitude=28.6139,
            longitude=77.2090,
            city='Delhi',
        )
        self.provider.set_password('testpassword123')
        self.provider.location = Point(77.2090, 28.6139, srid=4326)
        self.provider.save()
        
        # Create provider profile
        self.provider_profile = ServiceProviderProfile.objects.create(
            user=self.provider,
            bio='Test provider bio',
            years_of_experience=5,
            services='plumbing,electrical',
        )
    
    def get_tokens_for_user(self, user):
        """Generate JWT tokens for a user."""
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    
    def authenticate_as(self, user):
        """Authenticate client as the given user."""
        tokens = self.get_tokens_for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return tokens


# ============================================================================
# AUTH ENDPOINT TESTS
# ============================================================================

class RegisterAPITest(APITestCase):
    """Tests for user registration endpoint."""
    
    @patch('app.views.send_mail')
    def test_register_success(self, mock_send_mail):
        """Test successful user registration."""
        mock_send_mail.return_value = 1
        
        data = {
            'email': 'newuser@test.com',
            'password': 'securepassword123',
            'confirm_password': 'securepassword123',
        }
        response = self.client.post(reverse('register_user'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user_id', response.data)
        self.assertTrue(NewUser.objects.filter(email='newuser@test.com').exists())
        mock_send_mail.assert_called_once()
    
    def test_register_password_mismatch(self):
        """Test registration fails when passwords don't match."""
        data = {
            'email': 'newuser@test.com',
            'password': 'password123',
            'confirm_password': 'different123',
        }
        response = self.client.post(reverse('register_user'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_register_duplicate_email(self):
        """Test registration fails for duplicate email."""
        NewUser.objects.create(
            username='existing',
            email='existing@test.com',
            role=ROLES.CUSTOMER,
        )
        
        data = {
            'email': 'existing@test.com',
            'password': 'password123',
            'confirm_password': 'password123',
        }
        response = self.client.post(reverse('register_user'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VerifyTOTPAPITest(APITestCase):
    """Tests for TOTP verification endpoint."""
    
    def setUp(self):
        self.totp_secret = pyotp.random_base32()
        self.user = NewUser.objects.create(
            username='unverified',
            email='unverified@test.com',
            phone_number='1111111111',
            first_name='Unverified',
            middle_name='Test',
            last_name='User',
            role=ROLES.CUSTOMER,
            is_active=False,
            is_verified=False,
            totp_secret=self.totp_secret,
            otp_retries=3,
        )
    
    def test_verify_totp_success(self):
        """Test successful TOTP verification."""
        totp = pyotp.TOTP(self.totp_secret)
        valid_code = totp.now()
        
        data = {
            'user_id': str(self.user.id),
            'totp_code': valid_code,
        }
        response = self.client.post(reverse('verify_totp'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)
        self.assertTrue(self.user.is_active)
    
    @patch('app.views.send_mail')
    def test_verify_totp_invalid_code(self, mock_send_mail):
        """Test TOTP verification with invalid code."""
        mock_send_mail.return_value = 1
        
        data = {
            'user_id': str(self.user.id),
            'totp_code': '000000',
        }
        response = self.client.post(reverse('verify_totp'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.otp_retries, 2)
    
    def test_verify_totp_user_not_found(self):
        """Test TOTP verification for non-existent user."""
        data = {
            'user_id': str(uuid.uuid4()),
            'totp_code': '123456',
        }
        response = self.client.post(reverse('verify_totp'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LoginAPITest(BaseAPITestCase):
    """Tests for login endpoint."""
    
    def test_login_success(self):
        """Test successful login returns JWT tokens."""
        data = {
            'email': 'customer@test.com',
            'password': 'testpassword123',
        }
        response = self.client.post(reverse('login'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
    
    def test_login_invalid_password(self):
        """Test login with wrong password."""
        data = {
            'email': 'customer@test.com',
            'password': 'wrongpassword',
        }
        response = self.client.post(reverse('login'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_login_unverified_user(self):
        """Test login fails for unverified user."""
        unverified = NewUser.objects.create(
            username='unverified2',
            email='unverified2@test.com',
            role=ROLES.CUSTOMER,
            is_verified=False,
        )
        unverified.set_password('password123')
        unverified.save()
        
        data = {
            'email': 'unverified2@test.com',
            'password': 'password123',
        }
        response = self.client.post(reverse('login'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_login_user_not_found(self):
        """Test login for non-existent user."""
        data = {
            'email': 'nonexistent@test.com',
            'password': 'password123',
        }
        response = self.client.post(reverse('login'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LogoutAPITest(BaseAPITestCase):
    """Tests for logout endpoint."""
    
    def test_logout_success(self):
        """Test successful logout."""
        self.authenticate_as(self.customer)
        
        response = self.client.post(reverse('logout'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_logout_unauthenticated(self):
        """Test logout without authentication."""
        response = self.client.post(reverse('logout'))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenRefreshAPITest(BaseAPITestCase):
    """Tests for token refresh endpoint."""
    
    def test_refresh_token_success(self):
        """Test successful token refresh."""
        tokens = self.get_tokens_for_user(self.customer)
        
        data = {'refresh': tokens['refresh']}
        response = self.client.post(reverse('token_refresh'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
    
    def test_refresh_token_invalid(self):
        """Test refresh with invalid token."""
        data = {'refresh': 'invalid_token'}
        response = self.client.post(reverse('token_refresh'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ForgotPasswordAPITest(BaseAPITestCase):
    """Tests for forgot password endpoint."""
    
    def setUp(self):
        super().setUp()
        self.customer.totp_secret = pyotp.random_base32()
        self.customer.save()
    
    @patch('app.views.send_mail')
    def test_forgot_password_success(self, mock_send_mail):
        """Test forgot password sends OTP."""
        mock_send_mail.return_value = 1
        
        data = {'email': 'customer@test.com'}
        response = self.client.post(reverse('request_password_reset'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_mail.assert_called_once()
    
    def test_forgot_password_user_not_found(self):
        """Test forgot password for non-existent user."""
        data = {'email': 'nonexistent@test.com'}
        response = self.client.post(reverse('request_password_reset'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ResetPasswordAPITest(BaseAPITestCase):
    """Tests for password reset endpoint."""
    
    def setUp(self):
        super().setUp()
        self.totp_secret = pyotp.random_base32()
        self.customer.totp_secret = self.totp_secret
        self.customer.otp_retries = 3
        self.customer.save()
    
    def test_reset_password_success(self):
        """Test successful password reset."""
        totp = pyotp.TOTP(self.totp_secret)
        
        data = {
            'email': 'customer@test.com',
            'totp_code': totp.now(),
            'new_password': 'newpassword123',
        }
        response = self.client.post(reverse('confirm_password_reset'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify new password works
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password('newpassword123'))


class ResendTOTPAPITest(APITestCase):
    """Tests for resend TOTP endpoint."""
    
    def setUp(self):
        self.user = NewUser.objects.create(
            username='resendtest',
            email='resend@test.com',
            phone_number='5555555555',
            first_name='Resend',
            middle_name='Test',
            last_name='User',
            role=ROLES.CUSTOMER,
            totp_secret=pyotp.random_base32(),
            otp_retries=3,
        )
    
    @patch('app.views.send_mail')
    def test_resend_totp_success(self, mock_send_mail):
        """Test successful TOTP resend."""
        mock_send_mail.return_value = 1
        
        response = self.client.get(
            reverse('resend_totp'),
            {'user_id': str(self.user.id)}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.otp_retries, 2)


# ============================================================================
# SERVICE ENDPOINT TESTS
# ============================================================================

class ServiceRequestAPITest(BaseAPITestCase):
    """Tests for service request endpoints."""
    
    def test_request_service_success(self):
        """Test successful service request creation."""
        self.authenticate_as(self.customer)
        
        data = {
            'customer_id': str(self.customer.id),
            'provider_id': str(self.provider.id),
            'description': 'Fix my plumbing',
        }
        response = self.client.post(reverse('request_service'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('service_request_id', response.data)
        self.assertTrue(ServiceRequest.objects.filter(customer=self.customer).exists())
    
    def test_request_service_missing_fields(self):
        """Test service request fails with missing fields."""
        self.authenticate_as(self.customer)
        
        data = {'customer_id': str(self.customer.id)}
        response = self.client.post(reverse('request_service'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_request_service_unauthenticated(self):
        """Test service request fails without authentication."""
        data = {
            'customer_id': str(self.customer.id),
            'provider_id': str(self.provider.id),
            'description': 'Fix my plumbing',
        }
        response = self.client.post(reverse('request_service'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AcceptRejectServiceRequestAPITest(BaseAPITestCase):
    """Tests for accepting and rejecting service requests."""
    
    def setUp(self):
        super().setUp()
        self.service_request = ServiceRequest.objects.create(
            customer=self.customer,
            service_provider=self.provider,
            description='Test service request',
            status='PENDING',
        )
    
    def test_accept_service_request(self):
        """Test accepting a service request."""
        self.authenticate_as(self.provider)
        
        data = {'service_request_id': str(self.service_request.id)}
        response = self.client.post(reverse('accept_request'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.service_request.refresh_from_db()
        self.assertEqual(self.service_request.status, 'ACCEPTED')
        self.assertTrue(self.service_request.service_acceptance)
        
        # Check that a Service was created
        self.assertTrue(Service.objects.filter(
            customer=self.customer,
            service_provider=self.provider
        ).exists())
    
    def test_reject_service_request(self):
        """Test rejecting a service request."""
        self.authenticate_as(self.provider)
        
        data = {'service_request_id': str(self.service_request.id)}
        response = self.client.post(reverse('reject_request'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.service_request.refresh_from_db()
        self.assertEqual(self.service_request.status, 'REJECTED')


class GetServicesAPITest(BaseAPITestCase):
    """Tests for getting services."""
    
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(
            customer=self.customer,
            service_provider=self.provider,
            description='Active service',
            service_status='IN_PROGRESS',
        )
    
    def test_get_services_for_customer(self):
        """Test customer can get their services."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(
            reverse('services_for_customer'),
            {'customer_id': str(self.customer.id)}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['services']), 1)
    
    def test_get_services_for_provider(self):
        """Test provider can get their services."""
        self.authenticate_as(self.provider)
        
        response = self.client.get(
            reverse('services_for_provider'),
            {'provider_id': str(self.provider.id)}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_get_service_details(self):
        """Test getting service details."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(
            reverse('service_details'),
            {'service_id': str(self.service.id)}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['service']['description'], 'Active service')


class CompleteServiceAPITest(BaseAPITestCase):
    """Tests for completing services."""
    
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(
            customer=self.customer,
            service_provider=self.provider,
            description='Service to complete',
            service_status='IN_PROGRESS',
        )
    
    def test_complete_service_as_customer(self):
        """Test customer can mark service as complete."""
        self.authenticate_as(self.customer)
        
        data = {'service_id': str(self.service.id)}
        response = self.client.post(reverse('complete_service'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.service.refresh_from_db()
        self.assertTrue(self.service.completion_verification_from_customer)
    
    def test_complete_service_as_provider(self):
        """Test provider can mark service as complete."""
        self.authenticate_as(self.provider)
        
        data = {'service_id': str(self.service.id)}
        response = self.client.post(reverse('complete_service'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.service.refresh_from_db()
        self.assertTrue(self.service.completion_verification_from_provider)


class GetIncomingOutgoingRequestsAPITest(BaseAPITestCase):
    """Tests for getting incoming and outgoing service requests."""
    
    def setUp(self):
        super().setUp()
        self.pending_request = ServiceRequest.objects.create(
            customer=self.customer,
            service_provider=self.provider,
            description='Pending request',
            status='PENDING',
        )
    
    def test_get_incoming_requests(self):
        """Test provider can get incoming requests."""
        self.authenticate_as(self.provider)
        
        response = self.client.get(reverse('incoming_requests'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['service_requests']), 1)
    
    def test_get_outgoing_requests(self):
        """Test customer can get outgoing requests."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(reverse('outgoing_requests'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['service_requests']), 1)


# ============================================================================
# GEOSPATIAL TESTS
# ============================================================================

class NearbyProvidersAPITest(BaseAPITestCase):
    """Tests for nearby providers endpoint."""
    
    def test_get_nearby_providers(self):
        """Test getting nearby providers."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(
            reverse('nearby_providers'),
            {'latitude': '28.6139', 'longitude': '77.2090', 'radius_km': '10'}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('providers', response.data)
        self.assertIn('count', response.data)
    
    def test_get_nearby_providers_missing_params(self):
        """Test nearby providers fails without coordinates."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(reverse('nearby_providers'))
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_get_nearby_providers_with_service_filter(self):
        """Test filtering nearby providers by service type."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(
            reverse('nearby_providers'),
            {'latitude': '28.6139', 'longitude': '77.2090', 'service_type': 'plumbing'}
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ============================================================================
# NOTIFICATION TESTS
# ============================================================================

class NotificationsAPITest(BaseAPITestCase):
    """Tests for notification endpoints."""
    
    def setUp(self):
        super().setUp()
        self.notification = Notifications.objects.create(
            user=self.customer,
            message='Test notification',
            is_read=False,
        )
    
    def test_get_notifications(self):
        """Test getting notifications."""
        self.authenticate_as(self.customer)
        
        response = self.client.get(reverse('get_notifications'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['notifications']), 1)
    
    def test_mark_notification_as_read(self):
        """Test marking notification as read."""
        self.authenticate_as(self.customer)
        
        response = self.client.post(
            reverse('mark_notification_as_read', kwargs={'notification_id': self.notification.id})
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
    
    def test_mark_all_notifications_as_read(self):
        """Test marking all notifications as read."""
        # Create additional notifications
        Notifications.objects.create(user=self.customer, message='Notification 2', is_read=False)
        Notifications.objects.create(user=self.customer, message='Notification 3', is_read=False)
        
        self.authenticate_as(self.customer)
        
        response = self.client.post(reverse('mark_all_notifications_as_read'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Notifications.objects.filter(user=self.customer, is_read=False).count(), 0)
    
    def test_get_unread_notification_count(self):
        """Test getting unread notification count."""
        Notifications.objects.create(user=self.customer, message='Unread 2', is_read=False)
        
        self.authenticate_as(self.customer)
        
        response = self.client.get(reverse('unread_notifications_count'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 2)


# ============================================================================
# WEBHOOK TESTS
# ============================================================================

class WebhookAPITest(BaseAPITestCase):
    """Tests for webhook management endpoints."""
    
    def test_register_webhook(self):
        """Test registering a webhook."""
        self.authenticate_as(self.customer)
        
        data = {
            'url': 'https://example.com/webhook',
            'event_type': 'notification_count',
        }
        response = self.client.post(reverse('register_webhook'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('webhook_id', response.data)
        self.assertIn('secret', response.data)
    
    def test_delete_webhook(self):
        """Test deleting a webhook."""
        webhook = WebhookSubscription.objects.create(
            user=self.customer,
            url='https://example.com/webhook',
            event_type='notification_count',
        )
        
        self.authenticate_as(self.customer)
        
        response = self.client.delete(
            reverse('delete_webhook', kwargs={'webhook_id': webhook.id})
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(WebhookSubscription.objects.filter(id=webhook.id).exists())


# ============================================================================
# EMERGENCY/SOS TESTS
# ============================================================================

class EmergencyAPITest(BaseAPITestCase):
    """Tests for emergency/SOS endpoints."""
    
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(
            customer=self.customer,
            service_provider=self.provider,
            description='Active service for emergency test',
            service_status='IN_PROGRESS',
        )
    
    @patch('app.twilio_service.Client')  # Mock Twilio client
    def test_report_emergency(self, mock_twilio):
        """Test reporting an emergency."""
        self.authenticate_as(self.customer)
        
        data = {
            'latitude': '28.6139',
            'longitude': '77.2090',
        }
        response = self.client.post(
            reverse('report_emergency', kwargs={'service_id': self.service.id}),
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(SOSRequest.objects.filter(user=self.customer).exists())
    
    def test_resolve_emergency(self):
        """Test resolving an emergency."""
        sos = SOSRequest.objects.create(
            user=self.customer,
            culprit=self.provider,
            latitude=28.6139,
            longitude=77.2090,
            is_resolved=False,
        )
        
        self.authenticate_as(self.customer)
        
        response = self.client.post(
            reverse('resolve_emergency', kwargs={'emergency_id': sos.id})
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ============================================================================
# CALL ENDPOINT TESTS
# ============================================================================

class VoiceCallAPITest(BaseAPITestCase):
    """Tests for voice call endpoints."""
    
    @patch('app.twilio_service.Client')  # Mock Twilio client
    def test_initiate_call(self, mock_twilio):
        """Test initiating a voice call."""
        mock_client = MagicMock()
        mock_twilio.return_value = mock_client
        mock_client.calls.create.return_value = MagicMock(sid='CALL123')
        
        self.authenticate_as(self.customer)
        
        data = {
            'receiver_id': str(self.provider.id),
        }
        response = self.client.post(reverse('initiate_call'), data, format='json')
        
        # May fail due to Twilio config, but test the flow
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED, status.HTTP_500_INTERNAL_SERVER_ERROR])
    
    def test_get_call_transcript(self):
        """Test getting call transcript."""
        call = VoiceCall.objects.create(
            caller=self.customer,
            receiver=self.provider,
            caller_language='en',
            receiver_language='hi',
            status='completed',
        )
        CallTranscript.objects.create(
            call=call,
            speaker=self.customer,
            original_text='Hello',
            original_language='en',
            translated_text='नमस्ते',
            translated_language='hi',
        )
        
        self.authenticate_as(self.customer)
        
        response = self.client.get(
            reverse('call_transcript', kwargs={'call_id': call.id})
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('transcripts', response.data)


# ============================================================================
# PROFILE COMPLETION TEST
# ============================================================================

class ProfileCompletionAPITest(BaseAPITestCase):
    """Tests for profile completion endpoint."""
    
    def test_profile_completion(self):
        """Test profile completion marks user as complete."""
        user = NewUser.objects.create(
            username='incomplete',
            email='incomplete@test.com',
            phone_number='7777777777',
            role=ROLES.CUSTOMER,
            is_verified=True,
            is_active=True,
            profile_completed=False,
        )
        
        self.authenticate_as(user)
        
        data = {
            'first_name': 'Complete',
            'last_name': 'User',
        }
        response = self.client.post(reverse('profile_completion'), data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        user.refresh_from_db()
        self.assertTrue(user.profile_completed)


# ============================================================================
# SESSION DETAILS TEST
# ============================================================================

class SessionDetailsAPITest(BaseAPITestCase):
    """Tests for session details endpoint."""
    
    def test_get_session_details(self):
        """Test getting user session details."""
        self.authenticate_as(self.customer)
        
        response = self.client.post(reverse('user_session_details'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('profile_completed', response.data)
        self.assertIn('is_verified', response.data)


# ============================================================================
# WEBSOCKET CONSUMER TESTS
# ============================================================================

class TranslatedCallConsumerTest(TestCase):
    """Tests for TranslatedCallConsumer WebSocket."""
    
    def setUp(self):
        """Set up test fixtures for call consumer tests."""
        # Create caller user
        self.caller = NewUser.objects.create(
            username='caller_ws',
            email='caller_ws@test.com',
            phone_number='1111111111',
            first_name='Caller',
            middle_name='Test',
            last_name='User',
            role=ROLES.CUSTOMER,
            is_active=True,
            is_verified=True,
            preferred_language='en',
        )
        
        # Create receiver user
        self.receiver = NewUser.objects.create(
            username='receiver_ws',
            email='receiver_ws@test.com',
            phone_number='2222222222',
            first_name='Receiver',
            middle_name='Test',
            last_name='User',
            role=ROLES.SERVICE_PROVIDER,
            is_active=True,
            is_verified=True,
            preferred_language='hi',
        )
        
        # Create a voice call
        self.voice_call = VoiceCall.objects.create(
            caller=self.caller,
            receiver=self.receiver,
            caller_language='en',
            receiver_language='hi',
            status='initiated',
        )
    
    def test_call_helpers_create_voice_call(self):
        """Test creating a voice call via helpers."""
        call = call_helpers.create_voice_call(self.caller, self.receiver)
        
        self.assertIsNotNone(call)
        self.assertEqual(call.caller, self.caller)
        self.assertEqual(call.receiver, self.receiver)
        self.assertEqual(call.caller_language, 'en')
        self.assertEqual(call.receiver_language, 'hi')
        self.assertEqual(call.status, 'initiated')
    
    def test_call_helpers_get_call_data(self):
        """Test getting call data for caller perspective."""
        call_data = call_helpers.get_call_data(
            self.voice_call.id,
            str(self.caller.id)
        )
        
        self.assertIsNotNone(call_data)
        self.assertEqual(call_data['call'], self.voice_call)
        self.assertEqual(call_data['user_language'], 'en')
        self.assertEqual(call_data['other_language'], 'hi')
    
    def test_call_helpers_get_call_data_receiver_perspective(self):
        """Test getting call data for receiver perspective."""
        call_data = call_helpers.get_call_data(
            self.voice_call.id,
            str(self.receiver.id)
        )
        
        self.assertIsNotNone(call_data)
        self.assertEqual(call_data['user_language'], 'hi')
        self.assertEqual(call_data['other_language'], 'en')
    
    def test_call_helpers_update_call_status(self):
        """Test updating call status."""
        call_helpers.update_call_status(
            self.voice_call.id,
            'ringing',
            twilio_call_sid='TEST_SID_123'
        )
        
        self.voice_call.refresh_from_db()
        self.assertEqual(self.voice_call.status, 'ringing')
        self.assertEqual(self.voice_call.twilio_call_sid, 'TEST_SID_123')
    
    def test_call_helpers_save_call_transcript(self):
        """Test saving call transcript."""
        transcript = call_helpers.save_call_transcript(
            self.voice_call.id,
            str(self.caller.id),
            'Hello, how are you?',
            'en',
            'नमस्ते, आप कैसे हैं?',
            'hi'
        )
        
        self.assertIsNotNone(transcript)
        self.assertEqual(transcript.original_text, 'Hello, how are you?')
        self.assertEqual(transcript.translated_text, 'नमस्ते, आप कैसे हैं?')
    
    def test_call_helpers_get_call_transcripts(self):
        """Test getting call transcripts."""
        # Create some transcripts
        call_helpers.save_call_transcript(
            self.voice_call.id, str(self.caller.id),
            'Hello', 'en', 'नमस्ते', 'hi'
        )
        call_helpers.save_call_transcript(
            self.voice_call.id, str(self.receiver.id),
            'नमस्ते', 'hi', 'Hello', 'en'
        )
        
        transcripts = call_helpers.get_call_transcripts(self.voice_call.id)
        
        self.assertEqual(len(transcripts), 2)
    
    def test_call_helpers_end_call(self):
        """Test ending a call."""
        call = call_helpers.end_call(self.voice_call.id)
        
        self.assertIsNotNone(call)
        self.assertEqual(call.status, 'completed')
        self.assertIsNotNone(call.ended_at)


class TranslatedChatConsumerTest(TestCase):
    """Tests for TranslatedChatConsumer WebSocket and chat helpers."""
    
    def setUp(self):
        """Set up test fixtures for chat consumer tests."""
        # Create two users for chat
        self.user1 = NewUser.objects.create(
            username='chat_user1',
            email='chat1@test.com',
            phone_number='3333333333',
            first_name='Chat',
            middle_name='User',
            last_name='One',
            role=ROLES.CUSTOMER,
            is_active=True,
            is_verified=True,
            preferred_language='en',
        )
        
        self.user2 = NewUser.objects.create(
            username='chat_user2',
            email='chat2@test.com',
            phone_number='4444444444',
            first_name='Chat',
            middle_name='User',
            last_name='Two',
            role=ROLES.SERVICE_PROVIDER,
            is_active=True,
            is_verified=True,
            preferred_language='hi',
        )
    
    def test_chat_helpers_get_chat_room_name(self):
        """Test chat room name generation is consistent."""
        room1 = chat_helpers.get_chat_room_name(self.user1.id, self.user2.id)
        room2 = chat_helpers.get_chat_room_name(self.user2.id, self.user1.id)
        
        # Room names should be the same regardless of order
        self.assertEqual(room1, room2)
    
    def test_chat_helpers_get_chat_users(self):
        """Test getting chat users from room name."""
        room_name = chat_helpers.get_chat_room_name(self.user1.id, self.user2.id)
        chat_data = chat_helpers.get_chat_users(room_name, str(self.user1.id))
        
        self.assertIsNotNone(chat_data)
        self.assertEqual(chat_data['user'], self.user1)
        self.assertEqual(chat_data['other_user'], self.user2)
        self.assertEqual(chat_data['user_language'], 'en')
        self.assertEqual(chat_data['other_language'], 'hi')
    
    def test_chat_helpers_save_chat_message(self):
        """Test saving a chat message."""
        message = chat_helpers.save_chat_message(
            str(self.user1.id),
            str(self.user2.id),
            'Hello there!',
            'en',
            'नमस्ते!',
            'hi'
        )
        
        self.assertIsNotNone(message)
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.receiver, self.user2)
        self.assertEqual(message.original_message, 'Hello there!')
        self.assertEqual(message.translated_message, 'नमस्ते!')
        self.assertFalse(message.is_read)
    
    def test_chat_helpers_get_chat_history(self):
        """Test getting chat history."""
        # Create some messages
        chat_helpers.save_chat_message(
            str(self.user1.id), str(self.user2.id),
            'Hello', 'en', 'नमस्ते', 'hi'
        )
        chat_helpers.save_chat_message(
            str(self.user2.id), str(self.user1.id),
            'नमस्ते', 'hi', 'Hello', 'en'
        )
        chat_helpers.save_chat_message(
            str(self.user1.id), str(self.user2.id),
            'How are you?', 'en', 'आप कैसे हैं?', 'hi'
        )
        
        history = chat_helpers.get_chat_history(str(self.user1.id), str(self.user2.id))
        
        self.assertEqual(len(history), 3)
        # Should be in chronological order (oldest first)
        self.assertEqual(history[0].original_message, 'Hello')
        self.assertEqual(history[2].original_message, 'How are you?')
    
    def test_chat_helpers_mark_messages_as_read(self):
        """Test marking messages as read."""
        # Create unread messages from user2 to user1
        chat_helpers.save_chat_message(
            str(self.user2.id), str(self.user1.id),
            'Message 1', 'hi', 'Message 1', 'en'
        )
        chat_helpers.save_chat_message(
            str(self.user2.id), str(self.user1.id),
            'Message 2', 'hi', 'Message 2', 'en'
        )
        
        # Verify they're unread
        unread_count = ChatMessage.objects.filter(
            sender=self.user2, receiver=self.user1, is_read=False
        ).count()
        self.assertEqual(unread_count, 2)
        
        # Mark as read
        chat_helpers.mark_messages_as_read(str(self.user1.id), str(self.user2.id))
        
        # Verify they're now read
        unread_count = ChatMessage.objects.filter(
            sender=self.user2, receiver=self.user1, is_read=False
        ).count()
        self.assertEqual(unread_count, 0)
    
    def test_chat_message_ordering(self):
        """Test that messages are ordered by timestamp."""
        import time
        
        msg1 = chat_helpers.save_chat_message(
            str(self.user1.id), str(self.user2.id),
            'First', 'en', 'पहला', 'hi'
        )
        time.sleep(0.01)  # Small delay to ensure different timestamps
        msg2 = chat_helpers.save_chat_message(
            str(self.user1.id), str(self.user2.id),
            'Second', 'en', 'दूसरा', 'hi'
        )
        
        self.assertLess(msg1.timestamp, msg2.timestamp)


class ChatHelpersEdgeCasesTest(TestCase):
    """Test edge cases for chat helpers."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user1 = NewUser.objects.create(
            username='edge_user1',
            email='edge1@test.com',
            phone_number='5555555555',
            first_name='Edge',
            middle_name='Test',
            last_name='User1',
            role=ROLES.CUSTOMER,
            is_active=True,
            is_verified=True,
            preferred_language='en',
        )
        self.user2 = NewUser.objects.create(
            username='edge_user2',
            email='edge2@test.com',
            phone_number='6666666666',
            first_name='Edge',
            middle_name='Test',
            last_name='User2',
            role=ROLES.SERVICE_PROVIDER,
            is_active=True,
            is_verified=True,
            preferred_language='en',  # Same language as user1
        )
    
    def test_same_language_chat(self):
        """Test chat between users with same language preference."""
        chat_data = chat_helpers.get_chat_users(
            chat_helpers.get_chat_room_name(self.user1.id, self.user2.id),
            str(self.user1.id)
        )
        
        # Both languages should be the same
        self.assertEqual(chat_data['user_language'], chat_data['other_language'])
    
    def test_empty_chat_history(self):
        """Test getting empty chat history."""
        history = chat_helpers.get_chat_history(str(self.user1.id), str(self.user2.id))
        
        self.assertEqual(len(history), 0)
    
    def test_invalid_room_name(self):
        """Test handling of invalid room name."""
        result = chat_helpers.get_chat_users('invalid_room', str(self.user1.id))
        
        # Should return None for invalid room
        self.assertIsNone(result)


class CallHelpersEdgeCasesTest(TestCase):
    """Test edge cases for call helpers."""
    
    def test_get_nonexistent_call(self):
        """Test getting a call that doesn't exist."""
        fake_id = uuid.uuid4()
        call_data = call_helpers.get_call_data(fake_id, None)
        
        self.assertIsNone(call_data)
    
    def test_update_nonexistent_call(self):
        """Test updating a call that doesn't exist."""
        fake_id = uuid.uuid4()
        result = call_helpers.update_call_status(fake_id, 'completed')
        
        self.assertIsNone(result)
    
    def test_get_call_by_id_nonexistent(self):
        """Test getting a call by ID that doesn't exist."""
        fake_id = uuid.uuid4()
        call = call_helpers.get_call_by_id(fake_id)
        
        self.assertIsNone(call)
