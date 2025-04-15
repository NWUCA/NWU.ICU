import environ
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

env = environ.Env()


class CaptchaAnonRateThrottle(AnonRateThrottle):
    rate = env('NORMAL_THROTTLE_NOT_LOGIN', default='30/minute')


class CaptchaUserRateThrottle(UserRateThrottle):
    rate = env('NORMAL_THROTTLE_LOGIN', default='30/minute')


class EmailAnonRateThrottle(AnonRateThrottle):
    rate = env('EMAIL_THROTTLE_NOT_LOGIN', default='2/minute')


class EmailUserRateThrottle(UserRateThrottle):
    rate = env('EMAIL_THROTTLE_LOGIN', default='2/minute')
