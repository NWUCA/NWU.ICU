from rest_framework.exceptions import APIException


class ManagementAPIException(APIException):
    field = 'auth'
    err_code = 'management_error'
    err_msg = '管理员验证失败'


class AdminPasskeyRequired(ManagementAPIException):
    status_code = 403
    err_code = 'admin_passkey_required'
    err_msg = '请使用 Passkey 验证管理员身份'


class AdminPermissionDenied(ManagementAPIException):
    status_code = 403
    err_code = 'admin_permission_denied'
    err_msg = '没有执行此管理操作的权限'


class PasskeyCeremonyError(ManagementAPIException):
    status_code = 400
    field = 'passkey'
    err_code = 'passkey_verification_failed'
    err_msg = 'Passkey 验证失败，请重试'


class PasskeyNotEnrolled(ManagementAPIException):
    status_code = 409
    field = 'passkey'
    err_code = 'passkey_not_enrolled'
    err_msg = '管理员尚未绑定 Passkey'

