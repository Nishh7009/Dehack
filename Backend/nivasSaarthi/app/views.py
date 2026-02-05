from .serializers import UserRegistrationSerializer, UserBaseRegistrationSerializer
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsVerifiedAndAuthenticated
from django.contrib.auth import login
from .models import NewUser, Service, ServiceRequest, ServiceProviderProfile
from rest_framework.response import Response
from rest_framework import status
from pyotp import TOTP
from django.utils import timezone
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
        user.save()
        return Response({"message": "User registered successfully"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_totp(request):
    totp_code = request.data.get('totp_code')
    try:
        user = request.user
        totp = TOTP(user.totp_secret)
        if totp.verify(totp_code):
            user.is_verified = True
            user.otp_retries = 3 
            user.save()
            return Response({"message": "TOTP verified successfully"}, status=status.HTTP_200_OK)
        else:
            user.otp_retries -= 1
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
        provider = NewUser.objects.get(id=provider_id, role=NewUser.SERVICE_PROVIDER)
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
        if provider.role != NewUser.SERVICE_PROVIDER:
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
        if customer.role != NewUser.CUSTOMER:
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
        customer = NewUser.objects.get(id=customer_id, role=NewUser.CUSTOMER)
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
        if request.user.role == NewUser.SERVICE_PROVIDER:
            service = Service.objects.get(id=service_id, service_provider=request.user)
        elif request.user.role == NewUser.CUSTOMER:
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
    
    if not all([customer_id, provider_id, description]):
        return Response({'message': 'Customer ID, Provider ID and Description are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        customer = NewUser.objects.get(id=customer_id, role=NewUser.CUSTOMER)
        provider = NewUser.objects.get(id=provider_id, role=NewUser.SERVICE_PROVIDER)
         
        service_request = ServiceRequest.objects.create(
            customer=customer,
            service_provider=provider,
            description=description,
            requested_on=requested_date if requested_date else timezone.now()
        )
        return Response({'message': 'Service requested successfully', 'service_id': str(service_request.id)}, status=status.HTTP_201_CREATED)
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