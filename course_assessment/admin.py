from django.contrib import admin

from course_assessment.models import Course, Review, School, Teacher

admin.site.register(School)
admin.site.register(Course)
admin.site.register(Teacher)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'course', 'content', 'rating', 'created_by', 'anonymous')
