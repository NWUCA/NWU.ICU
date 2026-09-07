import hashlib
import json
import logging
import secrets
import time

from bs4 import BeautifulSoup
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from common.file.models import ResourceUploadDirectoryBlacklist, ResourceUploadFile, ResourceUploadRequest
from common.file.resource_blacklist import get_resource_upload_blacklist
from common.file.resource_directories import ResourceDirectoryCacheError, get_cached_child_directories
from common.file.resource_workflow import (
    ResourceReviewError,
    approve_resource_upload,
    reject_resource_upload,
    retry_resource_publish,
)
from common.file.serializers import ResourceDirectorySerializer, ResourceUploadRequestSerializer
from guestbook.announcements import publish_announcement
from guestbook.models import GuestbookEntry, GuestbookReport
from guestbook.moderation import ReportModerationError, resolve_guestbook_report
from guestbook.serializers import AnnouncementContentSerializer
from guestbook.views import serialize_entry
from utils.custom_pagination import StandardResultsSetPagination
from utils.utils import return_response

from .exceptions import PasskeyCeremonyError, PasskeyNotEnrolled
from .models import AdminPasskeyCredential, AdminPasskeyEnrollment, AdminPasskeyState
from .security import (
    CEREMONY_KEY,
    decode_bytes,
    elevate_admin_session,
    encode_bytes,
    is_admin_elevated,
    require_management_access,
)
from .serializers import (
    PasskeyAuthenticationVerifySerializer,
    PasskeyRegistrationOptionsSerializer,
    PasskeyRegistrationVerifySerializer,
    ReportResolutionSerializer,
    ResourceReviewSerializer,
    ResourceUploadBlacklistSerializer,
)
from .throttles import AdminPasskeyIPThrottle, AdminPasskeyUserThrottle


logger = logging.getLogger('management.security')
CEREMONY_SECONDS = 5 * 60
VALID_TRANSPORTS = {transport.value for transport in AuthenticatorTransport}


def _active_credentials(user):
    return AdminPasskeyCredential.objects.filter(user=user, revoked_at__isnull=True)


def _credential_descriptor(credential):
    transports = []
    for value in credential.transports:
        if value in VALID_TRANSPORTS:
            transports.append(AuthenticatorTransport(value))
    return PublicKeyCredentialDescriptor(id=bytes(credential.credential_id), transports=transports or None)


def _store_ceremony(request, *, kind, challenge, **extra):
    request.session[CEREMONY_KEY] = {
        'kind': kind,
        'challenge': encode_bytes(challenge),
        'expires_at': time.time() + CEREMONY_SECONDS,
        **extra,
    }
    request.session.modified = True


def _consume_ceremony(request, expected_kind):
    ceremony = request.session.pop(CEREMONY_KEY, None)
    request.session.modified = True
    if not ceremony or ceremony.get('kind') != expected_kind:
        raise PasskeyCeremonyError()
    try:
        if float(ceremony['expires_at']) <= time.time():
            raise PasskeyCeremonyError()
        ceremony['challenge'] = decode_bytes(ceremony['challenge'])
    except (KeyError, TypeError, ValueError):
        raise PasskeyCeremonyError()
    return ceremony


def _origins():
    origins = settings.WEBAUTHN_EXPECTED_ORIGINS
    return origins[0] if len(origins) == 1 else origins


def _permission_flags(user):
    return {
        'moderate_reports': user.has_perm('guestbook.moderate_reports'),
        'publish_announcements': user.has_perm('guestbook.publish_announcements'),
        'review_resource_uploads': user.has_perm('common.review_resource_uploads'),
    }


