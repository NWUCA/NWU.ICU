import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from common.file.models import UploadedFile


class Command(BaseCommand):
    help = 'Create init avatar'

    def get_file_size(self, file_path):
        try:
            with open(file_path, 'rb') as file:
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                return file_size
        except OSError as e:
            print(f"Error: {e}")
            return None

    def handle(self, *args, **options):
        file_dir = Path(settings.MEDIA_ROOT) / 'default_file'
        file_name_dict = {settings.DEFAULT_USER_AVATAR_FILE_NAME: settings.DEFAULT_USER_AVATAR_UUID,
                          settings.ANONYMOUS_USER_AVATAR_FILE_NAME: settings.ANONYMOUS_USER_AVATAR_UUID}

        for file_name, uuid in file_name_dict.items():
            file_path = file_dir / file_name

            if not file_path.exists():
                self.stdout.write(self.style.ERROR(f'File {file_name} does not exist'))
                return
            is_file_exist = UploadedFile.objects.filter(id=uuid).exists()
            if is_file_exist:
                confirm = input(
                    f'File {file_name} with uuid={settings.DEFAULT_USER_AVATAR_UUID} already exists, are you '
                    f'sure you want to overwrite it? (Y/n): ')
                if confirm.lower() == 'n':
                    self.stdout.write(self.style.WARNING('Operation cancelled.'))
                    return

            with open(file_path, 'rb') as file:
                if is_file_exist:
                    UploadedFile.objects.get(id=uuid).delete()
                new_file = UploadedFile(
                    id=uuid,
                    file=os.path.basename(file_path),
                    file_size=self.get_file_size(file_path),
                    file_type='avatar',
                    file_name=file_name,
                    created_by=None
                )
                new_file.file.save(os.path.basename(file_path), file, save=True)
                self.stdout.write(self.style.SUCCESS(
                    f'Successfully created {file_name} with uuid={uuid}'))
