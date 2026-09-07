import posixpath

from .models import ResourceUploadDirectoryBlacklist
from .resource_directories import normalize_directory_path


def get_resource_upload_blacklist():
    return list(ResourceUploadDirectoryBlacklist.objects.values_list('path', flat=True))


def is_resource_upload_path_blocked(path, blacklist):
    path = '/' + normalize_directory_path(path).lstrip('/')
    return any(path == blocked or path.startswith(blocked + '/') for blocked in blacklist)


def resource_upload_blacklist_errors(target_path, relative_paths):
    blacklist = get_resource_upload_blacklist()
    # Include each final file path so folder uploads cannot bypass a blocked child.
    paths = [target_path, *(posixpath.join(target_path, path) for path in relative_paths)]
    if any(is_resource_upload_path_blocked(path, blacklist) for path in paths):
        return {'target_path': {
            'err_code': 'resource_upload_directory_blocked',
            'err_msg': '所选目录不允许投稿，请选择其他文件夹',
        }}
    return {}
