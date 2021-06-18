# NWU.ICU
目前拥有导航, 课程评价和自动填报三个模块, 更多功能正在计划中..

## 起步
本项目使用 Django 开发, 并使用 pipenv 来管理依赖.
- 安装依赖:
    ```
    pipenv sync --dev
    ```
- 进入虚拟环境:
    ```
    pipenv shell
    ```
- 根据 `development.py.sample` 建立 `development.py` 配置文件.
- 建立数据库:
    ```
    python manage.py migrate
    ```
- 运行开发服务器:
    ```
    python manage.py runserver
    ```

## 部署
- 确保 clone 了整个仓库.. (版本号模块使用了 git describe)
- 根据 `production.py.sample` 建立 `production.py` 配置文件
- 配置静态文件
- 初始化数据库
- 执行 `start.sh`
- 配置反向代理

目前生产环境的部署流程见[这里](https://github.com/cjc7373/ansible/blob/master/playbooks/nwu.icu.yml).

## 自动填报
把 `report/trigger_report.sh` 加入 crontab 中.

## Roadmap
- [x] 首页添加类似 ustc.life 的导航
- [x] PWA
- [ ] 课程评价的 UX 改进

## TODO
- [x] 生产环境的配置, static files, DEBUG, 以及启动脚本
- [x] logging
- [x] 静态文件的图片 404 了
- [x] 使用 django form
- [ ] 登录的 throttle

### 自动填报
- [x] 失败后的提醒

### 课程评价
- [ ] 查看自己的评价
- [ ] 一条评价的历史 (评价的修改)
- [ ] 课程的分页
- [x] 课程和评价列表改成卡片
- [x] 搜索
- [x] 评价的日期时间
- [ ] 添加课程中按院系选择教师

## 贡献
欢迎提 PR 或 issue.

commit 之前请运行 `pre-commit` 以确保代码格式规范.
