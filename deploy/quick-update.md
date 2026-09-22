# NWU.ICU 日常更新速查

适用于普通前后端代码更新。默认域名和端口不变，因此**不修改、不重载 OpenResty**。

如果包含破坏性数据库迁移、端口变更、域名变更或上传规则变更，请改用
[完整生产发布 Runbook](production-runbook.md)。

> 当前生产发布目录是固定提交。下面的 `<当前发布目录>` 应替换为实际目录，例如
> `/opt/nwuicu/releases/20260908_152959`。

## 1. 拉取前后端代码

```bash
cd <当前发布目录>/NWU.ICU
git pull --ff-only origin master

cd ../new_nwu_icu_frontend
git pull --ff-only origin master

cd ../NWU.ICU
BACKEND_TAG=$(git rev-parse --short=8 HEAD)
FRONTEND_TAG=$(git -C ../new_nwu_icu_frontend rev-parse --short=8 HEAD)
echo "$BACKEND_TAG $FRONTEND_TAG"
```

确认两个提交号是本次准备部署的版本。

## 2. 更新镜像标签

编辑 `<当前发布目录>/docker-compose.server.yaml`：

```yaml
services:
  web:
    image: nwuicu-web:<新的后端短提交号>
  cron:
    image: nwuicu-web:<新的后端短提交号>
  resource-worker:
    image: nwuicu-web:<新的后端短提交号>
  gateway:
    image: nwuicu-gateway:<新的后端短提交号>-<新的前端短提交号>
```

只替换四处镜像标签，不改端口、卷或网络。

## 3. 检查并构建

```bash
cd <当前发布目录>/NWU.ICU

dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    -f docker-compose.production.yaml \
    -f ../docker-compose.server.yaml "$@"
}

dc config --quiet
COMPOSE_PARALLEL_LIMIT=1 dc build web gateway
```

构建失败就停止，不重启线上容器。

## 4. 迁移前备份

```bash
BACKUP_TIME=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/root/nwuicuBack/update_$BACKUP_TIME
install -d -m 700 "$BACKUP_DIR"

docker exec pgsql sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' \
  > "$BACKUP_DIR/nwuicu_$BACKUP_TIME.dump"

docker exec -i pgsql pg_restore --list \
  < "$BACKUP_DIR/nwuicu_$BACKUP_TIME.dump" \
  > "$BACKUP_DIR/nwuicu_$BACKUP_TIME.list"

sha256sum "$BACKUP_DIR"/*
```

## 5. 迁移并更新容器

```bash
dc run --rm --no-deps web python manage.py showmigrations --plan
dc run --rm --no-deps web python manage.py migrate --noinput

dc up -d --no-deps --no-build web gateway
dc up -d --no-deps --no-build resource-worker cron
```

不要执行 `docker compose down`，不要重启 `pgsql`，不要删除 `nwuicu_pgdata`。

## 6. 验证

```bash
dc ps
curl -fsS https://nwu.icu/ > /dev/null
curl -fsS https://nwu.icu/api/user/csrf/ > /dev/null
curl -fsS https://api.nwu.icu/api/user/csrf/ > /dev/null
dc logs --since 10m web gateway resource-worker cron
```

确认容器健康、没有持续 5xx 或迁移错误，即完成本次更新。

## 7. 签发管理员 Passkey 绑定码

如果仍在前面定义了 `dc` 函数的同一个 Shell 会话中：

```bash
dc exec web python manage.py admin_passkey_enroll <username>
```

如果已经重新登录服务器，则执行完整命令：

```bash
cd <当前发布目录>/NWU.ICU
docker compose --env-file /etc/nwuicu/production.env \
  -f docker-compose.production.yaml \
  -f ../docker-compose.server.yaml \
  exec web python manage.py admin_passkey_enroll <username>
```

把 `<username>` 替换成真实用户名，输入命令时不要保留尖括号。目标用户必须是启用状态的
staff 用户。命令会输出一个五分钟内有效的一次性绑定码；该用户登录后打开 `/manage`，输入
绑定码完成 Passkey 注册。再次为同一用户签发时，之前尚未使用的绑定码会立即失效。

## 最简记忆

```text
pull 前后端
→ 更新四处镜像标签
→ build web gateway
→ pg_dump
→ migrate
→ up web gateway resource-worker cron
→ curl 和 logs 验证
```

日常更新无需修改 OpenResty。只有域名、回环端口、上传大小或代理超时发生变化时才修改它。
