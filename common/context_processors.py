import subprocess

from common.models import Announcement


def announcements(request):
    return {'announcements': Announcement.objects.filter(enabled=True)}


def version(request):
    res = subprocess.run(["git", "describe", "--tag"], capture_output=True)
    return {'version': res.stdout.decode().strip()}
