# TradePilot 产品 Demo（P1 + P2 MVP）

外贸全链路 AI 数字员工 · **P1 主链路**：上传 PO → 解析 → 合同草稿 → 一源多单（PI/CI/PL）→ 一致性校验。  
**P2 财务**：收付汇核销 · 退税三态台账 · 订单毛利报表（接在 P1 结果下方）。

> 本目录是**可运行产品**，与仓库根目录的初赛方案书终稿（MD/HTML/DOCX/PDF）分离，互不覆盖。  
> 赛道 2 创业组参考评分码：T02-W-0081。

## 快速开始

```powershell
cd "D:\APPs\AI模型智能体大赛-余杭\tradepilot-app"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
copy .env.example .env
python scripts\smoke_loop.py
python scripts\smoke_p2.py
uvicorn backend.app.main:app --app-dir backend --host 127.0.0.1 --port 8787
```

浏览器打开：http://127.0.0.1:8787  

点击「加载样例 PO 并跑通全链路」，或「样例扫描件 OCR→魔搭抽取」，或上传/粘贴 PO。  
跑通后可在结果区下载 **合同 / PI / CI / PL PDF**，并在 **P2 财务台账** 中核销收付、推进退税、查看毛利。

## 验收

| 方式 | 命令/操作 | 期望 |
|------|-----------|------|
| P1 自动化 | `python scripts/smoke_loop.py` | 打印 `CLOSED_LOOP_OK` |
| P2 自动化 | `python scripts/smoke_p2.py` | 打印 `P2_OK` |
| 健康检查 | `GET /api/health` | `ok=true`，`demo_ready=true` |
| 手工 | 前端跑样例 → P2 写入演示收付 | 部分核销 → 补尾款已核销；退税三态可点 |

详细用例见 [`docs/P1-验收用例.md`](docs/P1-验收用例.md)、[`docs/P2-验收用例.md`](docs/P2-验收用例.md)。

## 配置（LLM · 魔搭开源模型）

默认走 **魔搭 API-Inference**（开源 Qwen，文本约有免费日额度；图/视频扣魔粒）：

1. 复制 `.env.example` → `.env`
2. 填写 `MODELSCOPE_API_KEY`（[Token 管理](https://modelscope.cn/my/myaccesstoken)）
3. 推荐模型：`Qwen/Qwen3.5-35B-A3B`（备用 `Qwen/Qwen3.5-27B`，以 `GET /v1/models` 现役为准）

```powershell
# 真模型闭环冒烟（期望 extractor 含 Qwen/... 且 CLOSED_LOOP_OK）
python scripts\smoke_loop.py

# 扫描件：RapidOCR → 魔搭 Qwen 抽取（期望 IMAGE_LOOP_OK）
python scripts\smoke_image.py

# P2 财务冒烟
python scripts\smoke_p2.py

# 可选：用魔搭 Qwen-Image / Wan 生成 90s 分镜素材（扣魔粒，可能排队）
python scripts\gen_ms_media.py
```

- `LLM_MODE=mock` 可无密钥纯规则演示；`api` 失败会软回退规则/模板。  
- **勿提交** `.env`；勿把 Token 写进代码或聊天。

## 目录结构

```
tradepilot-app/
  backend/app/          # FastAPI + Agent/服务（含 services/finance.py）
  frontend/             # 交互 Demo 页面（P1 + P2）
  sql/001_schema.sql    # 22 张核心表
  samples/              # 附录 C 样例 PO
  docs/                 # 规格、任务、验收、路演、进度
  scripts/smoke_loop.py
  scripts/smoke_p2.py
  requirements.txt
  .env.example
```

## 设计物与演示材料

- [`docs/P1-规格摘要.md`](docs/P1-规格摘要.md)  
- [`docs/P1-任务拆解.md`](docs/P1-任务拆解.md)（36 项）  
- [`docs/P1-验收用例.md`](docs/P1-验收用例.md)  
- [`docs/P2-验收用例.md`](docs/P2-验收用例.md)  
- [`docs/演示-90s分镜脚本.md`](docs/演示-90s分镜脚本.md)  
- [`docs/路演逐字稿-10分钟.md`](docs/路演逐字稿-10分钟.md)  
- [`docs/PROGRESS.md`](docs/PROGRESS.md)  
- [`docs/media/TradePilot-demo-90s.mp4`](docs/media/TradePilot-demo-90s.mp4)

## 与方案书技术栈的关系

方案书口径含 MySQL / Celery / Redis / MinIO / JWT / WebSocket。本 MVP 用 **SQLite + 同步流水线 + 本地文件** 保证可演示、可迭代；表结构已按 22 表对齐，可迁移生产。  
P2 财务业务已接表；Celery/Redis/JWT/MinIO/RPA 仍属 **P2+ later**。

## 安全提示

- 密钥只放环境变量或平台 Secrets。  
- 生成物在 `data/outputs/`，上传在 `data/uploads/`（已 gitignore）。  
- `/api/files` 仅允许读取 `data/outputs` 下文件。
