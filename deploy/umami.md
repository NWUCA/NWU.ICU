# Umami 复用现有 PostgreSQL

`docker-compose.umami.yaml` 只声明一个 Umami 服务，通过 external Docker 网络连接既有
PostgreSQL；不声明数据库容器或数据卷。数据库使用专用 `umami` 库和普通用户，不能把
`DATABASE_URL` 指向 Django 的业务库。两个库共用 PostgreSQL 进程、内存与磁盘资源。

当前生产 Runbook 记录：容器 `pgsql` 位于 `nwuicu_app-network`，数据库网络别名为 `db`。
本地开发网络也通常是 `nwuicu_app-network`，但必须按正在运行的实际项目名确认。
网络不存在时应检查名称，不要创建同名空网络来掩盖连接错误。

## 1. 确认网络并创建专用数据库

以下 Docker 命令在服务器 Linux 或提供 Docker CLI 的 WSL Debian1 中执行。
本地把 `pgsql` 替换成实际数据库容器名（通常是 `nwuicu-db-1`）：

```sh
docker inspect pgsql --format '{{json .NetworkSettings.Networks}}'
docker network inspect nwuicu_app-network
docker exec -it pgsql sh -c 'exec psql -U "$POSTGRES_USER" -d postgres'
```

在交互式 psql 中执行一次；如果同名用户或库已经存在，先核对用途，不要删除或覆盖：

```sql
CREATE ROLE umami LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password umami
CREATE DATABASE umami OWNER umami;
ALTER DATABASE umami SET timezone TO 'UTC';
\q
```

`\password` 会交互提示密码。数据库所有者可以在自己的库中创建 Umami 表。
不需要更改既有容器的 `POSTGRES_DB`、`POSTGRES_USER` 或初始化脚本，不需要重启 PostgreSQL。

## 2. 填写配置

复制 `.env.umami.example` 为私有配置文件，填写已发布的官方固定镜像版本或 digest、数据库
密码、两个不同的随机密钥以及实际网络名称。该模板故意不默认使用 `latest`。
官方镜像仓库为 `ghcr.io/umami-software/umami`。

密码中的 URL 保留字符需要 URI 编码；使用随机十六进制密码可避免这一问题。
私有配置权限设为 `0600`，不要提交真实密钥。

`512m` 容器限制和 `256MiB` Node 老生代堆限制是试运行起点，未经实测；启动迁移、事件上报
和面板查询都应观察内存峰值，限制过低会导致退出。数据库的额外内存不计入 Umami 容器限制。

## 3. 本地独立运行

先按项目约定启动现有开发栈。从 WSL 的 `/mnt/e/Code/nwuicu/NWU.ICU` 执行：

```sh
cp deploy/.env.umami.example deploy/.env.umami
chmod 600 deploy/.env.umami
# 编辑 deploy/.env.umami，填好所有必填项后再执行：
docker compose -p nwuicu-umami --env-file deploy/.env.umami \
  -f deploy/docker-compose.umami.yaml config --quiet
docker compose -p nwuicu-umami --env-file deploy/.env.umami \
  -f deploy/docker-compose.umami.yaml up -d --no-deps umami
```

打开 `http://127.0.0.1:13000`。首次启动会在专用库中执行 Umami 初始化/迁移；首次登录后
立即修改默认管理员密码。这个独立项目不会管理现有数据库容器或数据卷。

## 4. 生产接入方式

生产依照 [production-runbook.md](production-runbook.md) 和 [quick-update.md](quick-update.md)
准备已经 push 的固定提交与新发布目录。私有配置放在 `/etc/nwuicu/umami.env`，仅设置
`UMAMI_` 前缀变量，不覆盖已有生产配置。创建专用库、首次初始化之前按 Runbook 制作并校验
业务库快照；以后升级也须另外备份 `umami` 库。现有 `nwuicu-db-backup` 只备份业务库，
不会自动覆盖新增统计库。

在新发布的 `NWU.ICU` 目录中，保留生产要求的两个 Compose 文件，再追加本文件：

```sh
export ENV_FILE=/etc/nwuicu/production.env
umami_dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    --env-file /etc/nwuicu/umami.env \
    -f docker-compose.production.yaml \
    -f ../docker-compose.server.yaml \
    -f deploy/docker-compose.umami.yaml "$@"
}
umami_dc config --quiet
umami_dc pull umami
umami_dc up -d --no-deps --no-build umami
umami_dc ps umami
umami_dc logs --tail 100 umami
docker stats --no-stream nwuicu-umami-1 pgsql
```

只选择 `umami` 并使用 `--no-deps`；不运行全栈 `up`、`down` 或数据库重建。之后每次生产
更新都保留这个追加文件及相同项目名。该镜像直接拉取，不在生产服务器源码构建。

本配置仅提供本机面板入口和内部 `umami:3000` 地址。前端埋点、gateway 同域代理尚未接入；
正式接入时通过现有 gateway 发布脚本与采集接口，并保留真实客户端 IP 的可信代理链。
远程查看临时面板可使用 SSH 隧道：

```sh
ssh -L 13000:127.0.0.1:13000 resour
```

## 参考

- [Umami 官方 Compose](https://github.com/umami-software/umami/blob/master/docker-compose.yml)
- [Umami 环境变量](https://docs.umami.is/docs/environment-variables)
- [Compose 共享外部网络](https://docs.docker.com/compose/how-tos/networking/)
