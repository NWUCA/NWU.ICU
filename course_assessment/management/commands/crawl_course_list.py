import logging
from enum import Enum, auto

import requests
from django.core.management.base import BaseCommand

from course_assessment.models import Course, School, Semeseter, Teacher

logger = logging.getLogger(__name__)


class Code(Enum):
    SUCCESS = auto()
    SKIPPING = auto()
    FAILURE = auto()


class Command(BaseCommand):
    help = '爬取全校课表'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--cookies', nargs=1, help="cookies for jwxt")
        parser.add_argument('--migrate_old', action='store_true')
        parser.add_argument('--show', action='store_true')

    def process_course(self, course: dict[str, str]):
        try:
            semester, _ = Semeseter.objects.get_or_create(name="2022-春")
            try:
                school = School.objects.get(name__contains=course.get('kkxy', '未知'))
            except School.DoesNotExist:
                school = School.objects.create(name=course['kkxy'])
                logger.warning(f"添加新学院 {course['kkxy']}")

            teacher_str_list = course['rkjs'].split(';')
            teacher_obj_list = set(
                Teacher.objects.get_or_create(name=t, school=school)[0] for t in teacher_str_list
            )

            # 忽略已经爬取过的课程
            # 这是因为一门课程可能有多个教学班
            courses = Course.objects.filter(name=course['kcmc'])
            for c in courses:
                # logger.info(list(c.teacher.all()))
                # logger.info(teacher_obj_list)
                if set(c.teachers.all()) == teacher_obj_list:
                    logger.info(f"Skipping {c}")
                    return Code.SKIPPING

            classification = ""
            # logger.info(f"Parsing teacher {teacher_obj_list}")
            for c, name in Course.classification_choices:
                if name in course['kcxz']:
                    classification = c
            if not classification:
                logger.warning("未知的课程分类")
            c = Course.objects.create(
                course_id=course['kch'],
                name=course['kcmc'],
                classification=classification,
                school=school,
            )
            c.semester.add(semester)
            c.teachers.set(teacher_obj_list)
            c.save()
            logger.info(f"Created course {c}")
            return Code.SUCCESS
        except KeyError as e:
            logger.warning(f"Some key not found: {e}")
            logger.warning(f"Raw data: {course}")
            return Code.FAILURE

    def migrate_old_course(self, show=False):
        old_courses = Course.objects.filter(created_by__isnull=False)
        for course in old_courses:
            candidates = Course.objects.filter(
                name__contains=course.name[:3], teachers__name__contains=course.teachers.all()[0]
            ).exclude(id=course.id)
            if candidates:
                if show:
                    logger.info(course, "->", candidates)
                else:
                    logger.info(f"Migrating to {course}")
                    logger.info("Choose one course from: (default is 0, type any character to skip)")
                    for index, candidate in enumerate(candidates):
                        logger.info(f"{index}) {candidate}")
                    num = input()
                    try:
                        num = int(num) if num else 0
                    except ValueError:
                        continue
                    for review in course.review_set.all():
                        review.course = candidates[num]
                        review.save()
                    course.delete()
                    logger.info(f"{course} deleted")

    def crawl(self, cookies: dict[str, str]):
        url = (
            'https://jwgl.nwu.edu.cn/jwglxt/design/funcData_cxFuncDataList.html?'
            'func_widget_guid=5920CCA8B9E61FBAE0530100007F0493&gnmkdm=N219933'
        )
        cur_page = 1
        skipping = 0
        success = 0
        failure = 0

        while True:
            logger.info(f"Crawling page {cur_page}")
            data = {
                'xnm': "2021",
                "xqm": "12",
                "queryModel.showCount": "500",
                "queryModel.currentPage": f"{cur_page}",
            }
            r = requests.post(url, data=data, cookies=cookies).json()

            for course in r['items']:
                ret = self.process_course(course)
                if ret == Code.SKIPPING:
                    skipping += 1
                elif ret == Code.SUCCESS:
                    success += 1
                else:
                    failure += 1

            if cur_page < int(r['totalPage']):
                cur_page += 1
            else:
                break

        logger.info(f"Skipping: {skipping}")
        logger.info(f"Success: {success}")
        logger.info(f"Failure: {failure}")

    def handle(self, *args, **options):
        if options['migrate_old']:
            self.migrate_old_course(show=options['show'])
        else:
            cookie_str = options['cookies'][0]
            cookie = dict(x.split('=') for x in cookie_str.split(';'))
            self.crawl(cookie)
