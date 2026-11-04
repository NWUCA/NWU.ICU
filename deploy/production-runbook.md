# NWU.ICU 生产发布 Runbook

本文档是现有 `nwu.icu` 服务器的权威发布说明。它对应当前的“1Panel OpenResty +
Docker 回环端口”架构，不要求 OpenResty 加入 NWU.ICU 的 Docker 网络。

任何涉及停服、数据库迁移、OpenResty 重载、恢复数据库或删除旧内容的步骤，都应先单独确认。

## 1. 当前架构

```text
Internet
  -> 1Panel OpenResty（TLS、域名、外层上传限制）
  -> 127.0.0.1:18080
  -> nwuicu-gateway（Vue SPA、Django static、内部 API 代理）
  -> web:8000（Django）
  -> pgsql / nwuicu_pgdata（PostgreSQL 17）
```

兼容域名 `api.nwu.icu` 暂时由 OpenResty 直接代理到 `127.0.0.1:8000`。

生产服务：

- `nwuicu-web-1`：Django/Gunicorn；
- `nwuicu-gateway-1`：生产前端与内部反向代理；
- `nwuicu-resource-worker-1`：资源投稿发布队列；
- `nwuicu-cron-1`：定时更新和临时投稿清理；
- `nwuicu-archive-worker-1`：资源 ZIP 打包队列；
- `nwuicu-archive-cleaner-1`：归档缓存、任务记录清理与通知；
- `pgsql`：PostgreSQL，使用既有卷 `nwuicu_pgdata`。

重要路径：

```text
/opt/nwuicu/releases/<timestamp>/       每次发布的独立目录
/etc/nwuicu/production.env              权限 0600 的生产密钥与配置
/srv/nwuicu/media                       Django media
/srv/nwuicu/static                      collectstatic 输出
/srv/nwuicu/index                       资源目录索引
/opt/1panel/apps/alist/alist/data/mnt   AList 实际资源目录
/root/nwuicuBack                        数据库与 OpenResty 备份
```

Docker 只发布以下回环端口，不要改成 `0.0.0.0`：

```text
127.0.0.1:18080 -> gateway:80
127.0.0.1:8000  -> web:8000
```

## 2. 前端如何发布

前端不在服务器运行 `pnpm dev`。默认由 GitHub Actions 通过多阶段 Dockerfile 构建并发布到
GHCR，服务器主动拉取。配置及固定提交发布步骤见 [镜像发布说明](registry-images.md)：

1. Node 阶段运行 `pnpm install --frozen-lockfile` 和 `pnpm build`；
2. `dist/` 被复制到 gateway 镜像的 `/usr/share/nginx/html`；
3. gateway 内的 Nginx 提供 SPA，并把 `/api/` 转给 `web:8000`；
4. `/srv/nwuicu/static` 只读挂载到 `/srv/django-static`；
5. `/media/` 在 gateway 层固定返回 404。

因此前端更新需要在 GitHub 重建 gateway 镜像，服务器不运行 build；不要把 `dist/` 手工复制到 1Panel 站点目录。
gateway 构建时必须注入本次前后端完整提交号，页脚据此显示实际构建版本。
Actions 同时注入两个仓库 URL，使提交号链接到对应的 GitHub 提交页。
下文服务器本地构建是备用流程，默认镜像拉取流程不创建构建用 Swap。

## 3. 每次更新前的本地准备

后端与前端分别完成测试并 push，记录完整提交号：

```powershell
cd E:\Code\nwuicu\NWU.ICU
git status --short
git rev-parse HEAD

cd E:\Code\nwuicu\new_nwu_icu_frontend
git status --short
git rev-parse HEAD
```

后端测试应在 WSL Docker 中运行，前端测试和构建使用 Windows `pnpm`。不要部署未 push 的
工作区，也不要在服务器旧工作区执行 `git pull` 覆盖其本地修改。

## 4. 创建不可变发布目录

以下示例变量必须替换为本次真实值：

