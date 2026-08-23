from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal, receiver

from common.models import Chat, ChatMessage, ChatLike, ChatReply

soft_delete_signal = Signal()


def update_notice_unread_count(instance, notice_model):
    chat_item = Chat.objects.filter(pk=instance.chat_item_id).first()
    if chat_item is None:
        return
    unread_count = notice_model.objects.filter(
        chat_item=chat_item,
        receiver_id=instance.receiver_id,
        read=False,
    ).count()
    if chat_item.sender_id == instance.receiver_id:
        chat_item.sender_unread_count = unread_count
        chat_item.save(update_fields=('sender_unread_count',))
    elif chat_item.receiver_id == instance.receiver_id:
        chat_item.receiver_unread_count = unread_count
        chat_item.save(update_fields=('receiver_unread_count',))


@receiver(post_save, sender='common.ChatMessage')
def chat_message_handler(sender, instance, **kwargs):
    chat_item = instance.chat_item
    chat_item.last_message_content = instance.content
    chat_item.last_message_datetime = instance.create_time
    chat_item.last_message_id = instance.id
    if chat_item.sender == instance.created_by:
        chat_item.receiver_unread_count = ChatMessage.objects.filter(chat_item=chat_item, read=False,
                                                                     created_by=chat_item.sender).count()
    else:
        chat_item.sender_unread_count = ChatMessage.objects.filter(chat_item=chat_item, read=False,
                                                                   created_by=chat_item.receiver).count()
        # 不知道会不会有严重的性能问题
    chat_item.save()


@receiver([post_save, post_delete], sender='common.ChatLike')
def chat_like_handler(sender, instance, **kwargs):
    update_notice_unread_count(instance, ChatLike)


@receiver([post_save, post_delete], sender='common.ChatReply')
def chat_reply_handler(sender, instance, **kwargs):
    update_notice_unread_count(instance, ChatReply)
