import json
import base64
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import sarvam_service
from app.utils import call_helpers

class TranslatedCallConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.call_id = self.scope['url_route']['kwargs']['call_id']
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.audio_buffer = bytearray()
        
        call_data = await self.get_call_info()
        if not call_data:
            await self.close()
            return
        
        self.user_language = call_data['user_language']
        self.other_language = call_data['other_language']
        self.room_group_name = f'call_{self.call_id}'
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            data = json.loads(text_data)
            event_type = data.get('event')
            
            if event_type == 'media':
                audio_payload = data['media']['payload']
                audio_bytes = base64.b64decode(audio_payload)
                self.audio_buffer.extend(audio_bytes)
                
                if len(self.audio_buffer) >= 8000:
                    await self.process_audio()
            
            elif event_type == 'stop':
                await self.end_call()
    
    async def process_audio(self):
        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        
        # Speech to Text
        original_text = await asyncio.to_thread(
            sarvam_service.speech_to_text,
            audio_data,
            self.user_language
        )
        
        if not original_text:
            return
        
        print(f"Original ({self.user_language}): {original_text}")
        
        # Translate
        translated_text = await asyncio.to_thread(
            sarvam_service.translate_text,
            original_text,
            self.user_language,
            self.other_language
        )
        
        print(f"Translated ({self.other_language}): {translated_text}")
        
        # Text to Speech
        translated_audio = await asyncio.to_thread(
            sarvam_service.text_to_speech,
            translated_text,
            self.other_language
        )
        
        if not translated_audio:
            print("TTS failed, skipping")
            return
        
        # Save transcript
        await self.save_transcript_entry(original_text, translated_text)
        
        # Send to other user
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'send_audio',
                'audio': translated_audio,
                'text': translated_text,
                'sender_id': self.user_id
            }
        )
    
    async def send_audio(self, event):
        if event['sender_id'] != self.user_id:
            await self.send(text_data=json.dumps({
                'event': 'media',
                'media': {'payload': event['audio']},
                'streamSid': self.scope.get('stream_sid')
            }))
    
    @database_sync_to_async
    def get_call_info(self):
        return call_helpers.get_call_data(self.call_id, self.user_id)
    
    @database_sync_to_async
    def save_transcript_entry(self, original_text, translated_text):
        call_helpers.save_call_transcript(
            self.call_id,
            self.user_id,
            original_text,
            self.user_language,
            translated_text,
            self.other_language
        )
    
    @database_sync_to_async
    def end_call(self):
        from datetime import datetime
        call_helpers.update_call_status(
            self.call_id,
            'completed',
            ended_at=datetime.now()
        )