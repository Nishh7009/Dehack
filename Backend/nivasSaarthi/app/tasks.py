"""
Celery tasks for automated multi-provider negotiation.
"""

from linecache import cache
from .models import NewUser, NegotiationSession, ServiceRequest, Notifications, ROLES
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging
import requests
import os

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_telegram_notification(self, user_id: str, title: str, message: str, session_id: str = None):
    """
    Send notification to user via Telegram bot.
    Retries up to 3 times on failure.
    """
    
    try:
        user = NewUser.objects.get(id=user_id)
        
        if not user.telegram_chat_id:
            logger.warning(f"User {user_id} has no Telegram chat ID")
            return {'status': 'skipped', 'message': 'No Telegram chat ID'}
        
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        formatted_message = f"*{title}*\n\n{message}"
        if session_id:
            formatted_message += f"\n\nSession ID: {session_id}"
        
        response = requests.post(url, json={
            'chat_id': user.telegram_chat_id,
            'text': formatted_message,
            'parse_mode': 'Markdown'
        })
        
        if response.status_code == 200:
            logger.info(f"Telegram notification sent to user {user_id}")
            return {'status': 'sent', 'user_id': user_id}
        else:
            raise Exception(f"Telegram API error: {response.text}")
        
    except NewUser.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return {'status': 'error', 'message': 'User not found'}
    except Exception as exc:
        logger.error(f"Failed to send Telegram notification: {exc}")
        self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def negotiate_with_providers(self, service_request_id: str):
    """
    Main Celery task: Find nearby providers and start negotiations with all of them.
    
    This task:
    1. Finds providers within 5km matching ANY of the service types
    2. Creates a NegotiationSession for each provider
    3. For providers with Telegram - sends negotiation request via Telegram
    4. For providers without Telegram - creates a notification
    5. Updates progress tracking
    """
    from .models import ServiceRequest, NegotiationSession, NewUser, ServiceProviderProfile, Notifications
    from app import sarvam_service
    import requests
    
    try:
        service_request = ServiceRequest.objects.get(id=service_request_id)
    except ServiceRequest.DoesNotExist:
        logger.error(f"ServiceRequest {service_request_id} not found")
        return {'status': 'error', 'message': 'Service request not found'}
    
    # Update status to negotiating
    service_request.status = 'NEGOTIATING'
    service_request.save()
    
    # Find nearby providers matching ANY of the service types
    providers = find_matching_providers(service_request)
    
    if not providers:
        service_request.status = 'EXPIRED'
        service_request.save()
        logger.info(f"No providers found for request {service_request_id}")
        return {'status': 'no_providers', 'message': 'No matching providers found nearby'}
    
    # Expiry time for all sessions
    expires_at = timezone.now() + timedelta(hours=24)
    
    sessions_created = 0
    telegram_sent = 0
    notifications_sent = 0
    
    # Budget calculations
    max_price = service_request.customer_budget
    min_acceptable = max_price * Decimal('0.7')  # 70% of budget as minimum acceptable
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    for provider in providers[:10]:  # Limit to 10 providers
        try:
            # Determine the identifier - use telegram_chat_id if available, else phone
            provider_identifier = provider.telegram_chat_id if provider.telegram_chat_id else provider.phone_number
            
            if not provider_identifier:
                logger.warning(f"Provider {provider.id} has no phone or telegram, skipping")
                continue
            
            # Check for existing active session
            existing = NegotiationSession.objects.filter(
                service_request=service_request,
                provider_phone=provider_identifier,
                status='active'
            ).first()
            
            if existing:
                logger.info(f"Active session already exists for provider {provider.id}")
                continue
            
            # Create negotiation session
            session = NegotiationSession.objects.create(
                service_request=service_request,
                provider_phone=provider_identifier,
                max_price=max_price,
                min_acceptable=min_acceptable,
                status='active',
                expires_at=expires_at
            )
            sessions_created += 1
            
            # Format service types
            service_types = service_request.service_types
            if isinstance(service_types, list):
                service_types_str = ', '.join(service_types)
            else:
                service_types_str = str(service_types)
            
            # Build message
            message = (
                f"🔔 New Service Request\n\n"
                f"Service: {service_types_str}\n"
                f"Description: {service_request.description}\n"
                f"Budget Range: ₹{min_acceptable} - ₹{max_price}\n\n"
                f"Please reply with your price offer to start negotiation."
            )
            
            # If provider has Telegram, send via Telegram
            if provider.telegram_chat_id:
                # Translate message to provider's language
                target_lang = provider.preferred_language or 'en'
                if target_lang != 'en':
                    try:
                        message = sarvam_service.translate_text(message, 'en', target_lang)
                    except Exception as e:
                        logger.error(f"Translation error: {e}")
                
                # Send via Telegram API
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                response = requests.post(url, json={
                    'chat_id': provider.telegram_chat_id,
                    'text': message
                })
                
                if response.status_code == 200:
                    telegram_sent += 1
                    logger.info(f"Telegram message sent to provider {provider.id}")
                else:
                    logger.error(f"Failed to send Telegram to {provider.id}: {response.text}")
            else:
                # Create in-app notification for providers without Telegram
                Notifications.objects.create(
                    user=provider,
                    title="New Service Request",
                    message=f"New request for {service_types_str}. Budget: ₹{max_price}. Open app to respond.",
                    notification_type='service_request'
                )
                notifications_sent += 1
                logger.info(f"Notification created for provider {provider.id}")
                
        except Exception as e:
            logger.error(f"Error processing provider {provider.id}: {e}")
            continue
    
    # Update progress tracking
    service_request.providers_contacted = sessions_created
    
    if sessions_created == 0:
        service_request.status = 'EXPIRED'
        service_request.save()
        return {'status': 'failed', 'message': 'Could not reach any providers'}
    
    service_request.save()
    logger.info(f"Started {sessions_created} negotiations for request {service_request_id}")
    
    return {
        'status': 'started',
        'sessions_created': sessions_created,
        'telegram_sent': telegram_sent,
        'notifications_sent': notifications_sent,
        'expires_at': expires_at.isoformat()
    }


