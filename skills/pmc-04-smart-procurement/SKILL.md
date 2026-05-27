---
name: pmc-04-smart-procurement
version: 3.1.0
description: "场景04 v4：智能备货 — 消费场景02库存缺口，经在单覆盖→MOQ取整→OTB校验→健康度判定，输出可执行备货清单。板块2 事中过程，一期无供应商维度。"
triggers:
  - "智能备货"
  - "场景04"
  - "procurement"
  - "备货计划"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
  - dwd_sku_daily_metrics
  - dwd_params
design_docs:
  - date: "2026-05-26"
    change: "修复 `sales_target` 列不存在的 BUG。ods_skus 实际无 sales_target 列，COALESCE 回退模式报 Binder Error。改为仅使用 manual_daily_sale_target 单源。固定规则删除 sales_target 回退说明。"
  - date: "2026-05-22"
    change: "新增 Amazon MSKU 数据源与映射说明、新增已知问题#6(亚马逊无销售数据)和#7(平台TopN查询)、新增 references/amazon-msku-data.md 参考文件"
  - date: "2026-05-21"
    change: "简化参数与计算链路"
  - date: "2026-05-21"
    change: "新增已知问题与陷阱（备货膨胀/ods_po匹配率低/负库存/MOQ缺失）"
---

# 场景04：智能备货

> 把「缺多少」转化为「买多少」——以库存缺口和在单覆盖为主，不引入额外预算与批量约束。

## 数据源

| 表 | 字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name, weighted_daily, sellable_inv, onway_inv | 日均销 + 货盘 + 有效库存 |
| `ods_skus` | sku_code, manual_daily_sale_target, lead_time | 目标值（仅 manual_daily_sale_target，⚠️无 sales_target 列）+ 交期 |
| `dwd_params` | P1, P7 → 按 tier 展开的 param_value | 存销比目标 / 安全库存天数 |
| `ods_po` | sku_code, order_qty, eta | 在单覆盖 |
| `ods_amazon_msku_map` | msku, warehouse, store, match_status, match_note | 亚马逊MSKU→内码映射（msku 直接等于 sku_code） |
| `ods_amazon_msku_agg` | msku, store_group, warehouse_group, store_count, warehouse_count, match_status | 亚马逊MSKU聚合视图（按MSKU去重） |

> 固定规则：目标值仅使用 `manual_daily_sale_target`。⚠️ `ods_skus` 没有 `sales_target` 列。<br/>
> 更新于 2026-05-26：移除已失效的 COALESCE 回退逻辑。
>
> **亚马逊平台数据说明**：`ods_amazon_msku_agg` 中 13,381 个 matched MSKU 可直接作为 `sku_code` 查询 `dwd_sku_daily_metrics`（msku ≡ sku_code）。但所有亚马逊MSKU在 `dwd_sku_daily_metrics.weighted_daily` 中均为 0（无销售数据）。亚马逊销售数据走的是内部SKU编码体系（如 `PY1203-Light Camel-M`），与亚马逊MSKU（如 `A1021AB-3P01-S-1`）不是同一套编码。两者映射关系需通过 BOM 表或手动清洗实现（详见 `references/amazon-msku-data.md`）。

## 计算逻辑

### 主链路

```text
目标日均 = MAX(实际日均销, 目标值)
需求库存 = 目标日均 × 安全库存天数(P7)
库存缺口 = MAX(0, 需求库存 − 有效库存)
净备货量 = MAX(0, 库存缺口 − 在单未到量)
建议备货量 = 净备货量
```

### 核心 SQL

```sql
WITH dwd_base AS (
  SELECT
    d.sku_code,
    COALESCE(d.tier, 'N') AS tier,
    d.product_name,
    COALESCE(d.weighted_daily, 0) AS weighted_daily,
    COALESCE(d.sellable_inv, 0) + COALESCE(d.onway_inv, 0) AS effective_inv,
    COALESCE(
      CAST(NULLIF(sk.manual_daily_sale_target, '') AS DOUBLE),
      0
    ) AS target_daily,
    COALESCE(CAST(NULLIF(sk.lead_time, '') AS DOUBLE), 14) AS lead_time
  FROM dwd_sku_daily_metrics d
  JOIN ods_skus sk ON d.sku_code = sk.sku_code
  WHERE d.weighted_daily > 0
),
p7 AS (
  SELECT tier, CAST(param_value AS DOUBLE) AS safety_days
  FROM dwd_params
  WHERE param_no = 'P7'
),
on_order AS (
  SELECT sku_code, SUM(CAST(order_qty AS DOUBLE)) AS on_order_qty
  FROM ods_po
  GROUP BY sku_code
),
p1 AS (
  SELECT tier, CAST(param_value AS DOUBLE) AS p1_target
  FROM dwd_params
  WHERE param_no = 'P1'
)
SELECT
  b.sku_code,
  b.tier,
  b.product_name,
  b.weighted_daily AS daily_sales_actual,
  b.target_daily,
  COALESCE(p7.safety_days, 20) AS safety_days,
  b.effective_inv,
  ROUND(GREATEST(b.weighted_daily, b.target_daily) * COALESCE(p7.safety_days, 20), 0) AS required_inv,
  GREATEST(0, ROUND(GREATEST(b.weighted_daily, b.target_daily) * COALESCE(p7.safety_days, 20) - b.effective_inv, 0)) AS inventory_gap,
  COALESCE(o.on_order_qty, 0) AS on_order_qty,
  GREATEST(0, ROUND(GREATEST(b.weighted_daily, b.target_daily) * COALESCE(p7.safety_days, 20) - b.effective_inv - COALESCE(o.on_order_qty, 0), 0)) AS suggested_qty,
  b.lead_time,
  COALESCE(p1.p1_target, 1.0) AS p1_target
FROM dwd_base b
LEFT JOIN p7 ON p7.tier = b.tier
LEFT JOIN on_order o ON o.sku_code = b.sku_code
LEFT JOIN p1 ON p1.tier = b.tier
WHERE GREATEST(b.weighted_daily, b.target_daily) * COALESCE(p7.safety_days, 20) > b.effective_inv
ORDER BY suggested_qty DESC;
```

