from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from common.file.resource_directories import (
    ResourceDirectoryCacheError,
    resource_directory_cache_lock,
    write_resource_directory_cache,
)
from scripts.export_resource_tree import build_resource_tree


class Command(BaseCommand):
    help = '扫描本地资料目录并原子更新搜索索引，与管理操作共用写锁'

    def handle(self, *args, **options):
        try:
            with resource_directory_cache_lock():
                payload = build_resource_tree(settings.RESOURCE_STORAGE_ROOT)
                write_resource_directory_cache(
                    payload['paths'], source=payload['source'],
                    entries=payload['entries'], storage_root=payload['storage_root'],
                )
        except (ResourceDirectoryCacheError, ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(
            f'资料索引已更新：{payload["summary"]["directory_count"]} 个目录，'
            f'{payload["summary"]["file_count"]} 个文件。'
        ))
