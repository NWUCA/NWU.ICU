import logging
import random
import string

from django.contrib.auth import authenticate, login
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.serializers import ValidationError
from settings import development
from .models import User
from .models import VerificationCode
from .serializers import LoginSerializer
from .serializers import PasswordResetRequestSerializer
from .serializers import RegisterSerializer
from .serializers import VerificationCodeSerializer

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            password = request.data.get("password")
            try:
                serializer.validate_password_complexity(password)
            except ValidationError as e:
                custom_errors = {"fields": {"password": list(e.detail)}}
                return Response({
                    "status": 400,
                    "message": "Registration failed.",
                    "errors": custom_errors
                }, status=status.HTTP_400_BAD_REQUEST)

            user = serializer.save()
            return Response({
                "status": 200,
                "message": "Successfully registered.",
                "errors": None
            }, status=status.HTTP_201_CREATED)

        custom_errors = {"fields": {}}
        for field, errors in serializer.errors.items():
            custom_errors["fields"][field] = [str(error) for error in errors]

        return Response({
            "status": 400,
            "message": "Registration failed.",
            "errors": custom_errors
        }, status=status.HTTP_400_BAD_REQUEST)


class CaptchaView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerificationCodeSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

            VerificationCode.objects.update_or_create(email=email, defaults={'code': code})

            send_mail(
                'Your verification code',
                f'Your verification code is {code}',
                'from@example.com',
                [email]
            )
            return Response({"detail": "Verification code sent."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def decode(self, uid: str, token: str):
        uid = urlsafe_base64_decode(uid)
        user = User.objects.get(pk=uid)
        token_check = default_token_generator.check_token(user, token)
        if token_check:
            return Response({"detail": "Password reset link sent."}, status=status.HTTP_200_OK)
        else:
            Response({"detail": "Password reset link sent."}, status=status.HTTP_401_UNAUTHORIZED)

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            email = serializer.validated_data['email']
            try:
                user = User.objects.get(username=username, email=email)
            except User.DoesNotExist:
                return Response({"errors": "User with this email does not exist.", "content": None},
                                status=status.HTTP_400_BAD_REQUEST)

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_link = request.build_absolute_uri(f'/user/reset-password/{uid}/{token}/')

            mail_subject = 'Password Reset Request'
            message = render_to_string('password_reset_email.html', {
                'user': user,
                'reset_link': reset_link,
            })
            # send_mail(mail_subject, message, 'admin@nwu.icu', [user.email])
            return Response({"detail": "Password reset link sent."}, status=status.HTTP_200_OK)
        # fixme: 加一个频率验证
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                response = Response({"detail": "Login successful"}, status=status.HTTP_200_OK)
                response.set_cookie(
                    key='sessionid',
                    value=request.session.session_key,
                    httponly=True,
                    secure=(not development.DEBUG),
                    samesite='Lax'  # 根据需要设置
                )
                return response
            else:
                return Response({"detail": "Authentication failed."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Logout(APIView):
    def post(self, request):
        current_url = request.data.get('currentUrl', "/")
        if request.user.is_authenticated:
            logout(request)
            response = Response({"detail": "Logout successful", "redirectUrl": current_url}, status=status.HTTP_200_OK)
            response.delete_cookie('sessionid')
        else:
            response = Response({"detail": "User is not logged in", "redirectUrl": current_url},
                                status=status.HTTP_400_BAD_REQUEST)

        return response
