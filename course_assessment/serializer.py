from rest_framework import serializers

from utils.utils import get_err_msg
from .models import Review, ReviewHistory, ReviewReply, School, Teacher, Course


def school_exist(school):
    if str(school) not in [str(school.id) for school in School.objects.all()]:
        raise serializers.ValidationError({'school': get_err_msg('school_not_exist')})


def classification_exist(classification):
    course_classification_list = [type[0] for type in Course.classification_choices]
    if classification not in course_classification_list:
        raise serializers.ValidationError({'classification': get_err_msg('classification_not_exist')})


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
    review_id = serializers.CharField(required=True)

    def validate(self, data):
        try:
            Review.objects.get(id=data.get('review_id'))
        except Review.DoesNotExist:
            raise serializers.ValidationError({'review': get_err_msg('review_not_exist')})
        return data


class AddReviewReplySerializer(serializers.Serializer):
    content = serializers.CharField(required=True)
    parent_id = serializers.IntegerField(required=True)
    review_id = serializers.IntegerField(required=True)

    def validate(self, data):
        parent_id = data.get('parent_id')
        review_id = data.get('review_id')
        try:
            review = Review.objects.get(id=review_id)
        except Review.DoesNotExist:
            raise serializers.ValidationError({'course': get_err_msg('review_not_exist')})
        if parent_id != 0:
            try:
                review_reply = ReviewReply.objects.get(id=parent_id)
            except ReviewReply.DoesNotExist:
                raise serializers.ValidationError({'reply': get_err_msg('review_not_exist')})
            if review_reply.review_id != review_id:
                raise serializers.ValidationError({'reply': get_err_msg('wrong_parent_id')})

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
        try:
            Review.objects.get(id=data.get('review_id'))
        except Review.DoesNotExist:
            raise serializers.ValidationError({'review': get_err_msg('review_not_exist')})
        return data


class CourseTeacherSearchSerializer(serializers.Serializer):
    teacher_name = serializers.CharField(required=False)
    course_name = serializers.CharField(required=False)
    search_flag = serializers.CharField(required=True)


class AddCourseSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    school = serializers.IntegerField(required=True)
    classification = serializers.CharField(required=True)
    teacher_id = serializers.IntegerField(required=True)

    def validate(self, data):
        try:
            Teacher.objects.get(id=data.get('teacher_id'))
        except Teacher.DoesNotExist:
            raise serializers.ValidationError({'teacher': get_err_msg('teacher_not_exist')})
        school_exist(data.get('school'))
        classification_exist(data.get('classification'))
        try:
            Course.objects.get(name=data.get('name'),
                               school=data.get('school'),
                               classification=data.get('classification'))
        except Course.DoesNotExist:
            return data
        raise serializers.ValidationError({'course': get_err_msg('course_has_exist')})

    def create(self, validated_data):
        created_by = self.context['request'].user
        teacher = Teacher.objects.get(id=validated_data.pop('teacher_id'))
        school = School.objects.get(id=validated_data.pop('school'))
        course = Course.objects.create(created_by=created_by, school=school, **validated_data)
        course.teachers.add(teacher)
        return course


class TeacherSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    page_size = serializers.IntegerField(required=False, default=10)
    current_page = serializers.IntegerField(required=False, default=1)
    type = serializers.CharField(required=True)


class CourseLikeSerializer(serializers.Serializer):
    course_id = serializers.IntegerField(required=True)
    like = serializers.IntegerField(required=True)

    def validate(self, data):
        try:
            course = Course.objects.get(id=data.get('course_id'))
        except Course.DoesNotExist:
            raise serializers.ValidationError({'course': get_err_msg('course_not_exist')})
        if data.get('like') not in [-1, 1]:
            raise serializers.ValidationError({'like': get_err_msg('operation_error')})
        return data


class AddTeacherSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    school = serializers.CharField(required=True)
    avatar_uuid = serializers.CharField(required=False)

    def validate(self, data):
        school_exist(data.get('school'))
        return data
