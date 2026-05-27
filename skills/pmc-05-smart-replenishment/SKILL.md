---
name: pmc-05-smart-replenishment
version: 1.2.0
description: "场景05 v4：智能补货 — 基于海外库存天数与触发阈值，自动识别需补货SKU，MSU穿透。板块2 事中过程。"
metadata:
  triggers:
    - "补货计划"
    - "智能补货"
    - "海外补货"
    - "库存补货"
    - "场景05"
    - "补货建议"
  requires:
    bins: ["python3"]
    files: ["${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}"]
---

# 场景05：智能补货计划

## 数据源

统一消费 `dwd_sku_daily_metrics` + `dwd_params`，通过 DuckDB `${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}` 只读查询。

| 统一口径 | 关键字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name | SKU 主数据 |
| | weighted_daily | 加权日均销量 |
| | **overseas_inv_available** | **FBA 可售库存** — 真实海外可售 |
| | **overseas_inv_onway** | **FBA 在途库存** — 发往 FBA 途中的货 |
| | **overseas_ship_onway** | **FBA 海运在途** — 已发货未到预计到达日的货 |
| | sellable_inv | 国内可售库存（参考对比用） |
| `dwd_params` | param_no='P9', tier, param_value | 补货触发阈值（海外库存天数低于此触发） |
| | param_no='P10', tier, param_value | 目标海外库存天数（补货目标） |
| `ods_inventory_overseas` | sku_code, inv_available, inv_onway | FBA库存原始数据（仅当DWD中海外库存不足时补充） |
| `ods_ship` | sku_code, dest_warehouse, ship_qty | FBA发货明细，用于FC拆解 |

> **SKU 编码前提**：所有数据源的 SKU 编码必须在 ETL 层完成统一后再导入。`ods_inventory_overseas.sku_code` 必须与 `dwd_sku_daily_metrics.sku_code` 一致，直接 JOIN 即可，不需要中间映射表。如海外库存 SKU 编码与销量 SKU 不同，说明前置 ETL 未完成编码统一，需回退处理。

> **MSU 映射**：当前 DWD 口径无 MSU 维度。SKU→MSU 归因暂保留 ODS 直读（`ods_sales.msu_id`），**待接入 DWD 统一口径**后替换。详见下方「MSU 粒度补充信息」。

## 计算逻辑

### 1. 参数读取

**P9 — 补货触发阈值**（海外库存天数低于此值时触发补货）：

| Tier | 触发天数 | 含义 |
|:---|:---:|:---|
| S | 15 | 爆款库存紧张 |
| A | 12 | 畅销 |
| B | 10 | 平销 |
| C | 8 | 长尾 |
| N | 10 | 新品/淘汰品 |

**P10 — 目标海外库存天数**（补货后希望达到的库存覆盖率）：

| Tier | 目标天数 | 含义 |
|:---|:---:|:---|
| S | 30 | 爆款高覆盖 |
| A | 25 | 畅销 |
| B | 20 | 平销 |
| C | 15 | 长尾 |
| N | 20 | 新品/淘汰品 |

> 参数读取方式：`dwd_params` 按 `param_no + tier` 精确匹配，每行一个 tier 值，无需解析 JSON。

### 2. 日均销量

直接使用 `dwd_sku_daily_metrics.weighted_daily` 作为日均销量，无需从原始销售明细计算。

### 3. 海外库存天数计算

```
overseas_total_inv = COALESCE(overseas_inv_available, 0) + COALESCE(overseas_ship_onway, 0)
overseas_inv_days = CAST(overseas_total_inv AS DOUBLE) / NULLIF(weighted_daily, 0)
```

> **说明**：`overseas_inv_available` 为 FBA 可售库存，`overseas_ship_onway` 为海运在途（已发货未到预计到达日）。两者之和为当前海外可触及总库存。不再使用国内库存 `sellable_inv` 冒充海外。海外无销售历史的SKU标记为"无销售数据"。

### 4. 补货判定与补货量计算

```
触发条件：overseas_inv_days < P9_trigger[sku.tier]
补货量   = CEIL((P10_target[sku.tier] - overseas_inv_days) * avg_daily_sales)
```