class ManagementAPIView(APIView):
    permission_classes = [AllowAny]
    required_permission = None
    require_elevation = True

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_management_access(
            request,
            permission=self.required_permission,
            require_elevation=self.require_elevation,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        response['Pragma'] = 'no-cache'
        response['X-Frame-Options'] = 'DENY'
        return response


class PasskeyAPIView(ManagementAPIView):
    require_elevation = False
    throttle_classes = [AdminPasskeyUserThrottle, AdminPasskeyIPThrottle]


class ManagementSessionView(ManagementAPIView):
    require_elevation = False

    def get(self, request):
        credentials = _active_credentials(request.user)
        elevated = is_admin_elevated(request)
        until = request.session.get('admin_elevated_until') if elevated else None
        return return_response(contents={
            'passkey_enrolled': credentials.exists(),
            'passkey_count': credentials.count(),
            'elevated': elevated,
            'elevated_until': until,
            'permissions': _permission_flags(request.user),
        })


class PasskeyAuthenticationOptionsView(PasskeyAPIView):
    def post(self, request):
        credentials = list(_active_credentials(request.user))
        if not credentials:
            raise PasskeyNotEnrolled()
        challenge = secrets.token_bytes(32)
        options = generate_authentication_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            challenge=challenge,
            timeout=CEREMONY_SECONDS * 1000,
            allow_credentials=[_credential_descriptor(credential) for credential in credentials],
            # KeePassXC-Browser only takes over reliably when the browser request
            # uses the WebAuthn.io-compatible preference. Verification below still
            # requires the authenticator's UV flag before granting elevation.
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        _store_ceremony(request, kind='authentication', challenge=challenge)
        return return_response(contents=json.loads(options_to_json(options)))


class PasskeyAuthenticationVerifyView(PasskeyAPIView):
    def post(self, request):
        # Every verification attempt is one-shot, including malformed payloads.
        try:
            ceremony = _consume_ceremony(request, 'authentication')
        except PasskeyCeremonyError:
            logger.warning('missing or expired passkey authentication challenge user_id=%s', request.user.pk)
            raise
        serializer = PasskeyAuthenticationVerifySerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning('invalid passkey authentication payload user_id=%s', request.user.pk)
            raise PasskeyCeremonyError()
        credential_payload = serializer.validated_data['credential']
        try:
            credential_id = base64url_to_bytes(credential_payload['id'])
        except (KeyError, TypeError, ValueError):
            raise PasskeyCeremonyError()
        with transaction.atomic():
            credential = (
                AdminPasskeyCredential.objects.select_for_update()
                .filter(user=request.user, revoked_at__isnull=True, credential_id=credential_id)
                .first()
            )
            if credential is None:
                logger.warning('passkey credential mismatch user_id=%s', request.user.pk)
                raise PasskeyCeremonyError()
            try:
                verification = verify_authentication_response(
                    credential=credential_payload,
                    expected_challenge=ceremony['challenge'],
                    expected_rp_id=settings.WEBAUTHN_RP_ID,
                    expected_origin=_origins(),
                    credential_public_key=bytes(credential.public_key),
                    credential_current_sign_count=credential.sign_count,
                    require_user_verification=True,
                )
            except WebAuthnException:
                logger.warning('passkey verification failed user_id=%s', request.user.pk)
                raise PasskeyCeremonyError()
            if not verification.user_verified:
                logger.warning('passkey user verification missing user_id=%s', request.user.pk)
                raise PasskeyCeremonyError()
            credential.sign_count = verification.new_sign_count
            credential.last_used_at = timezone.now()
            credential.save(update_fields=('sign_count', 'last_used_at'))
        elevated_until = elevate_admin_session(request, credential)
        logger.info('passkey verification succeeded user_id=%s credential_id=%s', request.user.pk, credential.pk)
        return return_response(contents={'elevated_until': elevated_until.isoformat()})


class PasskeyRegistrationOptionsView(PasskeyAPIView):
    def post(self, request):
        serializer = PasskeyRegistrationOptionsSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        token_digest = hashlib.sha256(serializer.validated_data['enrollment_code'].encode('utf-8')).hexdigest()
        enrollment = AdminPasskeyEnrollment.objects.filter(
            user=request.user,
            token_digest=token_digest,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).first()
        if enrollment is None:
            logger.warning('invalid passkey enrollment code user_id=%s', request.user.pk)
            raise PasskeyCeremonyError()
        challenge = secrets.token_bytes(32)
        options = generate_registration_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
            user_id=request.user.uuid.bytes,
            user_name=request.user.username,
            user_display_name=request.user.nickname or request.user.username,
            challenge=challenge,
            timeout=CEREMONY_SECONDS * 1000,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                require_resident_key=False,
                # Keep authenticator discovery compatible with software passkey
                # providers; registration verification still requires actual UV.
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=[_credential_descriptor(item) for item in _active_credentials(request.user)],
        )
        _store_ceremony(
            request,
            kind='registration',
            challenge=challenge,
            enrollment_id=enrollment.pk,
            name=serializer.validated_data['name'],
        )
        return return_response(contents=json.loads(options_to_json(options)))


