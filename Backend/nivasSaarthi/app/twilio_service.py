import os
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Start, Stream

def get_twilio_client():
    return Client(
        os.getenv('TWILIO_ACCOUNT_SID'),
        os.getenv('TWILIO_AUTH_TOKEN')
    )

def initiate_twilio_call(to_number, callback_url):
    """Start a call to a user"""
    client = get_twilio_client()
    phone_number = os.getenv('TWILIO_PHONE_NUMBER')
    
    call = client.calls.create(
        to=to_number,
        from_=phone_number,
        url=callback_url,
        status_callback=callback_url + '/status',
        status_callback_event=['initiated', 'ringing', 'answered', 'completed']
    )
    return call.sid

def generate_twiml_with_stream(websocket_url):
    """Generate TwiML to start bidirectional audio streaming"""
    response = VoiceResponse()
    response.say("Connecting you now", language='en-IN')
    
    start = Start()
    stream = Stream(url=websocket_url)
    start.append(stream)
    response.append(start)
    
    response.pause(length=3600)  # 1 hour max
    
    return str(response)