```bash
OLD=<根据运行中容器的Compose标签核对的当前发布目录>
RELEASE_ID=$(date +%Y%m%d_%H%M%S)
BACKEND_COMMIT=<完整后端提交号>
FRONTEND_COMMIT=<完整前端提交号>
BACKEND_TAG=$(printf '%s' "$BACKEND_COMMIT" | cut -c1-8)
FRONTEND_TAG=$(printf '%s' "$FRONTEND_COMMIT" | cut -c1-8)
RELEASE=/opt/nwuicu/releases/${RELEASE_ID}_${BACKEND_TAG}_${FRONTEND_TAG}
```

从现有仓库读取 origin，但把代码检出到新目录：

```bash
install -d -m 755 "$RELEASE"

git clone --no-checkout "$(git -C /opt/nwuicu/NWU.ICU remote get-url origin)" \
  "$RELEASE/NWU.ICU"
git -C "$RELEASE/NWU.ICU" checkout --detach "$BACKEND_COMMIT"

git clone --no-checkout "$(git -C /opt/nwuicu/new_nwu_icu_frontend remote get-url origin)" \
  "$RELEASE/new_nwu_icu_frontend"
git -C "$RELEASE/new_nwu_icu_frontend" checkout --detach "$FRONTEND_COMMIT"
```

核对两个目录均为干净状态，且 `rev-parse HEAD` 与计划提交完全一致。

`/etc/nwuicu/production.env` 和 `/srv/nwuicu/*` 在后续发布中复用，不要从仓库模板覆盖真实密钥。

## 5. 服务器 Compose override

仓库的 `docker-compose.production.yaml` 保存通用配置；每个发布目录根部另放
`docker-compose.server.yaml`，只记录这台服务器的镜像标签、回环端口和既有卷。

默认使用 `deploy/docker-compose.server.registry.example.yaml`，先拉取并验证镜像，导入
`release-images.env` 中的两个固定摘要。模板以 `!reset null` 去掉应用服务的 `build`，
保留回环端口和既有数据库卷。保留上一发布的额外 override，且不要让 web 启动命令重复迁移。
详细步骤见 [镜像发布说明](registry-images.md)。以下固定本地标签示例只用于备用本地构建：

```yaml
services:
  web:
    image: nwuicu-web:<backend-short-sha>
    # 即使备用构建也不在 web 重启时执行迁移或业务初始化。
    command: >-
      bash -c "exec gunicorn settings.wsgi:application --bind 0.0.0.0:8000
      --workers $${GUNICORN_WORKERS:-3} --timeout $${GUNICORN_TIMEOUT:-300}
      --access-logfile - --error-logfile -"
    ports:
      - "127.0.0.1:8000:8000"

  cron:
    image: nwuicu-web:<backend-short-sha>

  resource-worker:
    image: nwuicu-web:<backend-short-sha>

  archive-worker:
    image: nwuicu-web:<backend-short-sha>

  archive-cleaner:
    image: nwuicu-web:<backend-short-sha>

  gateway:
    image: nwuicu-gateway:<backend-short-sha>-<frontend-short-sha>
    ports:
      - "127.0.0.1:18080:80"

volumes:
  pgdata:
    external: true
    name: nwuicu_pgdata
```

如果所部署提交尚未包含修正后的 HTTPS 健康检查或真实 crontab 文件，应继续沿用上一发布的
server override；不要临时关闭 `SECURE_SSL_REDIRECT`。

所有命令都使用同一组 Compose 参数：

```bash
cd "$RELEASE/NWU.ICU"
export ENV_FILE=/etc/nwuicu/production.env
docker compose \
  --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml \
  -f ../docker-compose.server.yaml \
  config --quiet
```

解析后的项目名必须是 `nwuicu`，数据库卷名必须是 `nwuicu_pgdata`。如果出现新的数据库卷，
立即停止，不要启动 Compose。

## 6. 拉取固定摘要镜像（默认）或本地构建（备用）

