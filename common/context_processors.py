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
