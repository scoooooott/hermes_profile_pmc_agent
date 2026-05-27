---
name: pmc-data-onboarding
version: 1.0.0
description: "PMC 新客户数据接入向导：分 5 阶段逐步引导客户完成数据探查 → 字段匹配 → 编码归一化 → 管道配置 → 端到端验证。PMC Agent 加载此 Skill 后按流程推进，确认一步再走下一步。"
metadata:
  triggers:
    - "新客户接入"
    - "数据接入"
    - "PMC onboarding"
    - "数据源配置"
    - "客户数据导入"
  requires:
    bins: ["duckdb", "python3"]
    files:
      - "~/workspace/pmc-agents/pmc_template_api.py"
      - "~/workspace/pmc-agents/scripts/pmc_import.py"
      - "~/workspace/pmc-agents/scripts/refresh_dwd_metrics.py"
      - "~/pmc-data/pmc_ods.duckdb"
  related_skills:
    - "pmc-data-pipeline"
---

# PMC 数据接入向导

## 这是流程引擎 Skill，不是自动化脚本

本 Skill 定义了 PMC Agent 引导新客户完成数据接入的**5 阶段对话流程**。Agent 加载后按序执行，每个阶段确认后才进入下一阶段。不要跳过步骤。

## 接入前检查：管线是否就绪

```
# 检查 API 是否运行
curl -s http://localhost:8765/ | python3 -m json.tool

# 检查 DuckDB 是否可读
duckdb ~/pmc-data/pmc_ods.duckdb -c "SELECT COUNT(*) FROM ods_skus;"
```

若 API 未启动：
```bash
cd ~/workspace/pmc-agents && nohup python3 pmc_template_api.py &
```

---

## 阶段 A — 板块发现

### 目标

向客户展示 PMC 系统的 6 大业务板块，逐一确认客户拥有哪块数据、数据来源是什么。

### 对话流程

**Step 1：展示全景图**

向客户发送以下 6 板块清单（用表格，紧凑）：

| # | 板块 | 核心表 | 内容 | 必选？ |
|---|------|--------|------|--------|
| ① | 商品档案 | ods_skus + ods_cdm_skubom | SKU主数据 + 编码归一化映射 | ✅ 必选 |
| ② | 每日销量 | ods_sales | 日销量 × SKU × 店铺 | ✅ 必选 |
| ③ | 库存快照 | ods_inventory_domestic + ods_inventory_overseas | 国内库存 + 海外FBA库存 | ✅ 必选 |
| ④ | 采购明细 | ods_po + ods_po_recv | 采购单 + 收货明细 | 建议 |
| ⑤ | 发货明细 | ods_ship | 国内→海外补货发货 | 建议 |
| ⑥ | 供需映射 | ods_wmap | SKU→店铺→仓库关系 | ✅ 必选 |
| ⑦ | 规则参数 | ods_params | P1-P14 业务参数 | ✅ 必选 |

> 商品档案中 `ods_cdm_skubom` 是编码归一化枢纽表（psku → sku_id, rm_qty 拆解比例），如果客户有多套 SKU 编码体系，必须提供映射。

**Step 2：逐一确认**

对每个板块，问清楚三件事：
- 有这块数据吗？（有/无/部分有）
- 数据在哪？（ERP/WMS/CSV导出/API/数据库/手工维护）
- 更新频率？（实时/每日/每周/手动）

若客户不确定，引导举例：「比如你们的商品主数据，是在什么系统里管理的？能导出一份吗？」

**Step 3：汇总确认**

汇总成一张表反馈给客户确认：

```
PMC 数据接入确认单

| 板块 | 状态 | 来源 | 更新频率 | 备注 |
|------|------|------|----------|------|
| 商品档案 | ✅ 有 | 万里牛ERP导出CSV | 每周 | 需确认字段映射 |
| 每日销量 | ✅ 有 | 客户数据源 API | 每日T+1 | 已对接 |
| ... | ... | ... | ... | ... |
```

客户确认后进入阶段 B。

---

## 阶段 B — 数据探查

### 目标

请客户提供每块数据的样例（前 5-10 行），与 PMC 标准 Schema 做字段匹配检查。

### 标准 Schema 参考

