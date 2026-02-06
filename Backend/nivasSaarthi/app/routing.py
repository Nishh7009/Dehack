from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    
    re_path(r'ws/chat/(?P<room_name>\w+)/$', consumers.ChatConsumer.as_asgi()),
    # Voice call WebSocket
    re_path(r'ws/call/(?P<call_id>[\w-]+)/user/(?P<user_id>[\w-]+)/$', 
            consumers.TranslatedCallConsumer.as_asgi()),
    re_path(r'ws/chat/(?P<room_name>[\w-]+)/user/(?P<user_id>[\w-]+)/$', 
            consumers.TranslatedChatConsumer.as_asgi()),
]