from rest_framework import serializers

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
        if data.get('rating') > 5 or data.get('rating') < 0:
            raise serializers.ValidationError({'rating': "评分必须是0-5之间的整数"})
        return data


class DeleteReviewSerializer(serializers.Serializer):
    review_id = serializers.CharField(write_only=True, required=True)


class AddReviewReplySerializer(serializers.Serializer):
    content = serializers.CharField(write_only=True, required=True)
    parent_id = serializers.IntegerField(write_only=True, required=True)

    def validate(self, data):
        parent_id = data.get('parent_id')
        if parent_id != 0:
            try:
                ReviewReply.objects.get(id=parent_id)
            except ReviewReply.DoesNotExist:
                raise serializers.ValidationError({'reply': 'reply parent does not exist'})
        return data


class DeleteReviewReplySerializer(serializers.Serializer):
    reply_id = serializers.IntegerField(write_only=True, required=True)


class ReviewAndReplyLikeSerializer(serializers.Serializer):
    review_id = serializers.IntegerField(write_only=True, required=True)
    reply_id = serializers.IntegerField(write_only=True, required=True)
    like_or_dislike = serializers.IntegerField(write_only=True, required=True)


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
                raise serializers.ValidationError({"teacher_id": "Teacher ID is required when teacher_exist is True."})
        else:
            if not data.get('teacher_name'):
                raise serializers.ValidationError(
                    {"teacher_name": "Teacher name is required when teacher_exist is False."})
            if not data.get('teacher_school'):
                raise serializers.ValidationError(
                    {"teacher_school": "Teacher school is required when teacher_exist is False."})

        return data


class TeacherSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    page_size = serializers.IntegerField(required=False, default=10)
    current_page = serializers.IntegerField(required=False, default=1)


class CourseLikeSerializer(serializers.Serializer):
    course_id = serializers.IntegerField(required=True)
    like = serializers.IntegerField(required=True)