从 DuckDB ODS 表结构反查（SQL 查询获取）：

```
duckdb ~/pmc-data/pmc_ods.duckdb -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='ods_skus' ORDER BY ordinal_position;"
```

**① 商品档案 ods_skus（11 业务列 + 1 元数据列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | sku_code | VARCHAR | ✅ | SKU编码，唯一标识 |
| 2 | spu_code | VARCHAR | | SPU/款式编码 |
| 3 | product_name | VARCHAR | | 商品名称 |
| 4 | category | VARCHAR | | 商品类目 |
| 5 | brand | VARCHAR | | 品牌 |  
| 6 | launch_date | VARCHAR | | 上架日期 YYYY-MM-DD |
| 7 | status | VARCHAR | | 上架状态：在售/下架 |
| 8 | lifecycle | VARCHAR | | 生命周期：新品/成长/成熟/衰退 |
| 9 | tier | VARCHAR | | 货盘等级：S/A/B/C/N |
| 10 | production_cycle_days | VARCHAR | | 生产周期天数 |
| 11 | manual_daily_sale_target | VARCHAR | | 人工日均销目标值 |
| 12 | moq | VARCHAR | | 最小起订量 |
| 13 | lead_time | VARCHAR | | 采购交期(天) |
| 14 | updated_at | VARCHAR | | 更新时间 |

**编码归一化表 ods_cdm_skubom**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | psku | VARCHAR | ✅ | 平台SKU（如 ERP 系统的 SKU） |
| 2 | sku_id | VARCHAR | ✅ | 归一化SKU（PMC 内部统一编码） |
| 3 | rm_qty | BIGINT | ✅ | 拆解比例（组合装 = 1拆N，单品 = 1） |

> **关键**：`psku` 可能是组合/套装编码，`rm_qty` 表示 1 个 psku 拆成多少个 sku_id。比如 `PSKU-A` 包含 3 个单品，则产生 3 行，每行 rm_qty=1（或按比例分配）。

**② 每日销量 ods_sales（4 列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | sku_code | VARCHAR | ✅ | SKU编码（归一化后） |
| 2 | sale_date | VARCHAR | ✅ | 销售日期 YYYY-MM-DD |
| 3 | daily_qty | VARCHAR | ✅ | 当日销售件数 |
| 4 | msu_id | VARCHAR | ✅ | 最小销售单元标识（如 CI-eu-DE） |

**③ 库存快照**

*ods_inventory_domestic（国内）*

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | sku_code | VARCHAR | ✅ | SKU编码 |
| 2 | inv_domestic | VARCHAR | ✅ | 国内仓库库存 |
| 3 | inv_purchase_onway | VARCHAR | ✅ | 采购在途（已下单未到仓） |
| 4 | snapshot_time | VARCHAR | ✅ | 快照时间戳 |

*ods_inventory_overseas（海外FBA）*

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | sku_code | VARCHAR | ✅ | SKU编码（归一化后） |
| 2 | shop | VARCHAR | ✅ | 店铺（如 CI-eu） |
| 3 | warehouse_code | VARCHAR | ✅ | 海外仓编码 |
| 4 | inv_available | VARCHAR | ✅ | 可售库存 |
| 5 | inv_onway | VARCHAR | ✅ | 在途库存 |
| 6 | snapshot_time | VARCHAR | ✅ | 快照时间戳 |

**④ 采购明细 ods_po（5 列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | po_number | VARCHAR | ✅ | 采购单号 |
| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
| 3 | order_date | VARCHAR | ✅ | 下单日期 |
| 4 | order_qty | VARCHAR | ✅ | 采购数量 |
| 5 | eta | VARCHAR | | 预计到货日期 |

**ods_po_recv（采购收货）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | po_number | VARCHAR | ✅ | 采购单号 |
| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
| 3 | receipt_date | VARCHAR | ✅ | 收货日期 |
| 4 | receipt_qty | VARCHAR | ✅ | 收货数量 |
| 5 | warehouse_id | VARCHAR | ✅ | 收货仓库 |

