"""
WhatsApp AI Negotiation System
Uses Sarvam AI to negotiate prices with service providers via Twilio WhatsApp.
"""

import os
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from twilio.rest import Client

from .models import ServiceRequest, NegotiationSession, NewUser, Notifications


# ============================================================================
# TWILIO WHATSAPP MESSAGING
# ============================================================================

def get_twilio_client():
    """Get Twilio client instance"""
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    return Client(account_sid, auth_token)


def send_whatsapp_message(to_phone: str, message: str) -> bool:
    """
    Send a WhatsApp message via Twilio.
    
    Args:
        to_phone: Recipient phone in E.164 format (+919876543210)
        message: Message text to send
    
    Returns:
        bool: True if sent successfully
    """
    try:
        client = get_twilio_client()
        from_whatsapp = f"whatsapp:{os.getenv('TWILIO_PHONE_NUMBER')}"
        to_whatsapp = f"whatsapp:{to_phone}"
        
        client.messages.create(
            body=message,
            from_=from_whatsapp,
            to=to_whatsapp
        )
        return True
    except Exception as e:
        print(f"WhatsApp send error: {e}")
        return False


# ============================================================================
# SARVAM AI CHAT
# ============================================================================

def get_sarvam_client():
    """Get Sarvam AI client"""
    from sarvamai import SarvamAI
    api_key = os.getenv("SARVAM_API_KEY")
    return SarvamAI(api_subscription_key=api_key)


def build_system_prompt(session: NegotiationSession) -> str:
    """Build the system prompt for Sarvam AI with negotiation context"""
    service_request = session.service_request
    
    return f"""You are a skilled negotiation agent for NivasSaarthi, negotiating service prices on behalf of customers.

NEGOTIATION CONTEXT:
- Service: {service_request.description}
- Customer's Maximum Budget: ₹{session.max_price}
- Auto-Accept Threshold: ₹{session.min_acceptable} (accept immediately if provider offers this or less)
- Current Provider Offer: ₹{session.current_offer or 'Not yet offered'}

YOUR OBJECTIVES:
1. Get the best possible price for the customer, ideally at or below ₹{session.min_acceptable}
2. NEVER agree to a price above ₹{session.max_price} - this is the hard limit
3. Use polite but firm negotiation tactics
4. Respond in the same language as the provider (Hindi, English, or regional languages)

NEGOTIATION TACTICS:
- Start with a counter-offer 10-20% below their ask
- Highlight the customer's value as a potential repeat client
- Mention comparable market rates if appropriate
- Be willing to meet in the middle, but stay within budget

RESPONSE FORMAT:
- If provider gives a price, respond with a counter-offer or acceptance
- If the price is within budget, you may accept with: "DEAL ACCEPTED: ₹[price]"
- If negotiation fails, respond with: "DEAL FAILED: [reason]"
- Keep responses concise and natural for WhatsApp

IMPORTANT: Your response will be sent directly to the provider via WhatsApp."""


