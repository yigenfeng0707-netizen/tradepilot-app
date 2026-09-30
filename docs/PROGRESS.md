# TradePilot 进度说明（统一）

**更新日期**：2026-10-01  
**落点目录**：`tradepilot-app/`

## 已完成

| 项 | 说明 |
|----|------|
| A–E | 规格 / MVP / Demo / 路演稿 / smoke |
| F | 魔搭开源 LLM（Qwen3.5-35B-A3B） |
| G | 素材脚本 + Qwen 分镜 JSON |
| H | 扫描件 RapidOCR → 魔搭抽取（`IMAGE_LOOP_OK`） |
| I | **PDF 精美出单**（合同 + PI/CI/PL/报关，`PDF_OK`） |
| J | **创空间静态产品页包** `deploy-studio/`（Studio Running） |
| K | **90s 演示成片** `docs/media/TradePilot-demo-90s.mp4`（~93.5s，CDP 录屏 + edge-tts + ffmpeg） |
| L | **P2 财务 MVP**：收付汇核销 · 退税三态 · 毛利报表（`P2_OK`） |

## 验收

- `python scripts/smoke_loop.py` → `CLOSED_LOOP_OK`
- `python scripts/smoke_image.py` → `IMAGE_LOOP_OK`
- `python scripts/smoke_p2.py` → `P2_OK`
- 流水线返回 `pdf_paths` 含 5 个 PDF；前端可点「PDF」下载
- Demo：http://127.0.0.1:8787 （P1 结果下接 P2 财务台账）
- 90s 成片：`docs/media/TradePilot-demo-90s.mp4`（ffprobe ~93.5s）
- P2 用例：[`docs/P2-验收用例.md`](P2-验收用例.md)

## P2 已交付

| 能力 | API / UI |
|------|----------|
| 收付汇核销 | `/api/finance/payments` · `/api/finance/settlement/{id}` · 登记表单 |
| 退税三态 | `/api/finance/rebates`（待申报/已申报/已退税） |
| 毛利报表 | `/api/finance/margin`（演示成本率 72% + HS 退税估算） |
| 一键演示 | `/api/finance/demo-seed/{order_id}` |

## 仍缺 / P2+ later

| 项 | 说明 |
|----|------|
| 魔搭原生 VL | API 空 choices；已用 OCR+Qwen 替代 |
| Celery / Redis | 未做（同步流水线足够演示） |
| WebSocket / JWT / MinIO | 未做 |
| Playwright RPA | 未做（90s 成片用 CDP 录屏，非业务 RPA） |
| 真实采购成本 | 毛利用演示成本率，非 ERP 进销存 |

## 90s 成片说明（2026-10-01）

- 脚本：`scripts/make_demo_90s.py`
- 录屏：Playwright `connect_over_cdp(http://127.0.0.1:9222)`，**不**下载 Chromium；连续录一次样例全链路
- TTS：`edge-tts --rate=-5%`（equals 形式）
- 片头：可选拼接 `intro-5s-wan-moli.mp4`（补静音轨后 concat）
- 健康检查：`/api/health`

## 魔搭图/视频（魔粒）

| 能力 | 通道 | 结果 |
|------|------|------|
| 生图 | API `Qwen/Qwen-Image`（扣魔粒） | ✅ `docs/media/frame-hero-moli.png` |
| 视频 | 网页 AIGC（API Wan 现报 Invalid model provider） | ✅ `docs/media/intro-5s-wan-moli.mp4` |
| 90s 成片 | 本机 CDP + TTS + ffmpeg | ✅ `docs/media/TradePilot-demo-90s.mp4` |

## 创空间部署

- Studio: https://www.modelscope.cn/studios/gsym236998/tradepilot-demo  
- Demo: https://gsym236998-tradepilot-demo.ms.show  
- 本地完整版仍用 `uvicorn`；线上为样例回放（Docker 创空间仅 PUT `index.html`）。
- **2026-10-01 深夜**：已 redeploy P2 静态财务台账（`P2-STATIC-20261001`）  
  - PUT `deploy-studio/index.html` ✅ → Deploy HTTP 200 → Status Running  
  - 核验：页脚/健康 pill 含 `P2-STATIC-20261001`；回放后 P2 可见；种子收付→部分核销 + 待申报退税  
  - 线上无 FastAPI：收付/退税/毛利为浏览器内本地状态演示（完整 API 仍在本地 `8787`）
