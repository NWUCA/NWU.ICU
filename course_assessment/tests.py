import pytest

from course_assessment.models import Course, School, Semeseter, Teacher


@pytest.fixture
def course():
    semester = Semeseter.objects.create(name="semester")
    school = School.objects.create(name='school')
    teacher = Teacher.objects.create(name='teacher', school=school)

    c = Course.objects.create(
        course_id='course_id',
        name='course',
        classification=Course.classification_choices[0],
        school=school,
    )
    c.semester.add(semester)
    c.teachers.add(teacher)
    c.save()
    return c


def test_add_review(logged_in_client, course):
    logged_in_client.post(
        f'/course/{course.id}/review_add/',
        data={
            'content': 'content',
            'rating': 3,
            'difficulty': 2,
            'grade': 1,
            'homework': 3,
            'reward': 3,
        },
    )
    # print(r.content)
    assert course.review_set.count() == 1


def test_crawl_course_list():
    from course_assessment.management.commands.crawl_course_list import _parse_semester

    assert _parse_semester("2022-春") == ("2021", "12")
    assert _parse_semester("2021-秋") == ("2021", "3")
    assert _parse_semester("2022-秋") == ("2022", "3")
