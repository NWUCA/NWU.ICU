import json
import logging
import pickle
import time
from concurrent import futures
from datetime import datetime
from time import sleep

import requests
from django.core.management.base import BaseCommand
from django.db import OperationalError

from report.models import Report

logger = logging.getLogger(__name__)
MAX_WORKERS = 100


class Command(BaseCommand):
    help = '执行自动填报'

    def test_connectivity(self):
        i = 0
        # retry 10 times
        while True:
            try:
                requests.get("https://app.nwu.edu.cn/")
                return True
            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError):
                i = i + 1
                sleep(1)
                if i < 10:
                    continue
                else:
                    return False

    def handle(self, *args, **options):
        if not self.test_connectivity():
            logger.critical("连接 https://app.nwu.edu.cn/ 失败!")
            return
        start_time = time.time()
        report_list = Report.objects.filter(status=True).select_related('user')
        workers = min(MAX_WORKERS, len(report_list))
        with futures.ThreadPoolExecutor(workers) as executor:
            results = executor.map(self.do_report, report_list)
        success = 0
        veri = 0
        net_error = 0
        for (result, status) in results:
            if result:
                success += 1
            elif status == 'veri':
                veri += 1
            elif status == 'net_error':
                net_error += 1
        logger.critical(
            f'成功人数: {success}/{len(report_list)}, 开启二级验证人数{veri}, 网络错误人数{net_error}, '
            f' 用时: {time.time() - start_time:.2f}s'
        )

    def model_save_with_retry(self, report: Report):
        """
        sqlite 似乎不支持这么高的并发, 一直会报错 database is locked
        https://docs.djangoproject.com/en/3.1/ref/databases/#database-is-locked-errors
        FIXME: 暂时用无限重试解决
        """
        retry = 0
        while retry >= 0:
            try:
                logger.info(f'writing {report.user.username:10} to database, retry={retry}')
                report.save()
                retry = -1
            except OperationalError:
                retry += 1

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
        i = 0
        while True:
            try:
                r = requests.post(
                    url,
                    headers=headers,
                    cookies=cookie_jar.get_dict(domain='app.nwu.edu.cn'),
                    data=data,
                )
                r = json.loads(r.text)
                if r['e'] == 1 or r['e'] == 0:
                    logger.info(f'{report.user.username}-{report.user.name} {r["m"]}')
                    if report.last_report_message:
                        report.last_report_message = ''
                        self.model_save_with_retry(report)
                    return (True, 'success')
                else:
                    logger.warning(f'{report.user.username}-{report.user.name} {r}')
                    report.last_report_message = f'[{datetime.now()} {r}]'
                    self.model_save_with_retry(report)
                    return (False, 'veri')
            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
                i = i + 1
                sleep(1)
                if i < 10:
                    continue
                else:
                    logger.warning(
                        f'{report.user.username}-{report.user.name} 连接失败,已重试10次\n' f'错误信息: {e}'
                    )
                    report.last_report_message = f'[{datetime.now()} 连接失败\n' f'错误信息: {e}]'
                    self.model_save_with_retry(report)
                    return (False, 'net_error')
