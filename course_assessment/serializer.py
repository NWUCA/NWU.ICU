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
                  'edited', 'like', 'difficulty', 'grade', 'homework', 'reward', 'source', 'review_history']


class AddReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['course', 'content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']


class DeleteReviewSerializer(serializers.Serializer):
    review_id = serializers.CharField(write_only=True, required=True)