def find_matching_providers(service_request):
    """
    Find providers within 5km who offer ANY of the requested service types.
    """
    from .models import NewUser, ServiceProviderProfile, ROLES
    
    # Build location point
    if not service_request.latitude or not service_request.longitude:
        logger.warning(f"Request {service_request.id} has no location")
        return []
    
    customer_location = Point(
        float(service_request.longitude),
        float(service_request.latitude),
        srid=4326
    )
    
    # Get service types list (could be list or string)
    service_types = service_request.service_types
    if isinstance(service_types, str):
        service_types = [service_types]
    service_types = [s.lower().strip() for s in service_types if s]
    
    if not service_types:
        logger.warning(f"Request {service_request.id} has no service types")
        return []
    
    providers = NewUser.objects.filter(
        role=ROLES.SERVICE_PROVIDER,
        is_active=True,
        is_verified=True,
        location__isnull=False
    ).annotate(
        distance=Distance('location', customer_location)
    ).order_by('distance')
    
    # Filter by service types (providers store services as comma-separated string)
    matching_providers = []
    for provider in providers:
        try:
            profile = provider.service_provider_profile
            if profile.services:
                provider_services = [s.strip().lower() for s in profile.services.split(',')]
                # Match if ANY of the requested types match
                for requested_type in service_types:
                    if requested_type in provider_services or any(requested_type in s for s in provider_services):
                        matching_providers.append(provider)
                        break  # Avoid adding same provider multiple times
        except ServiceProviderProfile.DoesNotExist:
            continue
    
    return matching_providers


def build_initial_message_for_provider(service_request, provider, budget):
    """Build personalized initial message for a provider"""
    customer = service_request.customer
    provider_name = provider.first_name if provider.first_name else "there"
    
    # Format service types nicely
    service_types = service_request.service_types
    if isinstance(service_types, list):
        types_str = ", ".join(service_types)
    else:
        types_str = str(service_types)
    
    return f"""Namaste {provider_name}! 🙏

A customer near you needs help with: {service_request.description}

Service type(s): {types_str}
Customer budget: up to ₹{budget}
{f"Preferred date: {service_request.requested_on.strftime('%d %b %Y')}" if service_request.requested_on else ""}

Are you available? Please share your quote for this job.

Thank you!
- NivasSaarthi AI Assistant"""