def get_ai_response(session: NegotiationSession, provider_message: str) -> str:
    """
    Get Sarvam AI's response for the negotiation.
    
    Args:
        session: The NegotiationSession
        provider_message: Latest message from the provider
    
    Returns:
        str: AI's response to send to provider
    """
    client = get_sarvam_client()
    
    # Build messages for API
    messages = [
        {"role": "system", "content": build_system_prompt(session)}
    ]
    
    # Add conversation history
    for msg in session.conversation_history[-8:]:  # Last 8 messages for context
        messages.append({
            "role": msg['role'],
            "content": msg['content']
        })
    
    # Add current provider message
    messages.append({"role": "user", "content": provider_message})
    
    try:
        response = client.chat.completions(
            model="sarvam-m",
            messages=messages,
            temperature=0.7,
            max_tokens=256
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Sarvam AI error: {e}")
        return "I'll need to get back to you on this. Thank you for your patience."


# ============================================================================
# NEGOTIATION FLOW
# ============================================================================

def start_negotiation(
    service_request_id: str,
    max_budget: Decimal,
    min_acceptable: Decimal,
    session_hours: int = 24
) -> NegotiationSession:
    """
    Start a new negotiation session for a service request.
    
    Args:
        service_request_id: UUID of the ServiceRequest
        max_budget: Customer's maximum budget
        min_acceptable: Price at which to auto-accept
        session_hours: Hours before session expires
    
    Returns:
        NegotiationSession: The created session
    """
    service_request = ServiceRequest.objects.get(id=service_request_id)
    provider = service_request.service_provider
    
    # Create session
    session = NegotiationSession.objects.create(
        service_request=service_request,
        provider_phone=provider.phone_number,
        max_price=max_budget,
        min_acceptable=min_acceptable,
        expires_at=timezone.now() + timedelta(hours=session_hours)
    )
    
    # Update service request status
    service_request.customer_budget = max_budget
    service_request.negotiation_status = 'IN_PROGRESS'
    service_request.save()
    
    # Build and send initial message
    initial_message = build_initial_message(service_request, max_budget)
    
    if send_whatsapp_message(provider.phone_number, initial_message):
        session.add_message('assistant', initial_message)
    
    return session


def build_initial_message(service_request: ServiceRequest, budget: Decimal) -> str:
    """Build the initial outreach message to the provider"""
    customer = service_request.customer
    
    return f"""Namaste! 🙏

I'm reaching out on behalf of {customer.first_name} who needs help with: {service_request.description}

Their budget for this service is around ₹{budget}.

Would you be available to help? Please share your quote for this job.

Thank you!
- NivasSaarthi AI Assistant"""


def process_provider_response(phone_number: str, message: str) -> str:
    """
    Process an incoming WhatsApp message from a provider.
    
    Args:
        phone_number: Provider's phone number (from Twilio webhook)
        message: Message content from provider
    
    Returns:
        str: Response to send back to provider
    """
    # Find active negotiation session for this phone
    try:
        session = NegotiationSession.objects.filter(
            provider_phone=phone_number,
            status='active'
        ).latest('created_at')
    except NegotiationSession.DoesNotExist:
        return "Sorry, I couldn't find an active negotiation. Please contact support."
    
    # Check if session expired
    if session.is_expired():
        session.status = 'expired'
        session.outcome = 'timeout'
        session.save()
        
        session.service_request.negotiation_status = 'EXPIRED'
        session.service_request.save()
        
        return "This negotiation has expired. Thank you for your time."
    
    # Add provider message to history
    session.add_message('user', message)
    
    # Try to extract price from message
    extracted_price = extract_price_from_message(message)
    if extracted_price:
        session.current_offer = extracted_price
        session.save()
        
        # Check if offer is auto-acceptable
        if extracted_price <= session.min_acceptable:
            return finalize_negotiation(session, extracted_price, 'agreed')
        
        # Check if offer exceeds max budget
        if extracted_price > session.max_price:
            # AI will try to negotiate down
            pass
    
    # Get AI response
    ai_response = get_ai_response(session, message)
    
    # Check if AI decided to accept or fail
    if "DEAL ACCEPTED:" in ai_response:
        # Extract the accepted price
        try:
            price_str = ai_response.split("DEAL ACCEPTED:")[1].strip()
            price = Decimal(price_str.replace("₹", "").replace(",", "").strip())
            return finalize_negotiation(session, price, 'agreed')
        except:
            pass
    
    if "DEAL FAILED:" in ai_response:
        session.status = 'failed'
        session.outcome = 'no_deal'
        session.save()
        
        session.service_request.negotiation_status = 'FAILED'
        session.service_request.save()
    
    # Save AI response and send
    session.add_message('assistant', ai_response)
    
    return ai_response


def extract_price_from_message(message: str) -> Decimal | None:
    """Extract price from a message, handling various formats"""
    import re
    
    # Common patterns for Indian Rupee prices
    patterns = [
        r'₹\s*([\d,]+)',           # ₹1,500 or ₹1500
        r'Rs\.?\s*([\d,]+)',       # Rs. 1500 or Rs 1500
        r'(\d{3,})\s*(?:rs|rupees|rupee|/-)', # 1500 rs or 1500/-
        r'(\d+,?\d*)\s*(?:only)?$' # Just a number at the end
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            try:
                price_str = match.group(1).replace(',', '')
                return Decimal(price_str)
            except:
                continue
    
    return None


def finalize_negotiation(session: NegotiationSession, agreed_price: Decimal, outcome: str) -> str:
    """
    Finalize a negotiation with the agreed price.
    
    Args:
        session: The NegotiationSession
        agreed_price: The final agreed price
        outcome: 'agreed' or 'no_deal'
    
    Returns:
        str: Final message to provider
    """
    session.status = 'completed'
    session.outcome = outcome
    session.current_offer = agreed_price
    session.save()
    
    # Update service request
    service_request = session.service_request
    service_request.negotiated_price = agreed_price
    service_request.negotiation_status = 'COMPLETED'
    service_request.save()
    
    # Notify customer
    Notifications.objects.create(
        user=service_request.customer,
        title="Negotiation Complete!",
        message=f"Great news! We've negotiated a price of ₹{agreed_price} for '{service_request.description}'. Please review and confirm.",
        notification_type='negotiation_complete'
    )
    
    return f"""Thank you! 🎉

The customer will be notified about your offer of ₹{agreed_price}.

We'll confirm the booking shortly. Looking forward to working with you!

- NivasSaarthi"""


def get_negotiation_status(session_id: str) -> dict:
    """Get the current status of a negotiation session"""
    try:
        session = NegotiationSession.objects.get(id=session_id)
        return {
            'status': session.status,
            'outcome': session.outcome,
            'current_offer': float(session.current_offer) if session.current_offer else None,
            'message_count': session.message_count,
            'is_expired': session.is_expired(),
            'expires_at': session.expires_at.isoformat(),
        }
    except NegotiationSession.DoesNotExist:
        return {'error': 'Session not found'}
