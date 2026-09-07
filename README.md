# NWU.ICU

目前拥有导航, 课程评价两个模块.

## 起步

本项目使用 Django Rest Framework开发, 并使用 uv 来管理依赖.

- 安装依赖:
    ```
    uv sync
    ```
- 在虚拟环境中执行命令:
    ```
    uv run python manage.py <command>
    ```
- 更改 `settings.py`文件下的DATABASES, 填写PostgreSQL连接信息
- PostgreSQL需要安装pg_trgm和zhparser插件, 来实现基于拼音的模糊搜索,
  推荐使用已安装好插件的[PostgreSQL](https://hub.docker.com/r/abcfy2/zhparser)
- 根据 `development.py.sample` 建立 `development.py` 配置文件.
- 建立数据库:
    ```
    uv run python manage.py migrate
    ```
- 运行开发服务器:
    ```
    uv run python manage.py runserver
    ```

## 环境与部署

Windows 调试、Debian 生产部署、Docker Compose 与 OpenResty 配置见
[部署文档](deploy/README.md)。

站内资料页、Windows / WSL 资料目录挂载和 Linux 配置见
[资料浏览说明](deploy/resource-browser.md)。

## Roadmap

- [x] 用户站内信
- [x] 楼中楼的课程评价回复
- [x] 模糊搜索课程与教师
- [ ] 语义化搜索评价具体内容/回复
- [x] 精细化的throttle
- [ ] 上传文件前hash去重
- [ ] 全面的站内信息提醒
- [ ] 图片ocr搜索
- [ ] llm总结课程评价内容

## 贡献

欢迎提 PR 或 issue.
