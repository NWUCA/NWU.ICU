import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db.models.functions import Length

from report.models import Report

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '清理无效的填报信息'

    def handle(self, *args, **options):
        invalid_reports = Report.objects.annotate(l=Length('user__username')).filter(
            Q(user__username__startswith='2017') | Q(user__username__startswith='2016'),
            Q(l=10) | Q(l=9),
            status=True,
        )
        for report in invalid_reports:
            logger.info(f"正在关闭 {report.user.username}-{report.user.name} 的填报")
            report.status = False
            report.save()