class PasskeyRegistrationVerifyView(PasskeyAPIView):
    def post(self, request):
        # Every verification attempt is one-shot, including malformed payloads.
        try:
            ceremony = _consume_ceremony(request, 'registration')
        except PasskeyCeremonyError:
            logger.warning('missing or expired passkey registration challenge user_id=%s', request.user.pk)
            raise
        serializer = PasskeyRegistrationVerifySerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning('invalid passkey registration payload user_id=%s', request.user.pk)
            raise PasskeyCeremonyError()
        try:
            verification = verify_registration_response(
                credential=serializer.validated_data['credential'],
                expected_challenge=ceremony['challenge'],
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=_origins(),
                require_user_presence=True,
                require_user_verification=True,
            )
        except WebAuthnException:
            logger.warning('passkey registration failed user_id=%s', request.user.pk)
            raise PasskeyCeremonyError()
        if not verification.user_verified:
            raise PasskeyCeremonyError()

        transports = serializer.validated_data['credential'].get('response', {}).get('transports', [])
        transports = [value for value in transports if value in VALID_TRANSPORTS]
        try:
            with transaction.atomic():
                enrollment = AdminPasskeyEnrollment.objects.select_for_update().filter(
                    pk=ceremony.get('enrollment_id'),
                    user=request.user,
                    used_at__isnull=True,
                    expires_at__gt=timezone.now(),
                ).first()
                if enrollment is None:
                    raise PasskeyCeremonyError()
                credential = AdminPasskeyCredential.objects.create(
                    user=request.user,
                    name=ceremony.get('name', 'Passkey'),
                    credential_id=verification.credential_id,
                    public_key=verification.credential_public_key,
                    sign_count=verification.sign_count,
                    transports=transports,
                    last_used_at=timezone.now(),
                )
                enrollment.used_at = timezone.now()
                enrollment.save(update_fields=('used_at',))
                state, _ = AdminPasskeyState.objects.select_for_update().get_or_create(user=request.user)
                state.revision += 1
                state.save(update_fields=('revision', 'updated_at'))
        except IntegrityError:
            raise PasskeyCeremonyError()
        elevated_until = elevate_admin_session(request, credential)
        logger.info('passkey registered user_id=%s credential_id=%s', request.user.pk, credential.pk)
        return return_response(
            contents={
                'credential': {'id': credential.pk, 'name': credential.name},
                'elevated_until': elevated_until.isoformat(),
            },
            status_code=status.HTTP_201_CREATED,
        )


def _plain_text(html):
    soup = BeautifulSoup(html or '', 'html.parser')
    for tag in soup.find_all(('script', 'style', 'iframe', 'object', 'embed', 'template')):
        tag.decompose()
    return soup.get_text(' ', strip=True)


def _report_payload(report):
    entry = report.entry
    parent = entry.parent
    return {
        'id': report.pk,
        'reason': report.reason,
        'detail': report.detail,
        'status': report.status,
        'handling_note': report.handling_note,
        'created_at': report.created_at,
        'handled_at': report.handled_at,
        'reporter': {'id': report.reporter_id, 'username': report.reporter.username, 'nickname': report.reporter.nickname},
        'entry': {
            'id': entry.pk,
            'board': entry.board,
            'title': entry.title,
            'content': _plain_text(entry.content),
            'is_deleted': entry.is_deleted,
            'parent_id': entry.parent_id,
            'root_id': entry.root_id,
            'author': {'id': entry.author_id, 'username': entry.author.username, 'nickname': entry.author.nickname},
            'parent_content': _plain_text(parent.content) if parent else '',
        },
    }