## 输出字段

| # | 列名 | 说明 |
|---|---|---|
| 1 | SKU编码 | 标识 |
| 2 | 货盘等级 | S/A/B/C/N |
| 3 | 商品名称 | 标识 |
| 4 | 实际日均销量 | `weighted_daily` |
| 5 | 目标日均销量 | 覆盖规则后的目标值 |
| 6 | 安全库存天数 | P7 |
| 7 | 有效库存 | 可售+在途 |
| 8 | 需求库存 | 目标日均×安全天数 |
| 9 | 库存缺口 | 需求库存-有效库存 |
| 10 | 在单未到量 | `ods_po` 汇总 |
| 11 | 建议备货量 | 缺口-在单 |
| 12 | 交期(天) | lead_time |
| 13 | 存销比(P1)目标 | P1 target |

## 已知问题与陷阱

### 1. `GREATEST(weighted_daily, target_daily)` 导致 S 级备货膨胀

当 S 级 SKU 的 `manual_daily_sale_target` 设为均值（如 25/日），但实际 `weighted_daily` 仅 2~5 件时，`MAX(2.6, 25) = 25`，需求库存 = 25 × 30 (P7) = 750 件。但实际只需要 2.6 × 30 ≈ 78 件。

**影响**：S 级 Top 3 备货量 700~750 件的 SKU 多为这种情况。备货量是目标导向而非需求导向的。

**应对**：输出报告中加注「⚠️ 目标驱动型备货」标识。如需纯需求导向，修改公式为 `weighted_daily × P7`（不使用 `MAX`）：

```sql
-- 需求导向公式（替代当前 MAX 公式）
ROUND(b.weighted_daily * COALESCE(p7.safety_days, 20), 0) AS required_inv
```

### 2. `ods_po` 在单覆盖量多为0（SKU有销量但无PO记录）

当前数据（2026-05-26）：`ods_po` 有 348 行、342 个 SKU，其中 247 个在 `dwd_sku_daily_metrics` 中有 tier 信息，但这些 SKU 的 `weighted_daily` 绝大多数为 0（无近期销售）。场景04 过滤 `WHERE weighted_daily > 0`，因此 PO 中的 SKU 和有销量的 SKU 几乎无交集，`on_order_qty` 覆盖率趋向 0。

**原因**：采购单覆盖的是「在途滞销/无销售」的 SKU，而非「当前有动销」的 SKU。这不是编码映射问题，而是业务数据覆盖面问题。

**应对**：
- 输出报告中加注「在单覆盖量为0」说明，避免用户误以为是程序问题
- 如果期望在单真实抵扣备货，需确保 PO 数据覆盖有销量的 SKU

### 3. 安全库存参数 P7 当前值

| Tier | P7 安全库存天数 |
|:---:|:---:|
| S | 30 |
| A | 25 |
| B | 20 |
| C | 15 |
| N | 20 |

P7 值过大会放大备货膨胀问题。如需降低 S 级备货量，可考虑将 S 级 P7 从 30 降到 15~20。

### 4. 负库存处理

`dwd_sku_daily_metrics` 中的 `sellable_inv` 和 `onway_inv` 可能包含负值（库存回溯修正导致）。场景04 在计算 `effective_inv` 时未做 `GREATEST(..., 0)` 钳位。如遇到 `effective_inv` 为负数，计算 `required_inv - (-50)` 时缺口会被高估 50 件。

建议修复：
```sql
GREATEST(COALESCE(d.sellable_inv, 0), 0) + GREATEST(COALESCE(d.onway_inv, 0), 0) AS effective_inv
```

### 5. 无 MOQ 与批量约束

当前建议备货量是「净缺口—在单」后的原始值，未考虑最小起订量(MOQ)和包装批量取整。一期不做供应商维度和批量约束。输出到 Excel 后需采购人工校验。

### 6. 亚马逊平台 SKU 在 DWD 层无销售数据