### 5. 核心 SQL — 补货判定

```sql
WITH
params AS (
  SELECT
    p9.tier,
    CAST(p9.param_value AS BIGINT) AS trigger_threshold,
    CAST(p10.param_value AS BIGINT) AS target_days
  FROM dwd_params p9
  JOIN dwd_params p10 USING (tier)
  WHERE p9.param_no = 'P9'
    AND p10.param_no = 'P10'
),
combined AS (
  SELECT
    m.sku_code,
    m.product_name,
    COALESCE(m.tier, 'N') AS tier,
    COALESCE(m.weighted_daily, 0) AS avg_daily_sales,
    -- 海外真实库存（FBA 可售 + 海运在途）
    GREATEST(COALESCE(m.overseas_inv_available, 0), 0)
      + GREATEST(COALESCE(m.overseas_ship_onway, 0), 0) AS ov_total_inv,
    COALESCE(m.overseas_inv_onway, 0) AS ov_inv_onway,
    GREATEST(COALESCE(m.sellable_inv, 0), 0) AS domestic_sellable_inv,
    p.trigger_threshold,
    p.target_days
  FROM dwd_sku_daily_metrics m
  LEFT JOIN params p ON COALESCE(m.tier, 'N') = p.tier
)
SELECT
  sku_code,
  product_name,
  tier,
  ROUND(avg_daily_sales, 2) AS avg_daily_sales,
  ov_total_inv AS overseas_total_inventory,
  -- 海外库存天数（基于真实海外数据）
  CASE
    WHEN avg_daily_sales > 0 THEN ROUND(ov_total_inv / avg_daily_sales, 1)
    ELSE NULL
  END AS overseas_inv_days,
  trigger_threshold,
  target_days,
  -- 补货判定
  CASE
    WHEN avg_daily_sales = 0 THEN '无销售数据-不触发'
    WHEN ov_total_inv = 0 AND avg_daily_sales > 0 THEN '急需补货-库存归零'
    WHEN ov_total_inv > 0 AND (ov_total_inv / avg_daily_sales) < trigger_threshold THEN '建议补货'
    ELSE '库存充足'
  END AS replenish_status,
  -- 建议补货量
  CASE
    WHEN avg_daily_sales > 0
     AND (ov_total_inv = 0 OR (ov_total_inv / avg_daily_sales) < trigger_threshold)
    THEN GREATEST(
           CEIL((target_days - COALESCE(ov_total_inv / NULLIF(avg_daily_sales, 0), 0)) * avg_daily_sales),
           1
         )
    ELSE 0
  END AS suggested_replenish_qty
FROM combined
ORDER BY
  CASE WHEN replenish_status = '急需补货-库存归零' THEN 0
       WHEN replenish_status = '建议补货' THEN 1
       ELSE 2 END,
  trigger_threshold - COALESCE(overseas_inv_days, 0) DESC,
  avg_daily_sales DESC;
```

### 6. FC 拆解 — 按 FBA 收货仓库分配补货量

补货总量确定后，按历史发货比例分配到各 fulfillment_center，输出可执行的发货计划。

```sql
WITH replenishment_result AS (
  -- 复用上面的补货 SQL（同上逻辑）
  ... -- 同上 SELECT（建议补货量 > 0 的 SKU）
),
fc_distribution AS (
  SELECT
    s.sku_code,
    s.dest_warehouse AS fulfillment_center,
    SUM(CAST(s.ship_qty AS DOUBLE)) AS fc_qty
  FROM ods_ship s
  WHERE s.dest_warehouse IS NOT NULL AND s.dest_warehouse != ''
  GROUP BY s.sku_code, s.dest_warehouse
),
fc_ratio AS (
  SELECT
    sku_code,
    fulfillment_center,
    fc_qty,
    SUM(fc_qty) OVER (PARTITION BY sku_code) AS total_qty,
    ROUND(fc_qty / NULLIF(SUM(fc_qty) OVER (PARTITION BY sku_code), 0), 4) AS ratio
  FROM fc_distribution
)
SELECT
  r.sku_code,
  r.product_name,
  r.tier,
  r.suggested_replenish_qty AS total_replenish_qty,
  fc.fulfillment_center,
  GREATEST(ROUND(r.suggested_replenish_qty * fc.ratio), 1) AS ship_recommend_qty,
  fc.ratio,
  fc.fc_qty AS historical_qty
FROM replenishment_result r
JOIN fc_ratio fc ON r.sku_code = fc.sku_code
WHERE r.suggested_replenish_qty > 0
ORDER BY r.sku_code, fc.ratio DESC
```

