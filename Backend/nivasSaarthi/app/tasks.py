"""
Celery tasks for automated multi-provider negotiation.
"""

from linecache import cache
from .models import NewUser
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging
from telegram import Bot

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def negotiate_with_providers(self, service_request_id: str):
    """
    Main Celery task: Find nearby providers and start negotiations with all of them.
    
    This task:
    1. Finds providers within 5km matching ANY of the service types
    2. Creates a NegotiationSession for each provider
    3. Sends initial WhatsApp messages to all providers
    4. Updates progress tracking
    5. The webhook handles responses asynchronously
    """
    from .models import ServiceRequest, NegotiationSession, NewUser, ServiceProviderProfile
    from .whatsapp_negotiator import send_whatsapp_message
    
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
    expires_at = timezone.now() + timedelta(hours=settings.NEGOTIATION_TIMEOUT_HOURS)
    
    sessions_created = 0
    
    for provider in providers[:settings.NEGOTIATION_MAX_PROVIDERS]:
        # Skip if no phone number
        if not provider.phone_number:
            logger.warning(f"Provider {provider.id} has no phone number, skipping")
            continue
        
        # Create negotiation session
        session = NegotiationSession.objects.create(
            service_request=service_request,
            provider_phone=provider.phone_number,
            max_price=service_request.customer_budget,
            expires_at=expires_at
        )
        
        # Build and send initial message
        initial_message = build_initial_message_for_provider(
            service_request=service_request,
            provider=provider,
            budget=service_request.customer_budget
        )
        
        if send_whatsapp_message(provider.phone_number, initial_message):
            session.add_message('assistant', initial_message)
            sessions_created += 1
            logger.info(f"Started negotiation with provider {provider.id}")
        else:
            session.status = 'failed'
            session.outcome = 'no_deal'
            session.save()
            logger.error(f"Failed to send WhatsApp to provider {provider.id}")
    
    # Update progress tracking
    service_request.providers_contacted = sessions_created
    
    if sessions_created == 0:
        service_request.status = 'EXPIRED'
        service_request.save()
        return {'status': 'failed', 'message': 'Could not reach any providers'}
    
    service_request.save()
    logger.info(f"Started {sessions_created} negotiations for request {service_request_id}")
    
    # Schedule a task to check for completion
    check_negotiation_status.apply_async(
        args=[service_request_id],
        countdown=settings.NEGOTIATION_TIMEOUT_HOURS * 3600  # Check after timeout
    )
    
    return {
        'status': 'started',
        'providers_contacted': sessions_created,
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
    ).filter(
        distance__lte=5000  # 5km in meters
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