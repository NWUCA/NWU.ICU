# NWU.ICU 部署说明

> 当前 `nwu.icu` 生产服务器采用 1Panel OpenResty 代理到宿主机回环端口。日常前后端更新、
> 数据库迁移、OpenResty 修改和回滚请以
> [生产发布 Runbook](production-runbook.md) 为准。本文后面的自动化/共享 Docker 网络方案
> 是通用替代方案，不是当前服务器的实际拓扑。

普通代码更新可直接查看 [日常更新速查](quick-update.md)。

推荐让前后端仓库保持同级目录，生产 Compose 会同时构建两个项目：

```text
/opt/nwuicu/
├── NWU.ICU/
└── new_nwu_icu_frontend/
```

配置文件分为两套，真实配置均已加入 `.gitignore`，不要提交密码或密钥：

| 环境 | 后端模板 | 前端模板 | 上传文件权限 |
| --- | --- | --- | --- |
| Windows 调试 | `.env.windows.example` → `.env.windows` | `.env.windows.example` → `.env.windows.local` | 不执行 `chmod` |
| Debian 生产 | `.env.production.example` → `.env.production` | 生产镜像使用同源 `/api`，通常无需运行时 env | 文件 `0640`、目录 `0750` |

## Windows + Docker 调试

Windows bind mount 不完整支持 Linux `chmod(2)`。调试模板设置了
`DISABLE_FILE_UPLOAD_CHMOD=True`；它只跳过 chmod，实际访问仍由 Windows ACL 和 Docker 挂载控制。

在 PowerShell 中执行：

```powershell
cd NWU.ICU
Copy-Item .env.windows.example .env.windows
# 按需修改本地管理员账号等配置
powershell -ExecutionPolicy Bypass -File scripts/start-windows.ps1
```

如果已有 `.env`，脚本会以它为基础生成 `.env.windows`，从而保留现有数据库凭据和挂载路径；
随后只覆盖 Windows 调试必需的 DEBUG、HTTPS、CSRF 和 chmod 开关。脚本会：

1. 创建缺失的本地环境文件和挂载目录；
2. 构建并启动 PostgreSQL、Django、定时任务和资源发布 worker；
3. 安装前端依赖，并在 `http://localhost:5173` 启动 Vite。

只启动后端：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-windows.ps1 -SkipFrontend
```

停止后端容器：

```powershell
$env:ENV_FILE='.env.windows'
docker compose --env-file .env.windows -f docker-compose.yaml down
Remove-Item Env:ENV_FILE
```

## Debian 自动化生产部署

生产结构为：已有的 Docker OpenResty → 共享 Docker 网络 → 前端 gateway → Django。
PostgreSQL、Django 和 gateway 均不直接暴露到公网。gateway 同时提供 SPA、Django
`/static/` 并代理 `/api/`；`/media/` 被明确拒绝，待审核投稿只能通过鉴权 API 下载。

前置条件：

- Debian 已安装 Docker Engine 和 Compose plugin；
- 现有 OpenResty 容器已负责公网域名、TLS 和证书续期；
- 域名 A/AAAA 记录已指向服务器，防火墙只需开放 22、80、443；
- 两个仓库按上面的同级目录方式 clone；
- AList 的 Local 存储物理目录已经存在，并允许容器 UID/GID `10001` 写入。

首次部署：

```bash
cd /opt/nwuicu/NWU.ICU
cp .env.production.example .env.production
chmod 600 .env.production
openssl rand -base64 48
# 将输出写入 SECRET_KEY，并替换所有 CHANGE_ME 项及实际宿主机路径
sudo bash ./scripts/deploy-production.sh .env.production
```

## 管理员 Passkey

管理员先以普通账号登录，再手动访问 `/manage`。管理操作和 Django Admin 均要求一次
Passkey 验证，提权有效期为 10 分钟，每次通过校验的管理请求都会重新计时；连续 10 分钟
没有管理请求后需重新验证。生产环境需将 `WEBAUTHN_RP_ID` 设为站点域名，
并在 `WEBAUTHN_EXPECTED_ORIGINS` 中逐项填写精确的 HTTPS origin。

首次绑定或添加设备时，在服务器签发五分钟有效的一次性许可码：

```console
docker compose exec web python manage.py admin_passkey_enroll <username>
```

凭据查询与撤销：

```console
docker compose exec web python manage.py admin_passkey_list <username>
docker compose exec web python manage.py admin_passkey_revoke <username> --credential-id <id>
docker compose exec web python manage.py admin_passkey_revoke <username> --all
```

许可码只显示一次且服务端仅保存摘要。设备全部丢失时，不提供在线降级恢复；通过服务器
撤销旧凭据后重新签发许可码。建议每位管理员至少绑定两个独立凭据。

脚本会自动：

1. 检查环境变量中是否仍有 `CHANGE_ME`；
2. 以 UID/GID `10001` 创建 media、static、目录索引持久化目录；
3. 构建前端 Nginx 镜像和后端镜像；
4. 启动数据库、迁移、Django、cron、资源 worker 和前端网关；
5. 执行 `manage.py check --deploy` 并验证资源目录可写；
6. 创建供 OpenResty 与 gateway 通信的外部 Docker 网络。

脚本不会修改或重载 OpenResty，也不会申请证书。首次上线需要按
[OpenResty 接入说明](openresty.md) 将现有 OpenResty 容器加入共享网络并添加站点配置。

部署脚本是幂等的。以后更新两个仓库后，再执行同一命令即可重新构建和滚动替换容器：

```bash
sudo bash ./scripts/deploy-production.sh .env.production
```

生产 Compose 也可以手动运行：

```bash
export ENV_FILE=.env.production
docker compose --env-file .env.production -f docker-compose.production.yaml config
docker compose --env-file .env.production -f docker-compose.production.yaml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yaml ps
```

查看关键日志：

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml logs -f web gateway resource-worker
```

