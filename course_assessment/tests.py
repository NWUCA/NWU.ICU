import pytest

from course_assessment.models import Course, ReviewHistory, School, Semeseter, Teacher


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


@pytest.fixture
def make_review():
    def _make_review(content="", rating=3, difficulty=2, grade=2, homework=2, reward=2):
        return {
            "content": content,
            "rating": rating,
            "difficulty": difficulty,
            "grade": grade,
            "homework": homework,
            "reward": reward,
        }

    return _make_review


def test_add_review(logged_in_client, course, make_review):
    logged_in_client.post(
        f'/course/{course.id}/review_add/',
        data=make_review(content="test"),
    )
    # print(r.content)
    assert course.review_set.count() == 1


def test_review_history(logged_in_client, user, course, make_review):
    content = "test"
    logged_in_client.post(
        f'/course/{course.id}/review_add/',
        data=make_review(content=content),
    )
    review = course.review_set.get(created_by=user.id)
    assert review.edited is False

    modified_content = "test2"
    logged_in_client.post(
        f'/course/{course.id}/review_add/',
        data=make_review(content=modified_content),
    )

    review.refresh_from_db()
    assert review.content == modified_content
    assert review.edited is True
    assert ReviewHistory.objects.get(review=review).content == content

    another_content = "test3"
    logged_in_client.post(
        f'/course/{course.id}/review_add/',
        data=make_review(content=another_content),
    )
    assert ReviewHistory.objects.count() == 2


def test_crawl_course_list():
    from course_assessment.management.commands.crawl_course_list import _parse_semester

    assert _parse_semester("2022-春") == ("2021", "12")
    assert _parse_semester("2021-秋") == ("2021", "3")
    assert _parse_semester("2022-秋") == ("2022", "3")
