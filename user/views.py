import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

import utils.utils
from utils.throttle import CaptchaAnonRateThrottle, CaptchaUserRateThrottle, EmailAnonRateThrottle, \
    EmailUserRateThrottle, EmailAddressRateThrottle, LoginIPRateThrottle, LoginUsernameRateThrottle
from utils.utils import return_response, get_err_msg, get_msg_msg
from .models import User
from .serializers import LoginSerializer, PasswordResetMailRequestSerializer, UsernameDuplicationSerializer, \
    PasswordResetWhenLoginSerializer, BindCollegeEmailSerializer, UpdateProfileSerializer, PrivateSerializer
from .serializers import PasswordResetRequestSerializer
from .serializers import RegisterSerializer
from .tokens import UserTokenPurpose, check_user_token, consume_user_token, get_user_token_data, issue_user_token

logger = logging.getLogger(__name__)


def build_frontend_action_link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}#{urlencode({'token': token})}"


class CsrfTokenView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return return_response(contents={'csrf_token': get_token(request)})


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [CaptchaAnonRateThrottle(), CaptchaUserRateThrottle()]
        return []

    @staticmethod
    def send_active_email(user: User, request):
        email = user.email
        mail_subject = f'[{settings.WEBSITE_NAME}] 激活邮箱'
        token = issue_user_token(
            user,
            UserTokenPurpose.ACCOUNT_ACTIVATION,
            email=email,
        )
        active_link = build_frontend_action_link('/user/activate', token)
        html_message = render_to_string('active_email.html', {
            'user': user,
            'active_link': active_link,
        })
        if settings.DEBUG:
            logger.info(f"debug mode not send activation email to {user.id}:{user.email}")
            return return_response(
                message=get_msg_msg('has_sent_email'),
                contents={"email": email, 'token': token, 'link': active_link})
        else:
            logger.info(f'send activation email to {user.id}:{user.email}')
            send_mail(
                subject=mail_subject,
                message=f'Hello {user.username}, 请访问以下页面来完成账号激活: {active_link}',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                html_message=html_message,
            )
        return return_response(message=get_msg_msg('has_sent_email'))

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user.is_active = False
            user.nickname = utils.utils.userUtils.generate_random_nickname()
            user.avatar_uuid = settings.DEFAULT_USER_AVATAR_UUID
            user.save()
            return self.send_active_email(user, request)
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class AccountActivationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        token_data = get_user_token_data(token, UserTokenPurpose.ACCOUNT_ACTIVATION)
        if token_data is None:
            return return_response(errors={'token': get_err_msg('invalid_token')}, status_code=HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=token_data.get('user_id'))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return return_response(errors={'token': get_err_msg('invalid_token')}, status_code=HTTP_400_BAD_REQUEST)
        if user.is_active or not check_user_token(user, token, UserTokenPurpose.ACCOUNT_ACTIVATION):
            return return_response(errors={'token': get_err_msg('invalid_token')}, status_code=HTTP_400_BAD_REQUEST)
        user.email = token_data.get('email')
        user.is_active = True
        user.save(update_fields=('email', 'is_active'))
        consume_user_token(user, token, UserTokenPurpose.ACCOUNT_ACTIVATION)
        return return_response(message=user.email)


class UsernameDuplicationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UsernameDuplicationSerializer(data=request.data)
        if serializer.is_valid():
            return return_response(message='用户名可用', status_code=HTTP_200_OK)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [EmailAnonRateThrottle(), EmailAddressRateThrottle()]
        return []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email'].strip().lower()
            user = User.objects.filter(email__iexact=email, is_active=True).order_by('pk').first()
            if user is None:
                logger.info('Password reset requested for an unregistered email address')
                return return_response(message=get_msg_msg('password_reset_email_sent'))

            token = issue_user_token(
                user,
                UserTokenPurpose.PASSWORD_RESET,
                email=email,
            )
            reset_link = build_frontend_action_link('/user/forget-password', token)
            mail_subject = f'[{settings.WEBSITE_NAME}] Reset Password / 重置密码'
            html_message = render_to_string('password_reset_email.html', {
                'user': user,
                'reset_link': reset_link,
            })
            if settings.DEBUG:
                logger.info(f"debug mode not send activation email to {user.id}:{user.email}")
                return return_response(
                    message='You are in debug mode, so do not send email',
                    contents={'token': token, 'link': reset_link},
                )
            else:
                logger.info(f"send reset password email to {user.id}:{user.email}")
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.nickname}, 请访问以下页面来设置一个新密码: {reset_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[user.email],
                    html_message=html_message,
                )
                return return_response(message=get_msg_msg('password_reset_email_sent'))
        logger.error(get_err_msg('send_reset_password_email_error') + str(serializer.errors))
        return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class PasswordMailResetVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        user_info_dict = get_user_token_data(
            token,
            UserTokenPurpose.PASSWORD_RESET,
        )
        if user_info_dict is None:
            return return_response(message='no', status_code=HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(id=user_info_dict.get('user_id'))
        except User.DoesNotExist:
            return return_response(message='no', status_code=HTTP_400_BAD_REQUEST)
        if user.is_active and check_user_token(
                user, token, UserTokenPurpose.PASSWORD_RESET):
            return return_response(message='ok', status_code=HTTP_200_OK)
        return return_response(message='no', status_code=HTTP_400_BAD_REQUEST)


class PasswordMailResetView(APIView):  # 点击邮件重置密码链接后
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        serializer = PasswordResetMailRequestSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user_info_dict = get_user_token_data(
                    token,
                    UserTokenPurpose.PASSWORD_RESET,
                )
                if user_info_dict is None:
                    return return_response(errors={'token': get_err_msg('invalid_token')},
                                           status_code=status.HTTP_401_UNAUTHORIZED)
                user = User.objects.get(id=user_info_dict.get('user_id'))
                token_check = user.is_active and check_user_token(
                    user, token, UserTokenPurpose.PASSWORD_RESET)
                if token_check:
                    new_password = serializer.validated_data['new_password']
                    user.password = make_password(new_password)
                    user.save()
                    consume_user_token(
                        user, token, UserTokenPurpose.PASSWORD_RESET)
                    return return_response(message=get_msg_msg('reset_password_success'))
                else:
                    return return_response(errors={'token': get_err_msg('invalid_token')},
                                           status_code=status.HTTP_401_UNAUTHORIZED)
            except User.DoesNotExist:
                return return_response(errors={'user': get_err_msg('user_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class PasswordResetWhenLoginView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordResetWhenLoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = request.user
            new_password = serializer.validated_data['new_password']
            user.password = make_password(new_password)
            user.save()
            response = return_response(message=get_msg_msg('reset_password_logout'))
            response.delete_cookie('sessionid')
            return response
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class Login(APIView):
    permission_classes = [AllowAny]

    throttle_classes = [LoginIPRateThrottle, LoginUsernameRateThrottle]

    def post(self, request):
        if request.user.is_authenticated:
            return return_response(message=get_msg_msg('have_login'), errors={"login": get_err_msg('have_login')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
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
                user = User.objects.filter(username=username).first()
                if user is not None and not user.is_active and user.check_password(password):
                    return return_response(errors={'user': get_err_msg('not_active')},
                                           status_code=HTTP_403_FORBIDDEN)
                return return_response(errors={'credentials': get_err_msg('password_incorrect')},
                                       status_code=status.HTTP_401_UNAUTHORIZED)

        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class ActiveUser(APIView):
    permission_classes = [AllowAny]

    throttle_classes = [LoginIPRateThrottle, LoginUsernameRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = User.objects.get(username=serializer.validated_data['username'])
            except User.DoesNotExist:
                return return_response(errors={'credentials': get_err_msg('password_incorrect')},
                                       status_code=status.HTTP_401_UNAUTHORIZED)
            if not user.is_active:
                if user.check_password(serializer.validated_data['password']):
                    return RegisterView.send_active_email(user, request)
                else:
                    return return_response(errors={'credentials': get_err_msg('password_incorrect')},
                                           status_code=status.HTTP_401_UNAUTHORIZED)
            else:
                return return_response(errors={'user': get_err_msg('has_active')}, status_code=HTTP_204_NO_CONTENT)
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET' and self.kwargs.get('user_id') is not None:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request, user_id=None):
        try:
            profile_user = request.user if user_id is None else User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return return_response(errors={'user': get_err_msg('user_not_exist')}, status_code=HTTP_400_BAD_REQUEST)
        is_me = (user_id == request.user.id) or (request.user.id is not None and user_id is None)
        user_info = {
            "id": profile_user.id,
            "bio": profile_user.bio,
            "nickname": profile_user.nickname,
            "avatar": profile_user.avatar_uuid,
            'is_me': is_me,
            'verified': profile_user.college_email_verified,
            "date_joined": profile_user.date_joined,
        }
        if is_me:
            user_info.update({
                "username": profile_user.username,
                "email": profile_user.email,
                "college_email": profile_user.college_email
            })
        return return_response(contents=user_info)

    def post(self, request):
        user = User.objects.get(pk=request.user.id)
        serializer = UpdateProfileSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            for key, value in serializer.validated_data.items():
                setattr(user, key, value)
            user.save()
            user.refresh_from_db()
            user_info = {
                "id": user.id,
                "nickname": user.nickname,
                "avatar": user.avatar_uuid,
                "bio": user.bio,
            }
            return return_response(contents=user_info)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class VerifyCollegeEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('token')
        try:
            with transaction.atomic():
                user_info_dict = get_user_token_data(
                    token,
                    UserTokenPurpose.COLLEGE_EMAIL_BIND,
                )
                user = User.objects.select_for_update().get(id=user_info_dict.get('user_id'))
                token_email = user_info_dict.get('email')
                if not (
                        user.id == request.user.id
                        and user.college_email == token_email
                        and check_user_token(
                            user, token, UserTokenPurpose.COLLEGE_EMAIL_BIND)
                ):
                    return return_response(message='无效的 token', status_code=HTTP_400_BAD_REQUEST)
                if User.objects.filter(
                        college_email__iexact=token_email,
                        college_email_verified=True,
                ).exclude(pk=user.pk).exists():
                    return return_response(errors={'college_email': get_err_msg('email_duplicate')},
                                           status_code=HTTP_400_BAD_REQUEST)
                user.college_email_verified = True
                user.save(update_fields=('college_email_verified',))
                consume_user_token(
                    user, token, UserTokenPurpose.COLLEGE_EMAIL_BIND)
                return return_response(contents=user_info_dict)
        except (TypeError, ValueError, OverflowError, AttributeError, User.DoesNotExist, IntegrityError):
            return return_response(message='无效的请求', status_code=HTTP_400_BAD_REQUEST)


class BindCollegeEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        return [EmailAnonRateThrottle(), EmailUserRateThrottle(), EmailAddressRateThrottle()]

    def post(self, request):
        serializer = BindCollegeEmailSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = request.user
            college_email = serializer.validated_data['college_email']
            user.college_email = college_email
            user.college_email_verified = False
            user.save()
            mail_subject = f'[{settings.WEBSITE_NAME}] 绑定{settings.UNIVERSITY_CHINESE_NAME}邮箱'
            token = issue_user_token(
                user,
                UserTokenPurpose.COLLEGE_EMAIL_BIND,
                email=college_email,
            )
            bind_link = build_frontend_action_link('/user/bind-college-email/', token)
            html_message = render_to_string('bind_nwu_email.html', {
                'username': user.username,
                'bind_link': bind_link,
            })
            if settings.DEBUG:
                return return_response(message="You are in debug mode, so do not send email",
                                       contents={"email": college_email, 'token': token, 'link': bind_link})
            else:
                send_mail(
                    subject=mail_subject,
                    message=f'Hello {user.username}, 请访问以下页面来完成邮箱绑定: {bind_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[college_email],
                    html_message=html_message,
                )
            return return_response(message=get_msg_msg('has_sent_email'), status_code=HTTP_200_OK)
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class PrivateView(APIView):
    permission_classes = [IsAuthenticated]

    def get_explain(self, private):
        return {'setting': private, 'explain': {key: value for key, value in User.PRIVATE_CHOICES}.get(private)}

    def get(self, request):
        user = request.user
        return return_response(
            contents={'review': self.get_explain(user.private_review),
                      'reply': self.get_explain(user.private_reply), })

    def post(self, request):
        serializer = PrivateSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            for key, value in serializer.validated_data.items():
                setattr(user, key, value)
            user.save()
            user.refresh_from_db()
            return return_response(message=get_msg_msg('setting_success'),
                                   contents={'review': self.get_explain(user.private_review),
                                             'reply': self.get_explain(user.private_reply), })
        else:
            return return_response(errors=serializer.errors, status_code=HTTP_400_BAD_REQUEST)


class Logout(APIView):
    def post(self, request):
        current_url = request.data.get('currentUrl', "/")
        logout(request)
        response = return_response(message=get_msg_msg('logout_success'), contents={'redirectUrl': current_url})
        response.delete_cookie('sessionid')
        return response
