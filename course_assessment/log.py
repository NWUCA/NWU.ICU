import logging

import telebot
from django.conf import settings


class TelegramBotHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.bot = telebot.TeleBot(settings.TELEGRAM_BOT_API_TOKEN)

    def emit(self, record):
        msg = self.format(record)
        self.bot.send_message(settings.TELEGRAM_CHAT_ID, msg)
