import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from common.file.models import UploadedFile


class Command(BaseCommand):
    help = 'Create default avatar'

    def handle(self, *args, **options):
        file_dir = Path(settings.MEDIA_ROOT) / 'default_file'
        file_name = settings.DEFAULT_USER_AVATAR_FILE_NAME
        file_path = file_dir / file_name

        if not file_path.exists():
            self.stdout.write(self.style.ERROR('Default avatar file does not exist'))
            return
        is_file_exist = UploadedFile.objects.filter(id=settings.DEFAULT_USER_AVATAR_UUID).exists()
        if is_file_exist:
            confirm = input(
                f'File with uuid={settings.DEFAULT_USER_AVATAR_UUID} already exists, are you sure you want to overwrite it? (Y/n): ')
            if confirm.lower() == 'n':
                self.stdout.write(self.style.WARNING('Operation cancelled.'))
                return

        with open(file_path, 'rb') as file:
            if is_file_exist:
                UploadedFile.objects.get(id=settings.DEFAULT_USER_AVATAR_UUID).delete()
            new_file = UploadedFile(
                id=settings.DEFAULT_USER_AVATAR_UUID,
                file=os.path.basename(file_path),
            )
            new_file.file.save(os.path.basename(file_path), file, save=True)
            self.stdout.write(self.style.SUCCESS(
                f'Successfully created default avatar with uuid={settings.DEFAULT_USER_AVATAR_UUID}'))
