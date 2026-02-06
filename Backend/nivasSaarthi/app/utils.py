import requests
import hashlib
import hmac
import json
from .models import WebhookSubscription, Notifications
from django.db.models.signals import post_save
from django.dispatch import receiver


def send_webhook(user, event_type, payload):
    """
    Send webhook to all active subscriptions for a user and event type
    """
    subscriptions = WebhookSubscription.objects.filter(
        user=user,
        event_type=event_type,
        is_active=True
    )
    
    for subscription in subscriptions:
        try:
            # Create signature for security
            payload_json = json.dumps(payload)
            signature = hmac.new(
                subscription.secret.encode(),
                payload_json.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Send webhook
            response = requests.post(
                subscription.url,
                json=payload,
                headers={
                    'Content-Type': 'application/json',
                    'X-Webhook-Signature': signature,
                    'X-Webhook-Event': event_type
                },
                timeout=5
            )
            
            response.raise_for_status()
            print(f"Webhook sent successfully to {subscription.url}")
            
        except Exception as e:
            print(f"Webhook failed for {subscription.url}: {str(e)}")
            # Optionally: deactivate webhook after X failed attempts


@receiver(post_save, sender=Notifications)
def notify_webhook_on_notification(sender, instance, created, **kwargs):
    if created:
        # Get unread count
        unread_count = Notifications.objects.filter(
            user=instance.user,
            is_read=False
        ).count()
        
        # Send webhook
        payload = {
            'user_id': str(instance.user.id),
            'unread_count': unread_count,
            'latest_notification': {
                'id': str(instance.id),
                'title': instance.title,
                'message': instance.message,
                'type': instance.notification_type,
                'created_at': instance.created_at.isoformat()
            }
        }
        
        send_webhook(instance.user, 'notification_count', payload)