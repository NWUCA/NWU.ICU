# NWU.ICU 后端与生产部署

## 本地后端

- 在 WSL 的 `/mnt/e/Code/nwuicu/NWU.ICU` 中使用 Docker Compose；不要在 Windows 原生 Python 中启动 Django。
- 若 `.env` 未设置资源目录，使用 `RESOURCE_STORAGE_HOST_PATH="$PWD/resource-storage" docker compose up -d`。

## 测试要求

- 完整测试流程见 `docs/testing.md`。
- 在提供 Docker CLI 的 WSL 发行版中运行后端测试；当前开发机使用 `Debian1`，不要改用 Windows 原生 Django。
- 每次测试必须显式使用 `--env-file .env.test`，并同时加载 `docker-compose.yaml` 与 `docker-compose.test.yaml`，确保 PostgreSQL 与 Django 测试容器使用同一套凭据。
- 每次测试必须使用非默认且唯一的 Compose 项目名（`-p nwuicu-test-<唯一后缀>`），隔离容器、网络和 `test-pgdata`。禁止用默认 `nwuicu` 项目运行测试覆盖文件，以免重建正在使用的开发数据库容器。
- 凭据不匹配或测试卷陈旧时，改用新的唯一项目名；不得擅自删除旧卷。测试结束后停止隔离测试项目的 `db`，不执行 `docker compose down`，不删除卷。
- 测试前后记录默认开发栈状态；若误影响默认栈，按 `docs/testing.md` 恢复并验证。

## 生产部署

- 生产服务器 SSH 别名为 `resour`。执行部署前必须完整阅读 `deploy/production-runbook.md` 和 `deploy/quick-update.md`。
- 只部署已 push、工作区干净的前后端固定提交，并在 `/opt/nwuicu/releases/` 创建新的不可变发布目录。不要修改正在运行的旧发布目录。
- 所有生产 Compose 命令必须设置 `ENV_FILE=/etc/nwuicu/production.env`，并同时使用 `docker-compose.production.yaml` 与发布目录根部的 `docker-compose.server.yaml`。
- 构建前创建 4GB 临时 `/swapfile`，设置 `COMPOSE_PARALLEL_LIMIT=1` 串行构建。gateway 构建必须注入完整的 `FRONTEND_COMMIT` 和 `BACKEND_COMMIT`。验收后关闭并删除临时 Swap，不加入 `/etc/fstab`。
- 数据库迁移前必须生成 PostgreSQL `-Fc` 快照、`pg_restore --list` 清单和 SHA-256。不得执行 `docker compose down`，不得重启或重建 PostgreSQL，不得删除卷、旧发布、镜像或备份。
- 先切换并验证 `web`、`gateway`，再切换 `resource-worker`、`cron`。普通更新不修改或重载 OpenResty。
- 验收必须检查 `https://nwu.icu/`、主要前端路由、`https://nwu.icu/api/user/csrf/`、`https://api.nwu.icu/api/user/csrf/`、容器健康与重启次数、近期错误日志以及前端产物内的两个提交号。
