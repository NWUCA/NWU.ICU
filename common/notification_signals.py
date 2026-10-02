from django.db.models.signals import post_delete
from django.dispatch import receiver

from guestbook.models import GuestbookEntry

from .models import Bulletin, Notification


@receiver(post_delete, sender=Bulletin)
def remove_bulletin_notifications(sender, instance, **kwargs):
    Notification.objects.filter(
        kind=Notification.KIND_SYSTEM,
        payload__source='bulletin', payload__bulletin__id=instance.pk,
    ).delete()


@receiver(post_delete, sender=GuestbookEntry)
def remove_deleted_announcement_notifications(sender, instance, **kwargs):
    if instance.board == GuestbookEntry.BOARD_ANNOUNCEMENT and instance.is_root:
        from guestbook.notifications import remove_announcement_notifications

        remove_announcement_notifications(instance.pk)
