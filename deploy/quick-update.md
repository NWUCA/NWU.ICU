# NWU.ICU 日常更新速查

适用于普通前后端代码更新。默认域名和端口不变，因此**不修改、不重载 OpenResty**。
若涉及破坏性迁移、端口、域名或上传规则变更，改用
[完整生产发布 Runbook](production-runbook.md)。

## 1. 创建固定提交的新发布目录

本地先确认前后端工作区干净、测试通过且提交已经 push。登录 `ssh resour` 后设置：

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

确认两个仓库状态干净。为新发布目录创建 `docker-compose.server.yaml`，只包含四个固定镜像
标签、`127.0.0.1` 回环端口和外部 `nwuicu_pgdata` 卷。不要在旧发布目录中 `git pull`。

## 2. 配置 Compose 和临时 Swap

```bash
cd "$RELEASE/NWU.ICU"
export ENV_FILE=/etc/nwuicu/production.env
export COMPOSE_PARALLEL_LIMIT=1

# production.env 中配置 FRONTEND_GITHUB_URL 和 BACKEND_GITHUB_URL，供页脚提交链接使用。

dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    -f docker-compose.production.yaml \
    -f ../docker-compose.server.yaml "$@"
}

dc config --quiet

test ! -e /swapfile
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
swapon --show
```

不要把 Swap 写入 `/etc/fstab`。

## 3. 串行构建固定镜像

```bash
dc build web
dc build \
  --build-arg FRONTEND_COMMIT="$FRONTEND_COMMIT" \
  --build-arg BACKEND_COMMIT="$BACKEND_COMMIT" \
  gateway
```

构建失败就停止，不重启线上容器。

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

dc up -d --no-deps --no-build web gateway
dc ps
curl -fsS https://nwu.icu/ > /dev/null
curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null

dc up -d --no-deps --no-build resource-worker cron
```

不要执行 `docker compose down`，不要重启 `pgsql`，不要删除 `nwuicu_pgdata`。

## 6. 验收并清理临时 Swap

```bash
curl -fsS https://nwu.icu/ > /dev/null
curl -fsS https://nwu.icu/review/timeline > /dev/null
curl -fsS https://nwu.icu/review/course/3040 > /dev/null
curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null
curl -fsS https://api.nwu.icu/api/user/csrf/ > /dev/null

dc ps
docker inspect nwuicu-web-1 nwuicu-gateway-1 nwuicu-resource-worker-1 nwuicu-cron-1 \
  --format '{{.Name}} restarts={{.RestartCount}} image={{.Config.Image}}'
dc logs --since 10m web gateway resource-worker cron

docker exec nwuicu-gateway-1 sh -lc \
  "grep -R -q '$FRONTEND_COMMIT' /usr/share/nginx/html/assets && \
   grep -R -q '$BACKEND_COMMIT' /usr/share/nginx/html/assets"

free -h
swapon --show
swapoff /swapfile
rm -f /swapfile
test -z "$(swapon --show=NAME --noheadings)"
```

确认两个域名的 CSRF 接口均为 200、容器健康、重启次数为 0、前端产物包含两个完整提交号，
并且没有持续 5xx 或迁移错误。

## 7. 签发管理员 Passkey 绑定码

```bash
dc exec web python manage.py admin_passkey_enroll <username>
```

目标用户必须是启用状态的 staff 用户。命令输出的绑定码五分钟内有效，再次签发会立即使之前
尚未使用的绑定码失效。

## 最简记忆

```text
创建固定提交的新发布目录
→ 更新四处镜像标签
→ 临时 Swap，串行 build web/gateway 并注入提交号
→ showmigrations、check、业务库 + Umami 库全量 pg_dump、完整读取与 SHA-256 校验
→ migrate
→ 先 up web/gateway，验证后 up worker/cron
→ curl、hash、重启次数和 logs 验证
→ swapoff 并删除临时 Swap
```
