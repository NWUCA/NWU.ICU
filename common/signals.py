from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

from common.models import ChatMessage, ChatLike

soft_delete_signal = Signal()


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


@receiver(post_save, sender='common.ChatLike')
def chat_like_handler(sender, instance, **kwargs):
    chat_item = instance.chat_item
    if chat_item is None:
        return
    chat_item.receiver_unread_count = ChatLike.objects.filter(receiver=chat_item.sender, read=False).count()
    chat_item.save()
