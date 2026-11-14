# 发布验收与观察

适用于 Runbook 与日常速查。以下命令在服务器 Bash、当前发布的 `NWU.ICU/` 中执行。
先加载本次 `release-images.env`（备用本地构建按 override 设置预期镜像），设置
`ENV_FILE=/etc/nwuicu/production.env`，并使用同一组 Compose 参数：

```bash
set -euo pipefail
export ENV_FILE=/etc/nwuicu/production.env
dc() {
  docker compose --env-file /etc/nwuicu/production.env \
    -f docker-compose.production.yaml -f ../docker-compose.server.yaml "$@"
}
```

## HTTP 与实际静态资源

核心切换后、后台切换后各执行一次：

```bash
python3 deploy/verify-release-http.py
```

脚本只读访问：严格要求首页、主要 HTML 路由、两个域名的 CSRF、学院接口为 200；
要求 `/media/` 为 404；校验 JSON 结构、CSRF token 和学院列表；读取首页引用的实际 JS/CSS
并检查状态、类型和非空内容。3xx、以 HTML 代替 JS/CSS、返回错误 JSON 都会失败。
这不等于浏览器功能测试，也不覆盖所有懒加载 chunk；人工打开登录、课程详情、`/manage`、
资源浏览页面，检查渲染、控制台及网络请求。投稿/管理员操作使用事先约定的测试账号和数据。

维护期间公网必须保持 503，先绕过外层入口验证本机应用：

```bash
python3 deploy/verify-release-http.py \
  --site http://127.0.0.1:18080 --api http://127.0.0.1:8000 --host nwu.icu
```

后台恢复检查通过后解除维护，再执行默认公网检查。不要为了让公网检查通过而提前解除维护。

### 公网管理入口

从公网执行以下检查。两个域名在 HTTP 和 HTTPS 下都应直接返回 404，包含不带末尾斜杠的 `/admin` 和登录页：

```bash
for host in nwu.icu api.nwu.icu; do
  for scheme in http https; do
    for path in /admin /admin/ /admin/login/; do
      url="$scheme://$host$path"
      code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "$url")
      printf '%s %s\n' "$code" "$url"
      test "$code" = 404 || exit 1
    done
  done
done
```

浏览器打开 `https://nwu.icu/manage`，页面文档和管理页面的 JS 应返回 200。未登录时，
`/api/management/session/` 应返回带 `detail` 的 JSON 404，页面显示“页面不存在”。
使用已绑定 Passkey 的 staff 测试账号登录并完成验证后，应能打开该账号有权限的管理页签。

## 六个服务、固定镜像与重启基线

切换前记录 PostgreSQL、Umami 的容器 ID、启动时间和重启次数，切换后确认未变化。
对本次六个应用服务执行以下断言（备用构建的两个 IMAGE 变量须设成 override 中的标签）：

```bash
export BACKEND_IMAGE GATEWAY_IMAGE
docker inspect nwuicu-web-1 nwuicu-gateway-1 nwuicu-resource-worker-1 nwuicu-cron-1 \
  nwuicu-archive-worker-1 nwuicu-archive-cleaner-1 | python3 -c '
import json, os, sys
containers = json.load(sys.stdin)
assert len(containers) == 6
for c in containers:
    service = c["Config"]["Labels"]["com.docker.compose.service"]
    expected = os.environ["GATEWAY_IMAGE" if service == "gateway" else "BACKEND_IMAGE"]
    assert c["Config"]["Image"] == expected, service + ": wrong image"
    assert c["State"]["Running"], service + ": not running"
    assert not c["State"].get("OOMKilled"), service + ": OOM"
    if service in ("web", "gateway"):
        assert c["State"]["Health"]["Status"] == "healthy", service
    print(service, c["Id"], "restarts=" + str(c["RestartCount"]))
'
docker exec nwuicu-gateway-1 sh -lc \
  "grep -R -q '$FRONTEND_COMMIT' /usr/share/nginx/html/assets && \
   grep -R -q '$BACKEND_COMMIT' /usr/share/nginx/html/assets"
```

新建容器重启数应为零；未重建服务可以有历史计数，但观察期不能增加，容器 ID 不能意外变化。
后台没有 healthcheck，不能用 `running` 代替下面的队列验证。

## 后台任务

切换前、切换后和观察结束均保存以下只读统计，不输出用户内容或通知载荷：

