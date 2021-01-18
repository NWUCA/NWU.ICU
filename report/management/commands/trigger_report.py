from concurrent import futures
from time import strftime
import pickle

from django.core.management.base import BaseCommand
import requests

from report.models import Report

MAX_WORKERS = 100


class Command(BaseCommand):
    help = '执行自动填报'

    def handle(self, *args, **options):
        report_list = Report.objects.filter(status=True).select_related('user')
        workers = min(MAX_WORKERS, len(report_list))
        with futures.ThreadPoolExecutor(workers) as executor:
            results = executor.map(self.do_report, report_list)
        for i, result in enumerate(results):
            print(f"{strftime('[%H:%M:%S]')} {i+1}/{len(report_list)} 已结束")  # TODO: replace with log

    def do_report(self, report: Report):
        url = 'https://app.nwu.edu.cn/ncov/wap/open-report/save'

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
            "Host": "app.nwu.edu.cn",
            "Accept-Language": "en-us",
            "Accept-Encoding": "br, gzip, deflate",
            "Origin": "https://app.nwu.edu.cn",
            "Referer": "https://app.nwu.edu.cn/site/ncov/dailyup",
            "Connection": "keep-alive",
            "Content-Length": "1780",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                          "Version/13.1 Safari/605.1.15",
            "X-Requested-With": "XMLHttpRequest"
        }

        data = {
            "sfzx": "1" if report.sfzx else "0",
            "tw": "1",
            "address": report.address,
            "area": report.area,
            "province": report.province,
            "city": report.city,
            "geo_api_info": report.geo_api_info,
            "sfcyglq": "0",
            "sfyzz": "0",
            "qtqk": "",
            "ymtys": ""
        }

        # FIXME: 修复有些人无 cookie, 之后可以移除
        try:
            cookie_jar = pickle.loads(report.user.cookie)
        except EOFError:
            print(f"{strftime('[%H:%M:%S]')} {report.user.username}-{report.user.name} 无 cookie")
            cookie_jar = {}
        try:
            r = requests.post(url, headers=headers, data=data, cookies=cookie_jar)
            print(f"{strftime('[%H:%M:%S]')} {report.user.username}-{report.user.name} {r.text}")
            return r
        except ConnectionError as e:
            print(f"{strftime('[%H:%M:%S]')} {report.user.username}-{report.user.name} 连接失败")
            print(f"错误信息: {e}")
        return None
