import logging
from copy import copy

import requests
import telebot
from django.conf import settings
from django.views.debug import ExceptionReporter


class TelegramBotHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.bot = telebot.TeleBot(settings.TELEGRAM_BOT_API_TOKEN)
        telebot.apihelper.RETRY_ON_ERROR = True

    def _get_msg(self, record):
        return self.format(record)

    def emit(self, record):
        msg = self._get_msg(record)

        # Telegram 限制单条消息的长度, 有必要进行切片发送
        MAX_LENGTH = 4000
        for s in [msg[i : i + MAX_LENGTH] for i in range(0, len(msg), MAX_LENGTH)]:
            self.bot.send_message(settings.TELEGRAM_CHAT_ID, s)


class TelegramBotHandlerWithContext(TelegramBotHandler):
    """
    把 request 的上下文包含到 log 中
    """

    def _get_msg(self, record):
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

        reporter = ExceptionReporter(request, is_email=True, *exc_info)

        msg = (
            f'{record.levelname}, {record.getMessage()}\n'
            f'{self.format(no_exc_record)}\n\n{reporter.get_traceback_text()}'
        )

        return msg

    def emit(self, record):
        msg = self._get_msg(record)

        r = requests.post('https://paste.coherence.space/api/', data={'content': msg})

        self.bot.send_message(settings.TELEGRAM_CHAT_ID, r.text.strip())
