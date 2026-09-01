from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from .models import GuestbookEntry


class SubmissionConflict(APIException):
    status_code = 409
    default_detail = '这次提交已经发布，请刷新后再发布新内容。'


def previous_submission(author, data, parent=None):
    submission_id = data.get('submission_id')
    if not submission_id:
        return None
    entry = GuestbookEntry.all_objects.filter(author=author, submission_id=submission_id).first()
    if entry and (
        entry.parent_id != (parent.id if parent else None)
        or entry.content != data['content']
        or entry.anonymous != data.get('anonymous', False)
    ):
        raise SubmissionConflict()
    return entry


def create_submission(author, data, parent=None):
    entry = previous_submission(author, data, parent)
    if entry:
        return entry, False
    try:
        # The savepoint lets a concurrent duplicate resolve to the committed entry.
        with transaction.atomic():
            entry = GuestbookEntry.objects.create(
                author=author, parent=parent, root_id=(parent.root_id or parent.id) if parent else None, **data,
            )
        return entry, True
    except IntegrityError:
        entry = previous_submission(author, data, parent)
        if entry is None:
            raise
        return entry, False