默认按 [镜像发布说明](registry-images.md) 在 GitHub 构建，服务器运行
`deploy/pull-release-images`，核对完整提交与配套摘要后再进入第 7 节。镜像拉取失败时旧容器
继续运行，不进入维护状态。此流程不创建、关闭或删除 Swap。

仅明确选择服务器本地构建时，才执行以下备用步骤，不能对 registry override 执行 build：

低内存服务器应串行构建；线上旧容器在此阶段继续运行：

```bash
export COMPOSE_PARALLEL_LIMIT=1

test ! -e /swapfile
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
export LOCAL_BUILD_SWAP_CREATED=1
swapon --show

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  build web

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  build \
  --build-arg FRONTEND_COMMIT="$FRONTEND_COMMIT" \
  --build-arg BACKEND_COMMIT="$BACKEND_COMMIT" \
  gateway
```

构建失败时不要进入维护状态。网络下载失败可以只重试失败的镜像。

不要把 Swap 写入 `/etc/fstab`。发布稳定且 `free -h` 显示的 available 内存足以容纳
`swapon --show` 的 used 数量后，执行 `swapoff /swapfile`，删除 `/swapfile` 并再次确认
`swapon --show` 为空。

## 7. 每次更新前全量备份；迁移时进入维护

**每次生产更新都必须在切换容器前，全量备份业务库和 `umami` 库。** 仅更新前端、gateway、
配置或 Umami 镜像，以及没有数据库迁移时，也不能跳过。已有每日备份不能替代本次更新前快照。
Umami 全量快照应包含完整结构与数据，包括账号、网站配置、访问事件以及已有的回放/热图数据；
不要只导出事件表或选择性业务表。

先记录待执行的迁移及第 12 节的回滚方案。只有已确认新结构、数据语义与旧版 web、全部
后台进程兼容的迁移，才可走日常在线更新；不能仅凭“没有删除字段”判断安全。未知兼容性、
长时间锁表或数据重写的迁移走维护窗口。普通在线备份不需要停止或重启 PostgreSQL。

维护窗口必须按以下顺序停写，不能只停 web/cron：

1. 备份入口配置，让 `nwu.icu` 和 `api.nwu.icu` 的业务入口均返回 503；通过
   `openresty -t` 后平滑重载，确认包括 API、投稿和归档入口在内均被阻断。
2. 停止旧 web 和 cron。确认已开始的请求、上传和 cron 子任务退出；检查
   [发布验收说明](release-validation.md) 中的任务统计。现有 worker 没有暂停领取/优雅排空
   开关：必须让可执行队列和活动任务排空，或事先确定中止与重试方案，不能把 SIGTERM 当作排空。
3. 停止 `resource-worker`、`archive-worker`、`archive-cleaner`，再次检查全部五个写入服务
   已停止且没有遗留写入进程。检查未完成任务和文件状态；存在中断任务时先处置，不继续迁移。
   不为了清空统计而删除任务或改状态。其他临时管理命令/外部写入者也必须结束。
4. 保持 `pgsql` 运行，确认停写后再制作下面的双库快照。若升级 Umami 并迁移其数据库，
   同时暂停 Umami 写入；否则不更换、不停止 Umami。

停止命令必须在旧发布目录中加载旧 manifest 和 override 执行：

```bash
# 仅在维护已获确认、入口已阻断后执行。
old_dc() {
  (set -euo pipefail
   cd "$OLD/NWU.ICU"
   if [ -f ../release-images.env ]; then
     set -a; source ../release-images.env; set +a
   fi
   export ENV_FILE=/etc/nwuicu/production.env
   docker compose --env-file /etc/nwuicu/production.env \
     -f docker-compose.production.yaml -f ../docker-compose.server.yaml "$@")
}
# OLD 必须事先根据运行中容器的 Compose 标签核对，不能拿历史发布记录代替。
old_dc stop web cron
# 按上述第 2 步确认队列、请求和子任务已排空后再执行：
old_dc stop resource-worker archive-worker archive-cleaner
old_dc ps -a
```

以下命令在服务器 Bash 中执行，生成两个 PostgreSQL 自定义格式全量快照、对象清单与校验文件：

