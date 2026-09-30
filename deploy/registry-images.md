# GitHub 构建镜像，服务器主动拉取

当前生产发布默认使用此流程。GitHub Actions 不连接服务器，不持有服务器 SSH 密钥，
不执行数据库迁移或容器切换。服务器只拉取已经构建的镜像，不运行 build，不为构建创建 Swap。
既有运行时 Swap 不由发布脚本调整。

## 1. 首次配置 GitHub

两个仓库启用 Actions，并允许工作流通过 `GITHUB_TOKEN` 写入 Packages。构建 job 已声明
`contents: read` 与 `packages: write`，不需要另存镜像推送 token。

镜像仓库分别是：

- 后端：`ghcr.io/nwuca/nwu.icu`。
- gateway：`ghcr.io/moowantfree/new_nwu_icu_frontend`。

第一次发布后在 GitHub Packages 中将这两个包设为 **Public**，与当前公开代码仓库一致。
GHCR 的新包默认是 Private；源码公开不会自动公开镜像。后端包必须先允许前端工作流读取，
前端才能发布。若保留 Private，需要给前端仓库授予后端包读取权限；服务器另外使用具有
`read:packages` 的 PAT classic 通过 `docker login ghcr.io --password-stdin` 登录，不把 token
写进仓库或命令参数。NWUCA 组织若限制包权限，需要在组织内配置相应访问权限。

`.dockerignore` 排除真实 `.env`、本地 settings、数据库和上传文件；构建只接收公开提交号、
仓库 URL 与配套镜像摘要，不接收生产密钥。

## 2. 在 GitHub 发布一组固定版本

后端 `Backend CI`：

- push 到 `master` 后，Lint 与测试通过才构建并发布 `linux/amd64` 镜像。
- 后端有历史格式问题，pre-commit 检查本次 push / PR 修改的文件，手动发布检查所选提交
  相对父提交的修改；所有 hooks 保留，完整 Django 测试和迁移检查仍检查整个项目。
- `Run workflow` 可重建所选分支或 tag 的提交；仍先执行同一套检查。
- 所选分支或 tag 必须包含新版 workflow；旧 ref 没有手动发布入口时先使用包含新版配置的 ref。
- PR 只检查，不发布镜像。
- 标签：`sha-<完整后端提交号>`，摘要显示在运行 Summary。

前端 `Frontend CI`：

- 普通 push / PR 继续运行类型检查、Lint、测试和构建。
- 发布时选择 **Run workflow**，选定前端分支或 tag，并填写 `backend_commit`（完整的
  40 位小写后端 SHA）。该后端镜像必须已发布且前端工作流有读取权限。
- 检查通过后拉取该后端镜像，核对后端 revision，再构建 gateway。
- 标签：`sha-<完整前端提交号>-backend-<完整后端提交号>`。
- gateway 静态文件包含两个完整提交号；镜像标签记录前端 revision、后端 commit 及
  **配套后端镜像的固定摘要**。Summary 给出两个可部署的镜像摘要。

因此后端更新后也要重新发布 gateway，才能准确显示新的后端版本。保留两个工作流的
成功记录及 Summary；未发布成功的版本不能部署。服务器使用 `linux/amd64`，当前后端
Dockerfile 的 Supercronic 二进制也只支持该平台。

## 3. 服务器拉取并固定镜像

先按 [日常更新速查](quick-update.md) 创建一个新的发布目录，检出已 push 的固定提交。
所有以下命令在服务器 Bash 中执行：

```bash
set -euo pipefail
cd "$RELEASE/NWU.ICU"
# 填入 Summary 中的 gateway 摘要，可避免后续重建相同标签影响本次发布。
GATEWAY_REF=ghcr.io/moowantfree/new_nwu_icu_frontend@sha256:<Summary中的摘要>
bash deploy/pull-release-images "$BACKEND_COMMIT" "$FRONTEND_COMMIT" "$GATEWAY_REF" \
  > ../release-images.env.tmp
mv ../release-images.env.tmp ../release-images.env
set -a
source ../release-images.env
set +a
export ENV_FILE=/etc/nwuicu/production.env
```

不传第三个参数时，脚本按前后端提交对解析 gateway 标签。已记录摘要的正式发布应传第三个参数。
脚本核对来源、平台、前后端提交与配套后端摘要，全部通过才输出 manifest。它不会构建、
启动或停止任何容器，也不修改生产配置。即使后端同一提交的标签被重新构建，服务器仍拉取
gateway 绑定的那个后端摘要。拉取失败就停止，旧容器继续运行。

将 `deploy/docker-compose.server.registry.example.yaml` 复制到新发布目录根部，命名为
`docker-compose.server.yaml`；比对上一发布 override，保留其额外的健康检查、运行参数、
挂载和网络修正。模板移除六个应用服务的 `build`，所有后端服务共用 `$BACKEND_IMAGE`，
gateway 使用 `$GATEWAY_IMAGE`。固定回环端口及外部数据库卷不变。

模板设置 `pull_policy: never`，因此一次性容器和正常服务都只使用事先校验的本地镜像。
模板要求 Docker Compose >= 2.24.4（`!reset`）；当前服务器 2.27.0 支持。
`web` 直接启动 Gunicorn，初始化和迁移由发布前的一次性容器执行，避免每次重启重复执行。

```bash
dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    -f docker-compose.production.yaml -f ../docker-compose.server.yaml "$@"
}
dc config --quiet
# 验证所有应用服务只有固定摘要镜像、没有 build；不输出环境密钥。
dc config --format json | python3 -c '
import json, sys
c = json.load(sys.stdin)
assert c["name"] == "nwuicu"
assert c["volumes"]["pgdata"]["external"] and c["volumes"]["pgdata"]["name"] == "nwuicu_pgdata"
for name in ("web", "gateway", "resource-worker", "cron", "archive-worker", "archive-cleaner"):
    service = c["services"][name]
    assert "build" not in service, name
    assert service["pull_policy"] == "never", name
    assert "@sha256:" in service["image"], name
print("Fixed images and existing database volume verified.")
'
```

该 manifest 不含密钥，记录完整 commit 与镜像摘要；保留在发布目录中。重新登录服务器操作
该发布时，必须重新 `source release-images.env` 并设置 `ENV_FILE`，缺失变量时 Compose 会报错。

## 4. 备份、迁移和切换

继续执行 [日常更新速查](quick-update.md) 的双库全量备份、迁移及静态文件收集。
一次性容器使用 `dc run --rm --no-deps web <command>`。服务器 Compose 2.27 的 `run`
不支持 `--no-build` 或 `--pull`；合并配置通过移除 `build` 并设置 `pull_policy: never`
限制为事先校验的本地镜像。核心切换的 `dc up` 使用：

```bash
dc up -d --no-deps --no-build --pull never --wait web gateway
# 核心接口、健康状态与提交号验收通过后再切换后台服务。
dc up -d --no-deps --no-build --pull never resource-worker cron archive-worker archive-cleaner
```

首次启用 archive 服务时按 [资源归档发布说明](resource-archives.md) 先核对挂载与队列。
不触碰 PostgreSQL，不修改 OpenResty，不删除旧镜像/发布/备份。任何数据库迁移仍按
[完整 Runbook](production-runbook.md) 判断维护和回滚边界。服务器主动拉取是一次明确的
发布操作，不轮询 `latest`，也不自动换掉线上容器。
