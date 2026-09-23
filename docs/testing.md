# NWU.ICU 测试要求

本说明适用于 `E:\Code\nwuicu` 工作区。目标是在不影响正在运行的本地开发栈、不删除任何现有数据卷的前提下完成前后端验证。

## 前端

在 Windows PowerShell 7 中运行：

```powershell
cd E:\Code\nwuicu\new_nwu_icu_frontend
pnpm check
```

`pnpm check` 必须完成类型检查、ESLint、全部 Vitest 测试和生产构建。若受限沙箱导致 Node.js 访问用户目录时报 `EPERM`，应在具备用户目录访问权限的执行环境中重试，不要为沙箱问题修改项目代码或配置。

## 后端

### 强制隔离规则

1. 后端测试只能在提供 Docker CLI 的 WSL 环境中运行，不使用 Windows 原生 Python 启动 Django。当前开发机的 Docker 位于 `Debian1`。
2. Compose 必须显式传入 `--env-file .env.test`。`docker-compose.test.yaml` 只为 `test` 服务声明了 `.env.test`；若省略全局 `--env-file`，`db` 服务仍会从默认 `.env` 插值，造成 Django 使用 `nwuicu_test` 凭据而 PostgreSQL 使用另一套凭据，所有测试会在建库阶段报密码认证失败。
3. 测试必须使用非默认且本次运行唯一的 Compose 项目名。禁止用默认项目名 `nwuicu` 加载测试覆盖文件，否则 Compose 可能重建、停止或改挂载正在为本地 `web`、`cron` 与 `resource-worker` 服务的 `nwuicu-db-1`。
4. 唯一项目名同时用于隔离容器、网络和 `test-pgdata`。若旧测试卷凭据不匹配，换一个新项目名，不要删除旧卷。
5. 测试结束后只停止本次隔离项目的 `db`。除非用户明确要求，不运行 `docker compose down`，不删除容器卷或其他持久数据。

### 运行前检查

从 Windows PowerShell 进入 Docker 所在的 WSL，先确认 Docker 和默认开发栈状态：

```powershell
wsl -d Debian1 -- docker version
wsl -d Debian1 -- bash -lc 'cd /mnt/e/Code/nwuicu/NWU.ICU && RESOURCE_STORAGE_HOST_PATH="$PWD/resource-storage" docker compose -f docker-compose.yaml ps'
```

记录 `db`、`web`、`cron`、`resource-worker` 的运行状态。测试命令不得改变这些默认项目容器。

### 完整后端验证

在同一个 WSL shell 中设置本次运行唯一的项目名。不要复用文档示例中的固定名称：

```bash
cd /mnt/e/Code/nwuicu/NWU.ICU
export RESOURCE_STORAGE_HOST_PATH="$PWD/resource-storage"
export NWUICU_TEST_PROJECT="nwuicu-test-$(date +%Y%m%d%H%M%S)"

docker compose --env-file .env.test \
  -p "$NWUICU_TEST_PROJECT" \
  -f docker-compose.yaml \
  -f docker-compose.test.yaml \
  run --rm test

docker compose --env-file .env.test \
  -p "$NWUICU_TEST_PROJECT" \
  -f docker-compose.yaml \
  -f docker-compose.test.yaml \
  run --rm test python manage.py makemigrations --check --dry-run

docker compose --env-file .env.test \
  -p "$NWUICU_TEST_PROJECT" \
  -f docker-compose.yaml \
  -f docker-compose.test.yaml \
  run --rm test python manage.py check
```

验收标准：

- Pytest 全部通过。
- `makemigrations --check --dry-run` 输出 `No changes detected`。
- `manage.py check` 输出 `System check identified no issues`。

完成后停止本次隔离数据库，保留测试卷：

```bash
docker compose --env-file .env.test \
  -p "$NWUICU_TEST_PROJECT" \
  -f docker-compose.yaml \
  -f docker-compose.test.yaml \
  stop db
```

再次运行默认开发栈的 `docker compose ps`，确认其状态与测试前一致。

### 常见故障与恢复

#### PostgreSQL 密码认证失败

如果全部测试在数据库准备阶段出现 `password authentication failed for user "nwuicu_test"`：

- 确认命令包含全局 `--env-file .env.test`。
- 确认 `db` 与 `test` 属于同一个唯一测试项目。
- 若该项目的 `test-pgdata` 已由其他凭据初始化，换一个新的唯一项目名；不要删除旧卷来绕过问题。

#### 误影响默认开发数据库

如果测试命令误用了默认 `nwuicu` 项目名，可能导致 `nwuicu-db-1` 被测试配置重建或停止。数据卷通常仍在，但必须立即恢复标准开发配置：

```bash
cd /mnt/e/Code/nwuicu/NWU.ICU
export RESOURCE_STORAGE_HOST_PATH="$PWD/resource-storage"
docker compose -f docker-compose.yaml up -d db
docker compose -f docker-compose.yaml ps
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8000/api/user/csrf/
```

若 `resource-worker` 因数据库 DNS 短暂不可用而持续重启，在 `db` 显示 healthy 后运行：

```bash
docker compose -f docker-compose.yaml restart resource-worker
docker compose -f docker-compose.yaml ps
```

恢复完成时应满足：数据库为 healthy，`web`、`cron`、`resource-worker` 均为运行状态，本地 CSRF 接口返回 HTTP 200。
