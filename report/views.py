import logging
import pickle

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.http import require_GET

from report.models import Report

logger = logging.getLogger(__name__)


class ReportIndex(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        try:
            report = Report.objects.get(user=user)
        except Report.DoesNotExist:
            report = Report.objects.create(user=user)
        context = {
            'status': report.status,
            'is_at_school': '在校' if report.sfzx else '不在校',
            'address': report.address,
            'last_report_message': report.last_report_message,
        }
        return render(request, 'report.html', context=context)

    def post(self, request):
        report = Report.objects.get(user=request.user)
        report.status = True if request.POST['status'] == 'true' else False
        if report.status:
            report.sfzx = True if request.POST['sfzx'] == 'true' else False
            report.address = request.POST['address']
            report.area = request.POST['area']
            report.province = request.POST['province']
            report.city = request.POST['city']
            report.geo_api_info = request.POST['geo_api_info']
            report.save()
            messages.success(request, '开启成功')
        else:
            report.save()
            messages.success(request, '关闭成功')
        return redirect('/report/')


@require_GET
@login_required
def check_cookie_status(request):
    cookie_jar = pickle.loads(request.user.cookie)
    try:
        r = requests.get(
            'https://app.nwu.edu.cn/uc/wap/login',
            cookies=cookie_jar.get_dict(domain='app.nwu.edu.cn'),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36'
            },
        )
    except requests.exceptions.ConnectionError:
        return HttpResponse("timeout")
    if r.url != 'https://app.nwu.edu.cn/site/center/personal':
        return HttpResponse("invalid")
    else:
        return HttpResponse("ok")
