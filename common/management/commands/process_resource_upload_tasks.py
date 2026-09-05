import time

from django.core.management.base import BaseCommand

from common.file.resource_tasks import process_one_notification, process_one_publish_job


class Command(BaseCommand):
    help = 'Process database-backed resource publishing and notification tasks'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process available tasks once and exit')
        parser.add_argument('--poll-seconds', type=float, default=5)

    def handle(self, *args, **options):
        while True:
            did_work = False
            while process_one_publish_job():
                did_work = True
            while process_one_notification():
                did_work = True
            if options['once']:
                return
            if not did_work:
                time.sleep(max(options['poll_seconds'], 1))