**⑤ 发货明细 ods_ship（7 列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | tracking_number | VARCHAR | ✅ | 物流单号 |
| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
| 3 | ship_date | VARCHAR | ✅ | 发货日期 |
| 4 | ship_qty | VARCHAR | ✅ | 发货数量 |
| 5 | dest_warehouse | VARCHAR | ✅ | 目的仓库 |
| 6 | expect_arrival | VARCHAR | | 预计到达日期 |
| 7 | shop | VARCHAR | | 店铺 |

**⑥ 供需映射 ods_wmap（4 列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | sku_code | VARCHAR | ✅ | SKU编码 |
| 2 | msu_id | VARCHAR | ✅ | 最小销售单元ID |
| 3 | warehouse_id | VARCHAR | | 供给仓库ID |
| 4 | updated_at | VARCHAR | | 更新时间 |

**⑦ 规则参数 ods_params（6 列）**

| # | 字段名 | 类型 | 必填 | 说明 |
|---|--------|------|------|------|
| 1 | param_no | VARCHAR | ✅ | 参数编号 P1-P14 |
| 2 | param_id | VARCHAR | ✅ | 参数英文标识 |
| 3 | param_name | VARCHAR | | 参数中文名称 |
| 4 | param_type | VARCHAR | | 数据类型/取值范围 |
| 5 | param_default | VARCHAR | | 默认值（JSON） |
| 6 | param_note | VARCHAR | | 备注 |

### 比对检查清单

拿到客户样例数据后，逐表做以下检查：

1. **必填字段是否齐全**：缺失必填字段 → 标记为「阻断」，需客户补充
2. **字段名能否映射**：客户字段名和标准字段名是否一致，不一致则记录映射关系
3. **数据类型是否一致**：日期是否统一 YYYY-MM-DD、数量是否为数字
4. **编码体系是否一致**：同一 SKU 在不同数据源里编码是否相同（这是下一阶段的重点）
5. **数据质量粗略检查**：是否有全 NULL 列、异常值、日期跳跃

### 输出：字段匹配报告

```
┌─ 商品档案 ods_skus ──────────────────────────────────────┐
│ 标准字段          │ 客户字段       │ 状态  │ 备注              │
│ sku_code          │ SKU编码        │ ✅ 匹配│                   │
│ spu_code          │ 款式编码       │ ✅ 匹配│                   │
│ product_name      │ 商品名称       │ ✅ 匹配│                   │
│ category          │ (无)           │ ⚠️ 缺失│ 可从类目表补充     │
│ brand             │ (无)           │ ⚠️ 缺失│ 需客户手动填写     │
│ tier              │ 等级           │ ⚡ 映射│ S/A/B/C vs 1/2/3/4│
│ production_cycle  │ 生产周期       │ ✅ 匹配│                   │
│ lead_time         │ (无)           │ ⚠️ 缺失│ 可设默认值30       │
└────────────────────────────────────────────────────────────┘
```

| 图例 | 含义 |
|------|------|
| ✅ | 可直接映射 |
| ⚡ | 需要值转换映射 |
| ⚠️ | 客户缺失，需补充或取默认值 |
| 🚫 | 阻断：核心字段缺失，无法接入 |

---

## 阶段 C — 编码归一化

### 目标

确认不同数据源的 SKU 编码是否统一。如不统一，帮客户建立 `ods_cdm_skubom` 映射。

### 为什么要归一化

PMC 系统各数据源可能使用不同的 SKU 编码体系：

| 来源 | 编码格式示例 | 备注 |
|------|-------------|------|
| 商品主数据 | `DA5002AE-4P1-XL` | 客户 ERP 原生 SKU |
| 日销量 | `BX451-Black-S` | 已归一化 SKU（产品-颜色-尺码） |
| BOM 映射表 | `01_BX451AB-1P01-S` | 带前缀的又一编码 |
| 采购明细 | `DA5002AE-4P1-XL` | 与商品主数据同体系 |

**不同体系间直接 JOIN 会得到空结果。** 必须通过 `ods_cdm_skubom` 做归一化桥接。

### 编码探测流程

**Step 1：建立 SKU 集合**

对客户提供的每块数据，提取所有不重复 SKU 值：

