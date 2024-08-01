import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import LoginSerializer, PasswordResetMailRequestSerializer, UsernameDuplicationSerializer
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
                "message": "Successfully registered.",
                "errors": None
            }, status=status.HTTP_201_CREATED)
        else:
            custom_errors = {"fields": {}}
            for field, errors in serializer.errors.items():
                custom_errors["fields"][field] = [str(error) for error in errors]

            return Response({
                "message": "Registration failed.",
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
                return Response({'message': 'Username usable.'}, status=status.HTTP_200_OK)
            return Response({'message': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
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
                return Response({"errors": "User with this email does not exist.", "content": None},
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
                    message=f'Hello {user}, 请访问以下页面来设置一个新密码: {reset_link}',
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[user.email],
                    html_message=html_message,
                )
                return Response({"detail": "Password reset link sent."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordMailResetView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, uid, token):
        uid = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=uid)
        if default_token_generator.check_token(user, token):
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

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
                    return Response({"detail": "Password has been reset successfully."}, status=status.HTTP_200_OK)
                else:
                    return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
            except User.DoesNotExist:
                return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            return Response({"detail": "You have already login"}, status=status.HTTP_400_BAD_REQUEST)
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                response = Response({"detail": "Login successful"}, status=status.HTTP_200_OK)
                return response
            else:
                return Response({"detail": "Authentication failed."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        User.objects.get(pk=request.user.id)
        user_info = {
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "date_joined": request.user.date_joined,
            "nickname": request.user.nickname,
            "avatar": request.user.avatar_uuid,
        }
        return Response({'message': user_info}, status=status.HTTP_200_OK)


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
