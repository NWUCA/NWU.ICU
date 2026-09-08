# 使用 Docker OpenResty 接入 NWU.ICU

生产部署脚本只负责 NWU.ICU 的目录、镜像、容器、迁移和健康检查，不会创建、修改或重载
OpenResty，也不会申请证书。HTTPS 与域名继续由现有 OpenResty 部署维护。

## 请求链路

```text
Internet
  -> OpenResty 容器（域名、TLS）
  -> nwuicu-gateway:80（Vue、静态文件、内部 API 代理）
  -> web:8000（Django）
```

OpenResty只需要访问 `nwuicu-gateway`，不需要加入 Django/PostgreSQL 的内部网络，也不要直接
代理到 Gunicorn。

## 1. 建立共享 Docker 网络

`.env.production` 默认使用：

```env
PROXY_NETWORK_NAME=web-proxy
```

部署脚本会在网络不存在时创建它。也可以手动创建：

```bash
docker network create web-proxy
```

NWU.ICU 的 `gateway` 会以固定网络别名 `nwuicu-gateway` 加入该网络。

## 2. 让 OpenResty 持久加入网络

在 OpenResty 自己的 Compose 中加入同一个外部网络：

```yaml
services:
  openresty:
    # 保留现有 image、ports、volumes 等配置
    networks:
      - web-proxy

networks:
  web-proxy:
    external: true
    name: web-proxy
```

然后重建 OpenResty 容器：

```bash
docker compose up -d
```

临时验证可以执行下面的命令，但它不会修改 OpenResty 的 Compose，容器重建后连接会消失：

```bash
docker network connect web-proxy <openresty-container-name>
```

不要把 NWU.ICU gateway 发布为 `0.0.0.0:8080` 来绕过 Docker 网络；共享网络能避免额外的
公网入口。

## 3. OpenResty 站点配置

将下面内容合并到现有 OpenResty 配置。证书路径按现有证书管理方案填写；如果 TLS 已在更外层
终止，只保留对应的监听方式即可。

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name nwu.icu www.nwu.icu;

    # 如果 ACME 客户端使用 HTTP-01，请同时保留它已有的 challenge location；
    # 更具体的 /.well-known/acme-challenge/ location 会优先于这里。
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name nwu.icu www.nwu.icu;

    ssl_certificate     /path/in/openresty/fullchain.pem;
    ssl_certificate_key /path/in/openresty/privkey.pem;

    # 普通页面和 API 默认最多 2 MiB；上传路由在下方单独放宽。
    client_max_body_size 2m;

    # 使用 Docker 内置 DNS，gateway 重建并更换 IP 后无需重启 OpenResty。
    resolver 127.0.0.11 valid=30s ipv6=off;

    location = /api/upload/ {
        client_max_body_size 26m;
        set $nwuicu_upstream http://nwuicu-gateway:80;
        proxy_pass $nwuicu_upstream;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 同时覆盖新建投稿和 /api/upload/request/<id>/ 编辑投稿。
    location ^~ /api/upload/request/ {
        client_max_body_size 1025m;
        set $nwuicu_upstream http://nwuicu-gateway:80;
        proxy_pass $nwuicu_upstream;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /api/management/resources/upload/ {
        client_max_body_size 2g;
        set $nwuicu_upstream http://nwuicu-gateway:80;
        proxy_pass $nwuicu_upstream;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        set $nwuicu_upstream http://nwuicu-gateway:80;
        proxy_pass $nwuicu_upstream;
        proxy_http_version 1.1;

        # 大文件直接流向内部 gateway，避免 OpenResty 先在磁盘缓存完整请求。
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

除三个需要放宽请求体限制的上传入口外，OpenResty 只需整体代理到 gateway；内部 gateway
仍负责 `/api/`、`/static/`、前端路由以及拒绝直接访问 `/media/` 中的待审核文件。

## 4. 检查与重载

先确认两个容器都在共享网络中：

```bash
docker network inspect web-proxy
```

从 OpenResty 容器验证内部域名可达（根据镜像内可用工具选择其一）：

```bash
docker exec <openresty-container-name> wget -S -O /dev/null http://nwuicu-gateway/
docker exec <openresty-container-name> curl -I http://nwuicu-gateway/
```

检查配置并平滑重载：

```bash
docker exec <openresty-container-name> openresty -t
docker exec <openresty-container-name> openresty -s reload
```

如果镜像使用 `nginx` 作为命令名，则改为：

```bash
docker exec <openresty-container-name> nginx -t
docker exec <openresty-container-name> nginx -s reload
```

最后验证：

```bash
curl -I https://nwu.icu/
curl -I https://nwu.icu/api/user/csrf/
```

## 5. 常见问题

- `host not found in upstream "nwuicu-gateway"`：OpenResty没有加入 `web-proxy`，或者网络名不一致。
- 返回 `502 Bad Gateway`：先从 OpenResty 容器访问 `http://nwuicu-gateway/`，再检查
  `docker compose logs gateway web`。
- 上传返回 `413`：外层 OpenResty 和内部 gateway 的 `client_max_body_size` 必须都足够大。
- 上传约 60 秒后失败：同时检查浏览器请求超时、两层代理超时和 Gunicorn 超时。
- HTTPS 重定向循环：确保 OpenResty传递 `X-Forwarded-Proto $scheme`，并保持生产环境
  `TRUST_X_FORWARDED_PROTO=True`。
- OpenResty重建后再次失联：必须在 OpenResty Compose 中声明外部网络，不能只执行一次
  `docker network connect`。
