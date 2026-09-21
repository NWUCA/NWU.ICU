from functools import partial

from django.core.management.base import BaseCommand
from django.db import transaction

from common.file.file_dedup import delete_storage_file_if_unreferenced
from common.file.models import UploadedFile
from common.file.references import collect_file_reference_counts, file_lifecycle


class Command(BaseCommand):
    help = 'Clean uploaded files with no remaining content references'

    def add_arguments(self, parser):
        parser.add_argument('-y', '--yes', action='store_true', help='Automatically confirm cleanup')

    @staticmethod
    def format_size(size):
        units = ['byte', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        return f'{size:,.2f} {units[unit_index]}'

    @staticmethod
    def reclaimable_size(files, counts):
        kept_names = {file.file.name for file in files if counts[file.pk]}
        kept_hashes = {file.file_hash for file in files if counts[file.pk] and file.file_hash}
        sizes = {}
        for file in files:
            if (not counts[file.pk] and file.file.name not in kept_names
                    and (not file.file_hash or file.file_hash not in kept_hashes)):
                sizes[file.file.name] = max(sizes.get(file.file.name, 0), file.file_size or 0)
        return sum(sizes.values())

    def handle(self, *args, **options):
        # Confirmation is deliberately outside the write transaction. Cancellation
        # must neither rewrite counters nor hold a lock while waiting for input.
        counts = collect_file_reference_counts()
        files = list(UploadedFile.objects.all())
        self.stdout.write(f'unused file sum size is {self.format_size(self.reclaimable_size(files, counts))}')
        if not options['yes']:
            self.stdout.write('Are you sure you want to delete the unused file? (y/N): ', ending='')
            if input().lower() != 'y':
                self.stdout.write(self.style.WARNING('Operation cancelled.'))
                return

        with file_lifecycle():
            # A reference may have been saved after the preview, so rebuild under
            # the same lock used by attachment and content writers.
            counts = collect_file_reference_counts()
            files = list(UploadedFile.objects.select_for_update().order_by('pk'))
            changed = []
            unused_ids = []
            storage_files = {}
            for file in files:
                count = counts[file.pk]
                if file.ref_count != count:
                    file.ref_count = count
                    changed.append(file)
                if count == 0:
                    unused_ids.append(file.pk)
                    previous_hash = storage_files.get(file.file.name, (None, None))[0]
                    storage_files[file.file.name] = (file.file_hash or previous_hash, file.file.storage)
            if changed:
                # A counter change must not invoke the file-processing pre_save signal.
                UploadedFile.objects.bulk_update(changed, ['ref_count'])
            UploadedFile.objects.filter(pk__in=unused_ids).delete()
            for file_name, (file_hash, storage) in storage_files.items():
                transaction.on_commit(partial(
                    delete_storage_file_if_unreferenced, file_hash, file_name, storage,
                ))
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {len(unused_ids)} unused file records'))
