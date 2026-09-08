from django.db import connection, transaction
from django.db.models import Q

from .models import UploadedFile


def lock_file_hash(file_hash):
    """Serialize deduplication and last-reference cleanup for one content hash."""
    if (
        not file_hash
        or connection.vendor != 'postgresql'
        or not connection.in_atomic_block
    ):
        return
    lock_key = int(file_hash[:16], 16)
    if lock_key >= 2 ** 63:
        lock_key -= 2 ** 64
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_key])


def delete_storage_file_if_unreferenced(file_hash, file_name, storage):
    if not file_name:
        return
    with transaction.atomic():
        lock_file_hash(file_hash)
        reference_filter = Q(file=file_name)
        if file_hash:
            reference_filter |= Q(file_hash=file_hash)
        references = UploadedFile.objects.select_for_update().filter(reference_filter)
        if references.exists():
            return
        storage.delete(file_name)