`ods_amazon_msku_agg` 中 `match_status='matched'` 的 MSKU 可以直接作为 `sku_code` 查询 `dwd_sku_daily_metrics`，但所有 13,381 个亚马逊 MSKU 的 `weighted_daily` 均为 0。

**原因**：亚马逊使用独立的 MSKU 编码体系（如 `A1021AB-3P01-S-1`），而销售数据走内部 SKU 编码（如 `PY1203-Light Camel-M`），两套编码未归一化。

**影响**：当用户要求"针对亚马逊 TopN SKU 做备货分析"时，不能直接用 `FROM dwd_sku_daily_metrics WHERE sku_code IN (SELECT msku FROM ods_amazon_msku_agg WHERE match_status='matched')` 筛选——会命中全零销售数据的 SKU，得不到有意义的备货建议。

**应对方案（二选一）**：
- **方案A**：向用户说明数据现状，建议在全量数据上跑场景04（忽略平台维度），因为 Top 销售 SKU 大概率同时覆盖亚马逊渠道。
- **方案B**：如果已有 BOM 映射表（如 `v_cdm_skubom`），尝试通过 BOM 将亚马逊 MSKU 映射到有销售数据的内部 SKU，再对映射后的 SKU 运行场景04。

### 7. 平台特定 TopN 查询的 MSKU→SKU 映射

当用户要求"亚马逊 Top20"等平台维度查询时，需遵循以下步骤：

1. **检查映射方式**：先在 `ods_amazon_msku_agg` 中确认 `match_status` 分布。matched MSKU 可以直接作为 `sku_code` 使用。
2. **验证销售数据**：执行 `SELECT COUNT(*), SUM(CASE WHEN weighted_daily > 0 THEN 1 ELSE 0 END) FROM dwd_sku_daily_metrics WHERE sku_code IN (SELECT msku FROM ods_amazon_msku_agg WHERE match_status='matched')`。
3. **根据结果选择方案**：
   - 如有销售数据 → 直接按 weighted_daily DESC 取 TopN，跑完整场景04
   - 如无销售数据（当前现状）→ 切换到全量 TopN，并告知用户原因
4. **在报告中注明**：若因数据映射问题切换了分析范围，在报告加一句说明，避免用户误以为分析有问题。

## 渠道交付策略

> 共享交付模块：`~/workspace/pmc-agents/scripts/pmc_delivery.py`

### 渠道判断
- **飞书 / Telegram**：支持文件附件 → 生成 PDF 报告 + Excel 明细
- **终端 / TUI**：纯文本 → 输出 Markdown

### 场景判断
场景04 的核心产出是**可执行备货建议清单**，Excel 是主力交付物（采购团队直接使用），PDF 作为**精简执行摘要**补充说明。

### PDF 报告映射

| PDF 板块 | 数据来源 | 布局说明 |
|:---|:---|---|
| **KPI 卡片区**（顶部4卡片） | 汇总聚合 | 卡片1：需备货SKU数、卡片2：总建议备货量、卡片3：总库存缺口、卡片4：平均安全库存天数 |
| **货盘分布表** | 按tier聚合 | 表格：货盘 \| SKU数 \| 需求库存 \| 有效库存 \| 库存缺口 \| 建议备货量。S/A/B/C/N各一行。 |
| **🔴 备货建议清单（Top 30）** | 建议SQL（LIMIT 30） | 表格：序号 \| SKU编码 \| 品名 \| 货盘 \| 实际日销 \| 目标日销 \| 需求库存 \| 有效库存 \| 库存缺口 \| 在单 \| 建议备货量 \| 交期。备货量大的行浅红高亮。 |
| **交期分布** | lead_time 聚合 | 简要展示各交期段SKU数（<7天 / 7-14天 / 14-30天 / >30天） |

### Excel 明细映射

| Sheet | 内容 | 关键列 |
|:---|:---|---|
| 备货建议总表（主力） | 所有建议备货SKU（采购执行用） | sku_code, product_name, tier, daily_sales_actual, target_daily, safety_days, effective_inv, required_inv, inventory_gap, on_order_qty, suggested_qty, lead_time, p1_target |
| 货盘汇总 | 按货盘聚合 | tier, sku_count, total_required_inv, total_gap, total_suggested, avg_lead_time |

### 执行流程
1. 运行场景04分析SQL，得到 `procurement_suggestions` DataFrame
2. 查询聚合：货盘汇总 + 交期分布
3. 调用 `pmc_delivery.detect_channel()` 判断渠道
4. 若支持附件：
   - 调用 `pmc_delivery.render_html_to_pdf()` 生成 PDF（含KPI卡片 + 货盘表 + Top 30建议 + 交期分布）
   - 调用 `pmc_delivery.render_dataframe_to_excel()` 生成 Excel（含备货建议总表主力Sheet）
   - 发送 PDF + Excel 到当前渠道，附加 3-5 句摘要（含需备货SKU数、总建议量、最大建议量SKU）
5. 若不支持附件：输出 Markdown 全文