### 6. MSU 粒度补充信息

> **⚠️ 待接入 DWD 统一口径**：当前 `dwd_sku_daily_metrics` 不含 MSU 维度。SKU→MSU 归因暂保留 ODS 直读（`ods_sales.msu_id`），后续接入 DWD 统一口径后替换。

**策略A — 当 wmap 有 SKU 级数据时**：
```sql
SELECT w.msu_id, w.sku_code
FROM ods_wmap w
WHERE w.sku_code IS NOT NULL
```

**策略B — 从 ods_sales 反向提取 SKU 的 MSU 归属**（当前推荐）：
```sql
WITH sku_msu AS (
  SELECT
    sku_code,
    msu_id,
    SUM(CAST(daily_qty AS BIGINT)) AS total_qty
  FROM ods_sales
  WHERE msu_id IS NOT NULL
  GROUP BY sku_code, msu_id
),
sku_primary_msu AS (
  SELECT DISTINCT ON (sku_code)
    sku_code,
    msu_id,
    total_qty
  FROM sku_msu
  ORDER BY sku_code, total_qty DESC
)
SELECT * FROM sku_primary_msu
```

## 执行步骤

1. `duckdb.connect('${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}')` 连接
2. 从 `dwd_params` 读取 P9（触发阈值）+ P10（目标天数），按 tier 匹配
3. 从 `dwd_sku_daily_metrics` 读取各 SKU 的加权日均销 + 原始海外库存
4. 读取并合并海外库存数据：从 `ods_inventory_overseas`（如需补充DWD）读取可售/在途库存，按 sku_code 直接 JOIN `dwd_sku_daily_metrics`（前提：SKU 编码已在 ETL 层统一）
5. 合并海外库存：`COALESCE(ov_available, overseas_inv_available)`，得到每个 SKU 的真实海外库存
6. 计算海外库存天数（`ov_total = ov_available + ov_ship_onway`），对比触发阈值
7. 对触发SKU计算建议补货量
8. 从 `ods_ship` 按 fulfillment_center 计算历史发货占比，分配补货量到各 FC
9. 输出补货建议清单（含 FC 拆解表）

## 输出格式

```
==============================
场景05：智能补货计划报告
生成时间：2026-05-18 01:06
==============================

补货参数：
  P9 触发阈值:  S=15天  A=12天  B=10天  C=8天  N=10天
  P10 目标天数: S=30天  A=25天  B=20天  C=15天  N=20天

🚨 需补货SKU清单（Top 30）
| SKU | 品名 | 货盘 | 日均销 | 海外库存 | 库存天数 | 触发阈值 | 建议补货量 | 状态 |
|-----|------|------|--------|----------|----------|----------|-----------|------|
| ... | ...  |  S   |  15.0  |   200    |  13.3    |   15     |   250     | 建议补货 |
| ... | ...  |  A   |  8.0   |    0     |   0.0    |   12     |   200     | 急需补货 |

📊 汇总
- 需补货SKU：XXX
  ├─ 急需补货(库存归零)：XX
  ├─ 建议补货：XXX
  └─ 库存充足：XXX

- 按MSU分布：
  MSU-xx：XX个SKU需补货
  MSU-yy：YY个SKU需补货

- 按FC拆解发货计划（Top 10）：
  | SKU | 总补货量 | FC代码 | 分配量 | 占比 |
  |-----|---------|--------|--------|------|
  | ... |  250    | IND9   |  100   | 40%  |
  | ... |  250    | FWA4   |  80    | 32%  |
```

## 常见问题

