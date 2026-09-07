from django.db import transaction
from django.db.models import F

from common.file.models import UploadedFile
from .models import GuestbookEntry
from .serializers import announcement_image_ids
from .submissions import create_submission


def publish_announcement(*, author, data):
    with transaction.atomic():
        entry, created = create_submission(
            author,
            {**data, 'anonymous': False},
            board=GuestbookEntry.BOARD_ANNOUNCEMENT,
        )
        if created:
            UploadedFile.objects.filter(id__in=announcement_image_ids(entry.content)).update(
                ref_count=F('ref_count') + 1,
            )
        return entry, created
