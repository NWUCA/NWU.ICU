import logging
from copy import copy

import telebot
from django.conf import settings
from django.views.debug import ExceptionReporter


class TrimmedExceptionReporter(ExceptionReporter):
    def get_traceback_data(self):
        data = super().get_traceback_data()
        data.pop('settings', None)
        data.pop('request_meta', None)
        return data


class TelegramBotHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.bot = telebot.TeleBot(settings.TELEGRAM_BOT_API_TOKEN)

    def emit(self, record):
        # 基本照着 django.utils.log.AdminEmailHandler 写的
        try:
            request = record.request
        except Exception:
            request = None

        # Since we add a nicely formatted traceback on our own, create a copy
        # of the log record without the exception data.
        no_exc_record = copy(record)
        no_exc_record.exc_info = None
        no_exc_record.exc_text = None

        if record.exc_info:
            exc_info = record.exc_info
        else:
            exc_info = (None, record.getMessage(), None)

        reporter = TrimmedExceptionReporter(request, is_email=True, *exc_info)

        msg = (
            f'{record.levelname}, {record.getMessage()}\n'
            f'{self.format(no_exc_record)}\n\n{reporter.get_traceback_text()}'
        )

        # Telegram 限制单条消息的长度, 有必要进行切片发送
        MAX_LENGTH = 4000
        for s in [msg[i : i + MAX_LENGTH] for i in range(0, len(msg), MAX_LENGTH)]:
            self.bot.send_message(settings.TELEGRAM_CHAT_ID, s)
