import json

import requests
from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.db.models import Q
from django.shortcuts import render
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from course_assessment.managers import SearchModuleErrorException
from course_assessment.models import Course, Review, Teacher
from settings import settings
from user.models import User
from utils.custom_pagination import StandardResultsSetPagination
from utils.throttle import CaptchaAnonRateThrottle, CaptchaUserRateThrottle
from utils.utils import return_response, get_err_msg, userUtils
from .models import Bulletin, About, Chat, ChatMessage, ChatLike, ChatReply
from .serializers import CaptchaSerializer, ChatMessageSerializer, ChatMessageGetSerializer, SearchSerializer


class CaptchaView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [CaptchaAnonRateThrottle, CaptchaUserRateThrottle]

    def get(self, request):
        new_key = CaptchaStore.generate_key()
        image_url = captcha_image_url(new_key)
        return return_response(contents={"key": new_key, "image_url": image_url})

    def post(self, request):
        serializer = CaptchaSerializer(data=request.data)
        if serializer.is_valid():
            return return_response(message="Captcha validated successfully!")
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class BulletinListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        bulletins = Bulletin.objects.filter(enabled=True).order_by('-update_time')

        bulletin_list = []
        for bulletin in bulletins:
            bulletin_list.append({
                "title": bulletin.title,
                "content": bulletin.content,
                "publisher": {"nickname": bulletin.publisher.nickname, 'id': bulletin.publisher.id,
                              'avatar': bulletin.publisher.avatar_uuid},
                "create_time": bulletin.create_time,
                "update_time": bulletin.update_time,
            })
        return return_response(contents={"bulletin_list": bulletin_list})


def index(request):
    return render(request, 'index.html')


class TosView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tos_content_database = About.objects.order_by('-update_time').get(type="tos")
        except About.DoesNotExist:
            return return_response(contents={"tos": ""})
        return return_response(contents={"tos": tos_content_database.content})


class AboutView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tos_content_database = About.objects.order_by('-update_time').get(type="about")
        except About.DoesNotExist:
            return return_response(contents={"about": ""})
        return return_response(contents={"about": tos_content_database.content})


