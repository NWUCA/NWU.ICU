import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from common.file.resource_archives import config, maintenance


class Command(BaseCommand):
    help = 'Clean idle/LRU ZIP artifacts and deliver aggregated Telegram notices'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            maintenance()
            if not options['watch']:
                return
            time.sleep(max(1, config()['cleanup_interval']))
