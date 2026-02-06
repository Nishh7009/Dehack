from app.models import ChatMessage, NewUser

def get_chat_room_name(user1_id, user2_id):
    """Create consistent room name for two users"""
    ids = sorted([str(user1_id), str(user2_id)])
    return f"{ids[0]}_{ids[1]}"

def get_chat_users(room_name, user_id):
    """Get both users in a chat room"""
    try:
        user_ids = room_name.split('_')
        user = NewUser.objects.get(id=user_id)
        other_user_id = user_ids[0] if str(user_id) == user_ids[1] else user_ids[1]
        other_user = NewUser.objects.get(id=other_user_id)
        
        return {
            'user': user,
            'other_user': other_user,
            'user_language': user.preferred_language,
            'other_language': other_user.preferred_language
        }
    except:
        return None

def save_chat_message(sender_id, receiver_id, original_msg, original_lang, translated_msg, translated_lang):
    """Save chat message to database"""
    sender = NewUser.objects.get(id=sender_id)
    receiver = NewUser.objects.get(id=receiver_id)
    
    return ChatMessage.objects.create(
        sender=sender,
        receiver=receiver,
        original_message=original_msg,
        original_language=original_lang,
        translated_message=translated_msg,
        translated_language=translated_lang
    )

def get_chat_history(user1_id, user2_id, limit=50):
    """Get chat history between two users"""
    messages = ChatMessage.objects.filter(
        sender_id__in=[user1_id, user2_id],
        receiver_id__in=[user1_id, user2_id]
    ).order_by('-timestamp')[:limit]
    
    return list(reversed(messages))

def mark_messages_as_read(user_id, other_user_id):
    """Mark all messages from other_user as read"""
    ChatMessage.objects.filter(
        sender_id=other_user_id,
        receiver_id=user_id,
        is_read=False
    ).update(is_read=True)