class MessageBoxView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_user_message_list(self, request, classify):
        chats = Chat.objects.filter((Q(receiver=request.user) | Q(sender=request.user)) & Q(classify=classify)) \
            .select_related('sender', 'receiver') \
            .order_by('-last_message_datetime')
        chats_page = self.paginate_queryset(chats)
        chat_list = []
        for chat in chats_page:
            chatter = chat.sender if chat.receiver == request.user else chat.receiver
            temp_dict = {
                'chatter': {'id': chatter.id, 'nickname': chatter.nickname, 'avatar': chatter.avatar_uuid},
                'last_message': {'id': chat.last_message_id, 'content': chat.last_message_content,
                                 'datetime': chat.last_message_datetime},
                'unread_count': chat.sender_unread_count if chat.sender == request.user else chat.receiver_unread_count,
            }
            chat_list.append(temp_dict)
        return self.get_paginated_response(chat_list)

    def get_particular_user_message(self, request, chat_object: Chat, last_message_id, order='before'):
        if order not in ['before', 'after']:
            order = 'before'
        if last_message_id is None or last_message_id == '':
            chat_message = ChatMessage.objects.filter(
                chat_item=chat_object).order_by('-create_time')
        else:
            if order == 'before':
                chat_message = ChatMessage.objects.filter(chat_item=chat_object, id__lt=last_message_id).order_by(
                    '-create_time')
            else:
                chat_message = ChatMessage.objects.filter(chat_item=chat_object, id__gt=last_message_id).order_by(
                    '-create_time')
        message_page = self.paginate_queryset(chat_message)
        unread_message_list = [
            message for message in message_page if message.created_by != request.user]
        ChatMessage.objects.filter(
            id__in=[message.id for message in unread_message_list]).update(read=True)
        if chat_object.sender == request.user:
            chat_object.receiver_unread_count = ChatMessage.objects.filter(chat_item=chat_object, read=False,
                                                                           created_by=chat_object.sender).count()
        else:
            chat_object.sender_unread_count = ChatMessage.objects.filter(chat_item=chat_object, read=False,
                                                                         created_by=chat_object.receiver).count()
        chat_object.save()
        message_list = []
        for message in message_page:
            message_list.append({
                'id': message.id,
                'chatter': {'id': message.created_by.id, 'nickname': message.created_by.nickname,
                            'avatar': message.created_by.avatar_uuid},
                'content': message.content,
                'datetime': message.create_time,
            })
        return self.get_paginated_response(message_list)

    def get_like_notice(self, request):
        like_notices = ChatLike.objects.filter(receiver=request.user).select_related('raw_post_course')
        notice_page = self.paginate_queryset(like_notices)
        notice_list = []
        for notice in notice_page:
            notice_list.append({
                'id': notice.id,
                'raw_info': {
                    'raw_post': {'classify': notice.raw_post_classify,
                                 'id': notice.raw_post_id,
                                 'content': notice.raw_post_content, },
                    'course': {'id': notice.raw_post_course_id,
                               'name': notice.raw_post_course.name},
                },
                'like': {
                    'like': notice.like_count,
                    'dislike': notice.dislike_count,
                },
                'datetime': notice.latest_like_datetime,
            })
            notice.read = True
            notice.save()
        return self.get_paginated_response(notice_list)

    def get_reply_notice(self, request):
        reply_notices = ChatReply.objects.filter(receiver=request.user).select_related('reply_content',
                                                                                       'raw_post_course',
                                                                                       'reply_content__created_by')
        notice_page = self.paginate_queryset(reply_notices)
        notice_list = []
        for notice in notice_page:
            if notice.reply_content.created_by != request.user:
                notice_list.append({
                    'id': notice.id,
                    'reply': {
                        'id': notice.reply_content.id,
                        'content': notice.reply_content.content,
                    },
                    'created_by': {
                        'id': notice.reply_content.created_by.id,
                        'nickname': notice.reply_content.created_by.nickname,
                        'avatar': notice.reply_content.created_by.avatar_uuid,
                    },
                    'course': {
                        'id': notice.raw_post_course_id,
                        'name': notice.raw_post_course.name
                    },
                    'raw_post': {
                        'id': notice.raw_post_id,
                        'classify': notice.raw_post_classify,
                        'content': notice.raw_post_content,
                    },
                    'datetime': notice.reply_content.create_time,
                })
        return self.get_paginated_response(notice_list)

    def get(self, request, classify, chatter_id=None):
        serializer = ChatMessageGetSerializer(data={'classify': classify})
        if serializer.is_valid():
            if chatter_id is None:
                if classify == 'user':
                    return self.get_user_message_list(request, classify)
                elif classify == 'like':
                    return self.get_like_notice(request)
                elif classify == 'reply':
                    return self.get_reply_notice(request)

            else:
                try:
                    chat = Chat.get_chat_object(sender=request.user, receiver=User.objects.get(id=chatter_id))
                except Chat.DoesNotExist:
                    return return_response(errors={'chat': get_err_msg('chat_not_exist')},
                                           status_code=status.HTTP_400_BAD_REQUEST)
                last_message_id = request.query_params.get('last_message_id', None)
                order = request.query_params.get('order', None)
                return self.get_particular_user_message(request, chat, last_message_id, order)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def post(self, request):
        serializer = ChatMessageSerializer(data=request.data)
        if serializer.is_valid():
            try:
                receiver = User.objects.get(id=serializer.validated_data['receiver'])
            except User.DoesNotExist:
                return return_response(errors={'user': get_err_msg('user_not_exist')},
                                       status_code=status.HTTP_400_BAD_REQUEST)
            if receiver == request.user:
                return return_response(errors={'user': get_err_msg('cannot_send_message_to_self')},
                                       status_code=status.HTTP_400_BAD_REQUEST)
            chat, created = Chat.get_or_create_chat(sender=request.user, receiver=receiver,
                                                    classify=serializer.validated_data['classify'])
            chat_message = ChatMessage.objects.create(
                content=serializer.validated_data['content'],
                chat_item=chat,
                created_by=request.user,
            )
            return return_response(contents={'message': chat_message.id}, status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class MessageUnreadView(APIView):

    def get(self, request):
        unread_counts = {}
        for i in Chat.classify_MESSAGE:
            unread_counts[i[0]] = 0
        for chat in Chat.objects.filter(sender=request.user):
            unread_counts[chat.classify] += chat.sender_unread_count
        for chat in Chat.objects.filter(receiver=request.user):
            unread_counts[chat.classify] += chat.receiver_unread_count
        return return_response(contents={'unread': unread_counts, 'total': sum(unread_counts.values())})


class CourseTeacherSearchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SearchSerializer(data=request.data)

        def course_search(search_keyword):
            courses = Course.objects.search(search_keyword, page_size=page_size,
                                            current_page=current_page,
                                            prefetch_related_fields=['semester', 'teachers'])
            search_result_list = [{'id': course.id, 'name': course.name, 'teacher': course.get_teachers(),
                                   'classification': course.get_classification(),
                                   'school': course.school.get_name(), 'semester': course.get_semester(),
                                   'rating': {
                                       'average_rating': course.average_rating,
                                       'normalized_rating': course.normalized_rating},
                                   'like': {
                                       'like': course.like_count,
                                       'dislike': course.dislike_count
                                   },
                                   'review_count': course.review_count,
                                   'latest_review_time': course.last_review_time} for course in
                                  courses['results']]
            page_info = {k: v for k, v in courses.items() if k != 'results'}
            return page_info, search_result_list

        def review_search(search_keyword):
            try:
                reviews = Review.objects.search(search_keyword, page_size=page_size,
                                                select_related_fields=['course', 'semester', 'created_by'])
            except SearchModuleErrorException:
                return return_response(errors={'module': get_err_msg('invalid_search_type')}, )
            search_result_list = [{'id': review.id,
                                   'course': {'id': review.course.id, 'name': review.course.get_name(), },
                                   'content': review.content,
                                   'rating': review.rating,
                                   'created_by': userUtils.get_user_info_in_review(review),
                                   'modify_time': review.modify_time,
                                   'like': {
                                       'like': review.like_count,
                                       'dislike': review.dislike_count,
                                   },
                                   'semester': review.semester.name,
                                   } for review in reviews['results']]
            page_info = {k: v for k, v in reviews.items() if k != 'results'}
            return page_info, search_result_list

        def teacher_search(search_keyword):
            teachers = Teacher.objects.search(search_keyword, page_size=page_size,
                                              current_page=current_page, select_related_fields=['school'])
            search_result_list = [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.get_name(),
                                   'avatar_uuid': teacher.avatar_uuid} for
                                  teacher in teachers['results']]
            page_info = {k: v for k, v in teachers.items() if k != 'results'}
            return page_info, search_result_list

        def resources_search(keyword, scope=0):
            base_url = settings.RESOURCES_WEBSITE_URL
            json_data = {
                'parent': '/',
                'keywords': keyword,
                'scope': scope,
                'page': current_page,
                'per_page': page_size,
                'password': '',
            }
            response = requests.post(base_url + '/api/fs/search', json=json_data)
            search_result_json = json.loads(response.text)
            if search_result_json['code'] != 200:
                return []
            file_list = []
            total = search_result_json['data']['total']
            for file in search_result_json['data']['content']:
                file_list.append({
                    'name': file['name'],
                    'size': file['size'],
                    'path': file['parent'],
                    'type': 'dir' if file['is_dir'] else 'file',
                    'url': base_url + file['parent']
                })
            page_info = {
                'total_pages': total // page_size + (0 if total % page_size == 0 else 1),
                'current_page': current_page,
                'has_next': total > current_page * page_size,
                'has_previous': current_page > 1,
                'total_count': total
            }
            return page_info, file_list

        if serializer.is_valid():
            search_type = serializer.validated_data['type']
            page_size = serializer.validated_data['page_size']
            current_page = serializer.validated_data['current_page']
            search_keyword = serializer.validated_data['keyword']
            if search_type == 'teacher':
                page_info, search_result_list = teacher_search(search_keyword)
            elif search_type == 'course':
                page_info, search_result_list = course_search(search_keyword)
            elif search_type == 'review':
                page_info, search_result_list = review_search(search_keyword)
            elif search_type == 'resource':
                page_info, search_result_list = resources_search(search_keyword)
            else:
                return return_response(errors=get_err_msg('invalid_type_field'),
                                       status_code=status.HTTP_400_BAD_REQUEST)
            return return_response(contents={'search_result': search_result_list, **page_info})
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
