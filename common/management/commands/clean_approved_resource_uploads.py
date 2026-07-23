from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from common.file.models import ResourceUploadRequest


class Command(BaseCommand):
    help = 'Delete files from approved resource upload requests after 30 days'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        upload_requests = ResourceUploadRequest.objects.filter(
            status=ResourceUploadRequest.STATUS_APPROVED,
            reviewed_at__lte=cutoff,
            files_deleted_at__isnull=True,
        ).prefetch_related('files')
        deleted_requests = 0
        deleted_files = 0
        for upload_request in upload_requests.iterator():
            all_deleted = True
            for upload_file in upload_request.files.all():
                try:
                    if upload_file.file:
                        upload_file.file.delete(save=False)
                        upload_file.file = None
                        upload_file.save(update_fields=('file',))
                        deleted_files += 1
                except Exception as error:
                    all_deleted = False
                    self.stderr.write(
                        self.style.ERROR(f'Failed to delete upload file {upload_file.pk}: {error}')
                    )
            if all_deleted:
                upload_request.files_deleted_at = timezone.now()
                upload_request.save(update_fields=('files_deleted_at',))
                deleted_requests += 1
        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted {deleted_files} files from {deleted_requests} approved resource upload requests'
            )
        )