### 1. SKU编码必须统一
所有数据源的 SKU 编码必须在 ETL 层统一后再导入。`ods_inventory_overseas.sku_code` 必须等于 `dwd_sku_daily_metrics.sku_code`，直接 JOIN 即可。
如两者不一致，说明前置 ETL 未完成编码统一，需回退到数据接入阶段重新处理，不允许在 DuckDB 内做映射桥接。
> cosboard 是客户的原始数据源，不是分析的直接消费层。所有 cosboard 数据必须经过 `pmc_template_api.py` → 标准 Excel → `pmc_import.py` → DuckDB 的管线。不要在 skill 里写 cosboard 直连 SQL，即使数据看起来已经存在。该管线的设计目的是保证数据格式一致、可审计、可追溯。

### 2. sellable_inv 有负值
部分 SKU 库存出现负值（如 -75），**执行时自动归零**处理，避免干扰库存天数计算。

### 3. SKU-MSU 映射
当前 DWD 口径无 MSU 维度。`ods_wmap.sku_code` 全为空，无法做标准 SKU→MSU 映射。替代方案：
- 暂保留从 `ods_sales.msu_id` 按销量反向归因（ODS 直读）
- **待 DWD 统一口径接入 MSU 维度后替换**
- 一期不做多MSU拆单

### 4. 无销量数据
加权日均销=0的SKU不触发补货，标记为"无销售数据-不触发"。

## 渠道交付策略

> 共享交付模块：`~/workspace/pmc-agents/scripts/pmc_delivery.py`

### 渠道判断
- **飞书 / Telegram**：支持文件附件 → 生成 PDF 报告 + Excel 明细
- **终端 / TUI**：纯文本 → 输出 Markdown

### PDF 报告映射

| PDF 板块 | 数据来源 | 布局说明 |
|:---|:---|---|
| **KPI 卡片区**（顶部4卡片） | 汇总聚合 | 卡片1：需补货SKU总数、卡片2：急需补货（库存归零）数（红色）、卡片3：建议补货数、卡片4：总建议补货量 |
| **参数参考表** | P9 / P10 | 小表格：Tier \| 触发阈值 \| 目标天数。S/A/B/C/N列出参考值，供读者对照。 |
| **🔴 需补货清单（Top 30）** | 补货SQL（LIMIT 30） | 表格：序号 \| SKU编码 \| 品名 \| 货盘 \| 日均销 \| 海外库存 \| 库存天数 \| 触发阈值 \| 建议补货量 \| 状态。库存归零行浅红高亮。 |
| **MSU 分布概览** | MSU聚合 | 按MSU展示需补货SKU数 + 建议补货量（如有MSU数据） |

### Excel 明细映射

| Sheet | 内容 | 关键列 |
|:---|:---|---|
| 补货建议总表（主力） | 所有SKU完整补货建议 | sku_code, product_name, tier, avg_daily_sales, overseas_total_inventory, overseas_inv_days, trigger_threshold, target_days, replenish_status, suggested_replenish_qty |
| 按FC拆解发货计划（新增） | 补货量按 fulfillment_center 分配 | sku_code, product_name, fulfillment_center, ship_recommend_qty, ratio, total_replenish_qty |
| 汇总统计 | 按状态/Tier聚合 | replenish_status, tier, sku_count, total_suggested_qty |
| MSU分布（如有） | 按MSU聚合 | msu_id, sku_count, total_suggested_qty |

### 执行流程
1. 运行场景05分析SQL，得到 `replenishment_result` DataFrame
2. 查询聚合：汇总统计 + MSU分布
3. 调用 `pmc_delivery.detect_channel()` 判断渠道
4. 若支持附件：
   - 调用 `pmc_delivery.render_html_to_pdf()` 生成 PDF（含KPI卡片 + 参数表 + Top 30建议 + MSU分布）
   - 调用 `pmc_delivery.render_dataframe_to_excel()` 生成 Excel（含以上3个Sheet）
   - 发送 PDF + Excel 到当前渠道，附加 3-5 句摘要（含需补货SKU数、急需补货数、Top 1 SKU）
5. 若不支持附件：输出 Markdown 全文
