import base64
import hashlib
import io
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from PIL import Image

from common.file.models import ResourcePublishJob, ResourceUploadRequest, UploadedFile
from common.models import Notification
from guestbook.models import GuestbookEntry, GuestbookReport
from management_panel.models import (
    AdminPasskeyCredential,
    AdminPasskeyEnrollment,
    AdminPasskeyState,
)
from management_panel.security import (
    CEREMONY_KEY,
    ELEVATED_CREDENTIAL_KEY,
    ELEVATED_REVISION_KEY,
    ELEVATED_UNTIL_KEY,
)
from test_project.common import create_user


def credential_id_json(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


class ManagementAccessTests(APITestCase):
    def setUp(self):
        self.staff = create_user(
            username='management-staff',
            email='management-staff@example.com',
            is_staff=True,
        )
        self.user = create_user(username='management-user', email='management-user@example.com')
        self.client = APIClient()

    def elevate(self, user=None):
        user = user or self.staff
        credential, _ = AdminPasskeyCredential.objects.get_or_create(
            user=user,
            credential_id=f'credential-{user.pk}'.encode(),
            defaults={'name': 'Test key', 'public_key': b'public-key'},
        )
        state, _ = AdminPasskeyState.objects.get_or_create(user=user)
        self.client.force_login(user)
        session = self.client.session
        session[ELEVATED_UNTIL_KEY] = time.time() + 600
        session[ELEVATED_CREDENTIAL_KEY] = credential.pk
        session[ELEVATED_REVISION_KEY] = state.revision
        session.save()
        return credential

    def grant(self, user, codename):
        user.user_permissions.add(Permission.objects.get(codename=codename))

    def test_management_session_hides_anonymous_and_non_staff_users(self):
        url = reverse('api:management-session')
        anonymous = self.client.get(url)
        self.assertEqual(anonymous.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(anonymous['Cache-Control'], 'no-store')

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_sees_enrollment_state_but_needs_elevation_for_management(self):
        self.client.force_login(self.staff)
        session_response = self.client.get(reverse('api:management-session'))
        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        self.assertFalse(session_response.data['contents']['passkey_enrolled'])
        self.assertFalse(session_response.data['contents']['elevated'])

        reports = self.client.get(reverse('api:management-reports'))
        self.assertEqual(reports.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reports.data['errors'][0]['err_code'], 'admin_passkey_required')

    def test_revocation_staff_and_permission_changes_apply_immediately(self):
        credential = self.elevate()
        self.grant(self.staff, 'moderate_reports')
        url = reverse('api:management-reports')
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

        credential.revoked_at = timezone.now()
        credential.save(update_fields=('revoked_at',))
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

        credential.revoked_at = None
        credential.save(update_fields=('revoked_at',))
        self.elevate()
        self.staff.user_permissions.clear()
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

        self.staff.is_staff = False
        self.staff.save(update_fields=('is_staff',))
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    def test_session_refreshes_elevation_for_ten_minutes(self):
        self.elevate()
        session = self.client.session
        now = time.time()
        original_until = now + 1
        session[ELEVATED_UNTIL_KEY] = original_until
        session.save()

        with patch('management_panel.security.time.time', return_value=now):
            response = self.client.get(reverse('api:management-session'))
        self.assertTrue(response.data['contents']['elevated'])
        self.assertEqual(response.data['contents']['elevated_until'], now + 600)
        self.assertEqual(self.client.session[ELEVATED_UNTIL_KEY], now + 600)

        with patch('management_panel.security.time.time', return_value=now + 600):
            response = self.client.get(reverse('api:management-session'))
        self.assertFalse(response.data['contents']['elevated'])
        self.assertIsNone(response.data['contents']['elevated_until'])
        self.assertNotIn(ELEVATED_UNTIL_KEY, self.client.session)

    def test_each_management_request_extends_elevation_beyond_initial_expiry(self):
        self.elevate()
        self.grant(self.staff, 'moderate_reports')
        original_until = self.client.session[ELEVATED_UNTIL_KEY]
        url = reverse('api:management-reports')

        for now in (original_until - 1, original_until + 598):
            with patch('management_panel.security.time.time', return_value=now):
                response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self.client.session[ELEVATED_UNTIL_KEY], now + 600)

        with patch('management_panel.security.time.time', return_value=now + 600):
            response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['errors'][0]['err_code'], 'admin_passkey_required')
        self.assertNotIn(ELEVATED_UNTIL_KEY, self.client.session)

    def test_admin_requests_refresh_elevation_and_redirect_after_inactivity(self):
        self.elevate()
        now = self.client.session[ELEVATED_UNTIL_KEY] - 1
        with patch('management_panel.security.time.time', return_value=now):
            response = self.client.get('/admin/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.session[ELEVATED_UNTIL_KEY], now + 600)

        with patch('management_panel.security.time.time', return_value=now + 600):
            response = self.client.get('/admin/')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, '/manage?next=%2Fadmin%2F')
        self.assertNotIn(ELEVATED_UNTIL_KEY, self.client.session)

    def test_admin_pages_redirect_to_manage_until_elevated(self):
        self.client.force_login(self.staff)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, '/manage?next=%2Fadmin%2F')

        self.elevate()
        self.assertEqual(self.client.get('/admin/').status_code, status.HTTP_200_OK)

    def test_django_admin_resource_review_requires_custom_permission(self):
        self.elevate()
        submitter = create_user(username='admin-upload-user', email='admin-upload-user@example.com')
        upload = ResourceUploadRequest.objects.create(uploaded_by=submitter, target_path='/target')
        url = reverse('admin:common_resourceuploadrequest_review', args=(upload.pk,))

        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)
        self.grant(self.staff, 'review_resource_uploads')
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

    def test_management_post_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        credential = AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='CSRF key',
            credential_id=b'csrf-key',
            public_key=b'public-key',
        )
        state, _ = AdminPasskeyState.objects.get_or_create(user=self.staff)
        client.force_login(self.staff)
        session = client.session
        session[ELEVATED_UNTIL_KEY] = time.time() + 600
        session[ELEVATED_CREDENTIAL_KEY] = credential.pk
        session[ELEVATED_REVISION_KEY] = state.revision
        session.save()
        self.grant(self.staff, 'publish_announcements')

        response = client.post(
            reverse('api:management-announcements'),
            {'title': 'CSRF', 'content': '<p>blocked</p>'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(
    WEBAUTHN_RP_ID='localhost',
    WEBAUTHN_RP_NAME='NWU.ICU Test',
    WEBAUTHN_EXPECTED_ORIGINS=['http://localhost'],
)
class PasskeyCeremonyTests(APITestCase):
    def setUp(self):
        self.staff = create_user(
            username='passkey-staff',
            email='passkey-staff@example.com',
            is_staff=True,
        )
        self.other_staff = create_user(
            username='passkey-other',
            email='passkey-other@example.com',
            is_staff=True,
        )
        self.client = APIClient()
        self.client.force_login(self.staff)

    def create_enrollment(self, code='valid-enrollment', **kwargs):
        return AdminPasskeyEnrollment.objects.create(
            user=self.staff,
            token_digest=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=kwargs.get('expires_at', timezone.now() + timedelta(minutes=5)),
        )

    def test_enrollment_code_is_scoped_expiring_and_single_use(self):
        self.create_enrollment('valid')
        url = reverse('api:passkey-register-options')
        self.assertEqual(
            self.client.post(url, {'enrollment_code': 'wrong', 'name': 'Laptop'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        options_response = self.client.post(
            url,
            {'enrollment_code': 'valid', 'name': 'Laptop'},
            format='json',
        )
        self.assertEqual(options_response.status_code, status.HTTP_200_OK)
        authenticator_selection = options_response.data['contents']['authenticatorSelection']
        self.assertEqual(authenticator_selection['residentKey'], 'preferred')
        self.assertFalse(authenticator_selection['requireResidentKey'])
        self.assertEqual(authenticator_selection['userVerification'], 'preferred')
        self.assertEqual(
            [parameter['alg'] for parameter in options_response.data['contents']['pubKeyCredParams']],
            [-8, -7, -257],
        )

        verify_result = SimpleNamespace(
            user_verified=True,
            credential_id=b'new-credential',
            credential_public_key=b'new-public-key',
            sign_count=0,
        )
        old_session_key = self.client.session.session_key
        with patch('management_panel.views.verify_registration_response', return_value=verify_result) as verify_registration:
            response = self.client.post(
                reverse('api:passkey-register-verify'),
                {'credential': {'response': {'transports': ['internal', 'invalid']}}},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(verify_registration.call_args.kwargs['require_user_verification'])
        self.assertNotEqual(self.client.session.session_key, old_session_key)
        credential = AdminPasskeyCredential.objects.get(user=self.staff)
        self.assertEqual(credential.transports, ['internal'])
        self.assertIsNotNone(AdminPasskeyEnrollment.objects.get(user=self.staff).used_at)
        self.assertTrue(self.client.get(reverse('api:management-session')).data['contents']['elevated'])
        self.assertEqual(
            self.client.post(url, {'enrollment_code': 'valid', 'name': 'Second'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_expired_and_other_users_enrollment_codes_fail(self):
        self.create_enrollment('expired', expires_at=timezone.now() - timedelta(seconds=1))
        AdminPasskeyEnrollment.objects.create(
            user=self.other_staff,
            token_digest=hashlib.sha256(b'other').hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        url = reverse('api:passkey-register-options')
        for code in ('expired', 'other'):
            response = self.client.post(url, {'enrollment_code': code, 'name': 'Key'}, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_authentication_cycles_session_updates_counter_and_consumes_challenge(self):
        credential = AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Laptop',
            credential_id=b'credential-id',
            public_key=b'public-key',
            sign_count=4,
        )
        options = self.client.post(reverse('api:passkey-auth-options'), format='json')
        self.assertEqual(options.status_code, status.HTTP_200_OK)
        self.assertEqual(options.data['contents']['userVerification'], 'preferred')
        old_session_key = self.client.session.session_key
        payload = {'credential': {'id': credential_id_json(b'credential-id')}}
        verification = SimpleNamespace(user_verified=True, new_sign_count=5)
        with patch('management_panel.views.verify_authentication_response', return_value=verification) as verify:
            response = self.client.post(reverse('api:passkey-auth-verify'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotEqual(self.client.session.session_key, old_session_key)
        credential.refresh_from_db()
        self.assertEqual(credential.sign_count, 5)
        self.assertIsNotNone(credential.last_used_at)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.kwargs['expected_rp_id'], 'localhost')
        self.assertEqual(verify.call_args.kwargs['expected_origin'], 'http://localhost')
        self.assertTrue(verify.call_args.kwargs['require_user_verification'])

        replay = self.client.post(reverse('api:passkey-auth-verify'), payload, format='json')
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)

    def test_expired_replaced_and_missing_uv_challenges_fail_closed(self):
        credential = AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Laptop',
            credential_id=b'credential-id',
            public_key=b'public-key',
            sign_count=7,
        )
        payload = {'credential': {'id': credential_id_json(b'credential-id')}}

        self.client.post(reverse('api:passkey-auth-options'), format='json')
        session = self.client.session
        ceremony = session[CEREMONY_KEY]
        ceremony['expires_at'] = time.time() - 1
        session[CEREMONY_KEY] = ceremony
        session.save()
        with patch('management_panel.views.verify_authentication_response') as verify:
            expired = self.client.post(reverse('api:passkey-auth-verify'), payload, format='json')
        self.assertEqual(expired.status_code, status.HTTP_400_BAD_REQUEST)
        verify.assert_not_called()

        self.client.post(reverse('api:passkey-auth-options'), format='json')
        self.create_enrollment('replace')
        self.client.post(
            reverse('api:passkey-register-options'),
            {'enrollment_code': 'replace', 'name': 'Replacement'},
            format='json',
        )
        replaced = self.client.post(reverse('api:passkey-auth-verify'), payload, format='json')
        self.assertEqual(replaced.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(CEREMONY_KEY, self.client.session)

        self.client.post(reverse('api:passkey-auth-options'), format='json')
        without_uv = SimpleNamespace(user_verified=False, new_sign_count=8)
        with patch('management_panel.views.verify_authentication_response', return_value=without_uv):
            response = self.client.post(reverse('api:passkey-auth-verify'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        credential.refresh_from_db()
        self.assertEqual(credential.sign_count, 7)

    def test_multiple_credentials_are_counted_independently(self):
        for index in range(2):
            AdminPasskeyCredential.objects.create(
                user=self.staff,
                name=f'Key {index}',
                credential_id=f'credential-{index}'.encode(),
                public_key=b'public-key',
            )
        response = self.client.get(reverse('api:management-session'))
        self.assertEqual(response.data['contents']['passkey_count'], 2)

    def test_malformed_verify_consumes_challenge(self):
        AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Laptop',
            credential_id=b'credential-id',
            public_key=b'public-key',
        )
        self.client.post(reverse('api:passkey-auth-options'), format='json')
        first = self.client.post(reverse('api:passkey-auth-verify'), {}, format='json')
        self.assertEqual(first.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(CEREMONY_KEY, self.client.session)

    def test_credential_must_belong_to_current_user(self):
        AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Mine',
            credential_id=b'mine',
            public_key=b'public-key',
        )
        AdminPasskeyCredential.objects.create(
            user=self.other_staff,
            name='Other',
            credential_id=b'other',
            public_key=b'public-key',
        )
        self.client.post(reverse('api:passkey-auth-options'), format='json')
        response = self.client.post(
            reverse('api:passkey-auth-verify'),
            {'credential': {'id': credential_id_json(b'other')}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ManagementBusinessTests(ManagementAccessTests):
    def test_report_list_is_plain_text_and_remove_resolves_all_pending_reports(self):
        self.elevate()
        self.grant(self.staff, 'moderate_reports')
        author = create_user(username='reported-author', email='reported-author@example.com')
        reporter_a = create_user(username='reporter-a', email='reporter-a@example.com')
        reporter_b = create_user(username='reporter-b', email='reporter-b@example.com')
        entry = GuestbookEntry.objects.create(author=author, content='<p>visible<script>secret()</script></p>')
        first = GuestbookReport.objects.create(entry=entry, reporter=reporter_a, reason='spam')
        second = GuestbookReport.objects.create(entry=entry, reporter=reporter_b, reason='abuse')

        listing = self.client.get(reverse('api:management-reports'))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data['contents']['results'][0]['entry']['content'], 'visible')

        response = self.client.post(
            reverse('api:management-report-resolve', kwargs={'report_id': first.pk}),
            {'decision': 'remove', 'note': '违反社区规则'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data['contents']['report_ids'], [first.pk, second.pk])
        entry.refresh_from_db()
        self.assertTrue(entry.is_deleted)
        self.assertEqual(
            set(GuestbookReport.objects.values_list('status', flat=True)),
            {GuestbookReport.STATUS_REMOVED},
        )
        self.assertEqual(Notification.objects.filter(kind=Notification.KIND_SYSTEM).count(), 2)

    def test_announcement_creation_is_permissioned_sanitized_and_idempotent(self):
        self.elevate()
        self.grant(self.staff, 'publish_announcements')
        url = reverse('api:management-announcements')
        payload = {
            'title': 'Maintenance',
            'content': '<p><strong>Tonight</strong><img src=x><script>bad()</script></p>',
            'submission_id': '00d4ed5e-c53d-4c31-9187-e806d77a790d',
        }
        first = self.client.post(url, payload, format='json')
        second = self.client.post(url, payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(GuestbookEntry.objects.filter(board=GuestbookEntry.BOARD_ANNOUNCEMENT).count(), 1)
        entry = GuestbookEntry.objects.get(board=GuestbookEntry.BOARD_ANNOUNCEMENT)
        self.assertEqual(entry.content, '<p><strong>Tonight</strong></p>')
        self.assertFalse(entry.anonymous)

    def test_announcement_accepts_owned_uploaded_images_only(self):
        self.elevate()
        self.grant(self.staff, 'publish_announcements')
        image_data = io.BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(image_data, format='PNG')
        upload = self.client.post(
            reverse('api:file-upload'),
            {
                'file': SimpleUploadedFile('announcement.png', image_data.getvalue(), content_type='image/png'),
                'file_type': 'img',
            },
            format='multipart',
        )
        self.assertEqual(upload.status_code, status.HTTP_201_CREATED)
        image_id = upload.data['contents']['uuid']

        response = self.client.post(
            reverse('api:management-announcements'),
            {
                'title': 'With image',
                'content': (
                    f'<p>Visible</p><img src="/api/download/{image_id}/" onerror="bad()">'
                    '<img src="https://example.com/external.png">'
                ),
                'submission_id': '10d4ed5e-c53d-4c31-9187-e806d77a790d',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = GuestbookEntry.objects.get(title='With image')
        self.assertIn(f'<img src="/api/download/{image_id}/"', entry.content)
        self.assertNotIn('onerror', entry.content)
        self.assertNotIn('example.com', entry.content)
        self.assertEqual(UploadedFile.objects.get(pk=image_id).ref_count, 1)
        delete_response = self.client.delete(reverse('api:file-delete', kwargs={'id': image_id}))
        self.assertEqual(delete_response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(UploadedFile.objects.filter(pk=image_id).exists())

    def test_announcement_rejects_another_users_uploaded_image(self):
        self.client.force_login(self.user)
        image_data = io.BytesIO()
        Image.new('RGB', (2, 2), color='red').save(image_data, format='PNG')
        upload = self.client.post(
            reverse('api:file-upload'),
            {
                'file': SimpleUploadedFile('other-user.png', image_data.getvalue(), content_type='image/png'),
                'file_type': 'img',
            },
            format='multipart',
        )
        image_id = upload.data['contents']['uuid']
        self.elevate()
        self.grant(self.staff, 'publish_announcements')

        response = self.client.post(
            reverse('api:management-announcements'),
            {
                'title': 'Invalid image owner',
                'content': f'<img src="/api/download/{image_id}/">',
                'submission_id': '20d4ed5e-c53d-4c31-9187-e806d77a790d',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(GuestbookEntry.objects.filter(title='Invalid image owner').exists())

    def test_resource_review_uses_workflow_and_revision(self):
        self.elevate()
        self.grant(self.staff, 'review_resource_uploads')
        submitter = create_user(username='upload-author', email='upload-author@example.com')
        upload = ResourceUploadRequest.objects.create(uploaded_by=submitter, target_path='/old')
        url = reverse('api:management-upload-detail', kwargs={'request_id': upload.pk})
        response = self.client.post(
            url,
            {'action': 'approve', 'expected_revision': upload.revision, 'target_path': '/final'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        upload.refresh_from_db()
        self.assertEqual(upload.status, ResourceUploadRequest.STATUS_PUBLISHING)
        self.assertEqual(upload.reviewed_by, self.staff)
        self.assertTrue(ResourcePublishJob.objects.filter(upload_request=upload).exists())

        stale = self.client.post(
            url,
            {'action': 'approve', 'expected_revision': 1, 'target_path': '/another'},
            format='json',
        )
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)


class PasskeyCommandTests(APITestCase):
    def setUp(self):
        self.staff = create_user(username='command-staff', email='command-staff@example.com', is_staff=True)

    def test_enroll_stores_only_hash_and_rejects_non_staff(self):
        output = io.StringIO()
        call_command('admin_passkey_enroll', self.staff.username, stdout=output)
        code = output.getvalue().strip().splitlines()[-1]
        enrollment = AdminPasskeyEnrollment.objects.get(user=self.staff)
        self.assertNotIn(code, enrollment.token_digest)
        self.assertEqual(enrollment.token_digest, hashlib.sha256(code.encode()).hexdigest())

        user = create_user(username='command-user', email='command-user@example.com')
        with self.assertRaises(CommandError):
            call_command('admin_passkey_enroll', user.username)

    def test_list_hides_key_material_and_revoke_invalidates_elevation_revision(self):
        credential = AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Security key',
            credential_id=b'secret-credential-id',
            public_key=b'secret-public-key',
        )
        output = io.StringIO()
        call_command('admin_passkey_list', self.staff.username, stdout=output)
        listing = output.getvalue()
        self.assertIn('Security key', listing)
        self.assertNotIn('secret-credential-id', listing)
        self.assertNotIn('secret-public-key', listing)

        state, _ = AdminPasskeyState.objects.get_or_create(user=self.staff)
        old_revision = state.revision
        call_command('admin_passkey_revoke', self.staff.username, credential_id=credential.pk, stdout=io.StringIO())
        credential.refresh_from_db()
        state.refresh_from_db()
        self.assertIsNotNone(credential.revoked_at)
        self.assertEqual(state.revision, old_revision + 1)