## OpenResty、内部 gateway 与大文件上传

生产请求会经过两层代理：

- 现有 Docker OpenResty：负责域名、TLS，并代理到 `nwuicu-gateway:80`；
- `new_nwu_icu_frontend/nginx/default.conf`：内部提供前端并转发 API。

两层都必须保留相同的上传和超时策略，具体配置、共享网络和检查命令见
[OpenResty 接入说明](openresty.md)。当前业务允许最多 20 个文件、单文件 100 MiB，示例使用
`client_max_body_size 2g`、关闭请求缓冲并把代理超时设为 300 秒。如果以后增加“单次投稿总大小”
限制，应同时降低 Django、前端提示和两层代理的限制，避免形成资源耗尽入口。

不要通过 Nginx 直接暴露 `/media/resource_uploads/`。投稿原件处于待审核状态，必须经过
Django 的归属与状态检查。审核通过后的文件由资源 worker 发布到独立的 AList 物理目录。

## Debian 文件权限

生产环境保持：

```env
DISABLE_FILE_UPLOAD_CHMOD=False
```

Django 会把新文件设为 `0640`、目录设为 `0750`。不要使用 `chmod 777`。`/srv/nwuicu/media`
和 `/srv/nwuicu/index` 应归 UID/GID `10001`；AList 资源目录需要让 AList 与资源 worker 通过
共享组或 ACL 获得最小必要的读写权限。

## 数据、清理与备份

资源投稿采用“先发布、后通过”：所有文件复制成功且目录缓存更新成功后才标记通过；已有同名
文件不会被覆盖。cron 每天 03:00 重建资源目录索引，03:15 清理已通过投稿原件，03:30 清理
过期退回投稿。

至少备份以下内容，并定期实际演练恢复：

- PostgreSQL（使用 `pg_dump`，不要只复制正在运行的数据目录）；
- `.env.production`（加密保存）；
- `MEDIA_STORAGE_HOST_PATH` 中仍处于审核流程的文件；
- AList 的资源存储及其配置；
- `RESOURCE_INDEX_HOST_PATH` 可重建，不应作为唯一资料来源。

部署前若已有 Course、Teacher 或 Review 数据，需要执行：

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml exec web \
  python manage.py update_module_pinyin_name <module>
```
