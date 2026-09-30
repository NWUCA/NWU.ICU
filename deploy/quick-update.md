# NWU.ICU 日常更新速查

适用于普通前后端代码更新。默认域名和端口不变，因此**不修改、不重载 OpenResty**。
若涉及破坏性迁移、端口、域名或上传规则变更，改用
[完整生产发布 Runbook](production-runbook.md)。

默认由 GitHub Actions 构建镜像，服务器主动拉取固定摘要。首次配置和前后端配对发布见
[镜像发布说明](registry-images.md)。此流程不在服务器 build，不创建或清理构建用 Swap。

## 1. 创建固定提交的新发布目录

本地先确认前后端工作区干净、测试通过且提交已经 push，并且一组配套镜像已经发布成功。
登录 `ssh resour` 后设置：

```bash
OLD=<当前发布目录>
BACKEND_COMMIT=<已推送的后端完整提交号>
FRONTEND_COMMIT=<已推送的前端完整提交号>
BACKEND_TAG=$(printf '%s' "$BACKEND_COMMIT" | cut -c1-8)
FRONTEND_TAG=$(printf '%s' "$FRONTEND_COMMIT" | cut -c1-8)
RELEASE_ID=$(date +%Y%m%d_%H%M%S)
RELEASE=/opt/nwuicu/releases/${RELEASE_ID}_${BACKEND_TAG}_${FRONTEND_TAG}

install -d -m 755 "$RELEASE"
git clone --no-checkout "$(git -C "$OLD/NWU.ICU" remote get-url origin)" "$RELEASE/NWU.ICU"
git -C "$RELEASE/NWU.ICU" checkout --detach "$BACKEND_COMMIT"
git clone --no-checkout "$(git -C "$OLD/new_nwu_icu_frontend" remote get-url origin)" \
  "$RELEASE/new_nwu_icu_frontend"
git -C "$RELEASE/new_nwu_icu_frontend" checkout --detach "$FRONTEND_COMMIT"
```

确认两个仓库状态干净。不要在旧发布目录中 `git pull`。

## 2. 拉取并验证固定镜像

```bash
cd "$RELEASE/NWU.ICU"
set -euo pipefail
GATEWAY_REF=ghcr.io/moowantfree/new_nwu_icu_frontend@sha256:<Actions-Summary中的摘要>
bash deploy/pull-release-images "$BACKEND_COMMIT" "$FRONTEND_COMMIT" "$GATEWAY_REF" \
  > ../release-images.env.tmp
mv ../release-images.env.tmp ../release-images.env
set -a
source ../release-images.env
set +a
export ENV_FILE=/etc/nwuicu/production.env
```

拉取失败就停止，旧容器继续运行。脚本按 gateway 绑定的后端摘要拉取，避免同一后端提交
被重建后版本对不上。Manifest 不含密钥，保留在本次发布目录。

## 3. 配置只使用镜像的 Compose

将 `deploy/docker-compose.server.registry.example.yaml` 复制到 `../docker-compose.server.yaml`，
核对并保留旧 override 的额外运行配置。模板移除六个应用服务的 build，保留回环端口与
外部 `nwuicu_pgdata` 卷。执行 [镜像发布说明](registry-images.md) 第 3 节的配置断言。

```bash
dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    -f docker-compose.production.yaml \
    -f ../docker-compose.server.yaml "$@"
}

dc config --quiet
```

Compose >= 2.24.4 支持模板中的 `!reset`。重新登录该发布目录操作时，重新 source
`release-images.env` 并 export `ENV_FILE`。`dc up` 带 `--no-build --pull never`；
`dc run` 不加这两个选项：服务器 Compose 2.27 的 `run` 都不支持。
合并配置移除 `build` 并设置 `pull_policy: never`，一次性容器也只使用预先拉取的镜像。

## 4. 检查迁移并全量备份两个数据库

**每次更新都必须备份业务库和 `umami` 库，包括仅更新前端/gateway、配置以及没有迁移的更新。**
在任何容器切换或迁移前执行，不用已有每日备份替代本次快照。两份备份必须完整包含结构和数据，
并通过完整读取、对象清单及 SHA-256 校验；任一步失败就停止更新。

