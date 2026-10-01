# P2+ 基础设施（JWT / Celery / MinIO）

可选增强；**默认全部关闭或优雅降级**，不破坏 `smoke_loop.py` / `smoke_p2.py` / 本地 Demo `:8787`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `AUTH_DISABLED` | `1` | `1` 跳过 Bearer 鉴权 |
| `JWT_SECRET` | _(空)_ | 空则同样跳过鉴权；开启鉴权时必填 |
| `JWT_EXPIRE_MINUTES` | `1440` | 令牌有效分钟 |
| `DEMO_PASSWORD` | `demo` | 种子用户 `demo` 密码（DB 无 hash 时） |
| `CELERY_ENABLED` | `0` | `0` = 同步流水线 |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` | Redis broker |
| `CELERY_RESULT_BACKEND` | `redis://127.0.0.1:6379/1` | 结果后端 |
| `MINIO_ENDPOINT` | _(空)_ | 空 = 仅本地 `data/` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | — | 与 endpoint 一并配置才启用 |
| `MINIO_BUCKET` | `tradepilot` | 桶名（自动创建） |
| `MINIO_SECURE` | `0` | `1` 使用 HTTPS |

复制 `.env.example` 相关段落到 `.env`（**勿提交 `.env`**）。

## JWT

开启：

```env
AUTH_DISABLED=0
JWT_SECRET=please-change-me
```

```http
POST /api/auth/login
{"username":"demo","password":"demo"}
→ { "access_token": "...", "token_type": "bearer" }
```

受保护（鉴权开启时）：流水线 POST、财务写、`GET /api/files`。  
请求头：`Authorization: Bearer <token>`。

前端：`/api/health` 的 `auth_required` 为真时自动用 demo 登录并缓存 token。

## Celery + Redis

```powershell
# 终端 1：Redis
redis-server

# 终端 2：Worker（在 backend 目录，保证 import app）
cd backend
celery -A app.celery_app.celery_app worker --loglevel=info --pool=solo

# 终端 3：API
$env:CELERY_ENABLED="1"
uvicorn backend.app.main:app --app-dir backend --host 127.0.0.1 --port 8787
```

异步入队：`POST /api/orders/sample?async=1`（或 body `"async": true`）。  
Broker 不可用时自动回落同步。

轮询：`GET /api/tasks/{task_id}`  
轻量进度：`WS /ws/tasks/{task_id}`

## MinIO

```env
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=tradepilot
MINIO_SECURE=0
```

流水线写本地 `data/uploads` / `data/outputs` 后尝试 `put` 镜像；失败则仅本地。  
`GET /api/files`：本地优先，缺失时尝试 MinIO。

## 冒烟

```powershell
python scripts\smoke_infra.py   # 期望 INFRA_OK
```

断言：鉴权关闭路径可用；JWT 签发/校验（临时 secret）；Celery/MinIO 未起则 skip 非失败。
