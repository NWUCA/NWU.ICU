from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from common.file.models import ResourceUploadRequest


class Command(BaseCommand):
    help = 'Delete expired rejected upload blobs while retaining their review records'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        request_ids = ResourceUploadRequest.objects.filter(
            status=ResourceUploadRequest.STATUS_REJECTED,
            reviewed_at__lte=cutoff,
            files_deleted_at__isnull=True,
        ).values_list('pk', flat=True)
        deleted_files = 0
        cleaned_requests = 0
        for request_id in request_ids.iterator():
            with transaction.atomic():
                # Lock and recheck after the initial scan. A concurrent resubmission
                # either completes first (and is skipped) or waits for this cleanup.
                upload_request = (
                    ResourceUploadRequest.objects.select_for_update()
                    .filter(
                        pk=request_id,
                        status=ResourceUploadRequest.STATUS_REJECTED,
                        reviewed_at__lte=cutoff,
                        files_deleted_at__isnull=True,
                    )
                    .first()
                )
                if upload_request is None:
                    continue
                all_deleted = True
                for upload_file in upload_request.files.select_for_update().all():
                    try:
                        if upload_file.file:
                            upload_file.file.delete(save=False)
                            upload_file.file = None
                            upload_file.save(update_fields=('file',))
                            deleted_files += 1
                    except Exception as error:
                        all_deleted = False
                        self.stderr.write(self.style.ERROR(
                            f'Failed to delete upload file {upload_file.pk}: {error}'
                        ))
                if all_deleted:
                    upload_request.files_deleted_at = timezone.now()
                    upload_request.save(update_fields=('files_deleted_at', 'updated_at'))
                    cleaned_requests += 1
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted_files} expired rejected upload files from {cleaned_requests} records'
        ))