```bash
dc run --rm --no-deps web python manage.py showmigrations --plan
dc run --rm --no-deps web python manage.py check --deploy

BACKUP_TIME=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/root/nwuicuBack/update_$BACKUP_TIME
set -euo pipefail
umask 077
install -d -m 700 "$BACKUP_DIR"
DB_USER=$(docker exec pgsql printenv POSTGRES_USER)
DB_NAME=$(docker exec pgsql printenv POSTGRES_DB)

for database in "$DB_NAME" umami; do
  if [ "$database" = "$DB_NAME" ]; then name=business_full; else name=umami_full; fi
  docker exec pgsql pg_dump -U "$DB_USER" -d "$database" \
    -Fc --no-owner --no-privileges > "$BACKUP_DIR/$name.dump"
  test -s "$BACKUP_DIR/$name.dump"
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

记录备份目录，不删除历史备份。双库快照和清单获得对应传输授权后下载到本地再校验 SHA-256；
其中包含 Umami 账号、网站配置和访问数据，不能提交仓库或公开分享。
角色和凭据不包含在库快照中，恢复时复用既有角色/私有配置并指定目标库所有者。

如果要修改 `/etc/nwuicu/production.env`，先以 `0600` 权限复制到本次备份目录。
`ALLOWED_HOSTS` 必须包含 `api.nwu.icu`。

## 5. 迁移并分阶段切换

```bash
dc run --rm --no-deps web python manage.py migrate --noinput
dc run --rm --no-deps web bash -c \
  "python manage.py create_super_user && \
   python manage.py create_init_avatar && \
   python manage.py createcachetable && \
   python manage.py init_school && \
   python manage.py update_semester && \
   python manage.py collectstatic --noinput"

dc up -d --no-deps --no-build --pull never --wait web gateway
dc ps
curl -fsS https://nwu.icu/ > /dev/null
curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null

dc up -d --no-deps --no-build --pull never resource-worker cron archive-worker archive-cleaner
```

不要执行 `docker compose down`，不要重启 `pgsql`，不要删除 `nwuicu_pgdata`。

## 6. 验收固定版本

```bash
curl -fsS https://nwu.icu/ > /dev/null
curl -fsS https://nwu.icu/review/timeline > /dev/null
curl -fsS https://nwu.icu/review/course/3040 > /dev/null
curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null
curl -fsS https://api.nwu.icu/api/user/csrf/ > /dev/null

dc ps
docker inspect nwuicu-web-1 nwuicu-gateway-1 nwuicu-resource-worker-1 nwuicu-cron-1 \
  nwuicu-archive-worker-1 nwuicu-archive-cleaner-1 \
  --format '{{.Name}} restarts={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} image={{.Config.Image}}'
dc logs --since 10m web gateway resource-worker cron archive-worker archive-cleaner

docker exec nwuicu-gateway-1 sh -lc \
  "grep -R -q '$FRONTEND_COMMIT' /usr/share/nginx/html/assets && \
   grep -R -q '$BACKEND_COMMIT' /usr/share/nginx/html/assets"

free -h
swapon --show
```

确认两个域名的 CSRF 接口均为 200、容器健康、重启次数为 0、前端产物包含两个完整提交号，
并且没有持续 5xx 或迁移错误。容器镜像摘要必须与本次 `release-images.env` 一致。
拉取式发布不调整既有 Swap；仅明确选择 Runbook 中的服务器备用构建时才创建和清理临时 Swap。

## 7. 签发管理员 Passkey 绑定码

```bash
dc exec web python manage.py admin_passkey_enroll <username>
```

目标用户必须是启用状态的 staff 用户。命令输出的绑定码五分钟内有效，再次签发会立即使之前
尚未使用的绑定码失效。

## 最简记忆

```text
创建固定提交的新发布目录
→ 拉取并核对 GitHub 已构建的配套镜像，记录摘要
→ registry override 去掉 build，固定镜像摘要
→ showmigrations、check、业务库 + Umami 库全量 pg_dump、完整读取与 SHA-256 校验
→ migrate
→ 先 up web/gateway，验证后 up worker/cron/archive
→ curl、hash、重启次数和 logs 验证
```
