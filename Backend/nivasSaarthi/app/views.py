from .serializers import UserRegistrationSerializer, UserBaseRegistrationSerializer
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsVerifiedAndAuthenticated
from django.contrib.auth import login
from .models import ROLES, NewUser, Service, ServiceRequest, ServiceProviderProfile
from rest_framework.response import Response
from django.core.mail import send_mail
from rest_framework import status
from pyotp import TOTP
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.gis.geos import Point
import tempfile
import os


#################################### AUTH VIEWS ####################################
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = UserBaseRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        user.totp_secret = TOTP.generate_secret()
        login(request, user)
        send_mail(
            subject="Your OTP for Nivas Saarthi Registration",
            message=f"Your OTP code is: {TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.",
            from_email=os.getenv('EMAIL_SENDER_ID'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        user.save()
        return Response({"message": "User registered successfully"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_totp(request):
    totp_code = request.data.get('totp_code')
    try:
        user = request.user
        if user.otp_retries <= 0:
            user.otp_retries = 3
            user.save()
            return Response({"error": "Maximum OTP retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)
        totp = TOTP(user.totp_secret)
        if totp.verify(totp_code):
            user.is_verified = True
            user.otp_retries = 3 
            user.save()
            return Response({"message": "TOTP verified successfully"}, status=status.HTTP_200_OK)
        else:
            user.otp_retries -= 1
            send_mail(
                subject="Your OTP for Nivas Saarthi Registration - Retry",
                message=f"Your OTP code is: {TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
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
        user.totp_secret = TOTP.generate_secret()
        user.otp_retries = 3 
        user.save()
        send_mail(
            subject="Your OTP for Nivas Saarthi Password Reset",
            message=f"Your OTP code is: {TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.",
            from_email=os.getenv('EMAIL_SENDER_ID'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return Response({"message": "Password reset OTP sent to email"}, status=status.HTTP_200_OK)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    try:
        email = request.data.get('email')
        totp_code = request.data.get('totp_code')
        new_password = request.data.get('new_password')
        user = NewUser.objects.get(email=email)
        totp = TOTP(user.totp_secret)
        if user.otp_retries <= 0:
            user.otp_retries = 3
            user.save()
            return Response({"error": "Maximum OTP retries exceeded"}, status=status.HTTP_400_BAD_REQUEST)
        if totp.verify(totp_code):
            user.set_password(new_password)
            user.totp_secret = None
            user.otp_retries = 3 
            user.save()
            return Response({"message": "Password reset successfully"}, status=status.HTTP_200_OK)
        else:
            user.otp_retries -= 1
            send_mail(
                subject="Your OTP for Nivas Saarthi Password Reset - Retry",
                message=f"Your OTP code is: {TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
                from_email=os.getenv('EMAIL_SENDER_ID'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            user.save()
            return Response({"error": "Invalid OTP code"}, status=status.HTTP_400_BAD_REQUEST)
    except NewUser.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def resend_totp(request):
    try:
        user = request.user
        if user.otp_retries > 0:
            user.totp_secret = TOTP.generate_secret()
            user.otp_retries -= 1
            user.save()
            send_mail(
                subject="Your OTP for Nivas Saarthi Registration - Resent",
                message=f"Your OTP code is: {TOTP(user.totp_secret).now()}\nThis code will expire in 30 seconds.\nYou have {user.otp_retries} retries left.",
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
    serializer = UserRegistrationSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
    user.profile_completed = True
    user.save()
    return Response({"message": "Profile marked as completed"}, status=status.HTTP_200_OK)

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
            'completed': service.completed
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
    customer_id = request.data.get('customer_id')
    provider_id = request.data.get('provider_id')
    description = request.data.get('description')
    requested_date = request.data.get('requested_date')
    
    # Location where the customer wants the service (required for distance validation)
    service_latitude = request.data.get('service_latitude')
    service_longitude = request.data.get('service_longitude')
    
    if not all([customer_id, provider_id, description]):
        return Response({'message': 'Customer ID, Provider ID and Description are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        customer = NewUser.objects.get(id=customer_id, role=ROLES.CUSTOMER)
        provider = NewUser.objects.get(id=provider_id, role=ROLES.SERVICE_PROVIDER)
        
        # Validate distance if location is provided
        if service_latitude and service_longitude and provider.location:
            service_location = Point(float(service_longitude), float(service_latitude), srid=4326)
            # Calculate distance in kilometers
            distance_m = provider.location.distance(service_location)
            # Convert to km (geography type returns distance in meters)
            distance_km = distance_m * 100  # Approximate conversion for geography
            
            # Use proper distance calculation with geodesic
            from django.contrib.gis.db.models.functions import Distance as GeoDistance
            provider_with_dist = NewUser.objects.filter(id=provider_id).annotate(
                distance=GeoDistance('location', service_location)
            ).first()
            
            if provider_with_dist and provider_with_dist.distance:
                distance_km = provider_with_dist.distance.km
                if distance_km > 5:
                    return Response({
                        'message': f'Provider is {distance_km:.1f}km away from the service location. Maximum allowed distance is 5km.',
                        'distance_km': round(distance_km, 2)
                    }, status=status.HTTP_400_BAD_REQUEST)
         
        service_request = ServiceRequest.objects.create(
            customer=customer,
            service_provider=provider,
            description=description,
            requested_on=requested_date if requested_date else timezone.now()
        )
        return Response({'message': 'Service requested successfully', 'service_request_id': str(service_request.id)}, status=status.HTTP_201_CREATED)
    except NewUser.DoesNotExist:
        return Response({'message': 'Customer or Service Provider not found'}, status=status.HTTP_404_NOT_FOUND)

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
            requested_on=service_request.requested_on
        )
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
        return Response({'message': 'Service request rejected'}, status=status.HTTP_200_OK)
    except ServiceRequest.DoesNotExist:
        return Response({'message': 'Service request not found or unauthorized'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([IsVerifiedAndAuthenticated])
def get_nearby_providers(request):
    """
    Get service providers within a radius of a given location.
    
    Query params:
    - latitude: Required. Latitude of the location to search from.
    - longitude: Required. Longitude of the location to search from.
    - radius_km: Optional. Search radius in kilometers (default: 5).
    - service_type: Optional. Filter by service type (comma-separated list).
    
    Returns:
    - providers: List of nearby providers with distance information.
    - count: Total number of providers found.
    """
    lat = request.query_params.get('latitude')
    lon = request.query_params.get('longitude')
    radius_km = float(request.query_params.get('radius_km', 5))
    service_type = request.query_params.get('service_type')
    
    # Validate required parameters
    if not lat or not lon:
        return Response(
            {'message': 'Latitude and longitude are required query parameters.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user_location = Point(float(lon), float(lat), srid=4326)
    except (ValueError, TypeError):
        return Response(
            {'message': 'Invalid latitude or longitude values.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Query providers within radius using PostGIS
    providers = NewUser.objects.filter(
        role=ROLES.SERVICE_PROVIDER,
        location__isnull=False,
        location__distance_lte=(user_location, D(km=radius_km))
    ).annotate(
        distance=Distance('location', user_location)
    ).select_related('service_provider_profile').order_by('distance')
    
    # Filter by service type if specified
    if service_type:
        service_types = [s.strip().lower() for s in service_type.split(',')]
        filtered_providers = []
        for p in providers:
            if hasattr(p, 'service_provider_profile'):
                provider_services = [s.lower() for s in p.service_provider_profile.get_services_list()]
                if any(st in provider_services for st in service_types):
                    filtered_providers.append(p)
        providers = filtered_providers
    
    providers_data = []
    for p in providers:
        provider_data = {
            'id': str(p.id),
            'first_name': p.first_name,
            'last_name': p.last_name,
            'phone_number': p.phone_number,
            'city': p.city,
            'distance_km': round(p.distance.km, 2) if hasattr(p, 'distance') and p.distance else None,
        }
        
        # Add service provider profile data if available
        if hasattr(p, 'service_provider_profile'):
            profile = p.service_provider_profile
            provider_data.update({
                'average_rating': profile.average_rating,
                'years_of_experience': profile.years_of_experience,
                'services': profile.get_services_list(),
                'bio': profile.bio,
            })
        else:
            provider_data.update({
                'average_rating': 0,
                'years_of_experience': 0,
                'services': [],
                'bio': '',
            })
        
        providers_data.append(provider_data)
    
    return Response({
        'providers': providers_data,
        'count': len(providers_data),
        'search_radius_km': radius_km,
        'search_location': {'latitude': lat, 'longitude': lon}
    }, status=status.HTTP_200_OK)

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
        traceback.print_exc()
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.unlink(temp_audio_path)
        # Fallback to browser TTS on any error
        return Response({'message': 'Error in text to speech', 'error': str(e), 'use_browser_tts': True}, status=status.HTTP_200_OK)
