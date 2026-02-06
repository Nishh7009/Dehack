"""
Call helper functions for voice call functionality.
Used by views.py and consumers.py for managing VoiceCall records and transcripts.
"""

from app.models import VoiceCall, CallTranscript, NewUser
from django.utils import timezone


def create_voice_call(caller: NewUser, receiver: NewUser) -> VoiceCall:
    """
    Create a new VoiceCall record between two users.
    
    Args:
        caller: The user initiating the call
        receiver: The user receiving the call
    
    Returns:
        VoiceCall: The created call record
    """
    call = VoiceCall.objects.create(
        caller=caller,
        receiver=receiver,
        caller_language=caller.preferred_language or 'en',
        receiver_language=receiver.preferred_language or 'en',
        status='initiated',
    )
    return call


def update_call_status(call_id, status=None, **kwargs):
    """
    Update the status and other fields of a VoiceCall.
    
    Args:
        call_id: UUID of the call to update
        status: New status string (initiated, ringing, in-progress, completed)
        **kwargs: Additional fields to update (twilio_call_sid, ended_at, duration)
    """
    try:
        call = VoiceCall.objects.get(id=call_id)
        
        if status:
            call.status = status
        
        # Update any additional fields passed as kwargs
        if 'twilio_call_sid' in kwargs:
            call.twilio_call_sid = kwargs['twilio_call_sid']
        
        if 'ended_at' in kwargs:
            call.ended_at = kwargs['ended_at']
        
        if 'duration' in kwargs:
            call.duration = kwargs['duration']
        
        call.save()
        return call
    except VoiceCall.DoesNotExist:
        return None


def get_call_data(call_id, user_id):
    """
    Get call data with language information for a specific user.
    
    Args:
        call_id: UUID of the call
        user_id: UUID of the user requesting the data (to determine language perspective)
    
    Returns:
        dict: Call data including call object and language info, or None if not found
    """
    try:
        call = VoiceCall.objects.select_related('caller', 'receiver').get(id=call_id)
        
        # Determine which language belongs to which user
        if user_id and str(call.caller.id) == str(user_id):
            user_language = call.caller_language
            other_language = call.receiver_language
        elif user_id and str(call.receiver.id) == str(user_id):
            user_language = call.receiver_language
            other_language = call.caller_language
        else:
            # Default/admin view - no user perspective
            user_language = call.caller_language
            other_language = call.receiver_language
        
        return {
            'call': call,
            'caller': call.caller,
            'receiver': call.receiver,
            'user_language': user_language,
            'other_language': other_language,
            'status': call.status,
            'started_at': call.started_at,
            'ended_at': call.ended_at,
            'duration': call.duration,
        }
    except VoiceCall.DoesNotExist:
        return None


def save_call_transcript(call_id, speaker_id, original_text, original_language,
                         translated_text, translated_language):
    """
    Save a transcript entry for a call.
    
    Args:
        call_id: UUID of the call
        speaker_id: UUID of the user who spoke
        original_text: The original spoken text
        original_language: Language code of the original text
        translated_text: The translated text
        translated_language: Language code of the translation
    
    Returns:
        CallTranscript: The created transcript entry, or None on error
    """
    try:
        call = VoiceCall.objects.get(id=call_id)
        speaker = NewUser.objects.get(id=speaker_id)
        
        transcript = CallTranscript.objects.create(
            call=call,
            speaker=speaker,
            original_text=original_text,
            original_language=original_language,
            translated_text=translated_text,
            translated_language=translated_language,
        )
        return transcript
    except (VoiceCall.DoesNotExist, NewUser.DoesNotExist) as e:
        print(f"Error saving transcript: {e}")
        return None


def get_call_transcripts(call_id):
    """
    Get all transcript entries for a call, ordered by timestamp.
    
    Args:
        call_id: UUID of the call
    
    Returns:
        QuerySet: CallTranscript objects ordered by timestamp
    """
    return CallTranscript.objects.filter(
        call_id=call_id
    ).select_related('speaker').order_by('timestamp')


def get_call_by_id(call_id):
    """
    Get a VoiceCall by its ID.
    
    Args:
        call_id: UUID of the call
    
    Returns:
        VoiceCall or None
    """
    try:
        return VoiceCall.objects.select_related('caller', 'receiver').get(id=call_id)
    except VoiceCall.DoesNotExist:
        return None


def get_user_calls(user_id, call_type='all', limit=20):
    """
    Get calls for a specific user.
    
    Args:
        user_id: UUID of the user
        call_type: 'incoming', 'outgoing', or 'all'
        limit: Maximum number of calls to return
    
    Returns:
        QuerySet: VoiceCall objects
    """
    if call_type == 'incoming':
        return VoiceCall.objects.filter(receiver_id=user_id).order_by('-started_at')[:limit]
    elif call_type == 'outgoing':
        return VoiceCall.objects.filter(caller_id=user_id).order_by('-started_at')[:limit]
    else:
        return VoiceCall.objects.filter(
            caller_id=user_id
        ).union(
            VoiceCall.objects.filter(receiver_id=user_id)
        ).order_by('-started_at')[:limit]


def end_call(call_id):
    """
    End a call and calculate duration.
    
    Args:
        call_id: UUID of the call to end
    
    Returns:
        VoiceCall: Updated call object, or None if not found
    """
    try:
        call = VoiceCall.objects.get(id=call_id)
        call.status = 'completed'
        call.ended_at = timezone.now()
        
        # Calculate duration in seconds
        if call.started_at:
            duration = (call.ended_at - call.started_at).total_seconds()
            call.duration = int(duration)
        
        call.save()
        return call
    except VoiceCall.DoesNotExist:
        return None