```bash
set -euo pipefail
umask 077
BACKUP_DIR=/root/nwuicuBack/predeploy_$RELEASE_ID
install -d -m 700 "$BACKUP_DIR"

DB_USER=$(docker exec pgsql printenv POSTGRES_USER)
DB_NAME=$(docker exec pgsql printenv POSTGRES_DB)

for database in "$DB_NAME" umami; do
  if [ "$database" = "$DB_NAME" ]; then name=business_full; else name=umami_full; fi
  docker exec pgsql pg_dump -U "$DB_USER" -d "$database" \
    -Fc --no-owner --no-privileges > "$BACKUP_DIR/$name.dump"
  test -s "$BACKUP_DIR/$name.dump"
  # Read/decompress the entire archive without restoring or modifying a database.
  docker exec -i pgsql pg_restore --file=/dev/null < "$BACKUP_DIR/$name.dump"
  docker exec -i pgsql pg_restore --list \
    < "$BACKUP_DIR/$name.dump" > "$BACKUP_DIR/$name.list"
  test -s "$BACKUP_DIR/$name.list"
done
(
  cd "$BACKUP_DIR"
  sha256sum business_full.dump business_full.list umami_full.dump umami_full.list > SHA256SUMS
  sha256sum -c SHA256SUMS
)
```

任一导出、完整读取、对象清单或 SHA-256 校验失败，都必须停止更新，不切换容器、不执行迁移。
数据库不存在时应核对配置，不能静默跳过 `umami`。记录本次备份目录，保留旧发布和历史备份。
两个库的快照与清单应在获得对应传输授权后下载到本地，并再次执行 `sha256sum -c SHA256SUMS`。
Umami 快照包含账号与访问数据，不能发布到仓库或公开目录。

`--no-owner --no-privileges` 不省略表结构或数据；恢复时需复用已存在的数据库角色与私有配置，
并按目标库所有者恢复。数据库角色、凭据及 `/etc/nwuicu/*.env` 不包含在这两个库的快照中。

## 8. 迁移和核心启动

现有 `pgsql` 已连接 `nwuicu_app-network`，网络别名为 `db`。正常更新不要重建、重启或启动
第二个 PostgreSQL 容器。

先查看迁移计划和部署检查：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  run --rm --no-deps web python manage.py showmigrations --plan

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  run --rm --no-deps web python manage.py check --deploy
```

通过一次性容器迁移，避免失败时因 restart policy 循环执行：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  run --rm --no-deps web python manage.py migrate --noinput
```

