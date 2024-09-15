from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class CaptchaAnonRateThrottle(AnonRateThrottle):
    rate = '30/minute'  # 匿名用户每分钟最多请求5次


class CaptchaUserRateThrottle(UserRateThrottle):
    rate = '60/minute'  # 登录用户每分钟最多请求10次
