from django.core.management.base import BaseCommand

from course_assessment.models import School


class Command(BaseCommand):
    help = 'Updates the semester annually'

    def handle(self, *args, **options):
        if School.objects.count() == 0:
            school_list = [
                "117信息科学与技术学院 (软件学院)", "101文学院", "102历史学院", "103经济管理学院", "104公共管理学院",
                "105外国语学院", "106新闻传播学院", "107法学院（知识产权学院）", "108哲学学院", "109艺术学院",
                "110地质学系",
                "111化学与材料科学学院", "112物理学院", "113生命科学学院", "114数学学院", "115化工学院",
                "116城市与环境学院", "119文化遗产学院", "食品科学与工程学院", "体育教研部", "其他", "医学院",
                "马克思主义学院", "学生工作部（处）", "体育教研室", "丝绸之路研究院（西北历史研究所）", "科学史高等研究院",
                "安莱学院", "保卫处、武装部",
            ]
            for school in school_list:
                School.objects.create(name=school)
            self.stdout.write(f'Update school successful!')
        else:
            self.stdout.write(f'School already exists...')
