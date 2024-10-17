from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from common.utils import return_response, get_err_msg
from user.models import User
from .models import Bulletin, About, Chat, ChatMessage, ChatLike, ChatReply
from .serializers import CaptchaSerializer, ChatMessageSerializer
from .throttle import CaptchaAnonRateThrottle, CaptchaUserRateThrottle


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


class MessageBoxView(APIView):
    permission_classes = [IsAuthenticated]

    def get_user_message_list(self, request, classify):
        chats = Chat.objects.filter((Q(receiver=request.user) | Q(sender=request.user)) & Q(classify=classify)) \
            .select_related('sender', 'receiver') \
            .order_by('-last_message_datetime')
        paginator = Paginator(chats, 10)
        page = request.query_params.get('page', 1)
        try:
            chats_page = paginator.page(page)
        except PageNotAnInteger:
            chats_page = paginator.page(1)
        except EmptyPage:
            chats_page = paginator.page(paginator.num_pages)
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
        chat_dict = {
            'chats': chat_list,
            'current_page': chats_page.number,
            'has_next': chats_page.has_next(),
        }
        return return_response(contents=chat_dict)

    def get_particular_user_message(self, request, chatter_id):
        chat_message = ChatMessage.objects.filter(chat_item_id=chatter_id).order_by('-create_time')
        paginator = Paginator(chat_message, 10)
        page = request.query_params.get('page', 1)
        try:
            message_page = paginator.page(page)
        except PageNotAnInteger:
            message_page = paginator.page(1)
        except EmptyPage:
            message_page = paginator.page(paginator.num_pages)
        message_list = []
        for message in message_page:
            message_list.append({
                'id': message.id,
                'content': message.content,
                'datetime': message.create_time,
            })
        message_dict = {
            'chats': message_list,
            'current_page': message_page.number,
            'has_next': message_page.has_next(),
        }
        return return_response(contents=message_dict)

    def get_like_notice(self, request):
        like_notices = ChatLike.objects.filter(receiver=request.user).select_related('raw_post_course')
        paginator = Paginator(like_notices, 10)
        page = request.query_params.get('page', 1)
        try:
            notice_page = paginator.page(page)
        except PageNotAnInteger:
            notice_page = paginator.page(1)
        except EmptyPage:
            notice_page = paginator.page(paginator.num_pages)
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
        notice_dict = {
            'notices': notice_list,
            'current_page': notice_page.number,
            'has_next': notice_page.has_next(),
        }
        return return_response(contents=notice_dict)

    def get_reply_notice(self, request):
        reply_notices = ChatReply.objects.filter(receiver=request.user).select_related('reply_content',
                                                                                       'raw_post_course',
                                                                                       'reply_content__created_by')
        paginator = Paginator(reply_notices, 10)
        page = request.query_params.get('page', 1)
        try:
            notice_page = paginator.page(page)
        except PageNotAnInteger:
            notice_page = paginator.page(1)
        except EmptyPage:
            notice_page = paginator.page(paginator.num_pages)
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
        notice_dict = {
            'notices': notice_list,
            'current_page': notice_page.number,
            'has_next': notice_page.has_next(),
        }
        return return_response(contents=notice_dict)

    def get(self, request, classify, chatter_id=None):
        if classify not in [message[0] for message in Chat.classify_MESSAGE]:
            return return_response(errors={'classify': get_err_msg('invalid_classify')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        if chatter_id is None:
            if classify == 'user':
                return self.get_user_message_list(request, classify)
            elif classify == 'like':
                return self.get_like_notice(request)
            elif classify == 'reply':
                return self.get_reply_notice(request)

        else:
            chat = Chat.objects.get(id=chatter_id)
            chat.unread_count = 0
            chat.save()
            return self.get_particular_user_message(request, chatter_id)

    def post(self, request):
        serializer = ChatMessageSerializer(data=request.data)
        if serializer.is_valid():
            try:
                receiver = User.objects.get(id=serializer.validated_data['receiver'])
            except User.DoesNotExist:
                return return_response(errors={'user': get_err_msg('user_not_exist')},
                                       status_code=status.HTTP_400_BAD_REQUEST)
            chat, created = Chat.get_or_create_chat(sender=request.user, receiver=receiver,
                                                    classify=serializer.validated_data['classify'])
            chat_message = ChatMessage.objects.create(
                content=serializer.validated_data['content'],
                chat_item=chat,
            )
            return return_response(contents=serializer.validated_data, status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