class ManagementReportListView(ManagementAPIView):
    required_permission = 'guestbook.moderate_reports'

    def get(self, request):
        queryset = GuestbookReport.objects.select_related('entry__author', 'entry__parent', 'reporter').order_by('-created_at', '-id')
        report_status = request.query_params.get('status', GuestbookReport.STATUS_PENDING)
        if report_status not in dict(GuestbookReport.STATUS_CHOICES):
            return return_response(
                errors={'status': {'err_code': 'invalid_status', 'err_msg': '无效的举报状态'}},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        queryset = queryset.filter(status=report_status)
        board = request.query_params.get('board')
        if board:
            if board not in dict(GuestbookEntry.BOARD_CHOICES):
                return return_response(
                    errors={'board': {'err_code': 'invalid_board', 'err_msg': '无效的来源'}},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(entry__board=board)
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response([_report_payload(report) for report in page])


class ManagementReportResolveView(ManagementAPIView):
    required_permission = 'guestbook.moderate_reports'

    def post(self, request, report_id):
        serializer = ReportResolutionSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        try:
            reports = resolve_guestbook_report(
                report_id=report_id,
                moderator=request.user,
                **serializer.validated_data,
            )
        except ReportModerationError as error:
            return return_response(
                errors={'report': {'err_code': 'report_conflict', 'err_msg': str(error)}},
                status_code=status.HTTP_409_CONFLICT if '已经' in str(error) else status.HTTP_404_NOT_FOUND,
            )
        return return_response(contents={'report_ids': [report.pk for report in reports]})


class ManagementAnnouncementView(ManagementAPIView):
    required_permission = 'guestbook.publish_announcements'

    def post(self, request):
        serializer = AnnouncementContentSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        entry, created = publish_announcement(author=request.user, data=serializer.validated_data)
        return return_response(
            message='公告发布成功',
            contents={'entry': serialize_entry(entry, request), 'created': created},
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ManagementResourceUploadBlacklistView(ManagementAPIView):
    required_permission = 'common.review_resource_uploads'

    def get(self, request):
        return return_response(contents={'paths': get_resource_upload_blacklist()})

    def post(self, request):
        serializer = ResourceUploadBlacklistSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        if data['action'] == 'add':
            ResourceUploadDirectoryBlacklist.objects.get_or_create(path=data['path'])
        else:
            ResourceUploadDirectoryBlacklist.objects.filter(path=data['path']).delete()
        return return_response(contents={'paths': get_resource_upload_blacklist()})


class ManagementResourceDirectoryView(ManagementAPIView):
    required_permission = 'common.review_resource_uploads'

    def get(self, request):
        serializer = ResourceDirectorySerializer(data=request.query_params)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        try:
            contents = get_cached_child_directories(serializer.validated_data['path'])
        except ResourceDirectoryCacheError:
            return return_response(
                errors={'directory': {'err_code': 'resource_service_unavailable', 'err_msg': '目录缓存暂时不可用，请稍后重试'}},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return return_response(contents=contents)


class ManagementResourceUploadListView(ManagementAPIView):
    required_permission = 'common.review_resource_uploads'

    def get(self, request):
        queryset = ResourceUploadRequest.objects.select_related('uploaded_by', 'reviewed_by').prefetch_related('files')
        upload_status = request.query_params.get('status')
        if upload_status:
            if upload_status not in dict(ResourceUploadRequest.STATUS_CHOICES):
                return return_response(
                    errors={'status': {'err_code': 'invalid_status', 'err_msg': '无效的投稿状态'}},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=upload_status)
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset.order_by('-created_at', '-id'), request)
        return paginator.get_paginated_response(ResourceUploadRequestSerializer(page, many=True).data)


class ManagementResourceUploadDetailView(ManagementAPIView):
    required_permission = 'common.review_resource_uploads'

    def get_object(self, request_id):
        upload_request = (
            ResourceUploadRequest.objects.select_related('uploaded_by', 'reviewed_by')
            .prefetch_related('files')
            .filter(pk=request_id)
            .first()
        )
        if upload_request is None:
            raise Http404
        return upload_request

    def get(self, request, request_id):
        return return_response(contents={'upload_request': ResourceUploadRequestSerializer(self.get_object(request_id)).data})

    def post(self, request, request_id):
        serializer = ResourceReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        try:
            if data['action'] == 'approve':
                result = approve_resource_upload(
                    upload_request_id=request_id,
                    reviewer=request.user,
                    expected_revision=data['expected_revision'],
                    target_path=data['target_path'],
                )
            elif data['action'] == 'reject':
                result = reject_resource_upload(
                    upload_request_id=request_id,
                    reviewer=request.user,
                    expected_revision=data['expected_revision'],
                    reason=data['reason'],
                )
            else:
                result = retry_resource_publish(
                    upload_request_id=request_id,
                    reviewer=request.user,
                    expected_revision=data['expected_revision'],
                    target_path=data['target_path'],
                )
        except ResourceUploadRequest.DoesNotExist:
            raise Http404
        except ResourceReviewError as error:
            return return_response(
                errors={'upload_request': {'err_code': 'resource_review_conflict', 'err_msg': str(error)}},
                status_code=status.HTTP_409_CONFLICT,
            )
        result = ResourceUploadRequest.objects.select_related('uploaded_by', 'reviewed_by').prefetch_related('files').get(pk=result.pk)
        return return_response(contents={'upload_request': ResourceUploadRequestSerializer(result).data})


class ManagementResourceUploadFileDownloadView(ManagementAPIView):
    required_permission = 'common.review_resource_uploads'

    def get(self, request, file_id):
        upload_file = ResourceUploadFile.objects.filter(pk=file_id).first()
        if upload_file is None or not upload_file.file:
            raise Http404
        try:
            file_handle = upload_file.file.open('rb')
        except (FileNotFoundError, ValueError):
            raise Http404
        response = FileResponse(file_handle, as_attachment=True, filename=upload_file.original_name)
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
