# NWU.ICU

NWU.ICU 是面向西北大学师生的课程评价与资料分享网站。

[访问网站](https://nwu.icu/) · [前端仓库](https://github.com/MooWantFree/new_nwu_icu_frontend)

## 功能与使用

- 课程评价：搜索课程或教师，查看评价、发表选课体验，并回复讨论。
- 资料下载：按目录浏览或搜索资料，预览 PDF、图片和文本，也可以选择多个文件打包下载。
- 资料投稿：登录后进入“分享资料”，选择目标目录并上传文件，审核通过后公开。可在投稿页面查看进度，审核结果通过站内信和邮件通知。
- 留言与公告：在留言板交流、反馈问题，在公告栏查看站点通知。
- 消息：查看私信、回复、收到的赞和系统通知。

资料默认允许游客浏览和下载，部分目录需要登录或管理员权限。需要账号的操作会提示登录。

管理员登录后访问 `/manage`，通过 Passkey 验证后，可按账号权限审核投稿、管理资料和公告。资料管理支持目录权限、回收站、操作记录和下载统计。

## 服务器部署

以下步骤用于在空白 Debian 服务器上首次安装，采用 Docker Compose 和容器化 OpenResty。已有站点请直接阅读下方“更新与备份”，避免新建数据库或覆盖配置。

### 1. 准备服务器

准备以下条件：

- 按 [Docker 官方说明](https://docs.docker.com/engine/install/debian/)安装 Docker Engine、Buildx 和 Compose 插件。
- 安装 Git、OpenSSL；服务器能够访问 GitHub 和镜像仓库。
- 将站点域名解析到服务器，准备 HTTPS 证书及负责续期的 OpenResty。
- 开放 HTTP、HTTPS 和所需的 SSH 端口，数据库无需向公网开放。
- 为数据库、资料和备份预留磁盘空间。

下文命令均在服务器 Bash 中以 root 执行。将 `campus.example.com` 替换为自己的域名。

```bash
docker version
docker compose version
git --version
```

### 2. 获取前后端代码

进入准备存放项目的空目录，保持两个仓库同级：

```bash
git clone https://github.com/NWUCA/NWU.ICU.git
git clone https://github.com/MooWantFree/new_nwu_icu_frontend.git
cd NWU.ICU
cp .env.production.example .env.production
chmod 600 .env.production
openssl rand -base64 48
```

将最后一条命令生成的随机值写入 `.env.production` 的 `SECRET_KEY`。配置文件包含密码，不要提交到 Git 或公开分享。

### 3. 填写配置

编辑 `.env.production`，替换全部 `CHANGE_ME` 占位值，将 `DEPLOY_ROOT` 改为两个仓库所在目录的绝对路径，并检查：

| 配置项 | 填写内容 |
| --- | --- |
| `SECRET_KEY` | 上一步生成的随机密钥 |
| `DB_NAME`、`DB_USER`、`DB_PASSWORD` | 数据库名称、账号和强密码 |
| `DEFAULT_SUPER_USER_*` | 首次创建的管理员账号、密码及邮箱 |
| `EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_HOST_USER`、`EMAIL_HOST_PASSWORD` | 可用的 SMTP 服务，用于验证邮件和通知 |
| `UNIVERSITY_*`、`WEBSITE_NAME` | 学校名称、邮箱后缀与站点名称 |
| `MEDIA_STORAGE_HOST_PATH` | 待审核投稿等上传文件的保存目录 |
| `RESOURCE_STORAGE_HOST_PATH` | 已发布资料的保存目录 |
| `STATIC_STORAGE_HOST_PATH`、`RESOURCE_INDEX_HOST_PATH` | 静态文件和资料索引目录 |

域名相关配置示例：

```dotenv
ALLOWED_HOSTS=campus.example.com
CSRF_TRUSTED_ORIGINS=https://campus.example.com
FRONTEND_URL=https://campus.example.com
ADMIN_PUBLIC_URL=https://campus.example.com
WEBAUTHN_RP_ID=campus.example.com
WEBAUTHN_EXPECTED_ORIGINS=https://campus.example.com
```

`WEBAUTHN_RP_ID` 只填一个域名，允许来源必须属于该域名或其子域名。`ALLOWED_HOSTS` 可用逗号分隔多个域名；`CSRF_TRUSTED_ORIGINS` 和 `WEBAUTHN_EXPECTED_ORIGINS` 可用逗号分隔多个完整地址。`FRONTEND_URL` 和 `ADMIN_PUBLIC_URL` 各填写一个完整地址。保留模板中的 `DEBUG=False`、HTTPS 和文件权限设置。

默认存储路径可直接使用。创建目录并授予应用写入权限：

```bash
export ENV_FILE="$(pwd)/.env.production"
source deploy/load-config.sh
install -d -o "$UPLOAD_UID" -g "$UPLOAD_GID" -m 0750 \
  "$MEDIA_STORAGE_HOST_PATH" "$STATIC_STORAGE_HOST_PATH" \
  "$RESOURCE_INDEX_HOST_PATH" "$RESOURCE_STORAGE_HOST_PATH"
```

若使用已有资料目录，将 `RESOURCE_STORAGE_HOST_PATH` 改为实际绝对路径，并让配置中的 `UPLOAD_UID` / `UPLOAD_GID` 具备读取、遍历和写入权限。资料浏览不依赖 AList；与其他服务共享目录时，需同时设置那些服务的访问权限。

站点与部署配置统一保存在 `.env.production`：

| 配置项 | 用途 |
| --- | --- |
| `WEBSITE_NAME`、`UNIVERSITY_SHORT_NAME`、`SITE_START_YEAR` | 页面名称、校邮提示和页脚年份 |
| `FRONTEND_URL` | 网站访问地址；资料 canonical、站点地图默认使用该地址 |
| `SITE_ORIGIN` | 可选，单独指定搜索引擎收录使用的站点地址 |
| `UNIVERSITY_*_MAIL_SUFFIX` | 注册和校邮绑定规则，前后端共同使用 |
| `SITE_NAVIGATION_LINKS` | 首页导航，格式为单引号包裹的 JSON 数组，例如 `'[{"label":"校园门户","url":"https://portal.example.com"}]'` |
| `ANALYTICS_WEBSITE_ID`、`ANALYTICS_DOMAINS` | 统计站点 ID 与允许统计的域名列表；ID 留空则关闭 |
| `SENTRY_DSN` | 错误上报地址，留空则关闭 |
| `FRONTEND_GITHUB_URL`、`BACKEND_GITHUB_URL` | 版本链接及镜像来源校验 |
| `BACKEND_IMAGE_REPOSITORY`、`GATEWAY_IMAGE_REPOSITORY` | 拉取预构建镜像的仓库 |
| `DEPLOY_ROOT` | 前后端仓库所在目录的绝对路径 |
| `COMPOSE_PROJECT_NAME`、`PROXY_NETWORK_NAME`、`GATEWAY_NETWORK_ALIAS` | Compose 项目、代理网络及网关别名 |
| `UPLOAD_UID`、`UPLOAD_GID` | 应用镜像中的用户与资料目录权限 |
| `POSTGRES_VOLUME_NAME`、`BACKEND_PORT`、`GATEWAY_PORT` | 使用 registry 覆盖模板时的既有数据库卷及回环端口 |

公开配置随页面返回。修改站点名称、导航或统计设置后，重新创建后端服务并刷新页面即可，无需重建前端。配置中不包含数据库密码、邮件密码或服务端密钥。浏览器使用最新版 Chrome、Firefox 或 Safari。

更改 UID/GID 后需重建后端镜像并调整已有目录权限。使用 GitHub Actions 构建时，在后端仓库的 `.env.production.example` 中同步这两个公开构建值；前端仓库同名模板中的镜像仓库和后端仓库地址用于 CI 配对构建，不应放入任何服务器密钥。

### 4. 构建并启动

健康检查会读取 `FRONTEND_URL`，无需另外修改检查域名。

在后端目录定义后续使用的 Compose 命令：

```bash
export ENV_FILE="$(pwd)/.env.production"
source deploy/load-config.sh
cd "$DEPLOY_ROOT/NWU.ICU"
export COMPOSE_PARALLEL_LIMIT=1

dc() {
  docker compose --env-file "$ENV_FILE" -f docker-compose.production.yaml "$@"
}

docker network inspect "$PROXY_NETWORK_NAME" >/dev/null 2>&1 || docker network create "$PROXY_NETWORK_NAME"
dc config --quiet
```

重新登录服务器后，进入后端目录，再次加载配置并定义 `dc` 函数。已有服务器覆盖文件时，在 `dc` 中追加对应的 `-f` 参数。

构建前后端镜像，并将本次代码版本写入前端：

```bash
BACKEND_COMMIT=$(git rev-parse HEAD)
FRONTEND_COMMIT=$(git -C ../new_nwu_icu_frontend rev-parse HEAD)

dc build web cron resource-worker archive-worker archive-cleaner
dc build \
  --build-arg FRONTEND_COMMIT="$FRONTEND_COMMIT" \
  --build-arg BACKEND_COMMIT="$BACKEND_COMMIT" \
  gateway

dc up -d --no-build --wait --wait-timeout 180 db web gateway
dc exec -T web python manage.py check --deploy --fail-level ERROR
dc up -d --no-build resource-worker cron archive-worker archive-cleaner
dc ps
```

首次启动会建立数据库表、管理员账号和初始数据。若启动失败，先检查日志：

```bash
dc logs --tail 100 web gateway resource-worker archive-worker archive-cleaner
```

服务器构建内存不足时，可改用 [GitHub Actions 构建与镜像发布](deploy/registry-images.md)。该文档中的既有服务器路径和数据卷配置需按自己的部署调整。

### 5. 接入域名和 HTTPS

将 OpenResty 容器加入 `PROXY_NETWORK_NAME` 指定的网络，并在它自己的 Compose 配置中持久保存网络设置。站点反向代理目标为：

```text
http://<GATEWAY_NETWORK_ALIAS>:80
```

按 [OpenResty 接入说明](deploy/openresty.md)填写站点域名、证书路径和代理规则，再检查配置并重载。上传接口需要使用文档中的请求大小和超时设置，避免大文件上传失败。

前端与 API 使用同一域名，API 路径为 `/api/`。无需单独开放后端或 PostgreSQL 端口。若 OpenResty 运行在宿主机上，应将 gateway 端口只绑定到宿主机回环地址，再由 OpenResty 转发。

### 6. 导入资料与启用管理

将已有资料放入 `RESOURCE_STORAGE_HOST_PATH` 指向的目录，然后建立搜索索引：

```bash
dc exec -T web python manage.py reindex_resources
```

之后通过管理页面上传、移动或删除资料会自动更新索引；直接在服务器修改文件后，需要手动刷新索引。

使用配置中的管理员账号登录网站，在服务器为该账号生成 Passkey 绑定码，将下面的用户名替换为实际值：

```bash
dc exec web python manage.py admin_passkey_enroll 'your_admin_username'
```

访问 `https://campus.example.com/manage`，使用五分钟内有效的绑定码绑定设备。建议绑定两个独立凭据，方便设备丢失时继续管理。

### 7. 检查是否部署成功

```bash
curl -fsS "$FRONTEND_URL/" > /dev/null
curl -fsS "$FRONTEND_URL/api/user/csrf/" > /dev/null
dc ps
```

首页与 CSRF 接口应返回 HTTP 200。再用浏览器检查登录、课程评价、资料搜索和下载，提交一份测试资料并完成审核；同时确认批量下载和管理员 Passkey 可用。

## 更新与备份

部署使用当前版本的完整配置。更新时先切换后端，再切换前端，保留密码、项目名、数据库卷和存储路径。

首次安装完成后，保留部署目录、配置和提交号。更新使用独立发布目录及固定版本，先备份，再检查迁移，最后切换服务。

- 数据库使用 `pg_dump` 备份，验证备份能被 `pg_restore` 读取，并保存 SHA-256 校验值。
- 同时备份环境配置、上传文件和已发布资料。资料目录中的 `.nwuicu-management/` 包含回收站内容，需要一并保存。
- 先更新并验证 `web`、`gateway`，再处理投稿、打包和清理任务。替换后台服务前，检查活动任务是否完成。
- 保留旧版本与备份；回退代码前确认它兼容当前数据库，恢复数据库会丢失备份之后的写入。
- 不使用 `docker compose down` 更新，不删除持久卷，也不重复执行首次安装流程。

现有 `nwu.icu` 的发布操作见[日常更新速查](deploy/quick-update.md)，迁移与回滚见[生产发布手册](deploy/production-runbook.md)。这些文档包含该站点专用的目录、数据库和代理配置，自建站点需要按自己的环境调整。

资料权限、目录说明和管理操作见[资料浏览说明](deploy/resource-browser.md)。

## 反馈与贡献

使用问题可在站内留言板反馈，代码问题和改进建议可提交 issue 或 PR。参与开发前请阅读[测试要求](docs/testing.md)。
