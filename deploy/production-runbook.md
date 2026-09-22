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

前端不在服务器运行 `pnpm dev`。它通过多阶段 Dockerfile 发布：

1. Node 阶段运行 `pnpm install --frozen-lockfile` 和 `pnpm build`；
2. `dist/` 被复制到 gateway 镜像的 `/usr/share/nginx/html`；
3. gateway 内的 Nginx 提供 SPA，并把 `/api/` 转给 `web:8000`；
4. `/srv/nwuicu/static` 只读挂载到 `/srv/django-static`；
5. `/media/` 在 gateway 层固定返回 404。

因此前端更新需要重建 gateway 镜像，不要把 `dist/` 手工复制到 1Panel 站点目录。

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
RELEASE_ID=$(date +%Y%m%d_%H%M%S)
BACKEND_COMMIT=<完整后端提交号>
FRONTEND_COMMIT=<完整前端提交号>
RELEASE=/opt/nwuicu/releases/$RELEASE_ID
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

示例：

```yaml
services:
  web:
    image: nwuicu-web:<backend-short-sha>
    ports:
      - "127.0.0.1:8000:8000"

  cron:
    image: nwuicu-web:<backend-short-sha>

  resource-worker:
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
docker compose \
  --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml \
  -f ../docker-compose.server.yaml \
  config --quiet
```

解析后的项目名必须是 `nwuicu`，数据库卷名必须是 `nwuicu_pgdata`。如果出现新的数据库卷，
立即停止，不要启动 Compose。

## 6. 构建固定标签镜像

低内存服务器应串行构建；线上旧容器在此阶段继续运行：

```bash
export COMPOSE_PARALLEL_LIMIT=1

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  build web

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  build gateway
```

构建失败时不要进入维护状态。网络下载失败可以只重试失败的镜像。

不要长期保留 Swap。只有确有内存压力时才临时创建，并在发布稳定后执行 `swapoff` 再删除；
不要写入 `/etc/fstab`。

## 7. 进入维护与制作快照

先让 `nwu.icu` 和 `api.nwu.icu` 返回 503 维护页，执行 `openresty -t` 成功后再平滑重载。
确认两个域名均为 503 后停止旧 `web` 与 `cron`，保持 `pgsql` 运行。

迁移前必须制作完整自定义格式快照：

```bash
BACKUP_DIR=/root/nwuicuBack/predeploy_$RELEASE_ID
install -d -m 700 "$BACKUP_DIR"

docker exec pgsql sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' \
  > "$BACKUP_DIR/nwuicu_full_pre_migration_$RELEASE_ID.dump"

docker exec -i pgsql pg_restore --list \
  < "$BACKUP_DIR/nwuicu_full_pre_migration_$RELEASE_ID.dump" \
  > "$BACKUP_DIR/nwuicu_full_pre_migration_$RELEASE_ID.list"

sha256sum "$BACKUP_DIR"/*
```

快照和目录清单应下载到本地并再次校验 SHA-256。完整快照用于回滚迁移，不应以选择性业务表
导出替代。

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

随后执行初始化与静态文件收集：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  run --rm --no-deps web bash -c \
  "python manage.py create_super_user && \
   python manage.py create_init_avatar && \
   python manage.py createcachetable && \
   python manage.py init_school && \
   python manage.py update_semester && \
   python manage.py collectstatic --noinput"
```

仅启动核心服务，不让 Compose 触碰 PostgreSQL：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  up -d --no-deps --no-build web gateway
```

在解除维护前检查：

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
| `/api/resources/file/` | 不放宽请求体 | `proxy_buffering off`，读取超时 300 秒 |

`api.nwu.icu/proxy/root.conf` 保持相同规则，但上游为 `127.0.0.1:8000`，并额外拒绝：

```nginx
location ^~ /media/ {
    return 404;
}
```

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

先统计待处理资源任务；确认没有异常积压后启动 worker：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  up -d --no-deps --no-build resource-worker
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
  up -d --no-deps --no-build cron
```

## 11. 验收与观察

至少检查：

- 首页、登录和验证码；
- 课程列表、课程详情、评价和评价回复；
- 学院、教师和学期接口；
- 资源浏览、搜索、授权下载与投稿；
- `/manage` Passkey；
- `api.nwu.icu` 兼容接口；
- `/media/` 返回 404；
- 所有容器重启次数保持为 0。

切流后观察日志至少 15 分钟：

```bash
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  ps

docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml -f ../docker-compose.server.yaml \
  logs --since 15m web gateway resource-worker cron
```

## 12. 回滚边界

- 尚未迁移数据库：可以恢复旧镜像和旧 OpenResty 配置；
- 已执行迁移：不能只换回旧代码；必须保持维护页，停止新应用，恢复完整 `-Fc` 快照，
  再恢复旧镜像和 OpenResty 配置；
- 任何数据库恢复、旧配置覆盖或目录删除都必须再次确认；
- 不自动删除旧发布目录、旧镜像和备份。

## 13. 当前发布记录

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