@shared_task
def check_negotiation_status(service_request_id: str):
    """
    Check if all negotiations are complete and update request status.
    Called after the timeout period.
    """
    from .models import ServiceRequest, NegotiationSession, Notifications
    
    try:
        service_request = ServiceRequest.objects.get(id=service_request_id)
    except ServiceRequest.DoesNotExist:
        return
    
    # If already accepted or cancelled, nothing to do
    if service_request.status in ['ACCEPTED', 'CANCELLED']:
        return
    
    # Get all sessions for this request
    sessions = service_request.negotiations.all()
    
    # Mark any still-active sessions as expired
    active_sessions = sessions.filter(status='active')
    for session in active_sessions:
        session.status = 'expired'
        session.outcome = 'timeout'
        session.save()
    
    # Check if we have any successful negotiations
    successful = sessions.filter(status='completed', outcome='agreed')
    offers_count = successful.count()
    
    # Update progress
    service_request.offers_received = offers_count
    
    if offers_count > 0:
        service_request.status = 'OFFERS_READY'
        service_request.save()
        
        # Format service types
        types_str = ", ".join(service_request.service_types) if isinstance(service_request.service_types, list) else str(service_request.service_types)
        
        # Notify customer
        Notifications.objects.create(
            user=service_request.customer,
            title="Offers Ready! 🎉",
            message=f"We've received {offers_count} offer(s) for your {types_str} request. Review and pick the best one!",
            notification_type='offers_ready'
        )
    else:
        service_request.status = 'EXPIRED'
        service_request.save()
        
        types_str = ", ".join(service_request.service_types) if isinstance(service_request.service_types, list) else str(service_request.service_types)
        
        Notifications.objects.create(
            user=service_request.customer,
            title="No Offers Received",
            message=f"Unfortunately, no providers responded to your {types_str} request. Try adjusting your budget or posting again.",
            notification_type='request_expired'
        )


@shared_task
def mark_offers_ready_if_complete(service_request_id: str):
    """
    Called when a negotiation completes successfully.
    Updates progress and checks if status should change.
    """
    from .models import ServiceRequest, Notifications
    
    try:
        service_request = ServiceRequest.objects.get(id=service_request_id)
    except ServiceRequest.DoesNotExist:
        return
    
    if service_request.status != 'NEGOTIATING':
        return
    
    sessions = service_request.negotiations.all()
    active_count = sessions.filter(status='active').count()
    successful_count = sessions.filter(status='completed', outcome='agreed').count()
    
    # Update offers_received count
    service_request.offers_received = successful_count
    service_request.save()
    
    types_str = ", ".join(service_request.service_types) if isinstance(service_request.service_types, list) else str(service_request.service_types)
    
    # If we have at least one successful offer and all negotiations are done
    if successful_count > 0 and active_count == 0:
        service_request.status = 'OFFERS_READY'
        service_request.save()
        
        Notifications.objects.create(
            user=service_request.customer,
            title="Offers Ready! 🎉",
            message=f"We've received {successful_count} offer(s) for your {types_str} request. Review and pick the best one!",
            notification_type='offers_ready'
        )
    elif successful_count > 0:
        # We have offers but some negotiations still active - notify customer
        Notifications.objects.create(
            user=service_request.customer,
            title="New Offer Received!",
            message=f"A provider has responded to your {types_str} request. More offers may be coming!",
            notification_type='new_offer'
        )
        
@shared_task
def send_telegram_invitation(user_id):
    """
    Create in-app notification prompting user to link Telegram
    """
    user = NewUser.objects.get(id=user_id)
    
    from app.models import Notifications
    
    # Create notification
    Notifications.objects.create(
        user=user,
        title="🔗 Link Your Telegram Account",
        message=(
            f"Get instant job notifications on Telegram! "
            f"Search for @{settings.TELEGRAM_BOT_USERNAME} and send /start"
        ),
        notification_type="telegram_invitation"
    )
    
    # Also store invitation status
    from django.core.cache import cache
    cache.set(f'telegram_invite_pending:{user.id}', True, timeout=2592000)  # 30 days
    
    print(f"✅ In-app invitation created for {user.first_name}")
