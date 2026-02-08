# app/management/commands/run_telegram_bot.py

from django.core.management.base import BaseCommand
from app.telegram_service import telegram_bot
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class Command(BaseCommand):
    help = 'Run the Telegram negotiation bot'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        self.stdout.write(self.style.WARNING('Press Ctrl+C to stop'))
        
        try:
            telegram_bot.run()
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\nBot stopped gracefully'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Bot error: {str(e)}'))