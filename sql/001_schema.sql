-- TradePilot 核心数据模型（22 表）
-- 对齐方案书：六层架构 + P1「上传 PO → 解析 → 合同 → 一源多单」
-- 演示默认 SQLite；生产可迁移 MySQL（类型标注见注释）
-- 生成日期：2026-09-30

PRAGMA foreign_keys = ON;

-- ========== 1. 租户与权限 ==========
CREATE TABLE IF NOT EXISTS tenants (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  code          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  schema_prefix TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  username      TEXT NOT NULL,
  display_name  TEXT,
  role          TEXT NOT NULL DEFAULT 'operator', -- admin/operator/finance/viewer
  password_hash TEXT,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(tenant_id, username)
);

-- ========== 2. 交易对手与主数据 ==========
CREATE TABLE IF NOT EXISTS parties (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  party_type    TEXT NOT NULL, -- buyer/seller/forwarder/bank
  name          TEXT NOT NULL,
  name_en       TEXT,
  country       TEXT,
  address       TEXT,
  tax_id        TEXT,
  contact_email TEXT,
  meta_json     TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bank_accounts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  party_id      INTEGER REFERENCES parties(id),
  bank_name     TEXT NOT NULL,
  account_name  TEXT,
  account_no    TEXT,
  swift_code    TEXT,
  currency      TEXT DEFAULT 'USD',
  is_default    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS product_master (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  sku           TEXT,
  name_cn       TEXT NOT NULL,
  name_en       TEXT,
  hs_code       TEXT,
  unit          TEXT DEFAULT 'PCS',
  default_unit_price REAL,
  meta_json     TEXT,
  UNIQUE(tenant_id, sku)
);

CREATE TABLE IF NOT EXISTS hs_codes (
  code          TEXT PRIMARY KEY,
  description_cn TEXT,
  description_en TEXT,
  rebate_rate   REAL, -- 退税率，P2 用
  declare_elements TEXT
);

-- ========== 3. 文档入库与抽取 ==========
CREATE TABLE IF NOT EXISTS documents (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  doc_type      TEXT NOT NULL, -- po/contract/pi/ci/pl/water_slip/invoice
  source        TEXT NOT NULL DEFAULT 'upload', -- upload/generated/email
  filename      TEXT,
  storage_path  TEXT,
  mime_type     TEXT,
  sha256        TEXT,
  status        TEXT NOT NULL DEFAULT 'received', -- received/parsed/failed
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS document_extractions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id   INTEGER NOT NULL REFERENCES documents(id),
  extractor     TEXT NOT NULL, -- rules / llm:model / ocr+llm
  raw_text      TEXT,
  fields_json   TEXT NOT NULL, -- 结构化字段
  confidence_json TEXT,        -- 字段置信度
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== 4. 订单与合同（一源） ==========
CREATE TABLE IF NOT EXISTS trade_orders (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_no      TEXT NOT NULL,
  po_no         TEXT,
  buyer_id      INTEGER REFERENCES parties(id),
  seller_id     INTEGER REFERENCES parties(id),
  currency      TEXT NOT NULL DEFAULT 'USD',
  trade_term    TEXT, -- CIF/FOB/...
  destination   TEXT,
  payment_terms TEXT,
  total_amount  REAL,
  status        TEXT NOT NULL DEFAULT 'draft', -- draft/confirmed/shipping/closed
  source_doc_id INTEGER REFERENCES documents(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(tenant_id, order_no)
);

CREATE TABLE IF NOT EXISTS order_line_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES trade_orders(id) ON DELETE CASCADE,
  line_no       INTEGER NOT NULL,
  product_name  TEXT NOT NULL,
  product_name_en TEXT,
  sku           TEXT,
  hs_code       TEXT,
  qty           REAL NOT NULL,
  unit          TEXT DEFAULT 'PCS',
  unit_price    REAL NOT NULL,
  amount        REAL NOT NULL,
  packages      INTEGER,
  gross_weight_kg REAL,
  net_weight_kg   REAL,
  volume_cbm      REAL
);

CREATE TABLE IF NOT EXISTS contracts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_id      INTEGER NOT NULL UNIQUE REFERENCES trade_orders(id),
  contract_no   TEXT NOT NULL,
  lang          TEXT NOT NULL DEFAULT 'zh_en',
  body_md       TEXT,
  body_html     TEXT,
  risk_alerts_json TEXT,
  status        TEXT NOT NULL DEFAULT 'draft', -- draft/pending_confirm/confirmed
  confirmed_at  TEXT,
  storage_path  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contract_clauses (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id   INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  clause_key    TEXT NOT NULL, -- payment/shipping/penalty/marking
  content       TEXT NOT NULL,
  is_risk       INTEGER NOT NULL DEFAULT 0
);

-- ========== 5. 一源多单生成物 ==========
CREATE TABLE IF NOT EXISTS generated_docs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_id      INTEGER NOT NULL REFERENCES trade_orders(id),
  contract_id   INTEGER REFERENCES contracts(id),
  doc_type      TEXT NOT NULL, -- pi/ci/pl/customs_elements
  doc_no        TEXT,
  fields_json   TEXT NOT NULL, -- 派生字段快照
  storage_path  TEXT,
  status        TEXT NOT NULL DEFAULT 'draft',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consistency_checks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id      INTEGER NOT NULL REFERENCES trade_orders(id),
  passed        INTEGER NOT NULL,
  summary       TEXT,
  diffs_json    TEXT, -- [{field, expected, actual, source_a, source_b}]
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== 6. Agent 任务与审计 ==========
CREATE TABLE IF NOT EXISTS agent_tasks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_id      INTEGER REFERENCES trade_orders(id),
  task_type     TEXT NOT NULL, -- parse_po/draft_contract/gen_docs/consistency
  agent_name    TEXT NOT NULL, -- dispatcher/contract/docs
  autonomy_level INTEGER NOT NULL DEFAULT 1, -- L0-L4
  status        TEXT NOT NULL DEFAULT 'pending', -- pending/running/done/failed/blocked
  input_json    TEXT,
  output_json   TEXT,
  error_message TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS task_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id       INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
  event_type    TEXT NOT NULL,
  message       TEXT,
  payload_json  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  actor         TEXT NOT NULL, -- user:xxx / agent:xxx
  action        TEXT NOT NULL, -- read/generate/modify/approve/call_llm
  entity_type   TEXT,
  entity_id     TEXT,
  detail_json   TEXT,
  prev_hash     TEXT,
  entry_hash    TEXT NOT NULL, -- SHA256 链
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_call_logs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER,
  task_id       INTEGER REFERENCES agent_tasks(id),
  call_point    TEXT NOT NULL, -- LLM-1..LLM-12
  model         TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_ms    INTEGER,
  success       INTEGER NOT NULL,
  fallback_used TEXT, -- rules/template
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== 7. 模板与自治配置 ==========
CREATE TABLE IF NOT EXISTS doc_templates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  template_key  TEXT NOT NULL, -- contract_zh_en/pi/ci/pl
  name          TEXT NOT NULL,
  engine        TEXT NOT NULL DEFAULT 'jinja2',
  body          TEXT NOT NULL,
  version       INTEGER NOT NULL DEFAULT 1,
  is_active     INTEGER NOT NULL DEFAULT 1,
  UNIQUE(tenant_id, template_key, version)
);

CREATE TABLE IF NOT EXISTS autonomy_policies (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  action_key    TEXT NOT NULL, -- contract_confirm/tax_declare/large_payment
  max_level     INTEGER NOT NULL DEFAULT 2, -- 禁止超过该等级自动执行
  risk_threshold REAL,
  UNIQUE(tenant_id, action_key)
);

-- ========== 8. P2 预留（收付/退税/财务，表结构占位） ==========
CREATE TABLE IF NOT EXISTS payment_records (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_id      INTEGER REFERENCES trade_orders(id),
  direction     TEXT NOT NULL, -- in/out
  amount        REAL NOT NULL,
  currency      TEXT NOT NULL,
  value_date    TEXT,
  water_slip_doc_id INTEGER REFERENCES documents(id),
  matched       INTEGER NOT NULL DEFAULT 0,
  fx_rate       REAL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tax_rebate_claims (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  order_id      INTEGER REFERENCES trade_orders(id),
  status        TEXT NOT NULL DEFAULT 'pending', -- pending/eligible/claimed/rejected
  claim_amount  REAL,
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 合计 22 张表：
-- tenants, users, parties, bank_accounts, product_master, hs_codes,
-- documents, document_extractions, trade_orders, order_line_items,
-- contracts, contract_clauses, generated_docs, consistency_checks,
-- agent_tasks, task_events, audit_logs, llm_call_logs,
-- doc_templates, autonomy_policies, payment_records, tax_rebate_claims

-- 种子：演示租户
INSERT OR IGNORE INTO tenants (id, code, name) VALUES (1, 'demo', 'TradePilot Demo Tenant');
INSERT OR IGNORE INTO users (id, tenant_id, username, display_name, role)
  VALUES (1, 1, 'demo', '演示操作员', 'operator');
INSERT OR IGNORE INTO parties (id, tenant_id, party_type, name, name_en, country, address)
  VALUES
  (1, 1, 'buyer', 'ABC Trading FZE', 'ABC Trading FZE', 'AE', 'Jebel Ali Free Zone, Dubai'),
  (2, 1, 'seller', '杭州余杭光电有限公司', 'Hangzhou Yuhang Optoelectronics Co., Ltd.', 'CN', '余杭区，杭州，浙江');
INSERT OR IGNORE INTO bank_accounts (tenant_id, party_id, bank_name, account_name, account_no, swift_code, currency, is_default)
  VALUES (1, 2, 'Bank of China Hangzhou Branch', 'Hangzhou Yuhang Optoelectronics Co., Ltd.', '123456789012', 'BKCHCNBJ910', 'USD', 1);
INSERT OR IGNORE INTO hs_codes (code, description_cn, description_en, rebate_rate, declare_elements)
  VALUES ('9405110000', 'LED 平板灯', 'LED Panel Light', 0.13, '品牌;型号;功率;尺寸');
INSERT OR IGNORE INTO autonomy_policies (tenant_id, action_key, max_level) VALUES
  (1, 'contract_confirm', 2),
  (1, 'tax_declare', 2),
  (1, 'large_payment', 2);
