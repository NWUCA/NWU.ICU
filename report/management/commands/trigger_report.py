import json
import logging
import pickle
import time
from concurrent import futures

import requests
from django.core.management.base import BaseCommand

from report.models import Report

logger = logging.getLogger(__name__)
MAX_WORKERS = 100


class Command(BaseCommand):
    help = '执行自动填报'

    def handle(self, *args, **options):
        start_time = time.time()
        report_list = Report.objects.filter(status=True).select_related('user')
        workers = min(MAX_WORKERS, len(report_list))
        with futures.ThreadPoolExecutor(workers) as executor:
            results = executor.map(self.do_report, report_list)
        success = 0
        for result in results:
            if result:
                success += 1
        logger.critical(
            f'成功人数: {success}/{len(report_list)}, 用时: {time.time()-start_time:.2f}s'
        )

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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/13.1 Safari/605.1.15",
            "X-Requested-With": "XMLHttpRequest",
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
            "ymtys": "",
        }

        cookie_jar = pickle.loads(report.user.cookie)
        try:
            r = requests.post(url, headers=headers, data=data, cookies=cookie_jar)
            r = json.loads(r.text)
            if r['e'] == 1 or r['e'] == 0:
                logger.info(f'{report.user.username}-{report.user.name} {r["m"]}')
                return True
            else:
                logger.warning(f'{report.user.username}-{report.user.name} {r}')
                return False
        except ConnectionError as e:
            logger.error(f'{report.user.username}-{report.user.name} 连接失败\n' f'错误信息: {e}')
        return False
