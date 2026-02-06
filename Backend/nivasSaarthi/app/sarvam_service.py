import os
import tempfile
from sarvamai import SarvamAI

def get_sarvam_client():
    """Get Sarvam AI client"""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise Exception("SARVAM_API_KEY not configured")
    return SarvamAI(api_subscription_key=api_key)

def speech_to_text(audio_data, language_code="unknown"):
    """Convert speech to text using Sarvam ASR"""
    client = get_sarvam_client()
    
    # Save audio data to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
        temp_audio.write(audio_data)
        temp_audio_path = temp_audio.name
    
    try:
        with open(temp_audio_path, "rb") as f:
            response = client.speech_to_text.transcribe(
                file=f,
                model="saarika:v2.5",
                language_code=language_code
            )
        
        os.unlink(temp_audio_path)
        
        # Extract transcript
        if hasattr(response, 'transcript'):
            return response.transcript
        elif isinstance(response, dict) and 'transcript' in response:
            return response['transcript']
        else:
            return str(response)
    
    except Exception as e:
        if os.path.exists(temp_audio_path):
            os.unlink(temp_audio_path)
        print(f"STT error: {e}")
        return ""

def translate_text(text, source_lang, target_lang):
    """Translate text between languages"""
    client = get_sarvam_client()
    
    # Map your language codes to Sarvam format
    lang_mapping = {
        'en': 'en-IN',
        'hi': 'hi-IN',
        'bn': 'bn-IN',
        'ta': 'ta-IN',
        'te': 'te-IN',
        'mr': 'mr-IN',
        'gu': 'gu-IN',
        'kn': 'kn-IN',
        'ml': 'ml-IN',
        'pa': 'pa-IN',
        'or': 'od-IN',  # Odia mapping
        'as': 'as-IN',
        'ur': 'ur-IN'
    }
    
    source = lang_mapping.get(source_lang, source_lang)
    target = lang_mapping.get(target_lang, target_lang)
    
    try:
        response = client.translate(
            input=text,
            source_language_code=source,
            target_language_code=target,
            mode='formal',
            model='mayura:v1'
        )
        
        if hasattr(response, 'translated_text'):
            return response.translated_text
        elif isinstance(response, dict) and 'translated_text' in response:
            return response['translated_text']
        else:
            return text
    
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def text_to_speech(text, language_code, speaker='meera'):
    """Convert text to speech using Sarvam TTS"""
    from sarvamai.play import save
    import base64
    
    client = get_sarvam_client()
    
    # Map language codes
    lang_mapping = {
        'en': 'en-IN',
        'hi': 'hi-IN',
        'bn': 'bn-IN',
        'ta': 'ta-IN',
        'te': 'te-IN',
        'mr': 'mr-IN',
        'gu': 'gu-IN',
        'kn': 'kn-IN',
        'ml': 'ml-IN',
        'pa': 'pa-IN',
        'or': 'od-IN',
        'as': 'as-IN',
        'ur': 'ur-IN'
    }
    
    sarvam_lang = lang_mapping.get(language_code, language_code)
    
    # Check if language is supported
    supported_langs = ['bn-IN', 'gu-IN', 'kn-IN', 'ml-IN', 'mr-IN', 'od-IN', 'pa-IN', 'ta-IN', 'te-IN', 'hi-IN']
    
    if sarvam_lang not in supported_langs:
        return None
    
    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code=sarvam_lang,
            enable_preprocessing=True,
            speaker=speaker
        )
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio_path = temp_audio.name
        
        save(response, temp_audio_path)
        
        # Read and encode to base64
        with open(temp_audio_path, 'rb') as f:
            audio_content = f.read()
        
        os.unlink(temp_audio_path)
        
        return base64.b64encode(audio_content).decode('utf-8')
    
    except Exception as e:
        print(f"TTS error: {e}")
        return None