from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

soft_delete_signal = Signal()


@receiver(post_save, sender='common.ChatMessage')
def chat_message_handler(sender, instance, **kwargs):
    chat_item = instance.chat_item
    chat_item.last_message_content = instance.content
    chat_item.last_message_datetime = instance.create_time
    chat_item.unread_count += 1
    chat_item.save()