```sql
-- DuckDB 中执行
SELECT 'ods_skus' AS source, COUNT(DISTINCT sku_code) AS cnt FROM ods_skus
UNION ALL
SELECT 'ods_sales' AS source, COUNT(DISTINCT sku_code) FROM ods_sales
UNION ALL
SELECT 'ods_inventory' AS source, COUNT(DISTINCT sku_code) FROM ods_inventory_domestic;
```

**Step 2：交叉匹配**

检查两两表之间 SKU 的匹配率：

```sql
-- 商品主数据 vs 日销量 SKU 匹配率
SELECT
    COUNT(*) AS total_skus_in_sales,
    COUNT(s.sku_code) AS matched,
    ROUND(COUNT(s.sku_code) * 100.0 / COUNT(*), 1) AS pct
FROM (SELECT DISTINCT sku_code FROM ods_sales) sale
LEFT JOIN (SELECT DISTINCT sku_code FROM ods_skus) s ON sale.sku_code = s.sku_code;
```

**Step 3：判断结果**

| 匹配率 | 判定 | 处理 |
|--------|------|------|
| > 95% | 编码统一 | 无需映射，直接进入阶段 D |
| 50-95% | 部分匹配 | 需要补全映射 |
| < 50% | 不同编码体系 | 必须建立完整映射表 |

**Step 4：建立映射**

给客户一个 Excel 模板，三列：

| psku | sku_id | rm_qty |
|------|--------|--------|
| `ERP-SKU-001` | `PMCSKU-Black-M` | 1 |
| `SET-COMBO-A` | `PMCSKU-Red-S` | 1 |
| `SET-COMBO-A` | `PMCSKU-Blue-L` | 1 |

> 组合装拆解：`SET-COMBO-A` 是包含 Red-S + Blue-L 的套装，rm_qty 按比例分配。

客户填完后，以 `ods_cdm_skubom` 表结构导入 DuckDB。

**Step 5：验证映射完整性**

```sql
-- 检查哪些 SKU 没有映射
SELECT DISTINCT d.sku_code
FROM ods_sales d
WHERE d.sku_code NOT IN (SELECT psku FROM ods_cdm_skubom)
  AND d.sku_code NOT IN (SELECT sku_id FROM ods_cdm_skubom);
```

---

## 阶段 D — 管道配置

### 目标

根据客户数据源类型，推荐接入方式，生成对应的导入模板。

### 四种接入模式

| 模式 | 适用场景 | 接入方式 | 模板 |
|------|----------|----------|------|
| **API 直接拉** | 客户有 客户数据库 | `pmc_template_api.py` 新增端点 → Excel → `pmc_import.py` 导入 | 参考现有 5 个端点 |
| **CSV/Excel 导入** | 客户从 ERP 导出文件 | 直接写 `pmc_import.py` 兼容的 Sheet 导入逻辑 | 见下方模板 |
| **客户 API 对接** | 客户提供 RESTful API | 写 cron 定时拉取 → 转 Excel → 导入 | 需客户提供 API 文档 |
| **手动维护** | 参数/映射等低频数据 | Excel 模板 + 客户定期更新 | 提供标准化 Excel 模板 |

### 模板生成：CSV/Excel 导入模式（最常用）

为客户的每块数据生成一个 DuckDB DDL + Python 导入函数。

**DDL 模板**（以 ods_sales 为例）：

```sql
CREATE TABLE IF NOT EXISTS ods_sales (
    sku_code VARCHAR,
    sale_date VARCHAR,
    daily_qty VARCHAR,
    msu_id VARCHAR
);
```

**Python 导入函数模板**（参考 `pmc_import.py` 的 `import_sheet` 函数）：

```python
import duckdb, os, csv

DB_PATH = os.path.expanduser("~/pmc-data/pmc_ods.duckdb")

def import_customer_sales(csv_path: str):
    """导入客户 CSV 格式的日销量数据 → ods_sales"""
    con = duckdb.connect(DB_PATH)

    # 1. 读 CSV（用 DuckDB 原生 read_csv，自动推断类型）
    rows = con.execute(f"""
        SELECT sku_code, sale_date,
               CAST(daily_qty AS INTEGER) AS daily_qty,
               msu_id
        FROM read_csv_auto('{csv_path}')
    """).fetchall()

    if not rows:
        print("⚠️ CSV 无数据，跳过")
        return

    # 2. UPSERT（按 sku_code + sale_date + msu_id 去重）
    con.executemany("""
        INSERT INTO ods_sales (sku_code, sale_date, daily_qty, msu_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (sku_code, sale_date, msu_id) DO UPDATE
        SET daily_qty = excluded.daily_qty
    """, rows)

    print(f"✅ 导入了 {len(rows)} 行 → ods_sales")
    con.close()
```