日常更新只收集静态文件，不重复创建管理员、初始化学院或改写学期：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  run --rm --no-deps web python manage.py collectstatic --noinput
```

`create_super_user`、`create_init_avatar`、`createcachetable`、`init_school` 和
`update_semester` 属于空数据库首次初始化或独立维护任务，已有生产库不要每次运行。
尤其 `update_semester` 会按 ID 重写现有名称；确需修正业务数据时必须单独检查前后差异。
首次初始化前检查管理员参数、默认头像文件、数据库缓存配置和预期学院/学期列表，
逐项执行并验收，不把初始化串放回 web 启动命令。

仅启动核心服务，不让 Compose 触碰 PostgreSQL：

```bash
CUTOVER_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
export CUTOVER_STARTED_AT
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  up -d --no-deps --no-build --pull never --wait --wait-timeout 180 web gateway
```

在解除维护前严格检查本机入口的状态与 JSON 内容，命令见
[发布验收说明](release-validation.md)。以下命令仅用于人工查看，不替代断言：

```bash
curl -H 'Host: nwu.icu' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:18080/
curl -H 'Host: nwu.icu' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:18080/api/user/csrf/
```

## 9. OpenResty / Nginx 配置

1Panel OpenResty 容器名当前为 `1Panel-openresty-lzym`。应修改宿主机挂载源，不要进入容器
编辑临时文件。

关键文件：

```text
/opt/1panel/apps/openresty/openresty/conf/conf.d/nwu.icu.conf
/opt/1panel/apps/openresty/openresty/www/sites/nwu.icu/proxy/proxy.conf
/opt/1panel/apps/openresty/openresty/conf/conf.d/api.nwu.icu.conf
/opt/1panel/apps/openresty/openresty/www/sites/api.nwu.icu/proxy/root.conf
```

日常前后端更新保持端口不变时，不需要修改 OpenResty，只需重建并替换 Docker 服务。

`nwu.icu.conf` 的主路由应代理到 gateway：

```nginx
location / {
    proxy_pass http://127.0.0.1:18080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header User-Agent $http_user_agent;
    proxy_connect_timeout 10s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
}
```

`nwu.icu/proxy/proxy.conf` 的 API 上游同样是 `127.0.0.1:18080`。外层和 gateway
必须同时保留以下限制：

| 路径 | `client_max_body_size` | 额外要求 |
| --- | ---: | --- |
| 普通 `/api/` | `2m` | `proxy_request_buffering off` |
| `/api/upload/` | `26m` | 发送/读取超时 300 秒 |
| `/api/upload/request/` | `1025m` | 关闭请求缓冲，超时 300 秒 |
| `/api/management/resources/upload/` | `2g` | 关闭请求缓冲，超时 300 秒 |
| `/api/resources/file/` | 不放宽请求体 | `proxy_cache off`、`proxy_buffering off`，读取超时 300 秒 |

文件代理必须显式关闭继承的全局 `proxy_cache`，即使应用响应包含 `private, no-store`。
否则外层缓存逻辑可能不向上游发送 `Range`，导致后端和 gateway 返回 206，而公网入口变成整文件 200。
`nwu.icu` 与 `api.nwu.icu` 都要检查；验收时用 GET + Range 比对字节，不能只测 HEAD 或首页状态。

`api.nwu.icu/proxy/root.conf` 保持相同规则，但上游为 `127.0.0.1:8000`，并额外拒绝：

```nginx
location ^~ /media/ {
    return 404;
}
```

`/etc/nwuicu/production.env` 的 `ALLOWED_HOSTS` 必须包含 `api.nwu.icu`；修改前将该文件以
`0600` 权限复制到本次备份目录。环境文件内容变化后要重建 `web` 容器才能生效。

修改前先备份四个文件。每次必须先检查、后重载：

```bash
docker exec 1Panel-openresty-lzym openresty -t
docker exec 1Panel-openresty-lzym openresty -s reload
```

如果 `openresty -t` 失败，不要重载。重载后验证：

```bash
curl -I https://nwu.icu/
curl -I https://nwu.icu/api/user/csrf/
curl -I https://nwu.icu/media/test
curl -I https://api.nwu.icu/api/user/csrf/
```

预期分别为 200、200、404、200。

## 10. 分阶段启动后台服务

按 [发布验收说明](release-validation.md) 保存队列基线；确认核心接口通过后启动三个后台服务。
维护发布先保持公网 503，验证后台恢复和待处理任务，再恢复入口配置；验证失败继续维护。

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  up -d --no-deps --no-build --pull never resource-worker archive-worker archive-cleaner
```

cron 使用镜像内版本化的 `/app/deploy/nwuicu.crontab`，生产时区为 `Asia/Shanghai`：

```text
00:00  更新学期
03:15  清理已批准投稿的临时文件
03:30  清理过期投稿文件
```

