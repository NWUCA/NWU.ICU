import json
from datetime import datetime

from django import forms
from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from pywebpush import webpush

from user.models import User
from .models import WebPushSubscription


def index(request):
    return render(request, 'index.html')


def about(request):
    day_difference = (datetime.now().date() - datetime(2019, 6, 8).date()).days
    cost_money = round(int(day_difference) * 662.51 / 365, 2)
    return render(request, 'about.html', {'day_difference': day_difference, 'cost_money': cost_money})


def tos(request):
    return render(request, 'tos.html')


def announcement_view(request):
    announcements = [
        {
            'title': '搜索性能和排序改进',
            'content': '之前评价社区的搜索功能依赖 <b>SQL LIKE</b>，性能比较差，每次快速查询时，服务器都会被打挂。例如 <i>2024 年 1 月的新学期快速课程构建时，单日动态查询的高并发达到 45 万次，尽管提前升级到了 16 核 CPU，但选课刚开始的那一个小时还是被打趴了。</i>',
            'publisher': '管理员',
            'publish_time': '2024年5月12日 23:08',
            'update_time': '2024年5月13日 00:01'
        },
        {
            'title': '升级富文本编辑器到 CKEditor 5',
            'content': '非常感谢 <b>taoky</b> 的贡献，把富文本编辑器升级到 <b>CKEditor 5</b>，总算是有一个看起来比较现代的富文本编辑器。',
            'publisher': '管理员',
            'publish_time': '2024年2月6日 23:04',
            'update_time': '2024年2月6日 23:04'
        }
    ]
    return render(request, 'announcements.html', {'announcements': announcements})


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
