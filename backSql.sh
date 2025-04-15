#!/bin/bash

# 获取脚本所在的目录并切换到该目录
cd "$(dirname "$0")"

# 创建backup文件夹（如果不存在）
mkdir -p ./backup

# 执行pg_dump命令
docker exec pgsql pg_dump -U newnwuicu -d mynwuicu \
    -t user_user -t course_assessment_review -t course_assessment_course \
    -t course_assessment_course_semester -t course_assessment_course_teachers \
    -t course_assessment_teacher --data-only --no-owner --no-privileges \
    > ./backup/exported_data_user_review_$(date +%Y%m%d_%H%M%S).sql