```bash
dc exec -T web python manage.py shell <<'PY'
from django.db.models import Count
from common.file.models import ResourcePublishJob, ResourceNotificationOutbox
from common.archive_models import ResourceArchive, ResourceArchiveNotice
for model in (ResourcePublishJob, ResourceNotificationOutbox, ResourceArchive):
    print(model.__name__, list(model.objects.values('status').annotate(count=Count('pk')).order_by('status')))
print('pending_archive_notices', ResourceArchiveNotice.objects.count())
PY
```

维护中 web 已停止时，用 Runbook 的 `old_dc run --rm --no-deps -T web python manage.py shell`
执行同一段查询；恢复后使用新发布的 `dc exec`。不得用会消费任务或修改状态的命令代替查询。

- 停写前检查发布/通知的 `processing`、归档的 `running/cancelling`，以及所有可执行待处理队列。
  还需检查 cron/cleaner 子任务和正在访问文件的进程；这些活动不能只靠上述状态计数推断。
- 可执行任务须有进展，失败/重试不能异常增加；延迟重试要核对 `available_at`，不能要求其立即清零。
  通知外发仍遵循既有授权，不为验收临时制造通知。队列为空时只能确认空闲与进程状态，
  不宣称已完成消费测试；需要端到端证明时使用已批准的测试任务。
- 当前 worker 没有暂停领取或优雅排空接口；统计与停止之间也非原子操作。入口阻断、上游生产者
  停止后，再排空、停止并复查。排空超时则停止发布并按预先确认的中止/恢复方案处理。
  不强杀任务、删除队列或清理卷来让检查通过。

## 下载与持续观察

### 资料下载验收

使用已知内容且超过 1024 字节的小型测试资料。维护期间通过 `127.0.0.1:18080` 验证本机 gateway，分别传入两个域名的 `Host` 和 `X-Forwarded-Proto: https`。公网恢复后分别通过 `nwu.icu` 和 `api.nwu.icu` 检查。直连 `127.0.0.1:8000` 时，授权成功的普通文件 GET 返回 `X-Accel-Redirect` 头和空正文。

| 项目 | 通过条件 |
| --- | --- |
| 断点续传 | 普通文件与旧版下载 URL 的 `Range: bytes=0-1023` GET 均返回 206 和 `Content-Range: bytes 0-1023/<总长度>`。响应体恰好 1024 字节，SHA-256 与源文件前 1024 字节一致。携带当前 ETag 的 `If-Range` 可续传，过期 ETag 返回完整样本及 200，越界 Range 返回 416。 |
| 权限和预览 | 公共样本可下载。仅登录可见的样本对匿名请求返回 401 或 403，普通用户能读取。仅资料管理员可见的样本对普通用户返回 404，有权限的账号能读取。外部请求 gateway 的 `/_protected/resources/` 下的文件返回 404。PDF 预览保留 `inline`，HTML 作为附件，文件响应带有 `private, no-store`。 |
| ZIP | 使用各域名有权访问的测试领取记录，确认现行和兼容 ZIP 路径的单段续传返回正确的 206 和字节。在隔离环境检查跨域名并发上限为 2、满额返回 429、名额在请求结束后释放，并确认清理任务保留活动下载直到文件锁释放。 |

测试下载可能计入业务统计。发布记录只保存状态码、长度、哈希和验收结果，不收录签名 URL、Cookie 或响应正文。

### 持续观察

在第一次 `up` 前记录并保存 `CUTOVER_STARTED_AT`（UTC）。全部后台服务启动且即时检查通过后，
每 30 秒执行 HTTP 检查，连续观察至少 900 秒，同时在起止点比较容器 ID/重启数与队列状态：

```bash
OBSERVE_END=$((SECONDS + 900))
while :; do
  date -u +%Y-%m-%dT%H:%M:%SZ
  python3 deploy/verify-release-http.py
  if (( SECONDS >= OBSERVE_END )); then break; fi
  sleep 30
done
dc logs --since "$CUTOVER_STARTED_AT" web gateway resource-worker cron archive-worker archive-cleaner
```

观察期间出现非预期状态、OOM、重启增长、迁移错误或持续 5xx，判定未通过；保留现场，
按 Runbook 的兼容性分类处理，不自动恢复数据库。人工检查日志时避免外传个人数据和密钥。
发布记录保存新旧提交/摘要、迁移、备份目录、切换与观察时间、检查结果和未验证项。
