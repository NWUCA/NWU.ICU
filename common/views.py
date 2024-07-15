import json

from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django import forms
from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from pywebpush import webpush
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import settings.settings
from user.models import User
from .models import Bulletin, About, UploadedFile
from .models import WebPushSubscription
from .serializers import AboutSerializer, CaptchaSerializer, UploadedFileSerializer
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


class FileUploadView(generics.CreateAPIView):
    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES['file']
        if file_obj.size > settings.settings.FILE_UPLOAD_SIZE_LIMIT:
            return Response({"error": "File too large. Size should not exceed 25 MB."},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class FileDownloadView(APIView):
    def get(self, request, file_uuid):
        try:
            file_instance = UploadedFile.objects.get(pk=file_uuid)
        except UploadedFile.DoesNotExist:
            return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(file_instance.file)
        response['Content-Disposition'] = f'attachment; filename="{file_instance.file.name}"'
        return response


class TosView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        tos_content_database = About.objects.order_by('-update_time').filter(type="tos")
        try:
            tos_content = AboutSerializer(tos_content_database, many=True).data[0]
        except IndexError:
            tos_content = "Get about content failed"
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


class SettingsForm(forms.Form):
    nickname = forms.CharField(max_length=30)


class Settings(LoginRequiredMixin, View):
    def get(self, request):
        settings_form = SettingsForm()
        context = {
            "VAPID_PUBLIC_KEY": dj_settings.WEBPUSH_SETTINGS["VAPID_PUBLIC_KEY"],
            "form": settings_form,
        }
        return render(request, 'settings.html', context=context)

    def post(self, request):
        f = SettingsForm(request.POST)
        if f.is_valid():
            # 考虑到数据库中可能已有重复昵称, 那么使用 model 中的 UniqueConstraint 会带来额外的迁移成本
            # 故直接在 view 中处理重复昵称
            if (
                    User.objects.exclude(id=request.user.id)
                            .filter(nickname=f.cleaned_data['nickname'])
                            .exists()
            ):
                messages.error(request, "昵称已被使用")
            else:
                request.user.nickname = f.cleaned_data['nickname']
                request.user.save()
                messages.success(request, "修改成功")
        else:
            messages.error(request, "昵称不合法")
        return redirect('/settings/')


@login_required
def save_push_subscription(request):
    data = json.loads(request.body)
    WebPushSubscription.objects.update_or_create(user=request.user, defaults={'subscription': data})
    return HttpResponse()


@permission_required('dumb_perm')  # superuser has all the permissions
def send_test_notification(request):
    try:
        msg = request.GET['msg']
        for s in WebPushSubscription.objects.all():
            webpush(
                s.subscription,
                msg,
                vapid_private_key=dj_settings.WEBPUSH_SETTINGS['VAPID_PRIVATE_KEY'],
                vapid_claims={"sub": f"mailto:{dj_settings.WEBPUSH_SETTINGS['VAPID_ADMIN_EMAIL']}"},
            )
        return HttpResponse('OK')
    except KeyError:
        return HttpResponse(status=400)


def manifest(request):
    """Serve manifest.json"""
    return render(request, 'manifest.json', content_type='application/json')


def service_worker(request):
    """Serve serviceworker.js"""
    return render(request, 'serviceworker.js', content_type='application/javascript')
