from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from report.models import Report


class ReportIndex(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        try:
            report = Report.objects.get(user=user)
        except Report.DoesNotExist:
            report = Report.objects.create(user=user)
        context = {
            'status': report.status,
            'cookie_status': True
            if datetime.now() - user.cookie_last_update < timedelta(hours=24)
            else False,
            'is_at_school': '在校' if report.sfzx else '不在校',
            'address': report.address,
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
