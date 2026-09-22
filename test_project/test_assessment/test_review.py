from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from unittest.mock import patch

from course_assessment.models import (
    ReviewAndReplyLike,
    ReviewHistory,
    Review,
    ReviewReply,
    Semeseter,
)
from common.models import Notification
from test_project.common import create_user, login_user


@override_settings(DEBUG=True)
class ReviewTests(APITestCase):
    fixtures = ['school_initial_data.json']

    def add_teacher_course(self):
        teacher_name = 'testTeacher'
        teacher_response = self.client.post(reverse('api:add_teacher'), data={'name': teacher_name, 'school': 1})
        teacher_id = teacher_response.data['contents']['teacher_id']
        course_data = {
            "name": "testCourse",
            "school": 1,
            "classification": "general",
            "teacher_id": teacher_id
        }
        course_response = self.client.post(reverse('api:add_course'), data=course_data)
        course_id = course_response.data['contents']['course_id']
        return course_id

    def setUp(self):
        call_command('flush', '--noinput')
        call_command('loaddata', 'school_initial_data.json')
        call_command('update_semester', start_year=2017)
        self.review_list_url = reverse('api:latest_review')
        self.review_url = reverse('api:review')
        self.client = APIClient()
        self.user = create_user(is_active=True)
        login_user(self.client)
        self.user_id = self.user.id
        self.course_id = self.add_teacher_course()

    def test_add_review(self):
        review_data = {
            "course": self.course_id,
            "content": "test_message",
            "rating": 2,
            "anonymous": False,
            "difficulty": 2,
            "grade": 1,
            "homework": 2,
            "reward": 1,
            "semester": 1
        }
        with patch('course_assessment.views.notify_course_review') as notify:
            add_review_response = self.client.post(self.review_url, review_data)
        notify.assert_called_once()
        latest_review_list_response = self.client.get(self.review_list_url)
        course_response = self.client.get(reverse('api:course', args=[self.course_id]))
        self.assertEqual(add_review_response.data['contents']['review_id'],
                         latest_review_list_response.data['contents']['results'][-1]['id'])
        self.assertEqual(latest_review_list_response.data['contents']['results'][-1]['author']['id'], self.user_id)
        self.assertEqual(latest_review_list_response.data['contents']['results'][-1]['author']['uuid'], self.user.uuid)
        self.assertIn('has_avatar', latest_review_list_response.data['contents']['results'][-1]['author'])
        self.assertEqual(
            latest_review_list_response.data['contents']['results'][-1]['like'],
            {'like': 0, 'dislike': 0, 'user_option': 0},
        )
        self.assertEqual(latest_review_list_response.data['contents']['count'], 1)
        self.assertEqual(course_response.data['contents']['reviews']['results'][0]['author']['id'], self.user_id)
        return add_review_response.data['contents']['review_id'], self.course_id

    def test_add_anonymous_review_browse_by_add_user(self):
        review_data = {
            "course": self.course_id,
            "content": "test_message",
            "rating": 2,
            "anonymous": True,
            "difficulty": 2,
            "grade": 1,
            "homework": 2,
            "reward": 1,
            "semester": 1
        }
        add_review_response = self.client.post(self.review_url, review_data)
        latest_review_list_response = self.client.get(self.review_list_url)
        course_response = self.client.get(reverse('api:course', args=[self.course_id]))
        self.assertEqual(add_review_response.data['contents']['review_id'],
                         latest_review_list_response.data['contents']['results'][-1]['id'])
        self.assertEqual(latest_review_list_response.data['contents']['results'][-1]['author']['id'], -1)
        self.assertEqual(latest_review_list_response.data['contents']['results'][-1]['author']['avatar_uuid'],
                         settings.ANONYMOUS_USER_AVATAR_UUID)
        self.assertNotIn('uuid', latest_review_list_response.data['contents']['results'][-1]['author'])
        self.assertNotIn('has_avatar', latest_review_list_response.data['contents']['results'][-1]['author'])
        self.assertEqual(course_response.data['contents']['reviews']['results'][0]['author']['id'], 1)
        self.assertTrue(course_response.data['contents']['reviews']['results'][0]['author']['anonymous'])
        self.assertEqual(latest_review_list_response.data['contents']['count'], 1)

    def test_reply_from_another_user_serializes_notification_avatar_ids(self):
        review_id, _ = self.test_add_review()
        reply_user = create_user(
            username='reply_user',
            email='reply@example.com',
            nickname='reply user',
        )
        reply_client = APIClient()
        reply_client.force_authenticate(user=reply_user)

        with patch('course_assessment.views.notify_course_review_reply') as notify:
            response = reply_client.post(reverse('api:add_reply'), {
                'review_id': review_id,
                'parent_id': 0,
                'content': 'reply from another user',
            })

        self.assertEqual(response.status_code, 201)
        notify.assert_called_once()
        notification = Notification.objects.get(
            dedupe_key=f'reply:{response.data["contents"]["reply_id"]}:{self.user.id}',
        )
        self.assertEqual(notification.payload['created_by']['uuid'], str(reply_user.uuid))
        self.assertEqual(notification.payload['created_by']['avatar'], str(reply_user.avatar_uuid))

    def test_delete_review(self):
        review_id, _ = self.test_add_review()
        delete_review_response = self.client.delete(self.review_url, data={'review_id': review_id})
        self.assertEqual(delete_review_response.data['contents']['review_id'], review_id)
        latest_review_list_response = self.client.get(self.review_list_url)
        with self.assertRaises(ObjectDoesNotExist):
            Review.objects.get(id=review_id)
        self.assertEqual(Review.all_objects.get(id=review_id).is_deleted, True)
        self.assertEqual(latest_review_list_response.data['contents']['count'], 0)

    def test_delete_review_keeps_reply_tree_and_redacts_review(self):
        review_id, _ = self.test_add_review()
        root = ReviewReply.objects.create(
            review_id=review_id,
            created_by=self.user,
            content='valuable root reply',
        )
        child = ReviewReply.objects.create(
            review_id=review_id,
            created_by=self.user,
            parent=root,
            content='valuable nested reply',
        )
        notification = Notification.objects.create(
            recipient=self.user,
            kind=Notification.KIND_REPLY,
            dedupe_key=f'reply:{root.id}:{self.user.id}',
            payload={
                'raw_post': {
                    'id': review_id,
                    'classify': 'review',
                    'content': 'test_message',
                },
            },
        )

        response = self.client.delete(self.review_url, data={'review_id': review_id})

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertEqual(notification.payload['raw_post']['content'], '内容已被删除')
        self.assertEqual(
            list(ReviewReply.objects.filter(review_id=review_id).values_list('id', flat=True)),
            [root.id, child.id],
        )
        course_response = self.client.get(reverse('api:course', args=[self.course_id]))
        reviews = course_response.data['contents']['reviews']['results']
        self.assertEqual(len(reviews), 1)
        self.assertTrue(reviews[0]['is_deleted'])
        self.assertEqual(reviews[0]['content'], '内容已被删除')
        self.assertEqual(reviews[0]['author']['id'], 0)
        self.assertEqual(reviews[0]['author']['nickname'], '已删除用户')
        self.assertEqual(
            [reply['content'] for reply in reviews[0]['reply']],
            ['valuable root reply', 'valuable nested reply'],
        )

        top_level_response = self.client.post(reverse('api:add_reply'), {
            'review_id': review_id,
            'parent_id': 0,
            'content': 'new top-level reply',
        })
        nested_response = self.client.post(reverse('api:add_reply'), {
            'review_id': review_id,
            'parent_id': child.id,
            'content': 'continue valuable discussion',
        })
        self.assertEqual(top_level_response.status_code, 400)
        self.assertEqual(nested_response.status_code, 201)

        like_response = self.client.post(reverse('api:review_like'), {
            'review_id': review_id,
            'reply_id': root.id,
            'like_or_dislike': 1,
        })
        self.assertEqual(like_response.status_code, 200)

    def test_edit_review(self):
        review_id, course_id = self.test_add_review()
        review = Review.objects.get(id=review_id)
        old_review_content = review.content
        edit_review_data = {
            "course": course_id,
            "content": "test_message_edit",
            "rating": 3,
            "anonymous": False,
            "difficulty": 3,
            "grade": 2,
            "homework": 3,
            "reward": 2,
            "semester": 1
        }
        edit_review_response = self.client.put(self.review_url, edit_review_data)
        self.assertEqual(edit_review_response.data['contents']['review_id'], review_id)
        review.refresh_from_db()
        self.assertNotEqual(review.content, old_review_content)
        review_history = ReviewHistory.objects.get(review=review)
        self.assertEqual(review_history.content, old_review_content)
        self.assertEqual(review.content, edit_review_data['content'])
        self.assertEqual(review.rating, edit_review_data['rating'])
        self.assertEqual(review.difficulty, edit_review_data['difficulty'])
        self.assertEqual(review.grade, edit_review_data['grade'])
        self.assertEqual(review.homework, edit_review_data['homework'])
        self.assertEqual(review.reward, edit_review_data['reward'])
        self.assertEqual(review.semester_id, edit_review_data['semester'])
        self.assertEqual(review.anonymous, edit_review_data['anonymous'])

    def test_identical_edit_does_not_change_modify_time_or_history(self):
        review_id, course_id = self.test_add_review()
        review = Review.objects.get(id=review_id)
        original_modify_time = review.modify_time
        identical_data = {
            'course': course_id,
            'content': review.content,
            'rating': review.rating,
            'anonymous': review.anonymous,
            'difficulty': review.difficulty,
            'grade': review.grade,
            'homework': review.homework,
            'reward': review.reward,
            'semester': review.semester_id,
        }

        response = self.client.put(self.review_url, identical_data)

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.modify_time, original_modify_time)
        self.assertFalse(review.edited)
        self.assertFalse(ReviewHistory.objects.filter(review=review).exists())

    def test_review_content_limits_are_enforced(self):
        review_data = {
            'course': self.course_id,
            'content': 'x' * 10_001,
            'rating': 3,
            'anonymous': False,
            'difficulty': 3,
            'grade': 3,
            'homework': 3,
            'reward': 3,
            'semester': 1,
        }
        response = self.client.post(self.review_url, review_data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['field'], 'content')

        review_data['content'] = 'valid'
        review_id = self.client.post(self.review_url, review_data).data['contents']['review_id']
        reply_response = self.client.post(reverse('api:add_reply'), {
            'review_id': review_id,
            'parent_id': 0,
            'content': 'x' * 2_001,
        })
        self.assertEqual(reply_response.status_code, 400)
        self.assertEqual(reply_response.data['errors'][0]['field'], 'content')

    def test_course_reviews_are_paginated_and_include_own_review_summary(self):
        own_review_id, _ = self.test_add_review()
        semester = Semeseter.objects.get(id=1)
        for index in range(11):
            author = create_user(
                is_active=True,
                username=f'pagination_user_{index}',
                email=f'pagination_{index}@example.com',
            )
            Review.objects.create(
                course_id=self.course_id,
                content=f'review {index}',
                created_by=author,
                rating=index % 5 + 1,
                anonymous=False,
                difficulty=3,
                grade=3,
                homework=3,
                reward=3,
                semester=semester,
                like_count=index,
            )

        response = self.client.get(
            reverse('api:course', args=[self.course_id]),
            {'page': 1, 'pageSize': 10, 'sort': 'liked'},
        )
        reviews = response.data['contents']['reviews']
        self.assertEqual(reviews['count'], 12)
        self.assertEqual(reviews['max_page'], 2)
        self.assertEqual(len(reviews['results']), 10)
        self.assertEqual(reviews['results'][0]['like']['like'], 10)
        self.assertEqual(response.data['contents']['request_user_review']['id'], own_review_id)

    def test_replies_are_returned_in_cursor_batches(self):
        review_id, _ = self.test_add_review()
        ReviewReply.objects.bulk_create([
            ReviewReply(
                review_id=review_id,
                created_by=self.user,
                content=f'reply {index}',
            )
            for index in range(25)
        ])

        course_response = self.client.get(reverse('api:course', args=[self.course_id]))
        review = course_response.data['contents']['reviews']['results'][0]
        self.assertEqual(review['reply_count'], 25)
        self.assertEqual(len(review['reply']), 20)
        self.assertIsNotNone(review['reply_next_cursor'])

        next_response = self.client.get(
            reverse('api:reply', args=[review_id]),
            {'after': review['reply_next_cursor']},
        )
        self.assertEqual(len(next_response.data['contents']['results']), 5)
        self.assertIsNone(next_response.data['contents']['next_cursor'])

    def test_my_review(self):
        self.test_edit_review()
        my_review_response = self.client.get(reverse('api:user_review', args=[self.user_id]))
        self.assertEqual(my_review_response.data['contents']['count'], 1)
        my_review = my_review_response.data['contents']['results'][-1]
        self.assertEqual(my_review['content']['current_content'], 'test_message_edit')
        self.assertEqual(len(my_review['content']['content_history']), 1)
        self.assertEqual(my_review['content']['content_history'][-1], 'test_message')
        self.assertEqual(my_review['rating']['rating'], 3)
        self.assertEqual(my_review['rating']['difficulty'], 3)
        self.assertEqual(my_review['rating']['grade'], 2)
        self.assertEqual(my_review['rating']['homework'], 3)
        self.assertEqual(my_review['rating']['reward'], 2)
        self.assertEqual(my_review['semester'], str(Semeseter.objects.get(id=1)))
        self.assertEqual(my_review['anonymous'], False)
        self.assertEqual(my_review['course']['id'], self.course_id)
        self.assertEqual(my_review['course']['name'], 'testCourse')
        self.assertEqual(my_review['teachers'][-1]['id'], 1)
        self.assertEqual(my_review['teachers'][-1]['name'], 'testTeacher')

    def test_review_like_dislike(self):
        clientB = APIClient()
        userB = create_user(is_active=True, username='test_userB', email='testB@example.com')
        login_user(clientB, user_info_dict={'username': 'test_userB', 'password': 'test_password'})

        review_id, _ = self.test_add_review()
        original_modify_time = Review.objects.get(id=review_id).modify_time
        like_response = clientB.post(reverse('api:review_like'),
                                     data={'review_id': review_id, 'reply_id': 0, 'like_or_dislike': 1})
        self.assertEqual(like_response.status_code, 200)
        review = Review.objects.get(id=review_id)
        self.assertEqual(review.like_count, 1)
        self.assertEqual(review.dislike_count, 0)
        self.assertEqual(review.modify_time, original_modify_time)

        repeal_like_response = clientB.post(reverse('api:review_like'),
                                            data={'review_id': review_id, 'reply_id': 0, 'like_or_dislike': 1})
        self.assertEqual(repeal_like_response.status_code, 200)
        review = Review.objects.get(id=review_id)
        self.assertEqual(review.like_count, 0)
        self.assertEqual(review.dislike_count, 0)

        clientB.post(reverse('api:review_like'),
                     data={'review_id': review_id, 'reply_id': 0, 'like_or_dislike': 1})
        timeline_response = clientB.get(self.review_list_url)
        timeline_like = timeline_response.data['contents']['results'][0]['like']
        self.assertEqual(timeline_like, {'like': 1, 'dislike': 0, 'user_option': 1})

        clientB.post(reverse('api:review_like'),
                     data={'review_id': review_id, 'reply_id': 0, 'like_or_dislike': -1})
        review.refresh_from_db()
        self.assertEqual(review.like_count, 0)
        self.assertEqual(review.dislike_count, 1)

        user_A_review_response = self.client.get(reverse('api:user_review', args=[self.user_id]))
        self.assertEqual(user_A_review_response.data['contents']['results'][0]['like']['like'], 0)
        self.assertEqual(user_A_review_response.data['contents']['results'][0]['like']['dislike'], 1)

        user_A_unread_message_response = self.client.get(reverse('api:unread_message'))
        self.assertEqual(user_A_unread_message_response.data['contents']['unread']['like'], 1)

        user_A_like_notice_response = self.client.get(reverse('api:check_all_message', args=['like']))
        self.assertEqual(user_A_like_notice_response.data['contents']['count'], 1)
        self.assertEqual(user_A_like_notice_response.data['contents']['results'][0]['like']['like'], 0)
        self.assertEqual(user_A_like_notice_response.data['contents']['results'][0]['like']['dislike'], 1)

        notification_id = user_A_like_notice_response.data['contents']['results'][0]['id']
        self.client.post(reverse('api:read_notifications'), {'ids': [notification_id]}, format='json')

        user_A_unread_message_response = self.client.get(reverse('api:unread_message'))
        self.assertEqual(user_A_unread_message_response.data['contents']['unread']['like'], 0)

    def test_switching_like_to_dislike_keeps_one_row_and_modify_time(self):
        second_client = APIClient()
        second_user = create_user(
            is_active=True, username='test_userB', email='testB@example.com'
        )
        login_user(
            second_client,
            user_info_dict={'username': 'test_userB', 'password': 'test_password'},
        )
        review_id, _ = self.test_add_review()
        original_modify_time = Review.objects.get(id=review_id).modify_time
        like_url = reverse('api:review_like')

        second_client.post(
            like_url,
            {'review_id': review_id, 'reply_id': 0, 'like_or_dislike': 1},
        )
        response = second_client.post(
            like_url,
            {'review_id': review_id, 'reply_id': 0, 'like_or_dislike': -1},
        )

        self.assertEqual(response.status_code, 200)
        review = Review.objects.get(id=review_id)
        self.assertEqual(review.like_count, 0)
        self.assertEqual(review.dislike_count, 1)
        self.assertEqual(review.modify_time, original_modify_time)
        likes = ReviewAndReplyLike.objects.filter(
            review_id=review_id, created_by=second_user, review_reply=None
        )
        self.assertEqual(likes.count(), 1)
        self.assertEqual(likes.get().like, -1)

    def test_review_like_database_constraints_reject_duplicates_and_invalid_values(self):
        review_id, _ = self.test_add_review()
        review = Review.objects.get(id=review_id)
        second_user = create_user(
            is_active=True, username='test_userB', email='testB@example.com'
        )
        ReviewAndReplyLike.objects.create(
            review=review, created_by=second_user, like=1
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewAndReplyLike.objects.create(
                review=review, created_by=second_user, like=-1
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewAndReplyLike.objects.create(
                review=review,
                created_by=create_user(
                    is_active=True,
                    username='test_userC',
                    email='testC@example.com',
                ),
                like=0,
            )

    def test_reply_cannot_be_liked_through_another_review(self):
        first_review_id, course_id = self.test_add_review()
        second_client = APIClient()
        create_user(is_active=True, username='test_userB', email='testB@example.com')
        login_user(second_client, user_info_dict={'username': 'test_userB', 'password': 'test_password'})
        review_data = {
            'course': course_id,
            'content': 'second review',
            'rating': 4,
            'anonymous': False,
            'difficulty': 2,
            'grade': 2,
            'homework': 2,
            'reward': 2,
            'semester': 1,
        }
        second_review_id = second_client.post(self.review_url, review_data).data['contents']['review_id']
        reply_response = second_client.post(reverse('api:add_reply'), {
            'review_id': second_review_id,
            'parent_id': 0,
            'content': 'reply on second review',
        })
        reply_id = reply_response.data['contents']['reply_id']

        response = second_client.post(reverse('api:review_like'), {
            'review_id': first_review_id,
            'reply_id': reply_id,
            'like_or_dislike': 1,
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReviewAndReplyLike.objects.filter(created_by__username='test_userB').exists())
        first_review = Review.objects.get(id=first_review_id)
        self.assertEqual(first_review.like_count, 0)
        self.assertEqual(first_review.dislike_count, 0)
