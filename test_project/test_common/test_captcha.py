from datetime import timedelta

from captcha.models import CaptchaStore
from django.test import TestCase, override_settings
from django.utils import timezone

from common.serializers import CaptchaSerializer


@override_settings(CAPTCHA_TEST_MODE=False)
class CaptchaSerializerTests(TestCase):
    def create_captcha(self, *, expiration):
        return CaptchaStore.objects.create(
            challenge='challenge',
            response='answer',
            hashkey='captcha-key',
            expiration=expiration,
        )

    def test_expired_captcha_is_rejected_and_consumed(self):
        self.create_captcha(expiration=timezone.now() - timedelta(seconds=1))

        serializer = CaptchaSerializer(data={
            'captcha_key': 'captcha-key',
            'captcha_value': 'answer',
        })

        self.assertFalse(serializer.is_valid())
        self.assertFalse(CaptchaStore.objects.filter(hashkey='captcha-key').exists())

    def test_wrong_answer_is_consumed(self):
        self.create_captcha(expiration=timezone.now() + timedelta(minutes=1))

        serializer = CaptchaSerializer(data={
            'captcha_key': 'captcha-key',
            'captcha_value': 'wrong',
        })

        self.assertFalse(serializer.is_valid())
        self.assertFalse(CaptchaStore.objects.filter(hashkey='captcha-key').exists())

    def test_valid_captcha_succeeds_once(self):
        self.create_captcha(expiration=timezone.now() + timedelta(minutes=1))
        data = {'captcha_key': 'captcha-key', 'captcha_value': 'ANSWER'}

        self.assertTrue(CaptchaSerializer(data=data).is_valid())
        self.assertFalse(CaptchaSerializer(data=data).is_valid())

