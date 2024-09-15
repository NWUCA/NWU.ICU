from rest_framework import serializers

from common.utils import get_err_msg
from .models import Review, ReviewHistory, ReviewReply


class ReviewHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewHistory
        fields = ['id', 'content', 'create_time']


class MyReviewSerializer(serializers.ModelSerializer):
    review_history = ReviewHistorySerializer(many=True, read_only=True, source='reviewhistory_set')

    class Meta:
        model = Review
        fields = ['id', 'course', 'content', 'rating', 'created_by', 'anonymous', 'create_time', 'modify_time',
                  'edited', 'like_count', 'dislike_count', 'difficulty', 'grade', 'homework', 'reward', 'source',
                  'review_history']


class AddReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['course', 'content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward', 'semester']

    def validate(self, data):
        fields = {
            'rating': (0, 5),
            'difficulty': (0, 3),
            'grade': (0, 3),
            'homework': (0, 3)
        }
        for field, (min_val, max_val) in fields.items():
            value = data.get(field)
            if value is not None and (value < min_val or value > max_val):
                raise serializers.ValidationError({'rating': get_err_msg('rating_out_range')})
        return data


class DeleteReviewSerializer(serializers.Serializer):
    review_id = serializers.CharField(write_only=True, required=True)


class AddReviewReplySerializer(serializers.Serializer):
    content = serializers.CharField(required=True)
    parent_id = serializers.IntegerField(required=True)
    review_id = serializers.IntegerField(required=True)

    def validate(self, data):
        parent_id = data.get('parent_id')
        if parent_id != 0:
            try:
                ReviewReply.objects.get(id=parent_id)
            except ReviewReply.DoesNotExist:
                raise serializers.ValidationError({'reply': get_err_msg('review_not_exist')})
        return data


class DeleteReviewReplySerializer(serializers.Serializer):
    review_id = serializers.IntegerField(required=True)
    reply_id = serializers.IntegerField(required=True)


class ReviewAndReplyLikeSerializer(serializers.Serializer):
    review_id = serializers.IntegerField(write_only=True, required=True)
    reply_id = serializers.IntegerField(write_only=True, required=True)
    like_or_dislike = serializers.IntegerField(write_only=True, required=True)

    def validate(self, data):
        if data.get('like_or_dislike') not in [-1, 1]:
            raise serializers.ValidationError({'like_or_dislike': get_err_msg('operation_error')})
        return data


class CourseTeacherSearchSerializer(serializers.Serializer):
    teacher_name = serializers.CharField(required=False)
    course_name = serializers.CharField(required=False)
    search_flag = serializers.CharField(required=True)


class AddCourseSerializer(serializers.Serializer):
    course_name = serializers.CharField(required=True)
    teacher_exist = serializers.BooleanField(required=True)

    teacher_id = serializers.IntegerField(required=False)
    teacher_name = serializers.CharField(required=False)
    teacher_school = serializers.IntegerField(required=False)

    school_name = serializers.CharField(required=True)
    course_page = serializers.CharField(required=False)

    def validate(self, data):
        teacher_exist = data.get('teacher_exist')

        if teacher_exist:
            if not data.get('teacher_id'):
                raise serializers.ValidationError(
                    {'teacher_id': get_err_msg('teacher_id_when_exist')})
        else:
            if not data.get('teacher_name'):
                raise serializers.ValidationError(
                    {'teacher_name': get_err_msg('teacher_name_when_not_exist')})
            if not data.get('teacher_school'):
                raise serializers.ValidationError(
                    {'teacher_school': get_err_msg('teacher_school_when_not_exist')})

        return data


class TeacherSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    page_size = serializers.IntegerField(required=False, default=10)
    current_page = serializers.IntegerField(required=False, default=1)


class CourseLikeSerializer(serializers.Serializer):
    course_id = serializers.IntegerField(required=True)
    like = serializers.IntegerField(required=True)

    def validate(self, data):
        if data.get('like') not in [-1, 1]:
            raise serializers.ValidationError({'like': get_err_msg('operation_error')})
        return data
