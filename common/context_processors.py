import subprocess
from functools import cache

from common.models import Announcement


def announcements(request):
    return {'announcements': Announcement.objects.filter(enabled=True)}


def version(request):
    return {'version': _version()}


@cache
def _version() -> str:
    res = subprocess.run(["git", "describe", "--tag"], capture_output=True)
    return res.stdout.decode().strip()


def login_status_get(request):
    current_path = request.path
    is_not_login_page = current_path != '/login/' and current_path != '/login'
    is_not_authenticated = not request.user.is_authenticated
    login_status = is_not_login_page and is_not_authenticated
    return {'login_status': login_status}