### 批量导入脚本生成

为每块数据生成独立的导入函数后，组装成 `import_customer_data.py`：

```python
#!/usr/bin/env python3
"""客户数据批量导入脚本 — 一键导入所有板块"""
import sys
from import_customer_sales import import_customer_sales
from import_customer_skus import import_customer_skus
# ... 其他导入函数

def main():
    print("开始导入客户数据...")

    # 1. 商品档案（先导入，其他表依赖它）
    import_customer_skus("/path/to/skus.csv")

    # 2. 供需映射
    import_customer_wmap("/path/to/wmap.csv")

    # 3. 库存快照
    import_customer_inventory("/path/to/inventory.csv")

    # 4. 日销量
    import_customer_sales("/path/to/sales_2025.csv")

    # 5. 采购明细
    import_customer_po("/path/to/po.csv")
    import_customer_po_recv("/path/to/po_recv.csv")

    # 6. 发货明细
    import_customer_ship("/path/to/ship.csv")

    # 7. 规则参数（如果客户有自定义参数）
    import_customer_params("/path/to/params.csv")

    print("\n✅ 全部导入完成")

if __name__ == "__main__":
    main()
```

### 导入顺序约束

由于表之间存在依赖关系（DWD 层从多张 ODS 表聚合），推荐导入顺序：

```
ods_skus  →  ods_wmap  →  ods_inventory_domestic/overseas
  →  ods_sales  →  ods_po/ods_po_recv  →  ods_ship  →  ods_params
```

> `ods_cdm_skubom` 如果有编码映射问题，在导入 ods_sales 之前完成。

### 生成交付清单

阶段 D 完成后，输出给客户的交付清单：

```
PMC 数据接入 — 管道配置

1. DuckDB DDL 脚本: /path/to/create_tables.sql  
2. 导入脚本: /path/to/import_customer_data.py  
3. 编码映射表: /path/to/cdm_skubom.xlsx（如需）  
4. 参数配置模板: /path/to/params_template.xlsx  
5. 每日导入 cron: 建议每天凌晨 3:00 执行 import_customer_data.py

下一步：阶段 E — 端到端验证
```

---

## 阶段 E — 验证

### 目标

数据导入完成后，跑一遍完整管线，确认数据能支撑场景计算。

### 验证步骤

**Step 1：刷新 DWD 指标层**

```bash
cd ~/workspace/pmc-agents && python3 scripts/refresh_dwd_metrics.py
```

检查输出：
- `ods_sales 最新日期` 是否接近当天
- `OK: N SKU, M 有销, K 有销有库存` 是否合理
- 新列填充情况是否正常

**Step 2：运行验证 SQL**

```sql
-- 验证 1：SKU 覆盖率
SELECT
    (SELECT COUNT(DISTINCT sku_code) FROM ods_skus) AS total_skus,
    (SELECT COUNT(DISTINCT sku_code) FROM ods_sales) AS skus_with_sales,
    (SELECT COUNT(DISTINCT sku_code) FROM ods_inventory_domestic) AS skus_with_inv;

-- 验证 2：日期连续性（最近30天）
SELECT sale_date, COUNT(DISTINCT sku_code) AS skus, SUM(CAST(daily_qty AS INTEGER)) AS total_qty
FROM ods_sales
WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 30
GROUP BY sale_date ORDER BY sale_date DESC
LIMIT 30;

-- 验证 3：DWD 数据合理性
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE weighted_daily > 0) AS with_sales,
    COUNT(*) FILTER (WHERE total_inventory > 0) AS with_inventory,
    COUNT(*) FILTER (WHERE inventory_days BETWEEN 1 AND 365) AS reasonable_days,
    COUNT(*) FILTER (WHERE inventory_days > 365) AS warning_slow_moving,
    COUNT(*) FILTER (WHERE inventory_days < 0) AS data_error
FROM dwd_sku_daily_metrics;

-- 验证 4：SKU 映射完整性
SELECT
    'unmapped_sales' AS issue,
    COUNT(DISTINCT s.sku_code) AS cnt
FROM ods_sales s
LEFT JOIN ods_cdm_skubom b ON s.sku_code = b.psku OR s.sku_code = b.sku_id
WHERE b.psku IS NULL
UNION ALL
SELECT
    'unmapped_inventory' AS issue,
    COUNT(DISTINCT i.sku_code) AS cnt
FROM ods_inventory_domestic i
LEFT JOIN ods_cdm_skubom b ON i.sku_code = b.psku OR i.sku_code = b.sku_id
WHERE b.psku IS NULL;
```

