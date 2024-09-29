# NWU.ICU

目前拥有导航, 课程评价两个模块.

## 起步

本项目使用 Django Rest Framework开发, 并使用 poetry 来管理依赖.

- 安装依赖:
    ```
    poetry install
    ```
- 进入虚拟环境:
    ```
    poetry shell
    ```
- 更改 `settings.py`文件下的DATABASES, 填写PostgreSQL连接信息
- PostgreSQL需要安装pg_trgm和zhparser插件, 来实现基于拼音的模糊搜索,
  推荐使用已安装好插件的[PostgreSQL](https://hub.docker.com/r/abcfy2/zhparser)
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

### 手动部署

- 确保 clone 了整个仓库
- 根据 `production.py.sample` 建立 `production.py` 配置文件
- 配置静态文件
- 初始化数据库
- 执行 `start.sh`
- 配置反向代理

目前生产环境的部署流程见[这里](https://github.com/cjc7373/ansible/blob/master/playbooks/nwu.icu.yml).

### Docker部署

1. git clone 本项目
2. 按照.env.sample新建一个.env文件, 将环境变量值填写
3. cd到项目目录
4. 执行docker-compose up, 构建并启动容器
5. 访问http:ip:8000, 看到NWU.ICU界面, 代表启动成功

### 注意事项

1. 当前日志转储使用的是RotatingFileHandler, 在reload模式下, 转储时会发生PermissionError, 故在生产环境启动需要添加参数-noreload
2. 学期的更新需要每年3,7月执行一次脚本(更建议每月一号执行一次), `python manage.py update_semester`, 推荐添加备忘录或使用Crontab
3. 如在部署项目之前, 有任何的Course,Teacher,Review数据, 需要执行`python manage.py update_module_pinyin_name <module>`,
   具体module取决于你之前存在什么数据, 每有一个上述内容, 就需执行一次, 以来实现拼音模糊搜索

> 比如之前只有Course数据, 则只执行`python manage.py update_module_pinyin_name course`

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
