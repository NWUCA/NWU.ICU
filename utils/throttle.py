from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class CaptchaAnonRateThrottle(AnonRateThrottle):
    rate = '30/minute'


class CaptchaUserRateThrottle(UserRateThrottle):
    rate = '30/minute'


class EmailAnonRateThrottle(AnonRateThrottle):
    rate = '4/minute'


class EmailUserRateThrottle(UserRateThrottle):
    rate = '4/minute'
