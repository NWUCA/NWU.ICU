据说某人五月份说要写这个来着... (咕咕咕

这本来是一个课程评价网站.. 为了复用 user 部分的代码把自动填报加进去了..
目前文件结构有些乱..

## 起步
```
pipenv sync --dev
```
根据 `development.py.sample` 建立 `development.py` 配置文件.

## 部署
- 确保 clone 了整个仓库.. (版本号模块使用了 git describe)
- 根据 `production.py.sample` 建立 `production.py` 配置文件
- 配置静态文件
- 初始化数据库
- 执行 `start.sh`
- 配置反向代理

## 自动填报
把 `report/trigger_report.sh` 加入 crontab 中.

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
