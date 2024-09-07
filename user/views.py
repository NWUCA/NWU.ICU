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
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from common.utils import return_response
from .models import User
from .serializers import LoginSerializer, PasswordResetMailRequestSerializer, UsernameDuplicationSerializer, \
    PasswordResetWhenLoginSerializer, BindNwuEmailSerializer, UpdateProfileSerializer
from .serializers import PasswordResetRequestSerializer
from .serializers import RegisterSerializer

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def send_active_email(user: User, request):
        email = user.email
        mail_subject = '[NWU.ICU] 激活邮箱'
        token = default_token_generator.make_token(user)
        cache.set(token, {'email': email, 'id': user.id}, timeout=None)
        active_link = request.build_absolute_uri(
            f'/user/activate?token={token}')
        html_message = render_to_string('active_email.html', {
            'user': user,
            'active_link': active_link,
        })
        if settings.DEBUG:
            logger.info(f"debug mode not send activation email to {user.id}:{user.email}")
            return return_response(
                message="You are in debug mode, so do not send email",
                contents={"email": email, 'token': token, 'link': active_link})
        else:
            logger.info(f'send activation email to {user.id}:{user.email}')
            send_mail(
                subject=mail_subject,
                message=f'Hello {user.nickname}, 请访问以下页面来完成账号激活: {active_link}',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                html_message=html_message,
            )
        return return_response(message="已发送邮件")

    def get(self, request, token):
        try:
            user_register_info = cache.get(token)
            uid = user_register_info['id']
            email = user_register_info['email']
            user = User.objects.get(pk=uid)

            if default_token_generator.check_token(user, token):
                user.email = email
                user.is_active = True
                user.save()
                cache.delete(token)
                return return_response(message=email)
            else:
                return return_response(message="无效的token", status_code=HTTP_400_BAD_REQUEST)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return return_response(message="无效的请求", status_code=HTTP_400_BAD_REQUEST)

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user.is_active = False
            user.save()
            return self.send_active_email(user, request)
        else:
            custom_errors = {"fields": {}}
            for field, errors in serializer.errors.items():
                custom_errors["fields"][field] = [str(error) for error in errors]
            return return_response(message="注册失败", errors=custom_errors, status_code=HTTP_400_BAD_REQUEST)


class UsernameDuplicationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UsernameDuplicationSerializer(data=request.data)
        if serializer.is_valid():
            try:
                User.objects.get(username=serializer.data['username'])
            except User.DoesNotExist:
                logger.info(f"用户名{serializer.data['username']}可用")
                return return_response(message='用户名可用', status_code=HTTP_200_OK)
            logger.warning(f"用户名{serializer.data['username']}不可用")
            return return_response(message='用户名已经存在', status_code=HTTP_400_BAD_REQUEST)
        else:
            logger.error('检查用户名重复错误' + str(serializer.errors))
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
                logger.warning(f'使用{email}邮箱的用户不存在')
                return return_response(message="使用这个邮箱的用户不存在",
                                       status_code=status.HTTP_400_BAD_REQUEST)

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_link = request.build_absolute_uri(f'/user/reset-password/{uid}/{token}/')

            mail_subject = '[NWU.ICU] Reset Password / 重置密码'
            html_message = render_to_string('password_reset_email.html', {
                'user': user,
                'reset_link': reset_link,
            })
            if settings.DEBUG:
                logger.info(f"debug mode not send activation email to {user.id}:{user.email}")
                return return_response(message='You are in debug mode, so do not send email', contents={"uid": uid,
                                                                                                        "token": token})
            else:
                logger.info(f"send reset password email to {user.id}:{user.email}")
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.nickname}, 请访问以下页面来设置一个新密码: {reset_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[user.email],
                    html_message=html_message,
                )
                return return_response(message='密码重置链接已经发送')
        logger.error("发送重置密码邮件错误" + str(serializer.errors))
        return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class PasswordMailResetView(APIView):  # 点击邮件重置密码链接后
    permission_classes = [AllowAny]

    def get(self, request, uid, token):
        uid = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=uid)
        if cache.get(token):
            logger.info('邮件中重置密码的token已被使用')
            return return_response(message='Token已经被使用', status_code=HTTP_200_OK)
        if default_token_generator.check_token(user, token):
            cache.set(token, True, settings.CACHE_TTL)
            return return_response(message='ok', status_code=HTTP_200_OK)
        else:
            return return_response(message='no', status_code=HTTP_400_BAD_REQUEST)

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
                    return return_response(message="已成功重置密码!")
                else:
                    return return_response(message="错误的Token", status_code=status.HTTP_401_UNAUTHORIZED)
            except User.DoesNotExist:
                return return_response(message="未找到用户", status_code=status.HTTP_404_NOT_FOUND)
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
            response = return_response(message='已成功重置密码, 即将登出')
            response.delete_cookie('sessionid')
            return response
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            return return_response("你已经登录", status_code=status.HTTP_400_BAD_REQUEST)
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
                    "bio": user.bio,
                }
                return return_response(contents=user_info)
            else:
                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    return return_response(message="用户不存在", status_code=status.HTTP_401_UNAUTHORIZED)
                if not user.is_active:
                    if user.check_password(serializer.validated_data['password']):
                        return RegisterView.send_active_email(user, request)

                return return_response(message='认证失败, 用户名或密码错误', status_code=status.HTTP_401_UNAUTHORIZED)

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
        logger.error(f"{request.user.id}:{request.user.username}:{request.user.nickname} get profile")
        logger.info(f"{request.user.id}:{request.user.username}:{request.user.nickname} get profile")
        return return_response(contents=user_info)

    def post(self, request):
        user = User.objects.get(pk=request.user.id)
        serializer = UpdateProfileSerializer(data=request.data, context={'request': request})
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
            return return_response(contents=user_info)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class BindNwuEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, email_b64, uid, token):
        try:
            uid = urlsafe_base64_decode(uid).decode()
            user = User.objects.get(pk=uid)
            email = base64.b64decode(email_b64).decode("utf-8")

            if cache.get(token):
                return return_response(message='Token 已经被使用', status_code=HTTP_400_BAD_REQUEST)

            if default_token_generator.check_token(user, token):
                user.nwu_email = email
                user.save()
                cache.set(token, True, settings.CACHE_TTL)
                return return_response(message=email)
            else:
                return return_response(message='无效的 token', status_code=HTTP_400_BAD_REQUEST)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return return_response(message='无效的请求', status_code=HTTP_400_BAD_REQUEST)

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
                'bind_link': bind_link,
            })
            if settings.DEBUG:
                return return_response(message="You are in debug mode, so do not send email",
                                       contents={"email": email, 'link': bind_link})
            else:
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.nickname}, 请访问以下页面来完成邮箱绑定: {bind_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    html_message=html_message,
                )
            return return_response(message='已发送邮件', status_code=HTTP_200_OK)
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class Logout(APIView):
    def post(self, request):
        current_url = request.data.get('currentUrl', "/")
        if request.user.is_authenticated:
            logout(request)
            response = return_response(message='成功登出', contents={'redirectUrl': current_url})
            response.delete_cookie('sessionid')
        else:
            response = return_response(message='用户尚未登录', contents={'redirectUrl': current_url})
        return response
