# TradePilot 创空间静态产品演示

对应工作室创空间（当前为方案书页）：`gsym236998/tradepilot-demo`  
Demo：`https://gsym236998-tradepilot-demo.ms.show`

## 本目录文件

| 文件 | 用途 |
|------|------|
| `index.html` | 产品 Demo 单文件（内联 CSS/JS/样例；含 P2 财务静态演示） |
| `styles.css` | 样式（多文件备选；Docker 创空间通常只 PUT index） |
| `app-static.js` | 样例回放逻辑（备选） |
| `sample-result.json` | 用魔搭 Qwen 实跑后的样例结果 |

## 部署（需 Chrome CDP 9222 + 已登录魔搭）

按 `modelscope-studio-deploy` skill：

1. 启动带调试端口的已登录 Chrome（见 chrome-cdp-session）
2. PUT 上述文件到创空间 repo（`Revision=master`）
3. POST openapi deploy，轮询至 Running
4. Ctrl+F5 打开 `*.ms.show` 核验

> 当前本机 CDP `9222` 未开时，自动化部署会停在登录/会话步骤；文件已备好，可随时上线。

## 与本地完整版差异

静态版：样例回放 + **P2 财务台账本地状态演示**（无 OCR/上传/真 FastAPI）。  
完整版：`tradepilot-app` 本地 `uvicorn`（魔搭 LLM + OCR + PDF + P2 API）。
