from collections import OrderedDict

from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.db.models import Q
from django.shortcuts import render
from requests.packages import target
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user.models import User
from .models import Bulletin, About, Message
from .serializers import AboutSerializer, CaptchaSerializer, MessageSerializer
from .serializers import BulletinSerializer


class CaptchaView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        new_key = CaptchaStore.generate_key()
        image_url = captcha_image_url(new_key)
        return Response({"key": new_key, "image_url": image_url})

    def post(self, request):
        serializer = CaptchaSerializer(data=request.data)
        if serializer.is_valid():
            return Response({"message": "Captcha validated successfully!"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BulletinListView(APIView):
    def get(self, request):
        bulletins = Bulletin.objects.filter(enabled=True).order_by('-update_time')
        serializer = BulletinSerializer(bulletins, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


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
        return Response({"detail": tos_content, },
                        status=status.HTTP_200_OK)


class AboutView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        about_content_database = About.objects.order_by('-update_time')
        try:
            about_content = AboutSerializer(about_content_database, many=True).data[0]
        except IndexError:
            about_content = "Get about content failed"
        return Response({"detail": about_content, },
                        status=status.HTTP_200_OK)


class MessageBoxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, sender_id=None):
        if sender_id is not None:
            messages = Message.objects.filter((Q(sender_id=sender_id) & Q(receiver=request.user)) |
                                              (Q(sender=request.user) & Q(receiver_id=sender_id))).select_related(
                'sender', 'receiver').order_by(
                '-create_time')
            message_dict = []
            for message in messages:
                message_dict.append({"time": message.create_time, "content": message.content})
                message.read = True
                message.save()
            return Response(message_dict, status=status.HTTP_200_OK)

        else:
            message_box_list = (
                Message.objects.filter(Q(receiver=request.user) | Q(sender=request.user)).select_related('sender',
                                                                                                         'receiver')
                .order_by('-create_time'))
            message_dict = {}
            for target_item in message_box_list:
                target_user_id = target_item.sender.id if target_item.sender != request.user else target_item.receiver.id
                if target_user_id in message_dict:
                    if message_dict[target_user_id]['time'] < target_item.create_time:
                        message_dict[target_user_id]['time'] = target_item.create_time
                        message_dict[target_user_id]['content'] = target_item.content
                    message_dict[target_user_id]['unread'] += 0 if target_item.read else 1
                else:
                    message_dict[target_user_id] = {
                        'content': target_item.content,
                        'time': target_item.create_time,
                        'sender': {'id': target_item.sender.id, 'nickname': target_item.sender.nickname},
                        'receiver': {'id': target_item.receiver.id, 'nickname': target_item.receiver.nickname},
                        'unread': 0 if target_item.read else 1
                    }
            sorted_message_dict = OrderedDict(
                sorted(message_dict.items(), key=lambda item: item[1]['time'], reverse=True)
            )

            return Response(sorted_message_dict, status=status.HTTP_200_OK)


def post(self, request):
    serializer = MessageSerializer(data=request.data)
    if serializer.is_valid():
        try:
            receiver = User.objects.get(id=serializer.validated_data['receiver'])
        except User.DoesNotExist:
            return Response({'error': '目标用户不存在'}, status=status.HTTP_400_BAD_REQUEST)

        message = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            content=serializer.validated_data['content'],
            type='user'
        )

        return Response(serializer.validated_data, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
