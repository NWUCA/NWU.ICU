from django.db import transaction
from django.utils import timezone

from .models import GuestbookReport
from .notifications import notify_guestbook_report


class ReportModerationError(Exception):
    pass


@transaction.atomic
def resolve_guestbook_report(*, report_id, moderator, decision, note):
    note = note.strip()
    if not note:
        raise ReportModerationError('处理说明不能为空')
    report = (
        GuestbookReport.objects.select_for_update()
        .select_related('entry', 'reporter')
        .filter(pk=report_id)
        .first()
    )
    if report is None:
        raise ReportModerationError('举报不存在')
    if report.status != GuestbookReport.STATUS_PENDING:
        raise ReportModerationError('举报已经被处理')

    now = timezone.now()
    if decision == 'dismiss':
        reports = [report]
        status = GuestbookReport.STATUS_DISMISSED
    elif decision == 'remove':
        reports = list(
            GuestbookReport.objects.select_for_update()
            .select_related('entry', 'reporter')
            .filter(entry_id=report.entry_id, status=GuestbookReport.STATUS_PENDING)
            .order_by('pk')
        )
        status = GuestbookReport.STATUS_REMOVED
        if not report.entry.is_deleted:
            report.entry.soft_delete()
    else:
        raise ReportModerationError('未知的处理操作')

    for item in reports:
        item.status = status
        item.handled_by = moderator
        item.handled_at = now
        item.handling_note = note
        item.save(update_fields=('status', 'handled_by', 'handled_at', 'handling_note'))
        notify_guestbook_report(item)
    return reports

