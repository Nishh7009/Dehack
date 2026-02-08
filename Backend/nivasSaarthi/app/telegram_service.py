# telegram_service.py
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from asgiref.sync import sync_to_async
from app.models import NewUser, NegotiationSession
import os
import re

# Language options supported by Sarvam
LANGUAGE_OPTIONS = {
    'en': 'English',
    'hi': 'हिंदी (Hindi)',
    'bn': 'বাংলা (Bengali)',
    'ta': 'தமிழ் (Tamil)',
    'te': 'తెలుగు (Telugu)',
    'mr': 'मराठी (Marathi)',
    'gu': 'ગુજરાતી (Gujarati)',
    'kn': 'ಕನ್ನಡ (Kannada)',
    'ml': 'മലയാളം (Malayalam)',
    'pa': 'ਪੰਜਾਬੀ (Punjabi)',
}

class TelegramNegotiationBot:
    # In TelegramNegotiationBot.__init__

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.application = Application.builder().token(self.bot_token).build()
        
        # Register handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("language", self.language_command))
        
        # Handle language selection callback
        self.application.add_handler(CallbackQueryHandler(self.handle_language_selection, pattern="^lang_"))
        
        # Handle accept/reject callbacks
        self.application.add_handler(CallbackQueryHandler(self.handle_accept, pattern="^accept_"))
        self.application.add_handler(CallbackQueryHandler(self.handle_reject, pattern="^reject_"))
        self.application.add_handler(CallbackQueryHandler(self.handle_counter, pattern="^counter_"))
        
        # Handle contact sharing (phone number)
        self.application.add_handler(MessageHandler(
            filters.CONTACT, 
            self.handle_contact
        ))
        
        # Handle text messages (for negotiation responses)
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_negotiation_message
        ))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /start - Auto-link by phone number
        User just sends /start, bot matches their Telegram account to phone
        """
        from telegram import KeyboardButton, ReplyKeyboardMarkup
        
        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username
        telegram_user = update.effective_user
        
        # Check if already linked
        existing_user = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        
        if existing_user:
            await update.message.reply_text(
                f"✅ Welcome back, {existing_user.first_name}!\n\n"
                "You're already linked and will receive service requests here."
            )
            return
        
        # Request phone number via contact button
        # Note: This button only works on mobile Telegram apps
        contact_button = KeyboardButton(
            text="📱 Share Phone Number",
            request_contact=True
        )
        reply_markup = ReplyKeyboardMarkup(
            [[contact_button]],
            one_time_keyboard=True,
            resize_keyboard=True
        )
        
        await update.message.reply_text(
            "👋 Welcome to ServiceConnect!\n\n"
            "To link your account and receive service requests, "
            "please share your phone number using the button below.\n\n"
            "⚠️ Note: The share button only works on mobile Telegram apps. "
            "If you're on desktop, please open Telegram on your phone.",
            reply_markup=reply_markup
        )
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle phone number shared by user
        This is automatically triggered when user shares contact
        """
        contact = update.message.contact
        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username
        
        if not contact:
            return
        
        # Get phone number (Telegram returns in format like +919876543210)
        phone_number = contact.phone_number
        
        # Normalize to 10 digits (strip country code +91 or 91)
        if phone_number:
            # Remove any non-digit characters
            phone_number = ''.join(filter(str.isdigit, phone_number))
            # Take last 10 digits (removes country code)
            if len(phone_number) > 10:
                phone_number = phone_number[-10:]
        
        # Find user by phone number
        user = await sync_to_async(NewUser.objects.filter(
            phone_number=phone_number
        ).first)()
        
        if not user:
            await update.message.reply_text(
                "❌ Phone number not found in our system.\n\n"
                "Please register in the app first, then come back here.",
                reply_markup={"remove_keyboard": True}
            )
            return
        
        # Check if this phone belongs to a different Telegram account
        if user.telegram_chat_id and user.telegram_chat_id != chat_id:
            await update.message.reply_text(
                "⚠️ This phone number is already linked to another Telegram account.\n\n"
                "Please contact support if this is an error.",
                reply_markup={"remove_keyboard": True}
            )
            return
        
        # Link the account!
        user.telegram_chat_id = chat_id
        user.telegram_username = username
        await sync_to_async(user.save)()
        
        # Remove keyboard and confirm
        from telegram import ReplyKeyboardRemove
        
        await update.message.reply_text(
            f"✅ Successfully linked!\n\n"
            f"Account: {user.first_name} {user.last_name}\n"
            f"Phone: {user.phone_number}\n"
            f"Role: {user.get_role_display()}\n\n"
            "You'll now receive service request notifications here!",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Notify user in the app
        from app.models import Notifications
        await sync_to_async(Notifications.objects.create)(
            user=user,
            title="Telegram Linked Successfully",
            message=f"Your Telegram account @{username} has been linked.",
            notification_type="telegram_linked"
        )
        
        # Ask for language preference
        await self.send_language_selection(update, user)

    async def language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /language command to change language preference"""
        chat_id = str(update.effective_chat.id)
        
        user = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        
        if not user:
            await update.message.reply_text(
                "Please link your account first using /start"
            )
            return
        
        await self.send_language_selection(update, user)

    async def send_language_selection(self, update: Update, user):
        """Send language selection inline keyboard"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        # Create inline keyboard with language options (2 columns)
        keyboard = []
        row = []
        for code, name in LANGUAGE_OPTIONS.items():
            # Add checkmark if this is current language
            display = f"✓ {name}" if user.preferred_language == code else name
            row.append(InlineKeyboardButton(display, callback_data=f"lang_{code}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        current_lang = LANGUAGE_OPTIONS.get(user.preferred_language, 'English')
        await update.message.reply_text(
            f"🌐 *Select your preferred language*\n\n"
            f"Current: {current_lang}\n\n"
            "All messages from the bot will be translated to your chosen language.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def handle_language_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle language selection callback"""
        query = update.callback_query
        await query.answer()
        
        chat_id = str(update.effective_chat.id)
        lang_code = query.data.replace("lang_", "")
        
        user = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        
        if not user:
            await query.edit_message_text("Error: User not found")
            return
        
        # Update user's language preference
        user.preferred_language = lang_code
        await sync_to_async(user.save)()
        
        lang_name = LANGUAGE_OPTIONS.get(lang_code, lang_code)
        
        # Translate confirmation message
        confirmation = await self.translate_message(
            f"Language set to {lang_name}. You will now receive messages in this language.",
            'en',
            lang_code
        )
        
        await query.edit_message_text(f"✅ {confirmation}")

    async def handle_negotiation_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages from providers during negotiation"""
        chat_id = str(update.effective_chat.id)
        message_text = update.message.text
        
        # Find active negotiation session for this chat
        session = await sync_to_async(NegotiationSession.objects.filter(
            provider_phone=chat_id,
            status='active'
        ).select_related('service_request').first)()
        
        if not session:
            # No active negotiation, ignore or send help message
            return
        
        # Get provider's language preference
        provider = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        target_lang = provider.preferred_language if provider else 'en'
        
        # Try to extract price from message
        price = self.extract_price(message_text)
        
        if price:
            # Update current offer
            session.current_offer = price
            session.message_count += 1
            
            # Add to conversation history
            history = session.conversation_history or []
            history.append({'role': 'provider', 'message': message_text, 'price': float(price)})
            session.conversation_history = history
            await sync_to_async(session.save)()
            
            # Check if price is acceptable
            if price <= session.min_acceptable:
                # Auto-accept
                response = f"Great! ₹{price} is within budget. The customer will be notified. Thank you!"
                if target_lang != 'en':
                    response = await self.translate_message(response, 'en', target_lang)
                
                session.status = 'completed'
                session.outcome = 'agreed'
                await sync_to_async(session.save)()
                
                await update.message.reply_text(f"✅ {response}")
                return
            
            elif price > session.max_price:
                # Price too high, negotiate
                response = await self.get_ai_negotiation_response(session, message_text, price)
                if target_lang != 'en':
                    response = await self.translate_message(response, 'en', target_lang)
                
                # Send with accept/reject/counter buttons
                await self.send_negotiation_options(update, session, response, price)
            
            else:
                # Price within range, ask customer via buttons
                response = f"You offered ₹{price}. This is within the customer's budget range."
                if target_lang != 'en':
                    response = await self.translate_message(response, 'en', target_lang)
                
                await self.send_negotiation_options(update, session, response, price)
        else:
            # No price found, ask for price
            response = "Please provide your price offer (e.g., ₹500 or 500)"
            if target_lang != 'en':
                response = await self.translate_message(response, 'en', target_lang)
            await update.message.reply_text(response)

    def extract_price(self, text: str):
        """Extract price from text message"""
        # Match patterns like ₹500, Rs.500, Rs 500, 500 rupees, just 500, etc.
        patterns = [
            r'₹\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'rs\.?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:rupees?|rs)',
            r'^(\d+(?:,\d+)*(?:\.\d+)?)$',  # Just a number
            r'(\d+(?:,\d+)*(?:\.\d+)?)',  # Any number in text
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.lower().replace(',', ''))
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except:
                    continue
        return None

    async def get_ai_negotiation_response(self, session, provider_message: str, offered_price: float) -> str:
        """Get AI-generated negotiation response using Sarvam"""
        try:
            from sarvamai import SarvamAI
            import os
            
            client = SarvamAI(api_subscription_key=os.getenv('SARVAM_API_KEY'))
            
            # Build context
            service_request = session.service_request
            budget_info = f"Customer budget: ₹{session.min_acceptable} (ideal) to ₹{session.max_price} (max)"
            
            system_prompt = f"""You are a friendly negotiation assistant helping a customer get the best price for a service.
            
Service: {', '.join(service_request.service_types) if isinstance(service_request.service_types, list) else service_request.service_types}
Description: {service_request.description}
{budget_info}

Current offer from provider: ₹{offered_price}

Your goal:
- If price is above max budget (₹{session.max_price}), politely decline and suggest a lower price
- If price is between ideal and max, try to negotiate down closer to ideal
- Be friendly and professional
- Keep responses short (1-2 sentences)
- Always mention a specific counter-offer price"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Provider says: {provider_message}"}
            ]
            
            response = client.chat.completions(
                model="sarvam-m",
                messages=messages,
                max_tokens=150
            )
            
            if hasattr(response, 'choices') and response.choices:
                return response.choices[0].message.content
            return f"Thank you for your offer of ₹{offered_price}. Could you consider ₹{session.min_acceptable + (session.max_price - session.min_acceptable) * 0.3:.0f}?"
            
        except Exception as e:
            print(f"AI negotiation error: {e}")
            # Fallback response
            counter = session.min_acceptable + (session.max_price - session.min_acceptable) * 0.3
            return f"Thank you for your offer. Our budget is around ₹{counter:.0f}. Would that work for you?"

    async def send_negotiation_options(self, update: Update, session, message: str, current_price: float):
        """Send message with accept/reject/counter buttons"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        session_id = str(session.id)
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"accept_{session_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{session_id}")
            ],
            [
                InlineKeyboardButton("💬 Counter Offer", callback_data=f"counter_{session_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        full_message = f"{message}\n\n💰 Current offer: ₹{current_price}"
        await update.message.reply_text(full_message, reply_markup=reply_markup)

    async def handle_accept(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle accept button press"""
        query = update.callback_query
        await query.answer()
        
        session_id = query.data.replace("accept_", "")
        chat_id = str(update.effective_chat.id)
        
        session = await sync_to_async(NegotiationSession.objects.filter(
            id=session_id,
            provider_phone=chat_id
        ).first)()
        
        if not session:
            await query.edit_message_text("Session not found or expired.")
            return
        
        # Get provider's language
        provider = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        target_lang = provider.preferred_language if provider else 'en'
        
        # Mark as completed
        session.status = 'completed'
        session.outcome = 'agreed'
        await sync_to_async(session.save)()
        
        response = f"✅ Deal accepted at ₹{session.current_offer}!\n\nThe customer will be notified and will contact you soon with further details."
        if target_lang != 'en':
            response = await self.translate_message(response, 'en', target_lang)
        
        await query.edit_message_text(response)
        
        # TODO: Notify customer about accepted offer

    async def handle_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle reject button press"""
        query = update.callback_query
        await query.answer()
        
        session_id = query.data.replace("reject_", "")
        chat_id = str(update.effective_chat.id)
        
        session = await sync_to_async(NegotiationSession.objects.filter(
            id=session_id,
            provider_phone=chat_id
        ).first)()
        
        if not session:
            await query.edit_message_text("Session not found or expired.")
            return
        
        # Get provider's language
        provider = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        target_lang = provider.preferred_language if provider else 'en'
        
        # Mark as failed
        session.status = 'failed'
        session.outcome = 'no_deal'
        await sync_to_async(session.save)()
        
        response = "❌ Negotiation ended. Thank you for your time. We'll reach out for future opportunities."
        if target_lang != 'en':
            response = await self.translate_message(response, 'en', target_lang)
        
        await query.edit_message_text(response)

    async def handle_counter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle counter offer button press"""
        query = update.callback_query
        await query.answer()
        
        session_id = query.data.replace("counter_", "")
        chat_id = str(update.effective_chat.id)
        
        session = await sync_to_async(NegotiationSession.objects.filter(
            id=session_id,
            provider_phone=chat_id
        ).first)()
        
        if not session:
            await query.edit_message_text("Session not found or expired.")
            return
        
        # Get provider's language
        provider = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        target_lang = provider.preferred_language if provider else 'en'
        
        response = "Please type your new price offer (e.g., 450 or ₹450)"
        if target_lang != 'en':
            response = await self.translate_message(response, 'en', target_lang)
        
        await query.edit_message_text(f"💬 {response}")

    async def translate_message(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text using Sarvam AI"""
        if source_lang == target_lang or target_lang == 'en':
            return text
        
        try:
            from app import sarvam_service
            print(f"Translating from {source_lang} to {target_lang}: {text[:50]}...")
            translated = await sync_to_async(sarvam_service.translate_text)(
                text, source_lang, target_lang
            )
            print(f"Translation result: {translated[:50] if translated else 'None'}...")
            return translated if translated else text
        except Exception as e:
            print(f"Translation error: {e}")
            import traceback
            traceback.print_exc()
            return text

    async def process_update(self, update_data: dict):
        """
        Process an incoming webhook update from Telegram.
        Call this from your Django webhook view.
        """
        update = Update.de_json(update_data, self.application.bot)
        await self.application.process_update(update)
    
    async def initialize(self):
        """Initialize the application (required before processing updates)."""
        await self.application.initialize()
    
    async def send_negotiation_request(self, chat_id: str, service_request, session):
        """
        Send a negotiation request message to a provider via Telegram.
        Translates the message to the provider's preferred language.
        """
        import asyncio
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        # Initialize the bot if needed
        try:
            await self.application.initialize()
        except Exception:
            pass  # Already initialized
        
        # Get provider's preferred language
        provider = await sync_to_async(NewUser.objects.filter(
            telegram_chat_id=chat_id
        ).first)()
        
        target_lang = provider.preferred_language if provider else 'en'
        
        # Format service types
        service_types = service_request.service_types
        if isinstance(service_types, list):
            service_types = ', '.join(service_types)
        
        # Build the message in English first
        message = (
            f"🔔 New Service Request\n\n"
            f"Service: {service_types}\n"
            f"Description: {service_request.description}\n"
            f"Budget Range: ₹{session.min_acceptable} - ₹{session.max_price}\n\n"
            f"Please reply with your price offer to start negotiation."
        )
        
        # Translate if not English
        if target_lang != 'en':
            message = await self.translate_message(message, 'en', target_lang)
        
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message
            )
            return True
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False
    
    def send_negotiation_request_sync(self, chat_id: str, service_request, session):
        """
        Synchronous wrapper for send_negotiation_request.
        Use this from Django views.
        """
        import asyncio
        import requests
        from app import sarvam_service
        
        # Get provider's preferred language
        try:
            provider = NewUser.objects.filter(telegram_chat_id=chat_id).first()
            target_lang = provider.preferred_language if provider else 'en'
        except Exception:
            target_lang = 'en'
        
        # Format service types
        service_types = service_request.service_types
        if isinstance(service_types, list):
            service_types = ', '.join(service_types)
        
        # Build the message in English first
        message = (
            f"🔔 New Service Request\n\n"
            f"Service: {service_types}\n"
            f"Description: {service_request.description}\n"
            f"Budget Range: ₹{session.min_acceptable} - ₹{session.max_price}\n\n"
            f"Please reply with your price offer to start negotiation."
        )
        
        # Translate if not English
        if target_lang and target_lang != 'en':
            try:
                translated = sarvam_service.translate_text(message, 'en', target_lang)
                if translated:
                    message = translated
            except Exception as e:
                print(f"Translation error: {e}")
        
        # Send via Telegram HTTP API directly (simpler than async)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message
        }
        
        try:
            response = requests.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False
    
    def run_polling(self):
        """Run the bot in polling mode (for development/testing)."""
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def run(self):
        """Alias for run_polling - used by management command."""
        self.run_polling()

telegram_bot = TelegramNegotiationBot()