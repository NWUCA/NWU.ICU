from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from common.file.resource_directories import (
    ResourceDirectoryCacheError,
    fetch_all_resource_directory_paths,
    resource_directory_cache_lock,
    write_resource_directory_cache,
)


class Command(BaseCommand):
    help = '使用 DFS 同步资料站的全部目录路径到本地 JSON 缓存'

    def handle(self, *args, **options):
        source = settings.RESOURCES_WEBSITE_URL.rstrip('/')
        self.stdout.write(f'正在从 {source} 同步资料目录……')
        try:
            paths = fetch_all_resource_directory_paths(source)
            with resource_directory_cache_lock():
                payload = write_resource_directory_cache(paths, source=source)
        except (ResourceDirectoryCacheError, ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f'已缓存 {len(payload["paths"])} 个目录：{settings.RESOURCE_DIRECTORY_CACHE_FILE}'
            )
        )
