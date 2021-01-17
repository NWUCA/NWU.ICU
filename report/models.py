from django.db import models

from user.models import User


class Report(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.BooleanField(default=False)

    # 下列字段均为晨午检中要求的
    sfzx = models.BooleanField(help_text='是否在校', default=False)
    area = models.TextField()
    city = models.TextField()
    province = models.TextField()
    address = models.TextField()
    geo_api_info = models.TextField()
