from django.db import migrations, models
from django.db.models import Q


def merge_duplicate_system_chats(apps, schema_editor):
    Chat = apps.get_model('common', 'Chat')
    ChatLike = apps.get_model('common', 'ChatLike')
    ChatMessage = apps.get_model('common', 'ChatMessage')
    ChatReply = apps.get_model('common', 'ChatReply')

    groups = (
        Chat.objects.filter(sender_id__isnull=True)
        .values('receiver_id', 'classify')
        .annotate(total=models.Count('id'))
        .filter(total__gt=1)
    )
    for group in groups.iterator():
        chats = list(
            Chat.objects.filter(
                sender_id__isnull=True,
                receiver_id=group['receiver_id'],
                classify=group['classify'],
            ).order_by('id')
        )
        primary, duplicates = chats[0], chats[1:]
        duplicate_ids = [chat.id for chat in duplicates]
        ChatMessage.objects.filter(chat_item_id__in=duplicate_ids).update(chat_item_id=primary.id)
        ChatLike.objects.filter(chat_item_id__in=duplicate_ids).update(chat_item_id=primary.id)
        ChatReply.objects.filter(chat_item_id__in=duplicate_ids).update(chat_item_id=primary.id)
        if primary.classify == 'reply':
            primary.receiver_unread_count = ChatReply.objects.filter(
                chat_item_id=primary.id,
                receiver_id=primary.receiver_id,
                read=False,
            ).count()
        elif primary.classify == 'like':
            primary.receiver_unread_count = ChatLike.objects.filter(
                chat_item_id=primary.id,
                receiver_id=primary.receiver_id,
                read=False,
            ).count()
        else:
            primary.receiver_unread_count = max(chat.receiver_unread_count for chat in chats)
        primary.sender_unread_count = 0
        latest = max(
            (chat for chat in chats if chat.last_message_datetime is not None),
            key=lambda chat: chat.last_message_datetime,
            default=None,
        )
        if latest is not None:
            primary.last_message_id = latest.last_message_id
            primary.last_message_content = latest.last_message_content
            primary.last_message_datetime = latest.last_message_datetime
        primary.save()
        Chat.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):

    # PostgreSQL cannot create the partial unique index while foreign-key
    # updates from the data migration still have pending trigger events.
    atomic = False

    dependencies = [
        ('common', '0035_resourceuploadrequest_creates_new_folder'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_system_chats, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='chat',
            constraint=models.UniqueConstraint(
                condition=Q(sender__isnull=True),
                fields=('receiver', 'classify'),
                name='unique_system_chat_receiver_classify',
            ),
        ),
    ]
