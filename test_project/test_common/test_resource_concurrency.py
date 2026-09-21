from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, local
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from common.file.models import ResourceNotificationOutbox, ResourcePublishJob, ResourceUploadRequest
from common.file.quota import lock_upload_quota
from common.file.resource_locks import lock_resource_upload_request
from common.file.resource_notifications import queue_resource_upload_notifications
from common.file.resource_tasks import claim_notification, process_one_publish_job
from common.file.resource_workflow import ResourceReviewError, reject_resource_upload
from test_project.common import create_user
from user.models import User


class ResourceWorkflowConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = create_user(username='resource-owner', email='resource-owner@example.com')
        self.reviewer = create_user(username='resource-reviewer', email='resource-reviewer@example.com')
        self.request = ResourceUploadRequest.objects.create(uploaded_by=self.user, target_path='/original')

    def run_connection(self, action):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            return action()
        finally:
            close_old_connections()

    def test_edit_and_rejection_acquire_user_before_request(self):
        owner_locked = Event()
        rejection_wants_user = Event()
        state = local()
        select_user_for_update = User.objects.select_for_update

        def observe_user_lock(*args, **kwargs):
            if getattr(state, 'rejecting', False):
                rejection_wants_user.set()
            return select_user_for_update(*args, **kwargs)

        def edit():
            with transaction.atomic():
                lock_upload_quota(self.user)
                owner_locked.set()
                self.assertTrue(rejection_wants_user.wait(timeout=5))
                # This is the same lock order used by the multipart editing API.
                request = ResourceUploadRequest.objects.select_for_update().get(pk=self.request.pk)
                request.revision += 1
                request.save(update_fields=('revision',))

        def reject():
            self.assertTrue(owner_locked.wait(timeout=5))
            state.rejecting = True
            with self.assertRaisesRegex(ResourceReviewError, '已被用户更新'):
                reject_resource_upload(
                    upload_request_id=self.request.pk, reviewer=self.reviewer,
                    expected_revision=1, reason='Original review',
                )

        with patch.object(User.objects, 'select_for_update', side_effect=observe_user_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.run_connection, action) for action in (edit, reject)]
                for future in futures:
                    future.result(timeout=15)
        self.request.refresh_from_db()
        self.assertEqual(self.request.revision, 2)
        self.assertEqual(self.request.status, ResourceUploadRequest.STATUS_PENDING)
        self.assertFalse(ResourceNotificationOutbox.objects.exists())

    def test_publish_worker_waits_for_owner_before_locking_job(self):
        self.request.status = ResourceUploadRequest.STATUS_PUBLISHING
        self.request.save(update_fields=('status',))
        job = ResourcePublishJob.objects.create(
            upload_request=self.request, revision=1, target_path=self.request.target_path,
            available_at=timezone.now(),
        )
        owner_locked = Event()
        worker_wants_user = Event()
        state = local()
        select_user_for_update = User.objects.select_for_update

        def observe_user_lock(*args, **kwargs):
            if getattr(state, 'worker', False):
                worker_wants_user.set()
            return select_user_for_update(*args, **kwargs)

        def review_transaction():
            with transaction.atomic():
                request = lock_resource_upload_request(self.request.pk)
                owner_locked.set()
                self.assertTrue(worker_wants_user.wait(timeout=5))
                ResourcePublishJob.objects.select_for_update().get(pk=job.pk)
                self.assertEqual(request.status, ResourceUploadRequest.STATUS_PUBLISHING)

        def publish():
            self.assertTrue(owner_locked.wait(timeout=5))
            state.worker = True
            return process_one_publish_job()

        with (
            patch.object(User.objects, 'select_for_update', side_effect=observe_user_lock),
            patch('common.file.resource_tasks.publish_resource_upload'),
            patch('common.file.resource_tasks.delete_resource_upload_staging_files', return_value=True),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.run_connection, action) for action in (review_transaction, publish)]
                for future in futures:
                    future.result(timeout=15)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ResourceUploadRequest.STATUS_APPROVED)
        self.assertEqual(ResourceNotificationOutbox.objects.count(), 2)

    def test_concurrent_claims_deliver_whole_batch_once_including_stale_rows(self):
        for index in range(3):
            request = ResourceUploadRequest.objects.create(uploaded_by=self.user, target_path=f'/course-{index}')
            queue_resource_upload_notifications(request, event='approved', reviewer=self.reviewer)
        ResourceNotificationOutbox.objects.filter(channel='email').delete()
        ResourceNotificationOutbox.objects.update(available_at=timezone.now() - timedelta(minutes=20))
        first = ResourceNotificationOutbox.objects.order_by('pk').first()
        ResourceNotificationOutbox.objects.filter(pk=first.pk).update(
            status=ResourceNotificationOutbox.STATUS_PROCESSING,
            locked_at=timezone.now() - timedelta(minutes=20),
        )
        barrier = Barrier(2)

        def claim():
            barrier.wait(timeout=5)
            return claim_notification()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.run_connection, claim) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        batches = [result for result in results if result]
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)
        self.assertEqual(ResourceNotificationOutbox.objects.filter(status='processing').count(), 3)