后两项可能删除符合条件的临时文件，应单独确认后再启动：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  up -d --no-deps --no-build --pull never cron
```

业务库和 `umami` 库的每日全量备份由宿主机的 `nwuicu-db-backup.timer` 管理，每天 04:00（`Asia/Shanghai`）
执行。备份写入 `/root/nwuicuBack/daily/<timestamp>/`，分别生成 `nwuicu_full_<timestamp>.dump` 和
`umami_full_<timestamp>.dump`，以及各自的 `pg_restore --list` 对象清单、元数据和 `SHA256SUMS`。
每份快照先通过 `pg_restore --file=/dev/null` 完整读取验证；任一库失败都会让任务失败，目录保留为
`.incomplete_*`，不发布为成功备份。timer 使用
`Persistent=true`，服务器错过执行时间时会在下次启动后补跑；它不会自动删除历史备份。
每日备份不能替代每次更新前第 7 节的双库全量快照。元数据的 `backup_format_version=2` 表示双库格式；
`deploy/nas-download-latest-db-backup` 同时校验两个库，并兼容历史单库备份。更新备份脚本时应配套更新
已有 NAS 下载端，否则旧版“恰好一个 dump/list”检查会拒绝新的双库目录。

安装或更新任务：

```bash
install -m 0755 deploy/nwuicu-db-backup /usr/local/sbin/nwuicu-db-backup
install -m 0644 deploy/systemd/nwuicu-db-backup.service \
  /etc/systemd/system/nwuicu-db-backup.service
install -m 0644 deploy/systemd/nwuicu-db-backup.timer \
  /etc/systemd/system/nwuicu-db-backup.timer
systemctl daemon-reload
systemctl enable --now nwuicu-db-backup.timer
```

安装后先手工执行并验证一次：

```bash
systemctl start nwuicu-db-backup.service
systemctl status --no-pager nwuicu-db-backup.service
systemctl list-timers --all nwuicu-db-backup.timer
latest=$(find /root/nwuicuBack/daily -mindepth 1 -maxdepth 1 -type d \
  ! -name '.incomplete_*' -printf '%f\n' | sort | tail -1)
(cd "/root/nwuicuBack/daily/$latest" && sha256sum -c SHA256SUMS)
```

## 11. 验收与观察

统一执行 [发布验收说明](release-validation.md)：精确 HTTP 状态和响应结构、实际 JS/CSS、
核心业务接口、下载 Range、六个服务的镜像/状态、队列进展，以及持续 15 分钟观察。
后台服务没有 healthcheck，`running` 或重启数为零不能单独证明消费正常。
单实例 Compose 替换有短暂中断；`--wait` 不提供零停机保证。

至少检查：

- 首页、登录和验证码；
- 课程列表、课程详情、评价和评价回复；
- 学院、教师和学期接口；
- 资源浏览、搜索、授权下载与投稿；
- `/manage` Passkey；
- `api.nwu.icu` 兼容接口；
- `/media/` 返回 404；
- 新容器重启次数为 0；未重建容器的历史计数在观察期不增加。

从 `$CUTOVER_STARTED_AT` 开始记录，后台切换和公网验收通过后再连续观察至少 15 分钟。
读取过去 15 分钟日志不是等待观察 15 分钟。以下辅助命令不能替代上述完整验收：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  ps

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  logs --since "$CUTOVER_STARTED_AT" web gateway resource-worker cron archive-worker archive-cleaner

docker inspect nwuicu-web-1 nwuicu-gateway-1 nwuicu-resource-worker-1 nwuicu-cron-1 \
  nwuicu-archive-worker-1 nwuicu-archive-cleaner-1 \
  --format '{{.Name}} restarts={{.RestartCount}} image={{.Config.Image}}'

docker exec nwuicu-gateway-1 sh -lc \
  "grep -R -q '$FRONTEND_COMMIT' /usr/share/nginx/html/assets && \
   grep -R -q '$BACKEND_COMMIT' /usr/share/nginx/html/assets"

curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null
curl -fsS https://api.nwu.icu/api/user/csrf/ > /dev/null

free -h
swapon --show
if [ "${LOCAL_BUILD_SWAP_CREATED:-0}" = 1 ]; then
  swapoff /swapfile
  rm -f /swapfile
  test -z "$(swapon --show=NAME --noheadings)"
fi
```

确认应用容器的重启次数符合上述基线、gateway 静态资源包含两个完整提交号、两个域名的 CSRF
接口均为 200。固定摘要发布还需核对容器镜像与本次 `release-images.env` 一致。
本节的 `swapoff`/删除命令仅适用于第 6 节备用构建创建的临时 Swap；默认拉取流程跳过它们。

