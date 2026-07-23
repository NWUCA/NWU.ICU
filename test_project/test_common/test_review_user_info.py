from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from utils.utils import userUtils


class ReviewUserInfoTests(SimpleTestCase):
    def make_review(self, verified):
        return SimpleNamespace(
            anonymous=False,
            created_by=SimpleNamespace(
                id=2,
                nickname='test user',
                avatar_uuid='avatar',
                college_email=(
                    f'test@{settings.UNIVERSITY_STUDENT_MAIL_SUFFIX}'
                ),
                college_email_verified=verified,
            ),
        )

    def test_unverified_college_email_is_not_shown_as_student(self):
        user_info = userUtils.get_user_info_in_review(
            self.make_review(verified=False)
        )

        self.assertFalse(user_info['is_student'])

    def test_verified_college_email_is_shown_as_student(self):
        user_info = userUtils.get_user_info_in_review(
            self.make_review(verified=True)
        )

        self.assertTrue(user_info['is_student'])

    def test_anonymous_review_does_not_expose_student_status(self):
        review = self.make_review(verified=True)
        review.anonymous = True

        user_info = userUtils.get_user_info_in_review(review)

        self.assertFalse(user_info['is_student'])
