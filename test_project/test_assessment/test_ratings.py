from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from io import StringIO
from threading import Barrier
from types import SimpleNamespace

from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from course_assessment.models import Course, CourseLike, Review, School, Semeseter
from course_assessment.ratings import recalculate_course_ratings
from test_project.common import create_user


class RatingFixtures:
    def setUp(self):
        self.author = create_user(username='rating-author', email='rating-author@example.com')
        self.other = create_user(username='rating-other', email='rating-other@example.com')
        school = School.objects.create(name='Rating school')
        self.semester = Semeseter.objects.create(name='2026-秋')
        self.first = Course.objects.create(name='First', course_code='A', classification='general', school=school)
        self.second = Course.objects.create(name='Second', course_code='B', classification='general', school=school)
        self.empty = Course.objects.create(name='Empty', course_code='C', classification='general', school=school)

    def create_review(self, course, rating, author=None):
        return Review.objects.create(
            course=course, rating=rating, created_by=author or self.author,
            semester=self.semester, content='rating content',
            difficulty=3, grade=3, homework=3, reward=3,
        )

    def assert_scores(self, expected):
        for course, average, normalized in expected:
            course.refresh_from_db()
            self.assertAlmostEqual(course.average_rating, average)
            self.assertAlmostEqual(course.normalized_rating, normalized)


class CourseRatingTests(RatingFixtures, TestCase):
    def test_other_courses_refresh_and_submission_order_does_not_change_scores(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_review(self.first, 5)
        with self.captureOnCommitCallbacks(execute=True):
            self.create_review(self.second, 1)
        self.assert_scores([(self.first, 5, 4), (self.second, 1, 2), (self.empty, 0, 0)])
        with self.captureOnCommitCallbacks(execute=True):
            Review.all_objects.all().delete()
            self.create_review(self.second, 1)
        with self.captureOnCommitCallbacks(execute=True):
            self.create_review(self.first, 5)
        self.assert_scores([(self.first, 5, 4), (self.second, 1, 2)])

    def test_edit_soft_delete_restore_and_hard_delete_update_all_courses(self):
        with self.captureOnCommitCallbacks(execute=True):
            first_review = self.create_review(self.first, 5)
            second_review = self.create_review(self.second, 1)
        with self.captureOnCommitCallbacks(execute=True):
            first_review.rating = 3
            first_review.save()
        self.assert_scores([(self.first, 3, 2.5), (self.second, 1, 1.5)])
        with self.captureOnCommitCallbacks(execute=True):
            first_review.soft_delete()
        self.assert_scores([(self.first, 0, 0), (self.second, 1, 1)])
        with self.captureOnCommitCallbacks(execute=True):
            first_review.restore()
        self.assert_scores([(self.first, 3, 2.5), (self.second, 1, 1.5)])
        with self.captureOnCommitCallbacks(execute=True):
            first_review.delete()
            second_review.delete()
        self.assert_scores([(self.first, 0, 0), (self.second, 0, 0)])

    def test_rolled_back_review_does_not_change_scores(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.create_review(self.first, 5)
                    raise ValueError('rollback')
            except ValueError:
                pass
        self.assert_scores([(self.first, 0, 0), (self.second, 0, 0)])
        self.assertFalse(Review.objects.exists())

    def test_stale_course_instance_in_like_signal_does_not_overwrite_scores(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_review(self.first, 5)
            self.create_review(self.second, 1)
        # The original course object predates the committed global recalculation.
        CourseLike.objects.create(course=self.first, created_by=self.other, like=1)
        self.assert_scores([(self.first, 5, 4), (self.second, 1, 2)])

    def test_backfill_migration_and_command_repair_historical_values(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create_review(self.first, 5)
            self.create_review(self.first, 3, self.other)
            deleted = self.create_review(self.second, 5, self.other)
            deleted.soft_delete()
            self.create_review(self.second, 1)
        expected = [(self.first, 4, 12.5 / 3.5), (self.second, 1, 5.5 / 2.5), (self.empty, 0, 0)]
        Course.objects.update(average_rating=99, normalized_rating=99)
        historical_apps = MigrationExecutor(connection).loader.project_state([
            ('course_assessment', '0031_expand_review_metric_scale'),
        ]).apps
        migration = import_module('course_assessment.migrations.0032_recalculate_course_ratings')
        migration.rebuild_ratings(historical_apps, SimpleNamespace(connection=connection))
        self.assert_scores(expected)
        Course.objects.update(average_rating=-1, normalized_rating=-1)
        call_command('recalculate_course_ratings', stdout=StringIO())
        self.assert_scores(expected)
        self.assertEqual(recalculate_course_ratings(), 0)


class CourseRatingConcurrencyTests(RatingFixtures, TransactionTestCase):
    def test_concurrent_course_reviews_end_with_one_consistent_baseline(self):
        barrier = Barrier(2)

        def write(course_id, rating):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                with transaction.atomic():
                    barrier.wait(timeout=10)
                    self.create_review(Course.objects.get(pk=course_id), rating)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, self.first.pk, 5), pool.submit(write, self.second.pk, 1)]
            for future in futures:
                future.result(timeout=20)
        self.assert_scores([(self.first, 5, 4), (self.second, 1, 2), (self.empty, 0, 0)])
        self.assertEqual(recalculate_course_ratings(), 0)
