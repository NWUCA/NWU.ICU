目前拥有课程评价和自动填报两个模块, 更多功能正在计划中..

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

## 自动填报
把 `report/trigger_report.sh` 加入 crontab 中.

## Roadmap
- [ ] 首页添加类似 ustc.life 的导航
- [ ] PWA
- [ ] 课程评价的 UX 改进

## TODO
- [x] 生产环境的配置, static files, DEBUG, 以及启动脚本
- [x] logging
- [x] 静态文件的图片 404 了
- [ ] 使用 django form
- [ ] 登录的 throttle

### 自动填报
- [x] 失败后的提醒

### 课程评价
- [ ] 每个评价的编号是错的
- [ ] 管理自己的评价 (改 and 删)
- [ ] 课程的分页
- [ ] 主页课程的平均评价

## 贡献
欢迎提 PR 或 issue.

commit 之前请运行 `pre-commit` 以确保代码格式规范.
