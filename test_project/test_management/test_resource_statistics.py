from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APIRequestFactory
from common.file.resource_statistics import client_ip
from common.models import ResourceDownloadEvent
from test_project.test_management import test_resource_files


class ResourceDownloadStatisticsTests(APITestCase):
    base = test_resource_files.ResourceFileManagementTests.base
    setUp = test_resource_files.ResourceFileManagementTests.setUp
    elevate = test_resource_files.ResourceFileManagementTests.elevate

    def download(self, client, **headers):
        response = client.get('/api/resources/file/', {'path': '/试卷 #1%.pdf'}, **headers)
        with patch('django.http.response.signals.request_finished.send'):
            response.close()
        self.assertEqual(response.status_code, 200)

    def test_captures_reported_ip_ua_and_authenticated_user_without_trust_checks(self):
        guest = APIClient()
        headers = {'HTTP_X_FORWARDED_FOR': '203.0.113.9, 10.0.0.1', 'HTTP_X_REAL_IP': '203.0.113.8',
                   'REMOTE_ADDR': '198.51.100.2', 'HTTP_USER_AGENT': 'Any made-up UA <script>text</script>'}
        self.download(guest, **headers)
        self.download(guest, **headers)
        self.download(self.client, **headers)
        self.assertEqual(ResourceDownloadEvent.objects.count(), 2)
        anon = ResourceDownloadEvent.objects.get(authenticated=False)
        self.assertEqual(anon.ip_address, '203.0.113.9')
        self.assertEqual(anon.user_agent, headers['HTTP_USER_AGENT'])
        self.assertIsNone(anon.user_id)
        self.assertEqual(anon.username, '')
        user = ResourceDownloadEvent.objects.get(authenticated=True)
        self.assertEqual((user.user_id, user.username), (self.staff.pk, self.staff.username))
        report = self.client.get(self.base + 'statistics/').data['contents']
        self.assertEqual((report['unique_ips'], report['unique_users'], report['unique_uas']), (1, 1, 1))
        self.assertEqual(report['ips'], [{'ip_address': '203.0.113.9', 'count': 2}])
        self.assertEqual(report['users'], [{'user_id': self.staff.pk, 'username': self.staff.username, 'count': 1}])
        self.assertEqual(report['events']['results'][0]['user_agent'], headers['HTTP_USER_AGENT'])

    def test_ip_header_fallback_and_ipv6_normalization(self):
        factory = APIRequestFactory()
        for headers, expected in [
            ({'HTTP_X_FORWARDED_FOR': '2001:0db8::1, 10.0.0.1'}, '2001:db8::1'),
            ({'HTTP_X_REAL_IP': '203.0.113.8'}, '203.0.113.8'),
            ({'HTTP_X_FORWARDED_FOR': 'not-an-ip', 'HTTP_X_REAL_IP': '::ffff:192.0.2.1'}, '192.0.2.1'),
            ({'REMOTE_ADDR': '192.0.2.7'}, '192.0.2.7'),
            ({'REMOTE_ADDR': ''}, None),
        ]:
            with self.subTest(headers=headers):
                self.assertEqual(client_ip(factory.get('/', **headers)), expected)

    def test_history_filters_pagination_and_renamed_user_grouping(self):
        ResourceDownloadEvent.objects.create(dedupe_key='historical', path='/旧资料', authenticated=True)
        ResourceDownloadEvent.objects.bulk_create([ResourceDownloadEvent(
            dedupe_key=f'new-{i}', path='/课程/试卷.pdf', authenticated=True, user_id=42,
            username='旧用户名' if i == 0 else '新用户名', ip_address='203.0.113.7', user_agent='ExampleBrowser/1') for i in range(51)])
        old = ResourceDownloadEvent.objects.create(dedupe_key='outside-range', path='/过期', ip_address='203.0.113.8', user_agent='OtherUA')
        ResourceDownloadEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        report = self.client.get(self.base + 'statistics/', {'days': 7}).data['contents']
        self.assertEqual(report['total'], 52)
        self.assertEqual((report['unknown_ip'], report['unknown_user'], report['unknown_ua']), (1, 1, 1))
        self.assertEqual(report['users'], [{'user_id': 42, 'username': '新用户名', 'count': 51}])
        report = self.client.get(self.base + 'statistics/', {'days': 7, 'ip': '203.0.113.7', 'user_id': 42, 'ua': 'examplebrowser', 'search': '试卷', 'page': 2}).data['contents']
        self.assertEqual(report['total'], 51)
        self.assertEqual(len(report['events']['results']), 1)
        self.assertEqual(report['events']['page'], 2)
        self.assertEqual(report['events']['results'][0]['username'], '旧用户名')
        self.assertEqual(sum(row['count'] for row in report['daily']), 51)
        self.assertEqual(self.client.get(self.base + 'statistics/', {'ip': 'invalid'}).status_code, 400)

    def test_statistics_detail_stays_behind_existing_management_gate(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.base + 'statistics/').status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.base + 'statistics/').status_code, 403)
