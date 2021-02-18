from common.models import Announcement


def announcements(request):
    return {'announcements': Announcement.objects.filter(enabled=True)}
