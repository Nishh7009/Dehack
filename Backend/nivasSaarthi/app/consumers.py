import json
import base64
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from app import sarvam_service
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

import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from app import sarvam_service
from app.utils import chat_helpers

class TranslatedChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.room_group_name = f'chat_{self.room_name}'
        
        # Get chat users and their languages
        chat_data = await self.get_chat_data()
        if not chat_data:
            await self.close()
            return
        
        self.user_language = chat_data['user_language']
        self.other_language = chat_data['other_language']
        self.other_user_id = str(chat_data['other_user'].id)
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send chat history
        await self.send_chat_history()
        
        # Mark messages as read
        await self.mark_read()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """Receive message from WebSocket"""
        data = json.loads(text_data)
        message_type = data.get('type')
        
        if message_type == 'chat_message':
            original_message = data.get('message')
            
            if not original_message or not original_message.strip():
                return
            
            # Translate the message
            translated_message = await self.translate_message(original_message)
            
            # Save to database
            await self.save_message(original_message, translated_message)
            
            # Send to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message_handler',
                    'sender_id': self.user_id,
                    'original_message': original_message,
                    'original_language': self.user_language,
                    'translated_message': translated_message,
                    'translated_language': self.other_language,
                    'timestamp': await self.get_timestamp()
                }
            )
        
        elif message_type == 'typing':
            # Broadcast typing indicator
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'typing_handler',
                    'sender_id': self.user_id,
                    'is_typing': data.get('is_typing', False)
                }
            )
        
        elif message_type == 'mark_read':
            # Mark messages as read
            await self.mark_read()
    
    async def chat_message_handler(self, event):
        """Send message to WebSocket"""
        sender_id = event['sender_id']
        
        # Determine which message to show (original or translated)
        if sender_id == self.user_id:
            # This is my message, show original
            message_to_show = event['original_message']
            language = event['original_language']
        else:
            # This is other person's message, show translation
            message_to_show = event['translated_message']
            language = event['translated_language']
        
        # Send to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'sender_id': sender_id,
            'message': message_to_show,
            'language': language,
            'timestamp': event['timestamp'],
            'is_mine': sender_id == self.user_id
        }))
    
    async def typing_handler(self, event):
        """Handle typing indicator"""
        if event['sender_id'] != self.user_id:
            # Only send typing indicator from other user
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'is_typing': event['is_typing']
            }))
    
    async def translate_message(self, message):
        """Translate message from user's language to other user's language"""
        # Check if translation is needed
        if self.user_language == self.other_language:
            return message
        
        # Translate using Sarvam
        translated = await asyncio.to_thread(
            sarvam_service.translate_text,
            message,
            self.user_language,
            self.other_language
        )
        
        return translated
    
    async def send_chat_history(self):
        """Send chat history to newly connected user"""
        history = await self.get_history()
        
        for msg in history:
            # Determine which version to show
            if str(msg.sender.id) == self.user_id:
                # My message - show original
                message_text = msg.original_message
                language = msg.original_language
            else:
                # Their message - show translation
                message_text = msg.translated_message
                language = msg.translated_language
            
            await self.send(text_data=json.dumps({
                'type': 'chat_message',
                'sender_id': str(msg.sender.id),
                'message': message_text,
                'language': language,
                'timestamp': msg.timestamp.isoformat(),
                'is_mine': str(msg.sender.id) == self.user_id,
                'is_read': msg.is_read
            }))
    
    @database_sync_to_async
    def get_chat_data(self):
        return chat_helpers.get_chat_users(self.room_name, self.user_id)
    
    @database_sync_to_async
    def save_message(self, original_message, translated_message):
        return chat_helpers.save_chat_message(
            self.user_id,
            self.other_user_id,
            original_message,
            self.user_language,
            translated_message,
            self.other_language
        )
    
    @database_sync_to_async
    def get_history(self):
        return chat_helpers.get_chat_history(self.user_id, self.other_user_id)
    
    @database_sync_to_async
    def mark_read(self):
        return chat_helpers.mark_messages_as_read(self.user_id, self.other_user_id)
    
    @database_sync_to_async
    def get_timestamp(self):
        from datetime import datetime
        return datetime.now().isoformat()