## 12. 回滚边界

发布前记录旧/新提交与镜像、快照目录、实际待执行迁移、旧代码兼容性、数据转换影响，
以及每个失败阶段的恢复方案。不能仅凭执行过 `migrate` 命令就决定恢复整库；该命令可能无事可做。

| 已发生的变化 | 恢复方式与前提 |
| --- | --- |
| 没有应用迁移，也没有其他不兼容数据/配置变更 | 可重新加载旧 manifest/override，按核心→后台顺序切回六个服务并验收；不触碰数据库 |
| 已应用迁移，但验证过旧代码兼容当前结构和数据 | 可保留当前数据库，仅回退应用；兼容性须包含所有旧 worker/cleaner |
| 旧代码不兼容，但有已演练且不会丢失所需数据的逆迁移 | 进入维护、排空并停止全部写入者，保留失败现场快照后，按指定迁移目标回退并验收；不自动猜测目标 |
| 不可逆、数据已损坏，或没有验证过的兼容回退路径 | 保持维护，评估向前修复或恢复快照；数据库恢复须单独确认 |

恢复快照会丢失快照时刻之后的写入。决定恢复前必须记录恢复点、损失窗口和需保留的新数据，
并核对数据库与 media、已发布资源、归档缓存的一致性；两份数据库快照不包含这些文件。
仅业务库受影响时不要连带恢复健康的 Umami 库。只有已验证兼容的应用回退才适合自动化；
不得自动恢复数据库、覆盖生产配置或删除旧发布/镜像/备份。
普通代码回退不修改 OpenResty；只有本次改过入口时才按保存的配置恢复并先执行语法检查。

## 13. 当前发布记录

2026-09-22 collation 维护：

```text
处理前快照：/root/nwuicuBack/daily/20260922_190303
NAS 副本：/opt/nwuicu-db-backups/backups/20260922_190303
维护记录：/root/nwuicuBack/collation_20260922_190836
```

生产 PostgreSQL 17.11 的 glibc collation 从 2.36 变为 2.41。处理前完整读取并校验
自定义格式快照，且 NAS 副本的 `SHA256SUMS` 文件哈希与服务器一致。维护期间两个域名返回
503，停止 `web`、`cron` 和 `resource-worker`，保持 `pgsql` 运行；随后执行
`REINDEX DATABASE mynwuicu`，并刷新 `mynwuicu`、`postgres` 与 `template1` 的 collation
版本。验收时三个数据库的记录版本和实际版本均为 2.41，应用库无无效索引，所有容器
重启次数为 0，OpenResty 配置已恢复且与维护前备份一致。

2026-09-22 发布：

```text
发布目录：/opt/nwuicu/releases/20260922_2f450fe_944a505
后端：2f450fe02d3ded383e7f0d87d2efe68b74ef5fa1
前端：944a5058c58b4458240da91cfe5698df8cd029ea
后端镜像：nwuicu-web:2f450fe0
gateway 镜像：nwuicu-gateway:2f450fe0-944a5058
数据库卷：nwuicu_pgdata
数据库快照：/root/nwuicuBack/update_20260922_180901
```

本次发布应用了 `management_panel.0002_telegramnotificationsettings`，并在备份生产环境文件后
将 `api.nwu.icu` 加入 `ALLOWED_HOSTS`。构建使用 4GB 临时 Swap，验收后已关闭并删除。

2026-09-08 发布：

```text
发布目录：/opt/nwuicu/releases/20260908_152959
后端：5c50a521333fff50798092721e7b7c2fac2a4eef
前端：5cce738e4f6a5cfb6622142bc11e99193221766e
后端镜像：nwuicu-web:5c50a521
gateway 镜像：nwuicu-gateway:5c50a521-5cce738e
数据库卷：nwuicu_pgdata
```

完整迁移前快照和 SHA-256 清单保存在服务器 `/root/nwuicuBack/predeploy_20260908_152959`
及本地 `server-backups/`。
