import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from common.file.resource_archives import process_one


class Command(BaseCommand):
    help = 'Process shared resource ZIP jobs independently of uploads'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            did_work = process_one()
            if options['once']:
                return
            if not did_work:
                time.sleep(1)
