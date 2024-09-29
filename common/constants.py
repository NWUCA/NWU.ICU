import settings.settings

errcode_dict = {
    'too_many_requests': '请求过多',
    'invalid_classify': '非法类别',
    'captcha_error': '验证码错误',
    'captcha_overdue': '验证码已失效',
    'auth_error': '权限不足',
    'user_not_exist': '目标用户不存在',
    'file_not_exist': '目标文件不存在',
    'course_not_exist': '课程不存在',
    'review_not_exist': '课程评价不存在',
    'reply_not_exist': '课程评价回复不存在',
    'teacher_not_exist': '教师不存在',
    'field missed': '输入缺失',
    'invalid_token': '无效的token',
    'have_login': '已经登录',
    'not_login': '尚未登录',
    'password_incorrect': '密码错误',
    'rating_out_range': '评分超过范围',
    'operation_error': '操作错误',
    'teacher_id_when_exist': '教师已存在应提交ID',
    'teacher_name_when_not_exist': '教师不存在应提交姓名',
    'teacher_school_when_not_exist': '教师不存在应提交学院',
    'file_over_size': 'File too large. Size should not exceed 25 MB.',
    'user_name': '用户名长度必须在8到29个字符之间',
    'username_not_match_length': '用户名长度必须在8到29个字符之间',
    'username_invalid_char': '用户名只能包含字母、数字和下划线',
    'password_invalid_char': '密码必须同时包含大写字母, 小写字母, 数字',
    'username_duplicate': '已存在一位使用该名字的用户',
    'email_duplicate': '此邮箱已被注册',
    'password_not_match_length': '密码长度必须在8-30之间',
    'password_old_not_true': '旧密码不正确',
    'password_re_not_consistent': '两次输入的密码不一致',
    'password_re_equal_old': '新老密码不可以一致',
    'invalid_college_email': f'注册时不可使用{settings.settings.UNIVERSITY_CHINESE_NAME}邮箱',
    'not_college_email': f'非{settings.settings.UNIVERSITY_CHINESE_NAME}邮箱',
    'avatar_uuid_error': '头像uuid错误',
    'nickname_not_match_length': '昵称长度必须在2到30之间',
    'nickname_invalid_char': '昵称只能包含汉字、英文字母、数字和!@#$%^&*()_+~\-={}',
    'not_active': '用户尚未激活',
    'has_active': '用户已经激活',
    'review_update_success':'课程评价更新成功',
    'review_has_exist':'课程评价已经存在',
}
