from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from user.models import User
from .models import Bulletin, About, Chat, ChatMessage
from .serializers import AboutSerializer, CaptchaSerializer, ChatMessageSerializer
from .serializers import BulletinSerializer
from .utils import return_response


class CaptchaView(APIView):
    permission_classes = [AllowAny]

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
        serializer = BulletinSerializer(bulletins, many=True)
        return return_response(contents=serializer.data)


def index(request):
    return render(request, 'index.html')


class TosView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        tos_content_database = About.objects.order_by('-update_time').filter(type="tos")
        try:
            tos_content = AboutSerializer(tos_content_database, many=True).data[0]
        except IndexError:
            tos_content = "Get tos content failed"
        return return_response(contents={"tos": tos_content})


class AboutView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        about_content_database = About.objects.order_by('-update_time')
        try:
            about_content = AboutSerializer(about_content_database, many=True).data[0]
        except IndexError:
            about_content = "Get about content failed"
        return return_response(contents={"tos": about_content})


class MessageBoxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, classify, chatter_id=None):
        if classify not in [message[0] for message in Chat.classify_MESSAGE]:
            return return_response(errors={'classify': "Invalid classify"}, status_code=status.HTTP_400_BAD_REQUEST)
        if chatter_id is None:
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
                chatter = chat.receiver if chat.receiver == request.user else chat.sender
                message = ChatMessage.objects.filter(chat_item=chat).order_by('-create_time').first()
                temp_dict = {
                    'id': chat.id,
                    'chatter': {'id': chatter.id, 'nickname': chatter.nickname, 'avatar': chatter.avatar_uuid},
                    'last_message': {'content': message.content, 'datetime': message.create_time},
                    'unread_count': chat.unread_count,
                }
                chat_list.append(temp_dict)
            chat_dict = {
                'chats': chat_list,
                'current_page': chats_page.number,
                'has_next': chats_page.has_next(),
            }
            return return_response(contents=chat_dict)
        else:
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

    def post(self, request):
        serializer = ChatMessageSerializer(data=request.data)
        if serializer.is_valid():
            try:
                receiver = User.objects.get(id=serializer.validated_data['receiver'])
            except User.DoesNotExist:
                return return_response(errors={'user': '目标用户不存在'}, status_code=status.HTTP_400_BAD_REQUEST)
            chat, created = Chat.get_or_create_chat(sender=request.user, receiver=receiver,
                                                    classify=serializer.validated_data['classify'])
            chat_message = ChatMessage.objects.create(
                content=serializer.validated_data['content'],
                chat_item=chat,
            )
            return return_response(contents=serializer.validated_data, status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
