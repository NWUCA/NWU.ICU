from rest_framework import serializers

from .models import Review, ReviewHistory


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


class DeleteReviewSerializer(serializers.Serializer):
    review_id = serializers.CharField(write_only=True, required=True)


class AddReviewReplySerializer(serializers.Serializer):
    content = serializers.CharField(write_only=True, required=True)


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
