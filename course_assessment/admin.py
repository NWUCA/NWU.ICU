from django.contrib import admin

from course_assessment.models import Course, Review, School, Teacher

admin.site.register(School)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'course', 'content', 'rating', 'created_by', 'anonymous')
    # 若 course 不为只读, 会产生和课程数相等的 SQL queries, 因每一课程都会去查相关联的教师表
    readonly_fields = ('course', 'created_by')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'classification', 'get_teachers', 'school', 'created_by')
    search_fields = ('teachers__name', 'name')

    def get_queryset(self, request):
        """To save an extra query"""
        qs = super().get_queryset(request)
        return qs.prefetch_related('teachers')


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    search_fields = ('name',)
