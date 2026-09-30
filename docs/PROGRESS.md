# TradePilot P1 进度说明（统一）

**更新日期**：2026-09-30  
**落点目录**：`tradepilot-app/`

## 已完成

| 项 | 说明 |
|----|------|
| A–E | 规格 / MVP / Demo / 路演稿 / smoke |
| F | 魔搭开源 LLM（Qwen3.5-35B-A3B） |
| G | 素材脚本 + Qwen 分镜 JSON |
| H | 扫描件 RapidOCR → 魔搭抽取（`IMAGE_LOOP_OK`） |
| I | **PDF 精美出单**（合同 + PI/CI/PL/报关，`PDF_OK`） |
| J | **创空间静态产品页包** `deploy-studio/`（待 CDP 登录后 PUT） |

## 验收

- `python scripts/smoke_loop.py` → `CLOSED_LOOP_OK`
- `python scripts/smoke_image.py` → `IMAGE_LOOP_OK`
- 流水线返回 `pdf_paths` 含 5 个 PDF；前端可点「PDF」下载
- Demo：http://127.0.0.1:8787

## 仍缺

| 项 | 说明 |
|----|------|
| 魔搭原生 VL | API 空 choices；已用 OCR+Qwen 替代 |
| P2 收付退税 | 未做 |
| 90s 成片剪辑 | 已有分镜 + 魔搭关键帧/5s 片头素材，待 Remotion/录屏合成 |

## 魔搭图/视频（魔粒）

| 能力 | 通道 | 结果 |
|------|------|------|
| 生图 | API `Qwen/Qwen-Image`（扣魔粒） | ✅ `docs/media/frame-hero-moli.png` |
| 视频 | 网页 AIGC（API Wan 现报 Invalid model provider） | ✅ `docs/media/intro-5s-wan-moli.mp4` |
| 余额 | 顶栏 | 约 **3222** 魔粒（提交前见预计消耗 34） |

## 创空间部署

- Studio: https://www.modelscope.cn/studios/gsym236998/tradepilot-demo  
- Demo: https://gsym236998-tradepilot-demo.ms.show  
- 2026-09-30：已 PUT 单文件产品回放页并 Deploy → **Running**（Docker sdk；新文件需先 UI 创建，故 CSS/JS/样例内联进 `index.html`）  
- 本地完整版仍用 `uvicorn`；线上为样例回放。

是否需要把本地变更 commit 并 push 到 GitHub？
