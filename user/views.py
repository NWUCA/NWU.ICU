import base64
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import LoginSerializer, PasswordResetMailRequestSerializer, UsernameDuplicationSerializer, \
    PasswordResetWhenLoginSerializer, BindNwuEmailSerializer, UpdateProfileSerializer
from .serializers import PasswordResetRequestSerializer
from .serializers import RegisterSerializer

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "注册成功!",
                "errors": None
            }, status=status.HTTP_201_CREATED)
        else:
            custom_errors = {"fields": {}}
            for field, errors in serializer.errors.items():
                custom_errors["fields"][field] = [str(error) for error in errors]

            return Response({
                "message": "注册失败",
                "errors": custom_errors
            }, status=status.HTTP_400_BAD_REQUEST)


class UsernameDuplicationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UsernameDuplicationSerializer(data=request.data)
        if serializer.is_valid():
            try:
                User.objects.get(username=serializer.data['username'])
            except User.DoesNotExist:
                return Response({'message': '用户名可用'}, status=status.HTTP_200_OK)
            return Response({'message': '用户名已经存在'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'message': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            email = serializer.validated_data['email']
            try:
                user = User.objects.get(username=username, email=email)
            except User.DoesNotExist:
                return Response({"errors": "使用这个邮箱的用户不存在", "content": None},
                                status=status.HTTP_400_BAD_REQUEST)

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_link = request.build_absolute_uri(f'/user/reset-password/{uid}/{token}/')

            mail_subject = '[NWU.ICU] Reset Password / 重置密码'
            html_message = render_to_string('password_reset_email.html', {
                'user': user,
                'reset_link': reset_link,
            })
            if settings.DEBUG:
                return Response({
                    "message": "You are in debug mode, so do not send email",
                    "uid": uid,
                    "token": token}, status=status.HTTP_200_OK)
            else:
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.nickname}, 请访问以下页面来设置一个新密码: {reset_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[user.email],
                    html_message=html_message,
                )
                return Response({"detail": "密码重置链接已经发送."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordMailResetView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, uid, token):
        uid = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=uid)
        if cache.get(token):
            return Response({'message': 'Token已经被使用'}, status=status.HTTP_200_OK)
        if default_token_generator.check_token(user, token):
            cache.set(token, True, settings.CACHE_TTL)
            return Response({'message': 'ok'}, status=status.HTTP_200_OK)
        else:
            return Response({'message': 'no'}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, uid: str, token: str):
        serializer = PasswordResetMailRequestSerializer(data=request.data)
        if serializer.is_valid():
            try:
                uid = urlsafe_base64_decode(uid).decode()
                user = User.objects.get(pk=uid)
                token_check = default_token_generator.check_token(user, token)
                if token_check:
                    # 更新用户密码
                    new_password = serializer.validated_data['new_password']
                    user.password = make_password(new_password)
                    user.save()
                    return Response({"detail": "已成功重置密码!"}, status=status.HTTP_200_OK)
                else:
                    return Response({"detail": "错误的Token"}, status=status.HTTP_401_UNAUTHORIZED)
            except User.DoesNotExist:
                return Response({"detail": "未找到用户"}, status=status.HTTP_404_NOT_FOUND)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetWhenLoginView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordResetWhenLoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = request.user
            new_password = serializer.validated_data['new_password']
            user.password = make_password(new_password)
            user.save()
            response = Response({"detail": "已成功重置密码, 即将登出"}, status=status.HTTP_200_OK)
            response.delete_cookie('sessionid')
            return response
        else:
            return Response({"detail": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            return Response({"message": "你已经登录"}, status=status.HTTP_400_BAD_REQUEST)
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                user_info = {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "date_joined": user.date_joined,
                    "nickname": user.nickname,
                    "avatar": user.avatar_uuid,
                }
                response = Response({"message": user_info}, status=status.HTTP_200_OK)
                return response
            else:
                return Response({"message": "认证失败, 用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        User.objects.get(pk=request.user.id)
        user_info = {
            "id": request.user.id,
            "username": request.user.username,
            "bio": request.user.bio,
            "email": request.user.email,
            "date_joined": request.user.date_joined,
            "nickname": request.user.nickname,
            "avatar": request.user.avatar_uuid,
            "nwu_email": request.user.nwu_email,
        }
        return Response({'message': user_info}, status=status.HTTP_200_OK)

    def post(self, request):
        user = User.objects.get(pk=request.user.id)
        serializer = UpdateProfileSerializer(data=request.data)
        if serializer.is_valid():
            for key, value in serializer.validated_data.items():
                setattr(user, key, value)
            user.save()
            user_info = {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "avatar_uuid": user.avatar_uuid,
                "bio": user.bio,
            }
            return Response({"message": user_info}, status=status.HTTP_200_OK)
        error_list = []
        for error in serializer.errors['non_field_errors']:
            error_list.append(error)
        return Response({'error': ",".join(error_list)}, status=status.HTTP_400_BAD_REQUEST)


class BindNwuEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, email_b64, uid, token):
        try:
            uid = urlsafe_base64_decode(uid).decode()
            user = User.objects.get(pk=uid)
            email = base64.b64decode(email_b64).decode("utf-8")

            if cache.get(token):
                return Response({'message': 'Token 已经被使用'}, status=status.HTTP_400_BAD_REQUEST)

            if default_token_generator.check_token(user, token):
                user.nwu_email = email
                user.save()
                cache.set(token, True, settings.CACHE_TTL)
                return Response({'message': email}, status=status.HTTP_200_OK)
            else:
                return Response({'message': '无效的 token'}, status=status.HTTP_400_BAD_REQUEST)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({'message': '无效的请求'}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request):
        serializer = BindNwuEmailSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            email = serializer.validated_data['nwu_email']
            email_base64 = base64.b64encode(email.encode("utf-8")).decode("utf-8")
            mail_subject = '[NWU.ICU] 绑定西北大学邮箱'
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            bind_link = request.build_absolute_uri(f'/user/bind-nwu-email/{email_base64}/{uid}/{token}/')
            html_message = render_to_string('password_reset_email.html', {
                'user': user,
                'reset_link': bind_link,
            })
            if settings.DEBUG:
                return Response({
                    "message": "You are in debug mode, so do not send email",
                    "email": email,
                    'link': bind_link}, status=status.HTTP_200_OK)
            else:
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.nickname}, 请访问以下页面来完成邮箱绑定: {bind_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    html_message=html_message,
                )
            return Response({"message": "已发送邮件"}, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Logout(APIView):
    def post(self, request):
        current_url = request.data.get('currentUrl', "/")
        if request.user.is_authenticated:
            logout(request)
            response = Response({"detail": "成功登出", "redirectUrl": current_url}, status=status.HTTP_200_OK)
            response.delete_cookie('sessionid')
        else:
            response = Response({"detail": "用户尚未登录", "redirectUrl": current_url},
                                status=status.HTTP_400_BAD_REQUEST)

        return response
