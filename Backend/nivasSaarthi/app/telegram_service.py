# app/telegram_service.py

import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from django.conf import settings
from asgiref.sync import sync_to_async
from app.models import NegotiationSession, ServiceRequest, ServiceProviderProfile
from app import sarvam_service
from decimal import Decimal
import re

class TelegramNegotiationBot:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.application = Application.builder().token(self.bot_token).build()
        
        # Register handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("accept", self.accept_command))
        self.application.add_handler(CommandHandler("reject", self.reject_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "Welcome! I'm an AI negotiation assistant. "
            "I'll help negotiate service prices with customers.\n\n"
            "You can:\n"
            "• Reply with your price offer\n"
            "• Use /accept to accept current offer\n"
            "• Use /reject to decline negotiation"
        )
    
    async def accept_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Provider accepts the current offer"""
        chat_id = str(update.effective_chat.id)
        
        # Find active negotiation
        session = await sync_to_async(NegotiationSession.objects.filter)(
            telegram_chat_id=chat_id,
            status='active'
        )
        session = await sync_to_async(session.first)()
        
        if not session:
            await update.message.reply_text("No active negotiation found.")
            return
        
        if session.counter_offer:
            # Accept the AI's counter offer
            session.current_offer = session.counter_offer
            session.status = 'completed'
            session.outcome = 'agreed'
            await sync_to_async(session.save)()
            
            await update.message.reply_text(
                f"✅ Deal confirmed at ₹{session.counter_offer}!\n"
                f"The customer will be notified. You'll receive booking details soon."
            )
            
            # Notify customer (you'll implement this)
            await self.notify_customer_deal_agreed(session)
        else:
            await update.message.reply_text("No offer to accept yet.")
    
    async def reject_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Provider rejects the negotiation"""
        chat_id = str(update.effective_chat.id)
        
        session = await sync_to_async(NegotiationSession.objects.filter)(
            telegram_chat_id=chat_id,
            status='active'
        )
        session = await sync_to_async(session.first)()
        
        if not session:
            await update.message.reply_text("No active negotiation found.")
            return
        
        session.status = 'completed'
        session.outcome = 'no_deal'
        await sync_to_async(session.save)()
        
        await update.message.reply_text(
            "Negotiation declined. Thank you for your time."
        )
        
        # Notify customer
        await self.notify_customer_deal_failed(session)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle provider's messages (price offers or questions)"""
        chat_id = str(update.effective_chat.id)
        message_text = update.message.text
        
        # Find active negotiation
        session = await sync_to_async(NegotiationSession.objects.filter)(
            telegram_chat_id=chat_id,
            status='active'
        )
        session = await sync_to_async(session.first)()
        
        if not session:
            await update.message.reply_text(
                "No active negotiation. Wait for a customer request."
            )
            return
        
        # Check if message contains a price
        price_match = re.search(r'(\d+(?:,\d+)*(?:\.\d+)?)', message_text)
        
        if price_match:
            # Extract and parse price
            price_str = price_match.group(1).replace(',', '')
            offered_price = Decimal(price_str)
            
            session.current_offer = offered_price
            await sync_to_async(session.add_message)('provider', message_text)
            
            # Check if within acceptable range
            if offered_price <= session.min_acceptable:
                # Auto-accept
                session.status = 'completed'
                session.outcome = 'agreed'
                await sync_to_async(session.save)()
                
                await update.message.reply_text(
                    f"✅ Excellent! Deal confirmed at ₹{offered_price}.\n"
                    f"The customer accepts your offer. Booking details will be sent shortly."
                )
                
                await self.notify_customer_deal_agreed(session)
                
            elif offered_price > session.max_price:
                # Too expensive - negotiate down
                ai_response = await self.generate_ai_response(session, "price_too_high")
                
                await update.message.reply_text(ai_response)
                await sync_to_async(session.add_message)('ai', ai_response)
                
            else:
                # Within range - continue negotiating
                ai_response = await self.generate_ai_response(session, "negotiate")
                
                await update.message.reply_text(ai_response)
                await sync_to_async(session.add_message)('ai', ai_response)
        else:
            # No price in message - respond with AI
            await sync_to_async(session.add_message)('provider', message_text)
            ai_response = await self.generate_ai_response(session, "general")
            
            await update.message.reply_text(ai_response)
            await sync_to_async(session.add_message)('ai', ai_response)
    
    async def generate_ai_response(self, session, scenario: str):
        """Generate AI negotiation response using Sarvam or GPT"""
        service_req = await sync_to_async(lambda: session.service_request)()
        
        if scenario == "price_too_high":
            # Price above max budget
            suggested_counter = min(
                session.max_price,
                session.current_offer * Decimal('0.85')  # 15% reduction
            )
            session.counter_offer = suggested_counter
            await sync_to_async(session.save)()
            
            prompt = f"""You are negotiating a {service_req.service_type} service.
The provider offered ₹{session.current_offer}, but the customer's budget is ₹{session.max_price}.

Politely counter-offer at ₹{suggested_counter}. Be friendly but firm.
Mention the customer's budget constraints."""
            
        elif scenario == "negotiate":
            # Within range - try to get lower
            suggested_counter = (session.current_offer + session.min_acceptable) / 2
            session.counter_offer = suggested_counter
            await sync_to_async(session.save)()
            
            prompt = f"""You are negotiating a {service_req.service_type} service.
The provider offered ₹{session.current_offer}. This is acceptable, but you want a better deal.

Counter-offer at ₹{suggested_counter}. Be polite and professional."""
            
        else:
            # General conversation
            prompt = f"""You are negotiating a {service_req.service_type} service.
Provider said: "{session.conversation_history[-1]['content']}"

Respond professionally and guide them to make a price offer if they haven't.
Budget range: ₹{session.min_acceptable} - ₹{session.max_price}"""
        
        # Use Sarvam AI or OpenAI
        try:
            # Option 1: Use Sarvam (if it supports chat)
            # response = await asyncio.to_thread(sarvam_service.generate_text, prompt)
            
            # Option 2: Simple template-based response (fallback)
            if scenario == "price_too_high":
                response = f"Thanks for the offer of ₹{session.current_offer}. However, that's a bit above our customer's budget. Would you consider ₹{session.counter_offer}?"
            elif scenario == "negotiate":
                response = f"₹{session.current_offer} is close! How about we meet in the middle at ₹{session.counter_offer}?"
            else:
                response = "Could you please share your best price for this service?"
            
            return response
            
        except Exception as e:
            return f"I understand. Could you share your best price for this {service_req.service_type} service?"
    
    async def send_negotiation_request(self, session: NegotiationSession):
        """Initiate negotiation with provider via Telegram"""
        bot = Bot(token=self.bot_token)
        
        service_req = await sync_to_async(lambda: session.service_request)()
        
        message = f"""🔔 New Service Request

Service: {service_req.service_type}
Location: {service_req.location}
Details: {service_req.description}

Customer's budget range: ₹{session.min_acceptable} - ₹{session.max_price}

Please share your best price for this service.

Commands:
/accept - Accept current offer
/reject - Decline this request"""
        
        try:
            await bot.send_message(
                chat_id=session.telegram_chat_id,
                text=message
            )
            
            await sync_to_async(session.add_message)('ai', message)
            return True
            
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False
    
    async def notify_customer_deal_agreed(self, session):
        """Notify customer that deal was agreed"""
        # Create notification
        from app.models import Notifications
        
        service_req = await sync_to_async(lambda: session.service_request)()
        customer = await sync_to_async(lambda: service_req.customer)()
        
        await sync_to_async(Notifications.objects.create)(
            user=customer,
            title="Negotiation Successful!",
            message=f"Provider agreed to ₹{session.current_offer} for your {service_req.service_type} service.",
            notification_type="negotiation_success"
        )
    
    async def notify_customer_deal_failed(self, session):
        """Notify customer that negotiation failed"""
        from app.models import Notifications
        
        service_req = await sync_to_async(lambda: session.service_request)()
        customer = await sync_to_async(lambda: service_req.customer)()
        
        await sync_to_async(Notifications.objects.create)(
            user=customer,
            title="Negotiation Failed",
            message=f"Provider declined the negotiation for your {service_req.service_type} service.",
            notification_type="negotiation_failed"
        )
    
    def run(self):
        """Run the bot"""
        self.application.run_polling()

# Global bot instance
telegram_bot = TelegramNegotiationBot()