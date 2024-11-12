from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.db.models import Q
from django.shortcuts import render
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from user.models import User
from utils.custom_pagination import StandardResultsSetPagination
from utils.throttle import CaptchaAnonRateThrottle, CaptchaUserRateThrottle
from utils.utils import return_response, get_err_msg
from .models import Bulletin, About, Chat, ChatMessage, ChatLike, ChatReply
from .serializers import CaptchaSerializer, ChatMessageSerializer, ChatMessageGetSerializer


class CaptchaView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [CaptchaAnonRateThrottle, CaptchaUserRateThrottle]

    def get(self, request):
        new_key = CaptchaStore.generate_key()
        image_url = captcha_image_url(new_key)
        return return_response(contents={"key": new_key, "image_url": image_url})

    def post(self, request):
        serializer = CaptchaSerializer(data=request.data)
        if serializer.is_valid():
            return return_response(message="Captcha validated successfully!")
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class BulletinListView(APIView):
    def get(self, request):
        bulletins = Bulletin.objects.filter(enabled=True).order_by('-update_time')

        bulletin_list = []
        for bulletin in bulletins:
            bulletin_list.append({
                "title": bulletin.title,
                "content": bulletin.content,
                "publisher": {"nickname": bulletin.publisher.nickname, 'id': bulletin.publisher.id,
                              'avatar': bulletin.publisher.avatar_uuid},
                "create_time": bulletin.create_time,
                "update_time": bulletin.update_time,
            })
        return return_response(contents={"bulletin_list": bulletin_list})


def index(request):
    return render(request, 'index.html')


class TosView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tos_content_database = About.objects.order_by('-update_time').get(type="tos")
        except About.DoesNotExist:
            return return_response(contents={"tos": ""})
        return return_response(contents={"tos": tos_content_database.content})


class AboutView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tos_content_database = About.objects.order_by('-update_time').get(type="about")
        except About.DoesNotExist:
            return return_response(contents={"about": ""})
        return return_response(contents={"about": tos_content_database.content})


class MessageBoxView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_user_message_list(self, request, classify):
        chats = Chat.objects.filter((Q(receiver=request.user) | Q(sender=request.user)) & Q(classify=classify)) \
            .select_related('sender', 'receiver') \
            .order_by('-last_message_datetime')
        chats_page = self.paginate_queryset(chats)
        chat_list = []
        for chat in chats_page:
            chatter = chat.sender if chat.receiver == request.user else chat.receiver
            temp_dict = {
                'id': chat.id,
                'chatter': {'id': chatter.id, 'nickname': chatter.nickname, 'avatar': chatter.avatar_uuid},
                'last_message': {'content': chat.last_message_content, 'datetime': chat.last_message_datetime},
                'unread_count': chat.unread_count,
            }
            chat_list.append(temp_dict)
        return self.get_paginated_response(chat_list)

    def get_particular_user_message(self, request, chat_object: Chat):
        chat_message = ChatMessage.objects.filter(chat_item=chat_object).order_by('-create_time')
        message_page = self.paginate_queryset(chat_message)
        message_list = []
        for message in message_page:
            if message.created_by != request.user:
                message.read = True
                message.save()
            message_list.append({
                'id': message.id,
                'content': message.content,
                'datetime': message.create_time,
            })
        return self.get_paginated_response(message_list)

    def get_like_notice(self, request):
        like_notices = ChatLike.objects.filter(receiver=request.user).select_related('raw_post_course')
        notice_page = self.paginate_queryset(like_notices)
        notice_list = []
        for notice in notice_page:
            notice_list.append({
                'id': notice.id,
                'raw_info': {
                    'raw_post': {'classify': notice.raw_post_classify,
                                 'id': notice.raw_post_id,
                                 'content': notice.raw_post_content, },
                    'course': {'id': notice.raw_post_course_id,
                               'name': notice.raw_post_course.name},
                },
                'like': {
                    'like': notice.like_count,
                    'dislike': notice.dislike_count,
                },
                'datetime': notice.latest_like_datetime,
            })
            notice.read = True
            notice.save()
        return self.get_paginated_response(notice_list)

    def get_reply_notice(self, request):
        reply_notices = ChatReply.objects.filter(receiver=request.user).select_related('reply_content',
                                                                                       'raw_post_course',
                                                                                       'reply_content__created_by')
        notice_page = self.paginate_queryset(reply_notices)
        notice_list = []
        for notice in notice_page:
            if notice.reply_content.created_by != request.user:
                notice_list.append({
                    'id': notice.id,
                    'reply': {
                        'id': notice.reply_content.id,
                        'content': notice.reply_content.content,
                    },
                    'created_by': {
                        'id': notice.reply_content.created_by.id,
                        'nickname': notice.reply_content.created_by.nickname,
                        'avatar': notice.reply_content.created_by.avatar_uuid,
                    },
                    'course': {
                        'id': notice.raw_post_course_id,
                        'name': notice.raw_post_course.name
                    },
                    'raw_post': {
                        'id': notice.raw_post_id,
                        'classify': notice.raw_post_classify,
                        'content': notice.raw_post_content,
                    },
                    'datetime': notice.reply_content.create_time,
                })
        return self.get_paginated_response(notice_list)

    def get(self, request, classify, chatter_id=None):
        serializer = ChatMessageGetSerializer(data={'classify': classify})
        if serializer.is_valid():
            if chatter_id is None:
                if classify == 'user':
                    return self.get_user_message_list(request, classify)
                elif classify == 'like':
                    return self.get_like_notice(request)
                elif classify == 'reply':
                    return self.get_reply_notice(request)

            else:
                try:
                    chat = Chat.get_chat_object(sender=request.user, receiver=User.objects.get(id=chatter_id))
                except Chat.DoesNotExist:
                    return return_response(errors={'chat': get_err_msg('chat_not_exist')},
                                           status_code=status.HTTP_400_BAD_REQUEST)
                return self.get_particular_user_message(request, chat)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def post(self, request):
        serializer = ChatMessageSerializer(data=request.data)
        if serializer.is_valid():
            try:
                receiver = User.objects.get(id=serializer.validated_data['receiver'])
            except User.DoesNotExist:
                return return_response(errors={'user': get_err_msg('user_not_exist')},
                                       status_code=status.HTTP_400_BAD_REQUEST)
            if receiver == request.user:
                return return_response(errors={'user': get_err_msg('cannot_send_message_to_self')},
                                       status_code=status.HTTP_400_BAD_REQUEST)
            chat, created = Chat.get_or_create_chat(sender=request.user, receiver=receiver,
                                                    classify=serializer.validated_data['classify'])
            ChatMessage.objects.create(
                content=serializer.validated_data['content'],
                chat_item=chat,
                created_by=request.user,
            )
            return return_response(contents=serializer.validated_data, status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class MessageUnreadView(APIView):

    def get(self, request):
        unread_counts = {}
        for i in Chat.classify_MESSAGE:
            unread_counts[i[0]] = 0
        for chat in Chat.objects.filter(sender=request.user):
            unread_counts[chat.classify] += chat.sender_unread_count
        for chat in Chat.objects.filter(receiver=request.user):
            unread_counts[chat.classify] += chat.receiver_unread_count
        return return_response(contents={'unread': unread_counts, 'total': sum(unread_counts.values())})
