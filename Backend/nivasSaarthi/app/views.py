from django.http import HttpResponse
from app.utils import call_helpers, chat_helpers
from app import twilio_service
from .serializers import UserRegistrationSerializer, UserBaseRegistrationSerializer
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsVerifiedAndAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .models import ROLES, NewUser, Service, ServiceRequest, ServiceProviderProfile, Notifications, SOSRequest, Blacklist, EmergencyContact, VoiceCall, CallTranscript, WebhookSubscription
from rest_framework.response import Response
from django.core.mail import send_mail
from django.db.models import Q
from rest_framework import status
import pyotp
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.gis.geos import Point
import tempfile
import os
from django.core.files import File
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt



#################################### AUTH VIEWS ####################################
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = UserBaseRegistrationSerializer(data=request.data)
    if NewUser.objects.filter(email=request.data.get('email')).exists():
        return Response({"error": "Email already registered"}, status=status.HTTP_400_BAD_REQUEST)
    if serializer.is_valid():
        if serializer.validated_data['password'] != serializer.validated_data['confirm_password']:
            return Response({"error": "Password and confirm password do not match"}, status=status.HTTP_400_BAD_REQUEST)
        user = NewUser.objects.create(
            username = serializer.validated_data['email'].split('@')[0],
            email=serializer.validated_data['email'],
            password=serializer.validated_data['password']
        )
        user.totp_secret = pyotp.random_base32()
        user.is_active = True
        user.is_verified = True
        refresh = RefreshToken.for_user(user)
        Notifications.objects.create(
            user=user,
            title="Welcome to Nivas Saarthi",
            message="Your account has been successfully verified.",
            notification_type = 'info'
        )
        user.save()
        return Response({"message": "User registered successfully", "user_id": user.id, "access": str(refresh.access_token), "refresh": str(refresh)}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_totp(request):
    totp_code = request.data.get('totp_code')
    # Ensure totp_code is a string and zero-padded to 6 digits
    if totp_code is not None:
        totp_code = str(totp_code).zfill(6)
    user_id = request.data.get('user_id')
    try:
        user = NewUser.objects.get(id=user_id)
        if user.otp_retries <= 0:
            user.otp_retries = 3
            user.delete()
            return Response({"error": "Maximum OTP retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)
        totp = pyotp.TOTP(user.totp_secret)
        # valid_window=2 allows codes from 2 time windows before/after (±60 seconds)
        if totp.verify(totp_code, valid_window=2):
            user.is_verified = True
            user.is_active = True  # Make sure this is set!
            user.otp_retries = 3
            user.save()
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            Notifications.objects.create(
                user=user,
                title="Welcome to Nivas Saarthi",
                message="Your account has been successfully verified.",
                notification_type = 'info'
            )
            return Response({
                "message": "TOTP verified successfully",
                "access": str(refresh.access_token),
                "refresh": str(refresh)
            }, status=status.HTTP_200_OK)
        else:
            user.otp_retries -= 1
            send_mail(
                subject="Your OTP for Nivas Saarthi Registration - Retry",
                message=f"Your OTP code is: {pyotp.TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
                from_email=os.getenv('EMAIL_SENDER_ID'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            user.save()
            return Response({"error": "Invalid OTP code, Another OTP has been sent to your email"}, status=status.HTTP_400_BAD_REQUEST)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    email = request.data.get('email')
    try:
        user = NewUser.objects.get(email=email)
        user.otp_retries = 3 
        user.save()
        send_mail(
            subject="Your OTP for Nivas Saarthi Password Reset",
            message=f"Your OTP code is: {pyotp.TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.",
            from_email=os.getenv('EMAIL_SENDER_ID'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return Response({"message": "Password reset OTP sent to email"}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get('email')
    password = request.data.get('password')
    try:
        user = NewUser.objects.get(email=email)
        if not user.is_verified:
            return Response({"error": "Email not verified"}, status=status.HTTP_403_FORBIDDEN)
        if user.check_password(password):
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "Login successful",
                "access": str(refresh.access_token),
                "refresh": str(refresh)
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    
@api_view(['GET'])
@permission_classes([AllowAny])
def user_session_details(request):
    user = request.user
    return Response({"profile_completed": user.profile_completed, "is_verified": user.is_verified, "user_id": user.id}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def logout_view(request):
    # JWT is stateless - just return success
    # Client should discard the tokens
    return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    try:
        email = request.data.get('email')
        totp_code = request.data.get('totp_code')
        # Ensure totp_code is a string and zero-padded to 6 digits
        if totp_code is not None:
            totp_code = str(totp_code).zfill(6)
        new_password = request.data.get('new_password')
        user = NewUser.objects.get(email=email)
        totp = pyotp.TOTP(user.totp_secret)
        if user.otp_retries <= 0:
            user.otp_retries = 3
            user.save()
            return Response({"error": "Maximum OTP retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)
        # valid_window=2 allows codes from 2 time windows before/after (±60 seconds)
        if totp.verify(totp_code, valid_window=2):
            user.set_password(new_password)
            user.totp_secret = None
            user.otp_retries = 3 
            user.save()
            return Response({"message": "Password reset successfully"}, status=status.HTTP_200_OK)
        else:
            user.otp_retries -= 1
            send_mail(
                subject="Your OTP for Nivas Saarthi Password Reset - Retry",
                message=f"Your OTP code is: {pyotp.TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
                from_email=os.getenv('EMAIL_SENDER_ID'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            user.save()
            return Response({"error": "Invalid OTP code"}, status=status.HTTP_400_BAD_REQUEST)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([AllowAny])
def resend_totp(request):
    user_id = request.data.get('user_id')
    try:
        user = NewUser.objects.get(id=user_id)
        if user.otp_retries > 0:
            user.otp_retries -= 1
            user.save()
            send_mail(
                subject="Your OTP for Nivas Saarthi Registration - Resent",
                message=f"Your OTP code is: {pyotp.TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
                from_email=os.getenv('EMAIL_SENDER_ID'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            return Response({"message": "TOTP resent successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Maximum OTP retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def profile_completion(request):
    user = request.user
    if user.profile_completed:
        return Response({"message": "Profile is already marked as completed"}, status=status.HTTP_200_OK)
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    city = request.data.get('city')
    role = request.data.get('role')
    phone_number = request.data.get('phone_number')
    address = request.data.get('address')
    state = request.data.get('state')
    pincode = request.data.get('pincode')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    user.first_name = first_name
    user.last_name = last_name
    user.city = city
    user.role = role
    user.phone_number = phone_number
    user.address = address
    user.state = state
    user.pincode = pincode
    if latitude and longitude:
        user.location = Point(float(longitude), float(latitude), srid=4326)
    if user.role == ROLES.SERVICE_PROVIDER:
        bio = request.data.get('bio', '')
        years_of_experience = request.data.get('years_of_experience', 0)
        average_rating = 2.5
        services = request.data.get('services', '')
        service_provider = ServiceProviderProfile.objects.create(user=user, bio=bio, years_of_experience=years_of_experience, average_rating=average_rating, services=services)
    user.profile_completed = True
    user.save()
    return Response({"message": "Profile marked as completed", "user_details": {
        'id': str(user.id),
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'phone_number': user.phone_number,
        'role': user.role,
        'city': user.city,
        'state': user.state,
        'address': user.address,
        'pincode': user.pincode,
        'location': {
            'latitude': user.location.y if user.location else None,
            'longitude': user.location.x if user.location else None
        }
    }, "provider_details": {
        'bio': service_provider.bio if hasattr(user, 'service_provider_profile') else '',
        'years_of_experience': service_provider.years_of_experience if hasattr(user, 'service_provider_profile') else 0,
        'average_rating': service_provider.average_rating if hasattr(user, 'service_provider_profile') else 0.0,
        'services': service_provider.get_services_list() if hasattr(user, 'service_provider_profile') else []
    }}, status=status.HTTP_200_OK)
    


################################### SERVICE VIEWS ###################################
@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_services_for_provider(request):
    provider_id = request.query_params.get('provider_id')
    if not provider_id:
        return Response({'message': 'Provider ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        provider = NewUser.objects.get(id=provider_id, role=ROLES.SERVICE_PROVIDER)
        if provider != request.user:
            return Response({'message': 'Unauthorized access to services'}, status=status.HTTP_403_FORBIDDEN)
        provider_profile = ServiceProviderProfile.objects.get(user=provider)
        services = Service.objects.filter(service_provider=provider).order_by('-requested_on')
        services_data = [{
            'id': str(service.id),
            'customer': service.customer.first_name + " " + service.customer.last_name,
            'description': service.description,
            'requested_on': service.requested_on,
            'completed': (service.service_status == 'COMPLETED')
        } for service in services]
        return Response({'services': services_data}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({'message': 'Service provider not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_incoming_requests(request):
    try:
        provider = request.user
        if provider.role != ROLES.SERVICE_PROVIDER:
            return Response({'message': 'Only service providers can view incoming requests'}, status=status.HTTP_403_FORBIDDEN)
        service_requests = ServiceRequest.objects.filter(service_provider=provider, status='PENDING').order_by('-requested_on')
        requests_data = [{
            'id': str(req.id),
            'customer': req.customer.first_name + " " + req.customer.last_name,
            'description': req.description,
            'requested_on': req.requested_on
        } for req in service_requests]
        return Response({'service_requests': requests_data}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({'message': 'Service provider not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_outgoing_requests(request):
    try:
        customer = request.user
        if customer.role != ROLES.CUSTOMER:
            return Response({'message': 'Only customers can view outgoing requests'}, status=status.HTTP_403_FORBIDDEN)
        service_requests = ServiceRequest.objects.filter(customer=customer).order_by('-requested_on')
        requests_data = [{
            'id': str(req.id),
            'service_provider': req.service_provider.first_name + " " + req.service_provider.last_name,
            'description': req.description,
            'status': req.status,
            'requested_on': req.requested_on
        } for req in service_requests]
        return Response({'service_requests': requests_data}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({'message': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_services_for_customer(request):
    customer_id = request.query_params.get('customer_id')
    if not customer_id:
        return Response({'message': 'Customer ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        customer = NewUser.objects.get(id=customer_id, role=ROLES.CUSTOMER)
        if customer != request.user:
            return Response({'message': 'Unauthorized access to services'}, status=status.HTTP_403_FORBIDDEN)
        services = Service.objects.filter(customer=customer).order_by('-requested_on')
        services_data = [{
            'id': str(service.id),
            'service_provider': service.service_provider.first_name + " " + service.service_provider.last_name,
            'description': service.description,
            'requested_on': service.requested_on
        } for service in services]
        return Response({'services': services_data}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({'message': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_service_details(request):
    try:
        service_id = request.query_params.get('service_id')
        if not service_id:
            return Response({'message': 'Service ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role == ROLES.SERVICE_PROVIDER:
            service = Service.objects.get(id=service_id, service_provider=request.user)
        else:
            service = Service.objects.get(id=service_id, customer=request.user)
        if service is None:
            return Response({'message': 'Unauthorized access to service details'}, status=status.HTTP_403_FORBIDDEN)
        service_data = {
            'id': str(service.id),
            'customer': service.customer.first_name + " " + service.customer.last_name,
            'service_provider': service.service_provider.first_name + " " + service.service_provider.last_name,
            'description': service.description,
            'requested_on': service.requested_on
        }
        return Response({'service': service_data}, status=status.HTTP_200_OK)
    except Service.DoesNotExist:
        return Response({'message': 'Service not found'}, status=status.HTTP_404_NOT_FOUND)
    
@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def complete_service(request):
    service_id = request.data.get('service_id')
    if not service_id:
        return Response({'message': 'Service ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        service = Service.objects.get(id=service_id)
        if service.customer == request.user:
            service.completion_verification_from_customer = True
        elif service.service_provider == request.user:
            service.completion_verification_from_provider = True
        else:
            return Response({'message': 'Unauthorized access to complete service'}, status=status.HTTP_403_FORBIDDEN)
        service.save()
        return Response({'message': 'Service marked as completed'}, status=status.HTTP_200_OK)
    except Service.DoesNotExist:
        return Response({'message': 'Service not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def request_service(request):
    """
    Create a new service request from customer to provider.
    
    Required fields:
    - provider_id: UUID of the service provider
    - description: Description of service needed
    
    Optional fields:
    - customer_budget: Customer's budget for negotiation
    - requested_date: When the service is needed
    - service_latitude: Latitude of service location
    - service_longitude: Longitude of service location
    """
    # Get authenticated user as customer
    customer = request.user
    
    # Verify user is a customer
    if customer.role != ROLES.CUSTOMER:
        return Response(
            {'message': 'Only customers can request services'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get request data
    provider_id = request.data.get('provider_id')
    description = request.data.get('description')
    requested_date = request.data.get('requested_date')
    customer_budget = request.data.get('customer_budget')
    service_latitude = request.data.get('service_latitude')
    service_longitude = request.data.get('service_longitude')
    
    # Validate required fields
    if not all([provider_id, description]):
        return Response(
            {'message': 'Provider ID and Description are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Get provider
        provider = NewUser.objects.get(id=provider_id, role=ROLES.SERVICE_PROVIDER)
        
        # Validate distance if service location is provided
        distance_km = None
        if service_latitude and service_longitude:
            if not provider.location:
                return Response(
                    {'message': 'Provider location not available for distance calculation'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                service_location = Point(float(service_longitude), float(service_latitude), srid=4326)
                
                # Calculate distance using PostGIS
                provider_with_dist = NewUser.objects.filter(id=provider_id).annotate(
                    distance=Distance('location', service_location)
                ).first()
                
                if provider_with_dist and provider_with_dist.distance:
                    distance_km = provider_with_dist.distance.km
                    
                    # Check if within acceptable range (configurable)
                    MAX_DISTANCE_KM = 50  # You can make this configurable
                    if distance_km > MAX_DISTANCE_KM:
                        return Response({
                            'message': f'Provider is {distance_km:.1f}km away from the service location. Maximum allowed distance is {MAX_DISTANCE_KM}km.',
                            'distance_km': round(distance_km, 2),
                            'provider_location': {
                                'latitude': provider.latitude,
                                'longitude': provider.longitude
                            },
                            'service_location': {
                                'latitude': service_latitude,
                                'longitude': service_longitude
                            }
                        }, status=status.HTTP_400_BAD_REQUEST)
                        
            except (ValueError, TypeError) as e:
                return Response(
                    {'message': f'Invalid service location coordinates: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Parse customer budget if provided
        if customer_budget:
            try:
                customer_budget = Decimal(str(customer_budget))
            except (ValueError, TypeError):
                return Response(
                    {'message': 'Invalid customer_budget format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Parse requested date if provided
        if requested_date:
            from datetime import datetime
            try:
                if isinstance(requested_date, str):
                    requested_date = datetime.fromisoformat(requested_date.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return Response(
                    {'message': 'Invalid requested_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            requested_date = timezone.now()
        
        # Create service request
        service_request = ServiceRequest.objects.create(
            customer=customer,
            service_provider=provider,
            description=description,
            requested_on=requested_date,
            customer_budget=customer_budget,
            status='PENDING',
            negotiation_status='NOT_STARTED'
        )
        
        # Create notification for provider
        notification_message = (
            f"New service request from {customer.first_name} {customer.last_name}. "
            f"Service: {description[:100]}"
        )
        if customer_budget:
            notification_message += f" Budget: ₹{customer_budget}"
        
        Notifications.objects.create(
            user=provider,
            title="🔔 New Service Request",
            message=notification_message,
            notification_type='new_service_request',
        )
        
        # Build response
        response_data = {
            'message': 'Service requested successfully',
            'service_request': {
                'id': str(service_request.id),
                'description': service_request.description,
                'status': service_request.status,
                'customer_budget': float(customer_budget) if customer_budget else None,
                'requested_on': service_request.requested_on.isoformat(),
                'provider': {
                    'id': str(provider.id),
                    'name': f"{provider.first_name} {provider.last_name}",
                    'phone': provider.phone_number,
                    'city': provider.city
                }
            }
        }
        
        if distance_km is not None:
            response_data['service_request']['distance_km'] = round(distance_km, 2)
        
        return Response(response_data, status=status.HTTP_201_CREATED)
        
    except NewUser.DoesNotExist:
        return Response(
            {'message': 'Service Provider not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'message': f'Error creating service request: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def accept_service_request(request):
    service_request_id = request.data.get('service_request_id')
    if not service_request_id:
        return Response({'message': 'Service Request ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        service_request = ServiceRequest.objects.get(id=service_request_id, service_provider=request.user)
        service_request.service_acceptance = True
        service_request.status = "ACCEPTED"
        Service.objects.create(
            customer=service_request.customer,
            service_provider=service_request.service_provider,
            description=service_request.description,
            requested_on=service_request.requested_on,
            negotiated_price=service_request.negotiated_price
        )
        # Create notification for customer
        notification = Notifications.objects.create(
            user=service_request.customer
        )
        notification.form_message({
            'event': 'service_request_accepted',
            'service_description': service_request.description,
            'service_provider_name': service_request.service_provider.first_name,
            'negotiated_offer': f"An offer of ₹{service_request.negotiated_price} has been accepted for your service request." if service_request.negotiated_price else "Your service request has been accepted."
        })
        notification.save()
        service_request.save()
        return Response({'message': 'Service request accepted'}, status=status.HTTP_200_OK)
    except ServiceRequest.DoesNotExist:
        return Response({'message': 'Service request not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def reject_service_request(request):
    service_request_id = request.data.get('service_request_id')
    if not service_request_id:
        return Response({'message': 'Service Request ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        service_request = ServiceRequest.objects.get(id=service_request_id, service_provider=request.user)
        service_request.service_acceptance = False
        service_request.status = "REJECTED"
        service_request.save()
        # Create notification for customer
        notification = Notifications.objects.create(
            user=service_request.customer
        )
        notification.form_message({
            'event': 'service_request_rejected',
            'service_description': service_request.description,
            'service_provider_name': service_request.service_provider.first_name,
        })
        notification.save()
        return Response({'message': 'Service request rejected'}, status=status.HTTP_200_OK)
    except ServiceRequest.DoesNotExist:
        return Response({'message': 'Service request not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_nearby_providers(request):
    """
    Find service providers near a given location.
    
    Query Parameters:
    - latitude: User's latitude coordinate (required)
    - longitude: User's longitude coordinate (required)
    - radius_km: Search radius in kilometers (default: 5)
    - service_type: Comma-separated list of service types to filter by (optional)
    
    Example: /api/nearby-providers/?latitude=28.3573131&longitude=75.5881653&radius_km=10&service_type=Plumber
    """
    lat = request.query_params.get('latitude')
    lon = request.query_params.get('longitude')
    radius_km = request.query_params.get('radius_km', 5)
    service_type = request.query_params.get('service_type')
    
    # Validate required parameters
    if not lat or not lon:
        return Response(
            {'message': 'Latitude and longitude are required query parameters.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        lat = float(lat)
        lon = float(lon)
        radius_km = float(radius_km)
        user_location = Point(lon, lat, srid=4326)
    except (ValueError, TypeError) as e:
        return Response(
            {'message': f'Invalid parameter values: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Query providers within radius
    providers_qs = NewUser.objects.filter(
        role=ROLES.SERVICE_PROVIDER,
        location__isnull=False,
        profile_completed=True  # Only show providers with completed profiles
    ).annotate(
        distance=Distance('location', user_location)
    ).filter(
        distance__lte=D(km=radius_km)
    ).select_related('service_provider_profile').order_by('distance')
    
    # Filter by service type if specified
    if service_type:
        service_types = [s.strip().lower() for s in service_type.split(',')]
        q_filter = Q()
        for st in service_types:
            q_filter |= Q(service_provider_profile__services__icontains=st)
        providers_qs = providers_qs.filter(q_filter)
    
    providers_list = list(providers_qs)
    
    # Build response data
    providers_data = []
    for p in providers_list:
        try:
            provider_data = {
                'id': str(p.id),
                'first_name': p.first_name or '',
                'last_name': p.last_name or '',
                'phone_number': p.phone_number or '',
                'email': p.email or '',
                'city': p.city or '',
                'address': p.address or '',
                'distance_km': round(p.distance.km, 2) if hasattr(p, 'distance') and p.distance else None,
            }
            
            # Add service provider profile data
            profile = getattr(p, 'service_provider_profile', None)
            if profile:
                provider_data.update({
                    'average_rating': float(profile.average_rating) if profile.average_rating else 0.0,
                    'years_of_experience': int(profile.years_of_experience) if profile.years_of_experience else 0,
                    'services': profile.get_services_list(),
                    'bio': profile.bio or '',
                })
            else:
                provider_data.update({
                    'average_rating': 0.0,
                    'years_of_experience': 0,
                    'services': [],
                    'bio': '',
                })
            
            providers_data.append(provider_data)
        except Exception as e:
            print(f"Error processing provider {p.id}: {str(e)}")
            continue
    
    return Response({
        'providers': providers_data,
        'count': len(providers_data),
        'search_radius_km': radius_km,
        'search_location': {'latitude': lat, 'longitude': lon}
    }, status=status.HTTP_200_OK)

################################### NOTIFICATION VIEWS ###################################
@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_notifications(request):
    notifications = Notifications.objects.filter(user=request.user).order_by('-created_at')
    notifications_data = [{
        'id': str(notification.id),
        'message': notification.message,
        'created_at': notification.created_at,
        'read': notification.is_read
    } for notification in notifications]
    return Response({'notifications': notifications_data}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def mark_notification_as_read(request, notification_id):
    try:
        notification = Notifications.objects.get(id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        return Response({'message': 'Notification marked as read'}, status=status.HTTP_200_OK)
    except Notifications.DoesNotExist:
        return Response({'message': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_unread_notification_count(request):
    unread_count = Notifications.objects.filter(user=request.user, is_read=False).count()
    return Response({'unread_count': unread_count}, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def mark_all_notifications_as_read(request):
    Notifications.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'message': 'All notifications marked as read'}, status=status.HTTP_200_OK)


################################### EMERGENCY VIEWS ###################################
@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def report_emergency(request, service_id):
    try:
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        user = request.user
        if not latitude or not longitude:
            return Response({'message': 'Latitude and longitude are required'}, status=status.HTTP_400_BAD_REQUEST)
        location = Point(float(longitude), float(latitude), srid=4326)
        emergency = SOSRequest.objects.create(
            user=user,
            longitude=location.x,
            latitude=location.y,
            culprit = NewUser.objects.get(id=Service.objects.get(id=service_id).service_provider.id)
        )
        Blacklist.objects.create(blocked_user=emergency.culprit, user=user)
        emergency.save()
        emergency_contacts = EmergencyContact.objects.filter(user=user)
        for contact in emergency_contacts:
            # Send SMS via Twilio
            twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            twilio_phone = os.getenv('TWILIO_PHONE_NUMBER')
            
            if twilio_account_sid and twilio_auth_token and twilio_phone:
                try:
                    client = twilio_service.get_twilio_client()
                    message = client.messages.create(
                        body=f"Emergency Alert! {user.first_name} {user.last_name} has reported an emergency.\nLocation: https://www.google.com/maps/search/?api=1&query={latitude},{longitude}\nTime: {emergency.reported_on.strftime('%Y-%m-%d %H:%M:%S')}",
                        from_=twilio_phone,
                        to=contact.phone_number
                    )
                except Exception as e:
                    print(f"SMS sending failed: {str(e)}")

        notification = Notifications.objects.create(
            user=user
        )

        notification.form_message({
            'event': 'emergency_reported',
            'latitude': latitude,
            'longitude': longitude,
            'reported_on': emergency.requested_on.strftime("%Y-%m-%d %H:%S")
        })
        notification.save()
        return Response({'message': 'Emergency reported successfully'}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'message': 'Error reporting emergency', 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def resolve_emergency(request, emergency_id):
    try:
        emergency = SOSRequest.objects.get(id=emergency_id, user=request.user)
        if Blacklist.objects.filter(user=emergency.culprit).exists():
            return Response({'message': 'Cannot resolve emergency involving a blacklisted user'}, status=status.HTTP_403_FORBIDDEN)
        emergency.resolved = True
        emergency.save()
        return Response({'message': 'Emergency marked as resolved'}, status=status.HTTP_200_OK)
    except SOSRequest.DoesNotExist:
        return Response({'message': 'Emergency not found'}, status=status.HTTP_404_NOT_FOUND)
################################### SARVAM VIEWS ###################################
@permission_classes([IsVerifiedAndAuthenticated])
@api_view(['POST'])
def speech_to_text_server(request):
    audio_file = request.FILES.get('audio')
    if not audio_file:
        return Response({'message': 'Audio file provided is missing!'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Save to temp file
    temp_audio_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            for chunk in audio_file.chunks():
                temp_audio.write(chunk)
            temp_audio_path = temp_audio.name
        
        from sarvamai import SarvamAI
        api_key = os.getenv("SARVAM_API_KEY")
        if not api_key:
             return Response({'message': 'SARVAM_API_KEY not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        client = SarvamAI(api_subscription_key=api_key)
        
        with open(temp_audio_path, "rb") as f:
            response = client.speech_to_text.transcribe(
                file=f,
                model="saarika:v2.5",
                language_code="unknown"
            )
        
        # Clean up temp file
        os.unlink(temp_audio_path)
        temp_audio_path = None

        # Determine how to extract transcript based on response type
        transcript = ""
        if hasattr(response, 'transcript'):
            transcript = response.transcript
        elif isinstance(response, dict) and 'transcript' in response:
            transcript = response['transcript']
        else:
             # Fallback: try to serialize or stringify
            transcript = str(response)

        return Response({'transcript': transcript}, status=status.HTTP_200_OK)

    except Exception as e:
        if temp_audio_path and os.path.exists(temp_audio_path):
             os.unlink(temp_audio_path)
        return Response({'message': 'Error in speech to text', 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@permission_classes([IsVerifiedAndAuthenticated])
@api_view(['POST'])
def text_to_speech_server(request):
    text = request.data.get('text')
    language = request.data.get('language', 'en-IN')
    
    if not text:
        return Response({'message': 'Text is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Supported Sarvam language codes (API accepts these exact codes)
    sarvam_languages = [
        'bn-IN',  # Bengali
        'gu-IN',  # Gujarati
        'kn-IN',  # Kannada
        'ml-IN',  # Malayalam
        'mr-IN',  # Marathi
        'od-IN',  # Odia (note: od-IN, not or-IN)
        'pa-IN',  # Punjabi
        'ta-IN',  # Tamil
        'te-IN',  # Telugu
        'hi-IN'   # Hindi
    ]
    
    # Map frontend language codes to Sarvam API codes
    lang_mapping = {
        'or-IN': 'od-IN',  # Odia mapping
    }
    
    # Apply mapping if needed
    sarvam_lang_code = lang_mapping.get(language, language)
    
    if sarvam_lang_code not in sarvam_languages:
        # Language not supported by Sarvam, tell frontend to use browser TTS
        return Response({'message': 'Language not supported by Sarvam, use browser TTS', 'use_browser_tts': True}, status=status.HTTP_200_OK)
    
    temp_audio_path = None
    try:
        from sarvamai import SarvamAI
        from sarvamai.play import save
        import base64
        
        api_key = os.getenv("SARVAM_API_KEY")
        if not api_key:
            return Response({'message': 'SARVAM_API_KEY not configured', 'use_browser_tts': True}, status=status.HTTP_200_OK)
        
        client = SarvamAI(api_subscription_key=api_key)
        
        # Use Sarvam SDK's convert method
        response = client.text_to_speech.convert(
            text=text,
            target_language_code=sarvam_lang_code,
            enable_preprocessing=True
        )
        
        # Save response to temporary file using Sarvam's save utility
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio_path = temp_audio.name
        
        # Use Sarvam's save function to properly save the audio
        save(response, temp_audio_path)
        
        # Read the audio file and encode to base64
        with open(temp_audio_path, 'rb') as audio_file:
            audio_content = audio_file.read()
        
        print(f"Audio file size: {len(audio_content)} bytes")
        
        # Clean up temp file
        os.unlink(temp_audio_path)
        temp_audio_path = None
        
        # Return audio as base64 encoded string
        audio_base64 = base64.b64encode(audio_content).decode('utf-8')
        
        return Response({
            'audio': audio_base64,
            'format': 'wav',
            'use_browser_tts': False
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        print(f"TTS error: {e}")
        import traceback
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.unlink(temp_audio_path)
        # Fallback to browser TTS on any error
        return Response({'message': 'Error in text to speech', 'error': str(e), 'use_browser_tts': True}, status=status.HTTP_200_OK)


##################################### WEBHOOK VIEWS #####################################
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def register_webhook(request):
    """Register a webhook URL for notifications"""
    url = request.data.get('url')
    event_type = request.data.get('event_type', 'notification_count')
    
    if not url:
        return Response({'error': 'URL is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    webhook = WebhookSubscription.objects.create(
        user=request.user,
        url=url,
        event_type=event_type
    )
    
    return Response({
        'message': 'Webhook registered successfully',
        'webhook_id': str(webhook.id),
        'secret': webhook.secret,  # Send this once, user should store it securely
        'url': webhook.url
    }, status=status.HTTP_201_CREATED)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_webhook(request, webhook_id):
    """Delete a webhook subscription"""
    try:
        webhook = WebhookSubscription.objects.get(id=webhook_id, user=request.user)
        webhook.delete()
        return Response({'message': 'Webhook deleted'}, status=status.HTTP_200_OK)
    except WebhookSubscription.DoesNotExist:
        return Response({'error': 'Webhook not found'}, status=status.HTTP_404_NOT_FOUND)

###################################### TWILLIO VIEWS ######################################
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initiate_call(request):
    """Start a translated voice call"""
    receiver_id = request.data.get('receiver_id')
    
    try:
        receiver = NewUser.objects.get(id=receiver_id)
    except NewUser.DoesNotExist:
        return Response({'error': 'Receiver not found'}, status=404)
    
    # Create call record
    call = call_helpers.create_voice_call(request.user, receiver)
    
    # Build callback URLs
    base_url = request.build_absolute_uri('/')[:-1]
    callback_url = f"{base_url}/api/calls/{call.id}/twiml"
    
    # Initiate Twilio calls
    caller_sid = twilio_service.initiate_twilio_call(
        request.user.phone_number,
        f"{callback_url}/caller"
    )
    
    receiver_sid = twilio_service.initiate_twilio_call(
        receiver.phone_number,
        f"{callback_url}/receiver"
    )
    
    # Update call with Twilio SID
    call_helpers.update_call_status(
        call.id,
        'ringing',
        twilio_call_sid=caller_sid
    )
    
    return Response({
        'message': 'Call initiated',
        'call_id': str(call.id),
        'status': 'ringing'
    })

@csrf_exempt
def call_twiml(request, call_id, participant):
    """Generate TwiML for Twilio call"""
    call_data = call_helpers.get_call_data(call_id, None)
    
    if participant == 'caller':
        user_id = str(call_data['call'].caller.id)
    else:
        user_id = str(call_data['call'].receiver.id)
    
    # Build WebSocket URL
    ws_protocol = 'wss' if request.is_secure() else 'ws'
    ws_host = request.get_host()
    websocket_url = f"{ws_protocol}://{ws_host}/ws/call/{call_id}/user/{user_id}/"
    
    twiml = twilio_service.generate_twiml_with_stream(websocket_url)
    
    return HttpResponse(twiml, content_type='text/xml')

@csrf_exempt
def call_status(request, call_id):
    """Handle Twilio status callbacks"""
    status = request.POST.get('CallStatus')
    
    kwargs = {'status': status}
    
    if status == 'completed':
        from datetime import datetime
        kwargs['ended_at'] = datetime.now()
        kwargs['duration'] = int(request.POST.get('CallDuration', 0))
    
    call_helpers.update_call_status(call_id, **kwargs)
    
    return HttpResponse(status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_call_transcript(request, call_id):
    """Get transcript of a completed call"""
    try:
        call = VoiceCall.objects.get(id=call_id)
        
        if call.caller != request.user and call.receiver != request.user:
            return Response({'error': 'Unauthorized'}, status=403)
        
        transcripts = call_helpers.get_call_transcripts(call_id)
        
        transcript_data = [
            {
                'speaker': t.speaker.first_name,
                'original_text': t.original_text,
                'translated_text': t.translated_text,
                'timestamp': t.timestamp.isoformat()
            }
            for t in transcripts
        ]
        
        return Response({
            'call_id': str(call.id),
            'transcripts': transcript_data
        })
    except VoiceCall.DoesNotExist:
        return Response({'error': 'Call not found'}, status=404)

########################################## CHAT BASED VIEWS ##########################################
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chat_room(request, other_user_id):
    """Get or create chat room name for two users"""
    try:
        other_user = NewUser.objects.get(id=other_user_id)
        room_name = chat_helpers.get_chat_room_name(request.user.id, other_user_id)
        
        return Response({
            'room_name': room_name,
            'other_user': {
                'id': str(other_user.id),
                'name': f"{other_user.first_name} {other_user.last_name}",
                'language': other_user.preferred_language
            },
            'websocket_url': f'ws://YOUR_SERVER/ws/chat/{room_name}/user/{request.user.id}/'
        })
    except NewUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chat_history(request, other_user_id):
    """Get chat history with another user"""
    messages = chat_helpers.get_chat_history(request.user.id, other_user_id)
    
    message_data = []
    for msg in messages:
        # Show appropriate version based on who's requesting
        if str(msg.sender.id) == str(request.user.id):
            message_text = msg.original_message
            language = msg.original_language
        else:
            message_text = msg.translated_message
            language = msg.translated_language
        
        message_data.append({
            'sender_id': str(msg.sender.id),
            'message': message_text,
            'language': language,
            'timestamp': msg.timestamp.isoformat(),
            'is_mine': str(msg.sender.id) == str(request.user.id),
            'is_read': msg.is_read
        })
    
    return Response({'messages': message_data})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chat_list(request):
    """Get list of all chats for current user"""
    # Get all users I've chatted with
    sent_to = ChatMessage.objects.filter(
        sender=request.user
    ).values_list('receiver_id', flat=True).distinct()
    
    received_from = ChatMessage.objects.filter(
        receiver=request.user
    ).values_list('sender_id', flat=True).distinct()
    
    # Combine and get unique user IDs
    chat_user_ids = set(list(sent_to) + list(received_from))
    
    chat_list = []
    for user_id in chat_user_ids:
        user = NewUser.objects.get(id=user_id)
        
        # Get last message
        last_message = ChatMessage.objects.filter(
            sender_id__in=[request.user.id, user_id],
            receiver_id__in=[request.user.id, user_id]
        ).order_by('-timestamp').first()
        
        # Get unread count
        unread_count = ChatMessage.objects.filter(
            sender_id=user_id,
            receiver_id=request.user.id,
            is_read=False
        ).count()
        
        chat_list.append({
            'user_id': str(user.id),
            'name': f"{user.first_name} {user.last_name}",
            'language': user.preferred_language,
            'room_name': chat_helpers.get_chat_room_name(request.user.id, user_id),
            'last_message': last_message.translated_message if last_message and last_message.sender_id != request.user.id else (last_message.original_message if last_message else None),
            'last_message_time': last_message.timestamp.isoformat() if last_message else None,
            'unread_count': unread_count
        })
    
    # Sort by last message time
    chat_list.sort(key=lambda x: x['last_message_time'] or '', reverse=True)
    
    return Response({'chats': chat_list})


################################### NEGOTIATION VIEWS ###################################
@csrf_exempt
def whatsapp_webhook(request):
    """
    Twilio webhook for incoming WhatsApp messages.
    This endpoint receives messages from service providers during negotiations.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)
    
    from twilio.twiml.messaging_response import MessagingResponse
    from . import whatsapp_negotiator
    
    # Extract message data from Twilio POST
    from_number = request.POST.get('From', '')  # "whatsapp:+919876543210"
    message_body = request.POST.get('Body', '')
    
    # Clean the phone number (remove "whatsapp:" prefix)
    phone = from_number.replace('whatsapp:', '')
    
    # Process the message through our negotiator
    response_message = whatsapp_negotiator.process_provider_response(phone, message_body)
    
    # Send the AI response back
    if response_message:
        whatsapp_negotiator.send_whatsapp_message(phone, response_message)
    
    # Return empty TwiML (we send messages separately)
    twiml = MessagingResponse()
    return HttpResponse(str(twiml), content_type='text/xml')


@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def start_negotiation(request):
    """
    Start an AI negotiation for a service request.
    
    Request body:
    - service_request_id: UUID of the ServiceRequest
    - max_budget: Maximum price the customer is willing to pay
    - min_acceptable: Price at which to auto-accept (optional, defaults to 80% of max)
    """
    from . import whatsapp_negotiator
    from .models import NegotiationSession
    from decimal import Decimal
    
    service_request_id = request.data.get('service_request_id')
    max_budget = request.data.get('max_budget')
    min_acceptable = request.data.get('min_acceptable')
    
    if not service_request_id or not max_budget:
        return Response(
            {'message': 'service_request_id and max_budget are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        max_budget = Decimal(str(max_budget))
        # Default min_acceptable to 80% of max_budget if not provided
        if min_acceptable:
            min_acceptable = Decimal(str(min_acceptable))
        else:
            min_acceptable = max_budget * Decimal('0.8')
        
        # Verify the user owns this request
        service_request = ServiceRequest.objects.get(id=service_request_id)
        if service_request.customer != request.user:
            return Response(
                {'message': 'You can only negotiate your own service requests'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if there's already an active negotiation
        active_session = NegotiationSession.objects.filter(
            service_request=service_request,
            status='active'
        ).first()
        
        if active_session:
            return Response(
                {'message': 'There is already an active negotiation for this request',
                 'session_id': str(active_session.id)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Start the negotiation
        session = whatsapp_negotiator.start_negotiation(
            service_request_id=service_request_id,
            max_budget=max_budget,
            min_acceptable=min_acceptable
        )
        
        return Response({
            'message': 'Negotiation started successfully',
            'session_id': str(session.id),
            'expires_at': session.expires_at.isoformat()
        }, status=status.HTTP_201_CREATED)
        
    except ServiceRequest.DoesNotExist:
        return Response({'message': 'Service request not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_negotiation_status(request, session_id):
    """Get the current status of a negotiation session"""
    from .models import NegotiationSession
    
    try:
        session = NegotiationSession.objects.get(id=session_id)
        
        # Verify user has access
        if session.service_request.customer != request.user:
            return Response({'message': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        return Response({
            'session_id': str(session.id),
            'status': session.status,
            'outcome': session.outcome,
            'current_offer': float(session.current_offer) if session.current_offer else None,
            'negotiated_price': float(session.service_request.negotiated_price) if session.service_request.negotiated_price else None,
            'message_count': session.message_count,
            'is_expired': session.is_expired(),
            'expires_at': session.expires_at.isoformat(),
            'created_at': session.created_at.isoformat()
        })
        
    except NegotiationSession.DoesNotExist:
        return Response({'message': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def accept_negotiated_offer(request, session_id):
    """
    Customer accepts the negotiated price offer.
    This creates the Service record and updates the request status.
    """
    from .models import NegotiationSession, Service
    
    try:
        session = NegotiationSession.objects.get(id=session_id)
        
        # Verify user owns this negotiation
        if session.service_request.customer != request.user:
            return Response({'message': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Verify negotiation is complete
        if session.status != 'completed' or session.outcome != 'agreed':
            return Response(
                {'message': 'This negotiation is not in a completed state'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service_request = session.service_request
        
        # Check if already accepted
        if service_request.status == 'ACCEPTED':
            return Response({'message': 'This offer has already been accepted'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update service request
        service_request.status = 'ACCEPTED'
        service_request.service_acceptance = True
        service_request.save()
        
        # Create the Service record
        service = Service.objects.create(
            customer=service_request.customer,
            service_provider=service_request.service_provider,
            description=f"{service_request.description} (Negotiated: ₹{service_request.negotiated_price})",
            requested_on=service_request.requested_on
        )
        
        # Notify the provider
        Notifications.objects.create(
            user=service_request.service_provider,
            title="Booking Confirmed!",
            message=f"{service_request.customer.first_name} has accepted your offer of ₹{service_request.negotiated_price} for '{service_request.description}'.",
            notification_type='booking_confirmed'
        )
        
        return Response({
            'message': 'Offer accepted! Service booking created.',
            'service_id': str(service.id),
            'negotiated_price': float(service_request.negotiated_price)
        })
        
    except NegotiationSession.DoesNotExist:
        return Response({'message': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsVerifiedAndAuthenticated])
def reject_negotiated_offer(request, session_id):
    """
    Customer rejects the negotiated price offer.
    This allows them to try negotiating with another provider.
    """
    from .models import NegotiationSession
    
    try:
        session = NegotiationSession.objects.get(id=session_id)
        
        # Verify user owns this negotiation
        if session.service_request.customer != request.user:
            return Response({'message': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Update session
        session.status = 'failed'
        session.outcome = 'cancelled'
        session.save()
        
        # Reset service request for potential re-negotiation
        service_request = session.service_request
        service_request.negotiation_status = 'NOT_STARTED'
        service_request.negotiated_price = None
        service_request.save()
        
        # Notify provider
        from . import whatsapp_negotiator
        whatsapp_negotiator.send_whatsapp_message(
            session.provider_phone,
            f"Thank you for your time. Unfortunately, the customer has decided not to proceed with this booking. We hope to connect you with other opportunities soon! - NivasSaarthi"
        )
        
        return Response({'message': 'Offer rejected. You can try negotiating with another provider.'})
        
    except NegotiationSession.DoesNotExist:
        return Response({'message': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