**Step 3：抽样场景验证**

随机选一个场景 Skill 跑一遍，确认不出 SQL 错误：

```bash
# 在 DuckDB 中跑场景的核心 SQL（抽取几条看看）
duckdb ~/pmc-data/pmc_ods.duckdb -c "
SELECT sku_code, weighted_daily, total_inventory, inventory_days, tier
FROM dwd_sku_daily_metrics
WHERE weighted_daily > 0 AND inventory_days > 0
ORDER BY inventory_days ASC
LIMIT 10;
"
```

**Step 4：输出验证报告**

```
PMC 数据接入 — 验证报告

数据概况
  SKU 总数:    1,234
  有销售 SKU:   892 (72.3%)
  有库存 SKU: 1,100 (89.1%)

销售数据
  最新日期:     2025-06-15 (延迟 1 天，正常)
  覆盖天数:     180 天
  日均销量:     342 件

DWD 指标
  有加权日均销: 892 条
  库存天数 1-365: 845 条
  呆滞预警 (>365天): 12 条  ← 需客户关注
  数据异常 (<0天): 0 条

✅ 整体判定: 通过
⚠️ 关注项: 12 条 SKU 库存天数超过 365 天，建议检查是否滞销品
```

---

## 快速接入模式（已有数据源接入经验的客户）

如果客户已有数据库访问权限，可以走快速通道：

```
1. 数据库连接信息 → 配置到 pmc_template_api.py
2. 跑标准 5 端点 → 下载 Excel
3. pmc_import.py 导入 → DuckDB ODS 10 张表
4. refresh_dwd_metrics.py → DWD 指标层
5. 按需导入编码映射表（从客户数据库已有视图）
```

不需要的阶段直接跳过，向客户确认即可。

---

## Agent 执行纪律

### 对话节奏

| 规则 | 说明 |
|------|------|
| 按阶段推进 | 阶段 A 没确认完，不进阶段 B |
| 主动列出下一步 | 每阶段结束告诉客户「下一步我需要您提供…」 |
| 不说废话 | 不要「太棒了」「完美！」之类，直接给结论 + 下一步 |
| 阻塞点明确 | 卡住了说清楚卡在哪，不要假装推进 |
| 输出文件给路径 | 生成的 DDL/脚本/模板落盘后给出绝对路径 |

### 常见阻塞及处理

| 阻塞 | 处理 |
|------|------|
| 客户提供不了某块数据 | 确认该板块是否必选。非必选跳过，必选则协商替代方案 |
| SKU 编码无法映射 | 先让客户给映射表，实在没有就做模糊匹配（编辑距离）辅助人工审核 |
| 字段完全对不上 | 回到阶段 B 重新确认，可能是客户给了错误的数据 |
| 管线报错 | 逐层排查：API 可用？→ Excel 格式正确？→ DuckDB DDL 匹配？ |

---

## 相关文件

- 管线 Skill: `~/.hermes/skills/pmc-data-pipeline/SKILL.md`
- API 源码: `~/workspace/pmc-agents/pmc_template_api.py`
- 导入脚本: `~/workspace/pmc-agents/scripts/pmc_import.py`
- DWD 刷新: `~/workspace/pmc-agents/scripts/refresh_dwd_metrics.py`
- DuckDB: `~/pmc-data/pmc_ods.duckdb`
