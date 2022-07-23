import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db.models.functions import Length

from report.models import Report

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '清理无效的填报信息'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='禁用所有填报')
        parser.add_argument('-d', '--dry-run', action='store_true', help='dry run')

    def handle(self, *args, **options):
        if options['all']:
            reports = Report.objects.filter(status=True)
        else:
            reports = Report.objects.annotate(l=Length('user__username')).filter(
                Q(user__username__startswith='2017')
                | Q(user__username__startswith='2016')
                | Q(user__username__startswith='2018'),
                Q(l=10) | Q(l=9),
                status=True,
            )
        for report in reports:
            logger.info(f"正在删除 {report.user.username}-{report.user.name} 的填报")
            if not options['dry_run']:
                report.delete()
        logger.info("正在删除所有已关闭的填报")
        if not options['dry_run']:
            Report.objects.filter(status=False).delete()
