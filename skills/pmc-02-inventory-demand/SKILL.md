---
name: pmc-02-inventory-demand
version: 2.2.0
description: "场景02 v4：库存需求 — 消费场景01销量缺口，按安全库存天数膨胀为库存缺口（件），输出需求库存量/有效库存/缺口。板块1 事前预测，全量覆盖。"
triggers:
  - "库存缺口"
  - "场景02"
  - "库存需求"
  - "inventory gap"
  - "膨胀"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
  - dwd_sku_daily_metrics
  - dwd_params
design_docs:
  - date: "2026-05-20"
    change: "ODS直读替换为DWD统一消费。"
  - date: "2026-05-26"
    change: "修复 `sales_target` 列不存在的 BUG。ods_skus 实际无 sales_target 列，COALESCE 回退模式报 Binder Error。改为仅使用 manual_daily_sale_target 单源。"
---

# 场景02：库存缺口膨胀

> 核心问题：要达成目标销量，需要准备多少库存？

本质是「销量缺口 → 库存需求」的转换器。

## 数据源

| 表 | 字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name, weighted_daily, avg_30d_qty, sellable_inv, onway_inv | 日均销 + 货盘 + 有效库存（统一DWD层） |
| `ods_skus` | sku_code, manual_daily_sale_target | 人工日均销售目标（唯一目标值来源，⚠️无 sales_target 列） |
| `dwd_params` | param_no='P7' → 按tier展开的param_value | 安全库存天数（按货盘，DWD已展开无需JSON解析） |
| `ods_po` | sku_code, order_qty | 在单覆盖量（已下单未发货） |

## P7 参数

```
P7 (dwd_params, 已按tier展开):
  S → 30, A → 25, B → 20, C → 15, N → 20
```

含义：S 级爆款需备 30 天安全库存，C 级长尾只需 15 天。

> **改造说明**：原ods_params存储JSON blob需JSON_EXTRACT解析。DWD层的dwd_params已按tier展开为独立行，JOIN条件 `dwd_params.tier = d.tier` 即可直接取值。

## 计算逻辑

### 主公式

```
需求库存量 = (加权日均 + 日均缺口) × P7[tier]
库存缺口   = MAX(0, 需求库存量 − 有效库存)

其中：
  加权日均   = dwd_sku_daily_metrics.weighted_daily
  日均缺口   = (目标值 / 30) − 加权日均
  有效库存   = dwd_sku_daily_metrics.sellable_inv + dwd_sku_daily_metrics.onway_inv
```

### 异常标记

| 标记 | 条件 |
|:---|:---|
| 🔴 缺口无覆盖 | 库存缺口 > 0 且 在单 = 0 |
| 🟡 呆滞风险 | 可售天数 > P5[tier]（P5=场景06阈值，默认60~120） |
| ⚠️ 在途不足 | 库存缺口 > 0 且 0 < 在单 < 库存缺口 |
| 🟢 充足 | 库存缺口 ≤ 0 |

## 核心 SQL

```sql
WITH dwd_base AS (
  SELECT
    d.sku_code,
    d.tier,
    d.product_name,
    d.weighted_daily,
    d.sellable_inv,
    d.onway_inv,
    d.avg_30d_qty,
    -- 有效库存
    COALESCE(d.sellable_inv, 0) + COALESCE(d.onway_inv, 0) AS effective_inv,
    -- 目标值：仅 manual_daily_sale_target（⚠️ ods_skus 没有 sales_target 列）
    CAST(NULLIF(sk.manual_daily_sale_target, '') AS DOUBLE) AS sales_target
  FROM dwd_sku_daily_metrics d
  LEFT JOIN ods_skus sk ON d.sku_code = sk.sku_code
  WHERE d.weighted_daily > 0
),
-- P7 安全库存天数（从 dwd_params 按 tier 直接取值，无需 JSON_EXTRACT）
p7 AS (
  SELECT tier, CAST(param_value AS DOUBLE) AS safety_days
  FROM dwd_params
  WHERE param_no = 'P7'
),
-- 场景01 内嵌：销量预测（基于 DWD 预计算指标）
scene01 AS (
  SELECT
    d.sku_code,
    COALESCE(d.tier, 'N') AS tier,
    d.product_name,
    COALESCE(d.weighted_daily, 0) AS forecast_daily,
    d.sales_target,
    d.effective_inv,
    d.sellable_inv,
    d.onway_inv,
    COALESCE(p7.safety_days, 20) AS safety_days
  FROM dwd_base d
  LEFT JOIN p7 ON p7.tier = COALESCE(d.tier, 'N')
  WHERE d.sales_target IS NOT NULL
),
-- 在单
on_order AS (
  SELECT sku_code, SUM(CAST(order_qty AS DOUBLE)) AS on_order_qty
  FROM ods_po GROUP BY sku_code
)
SELECT
  s01.sku_code, s01.product_name, s01.tier,
  ROUND(s01.forecast_daily, 2) AS forecast_daily,
  s01.sales_target,
  -- 日均缺口
  GREATEST(0, ROUND(s01.sales_target / 30.0 - s01.forecast_daily, 2)) AS daily_gap,
  -- 安全库存天数
  s01.safety_days,
  -- 需求库存量 = (日均销 + 日均缺口) × 安全库存天数
  ROUND((s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
    * s01.safety_days, 0) AS required_inv,
  -- 有效库存
  COALESCE(s01.effective_inv, 0) AS effective_inv,
  COALESCE(s01.sellable_inv, 0) AS sellable_inv,
  COALESCE(s01.onway_inv, 0) AS onway_inv,
  COALESCE(oo.on_order_qty, 0) AS on_order_qty,
  -- 库存缺口
  GREATEST(0, ROUND((s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
    * s01.safety_days - COALESCE(s01.effective_inv, 0), 0)) AS inventory_gap,
  -- 异常标记
  CASE
    WHEN (s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
      * s01.safety_days > COALESCE(s01.effective_inv, 0)
      AND COALESCE(oo.on_order_qty, 0) = 0 THEN '🔴缺口无覆盖'
    WHEN (s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
      * s01.safety_days > COALESCE(s01.effective_inv, 0)
      AND COALESCE(oo.on_order_qty, 0) < ((s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
      * s01.safety_days - COALESCE(s01.effective_inv, 0))
      THEN '⚠️在途不足'
    WHEN COALESCE(s01.effective_inv, 0) >= (s01.forecast_daily + GREATEST(0, s01.sales_target / 30.0 - s01.forecast_daily))
      * s01.safety_days
      THEN '🟢充足'
    ELSE '⚠️在途不足'
  END AS flag
FROM scene01 s01
LEFT JOIN on_order oo ON s01.sku_code = oo.sku_code
ORDER BY inventory_gap DESC
```

## 输出格式

```
场景02 库存缺口膨胀 @ {report_date}

═══════════════════════════════════════
📊 概览
  已设目标 SKU：{n}
  总需求库存量：{qty} 件
  总库存缺口：{gap} 件
  缺口 SKU 数：{m}（{pct}%）
  缺口覆盖率：{on_order_covers} SKU 有在途覆盖

═══════════════════════════════════════
📋 货盘汇总
| 货盘 | SKU数 | 需求库存 | 有效库存 | 库存缺口 | 缺口占比 | 在途覆盖 |
|------|-------|----------|----------|----------|----------|----------|
| S    | xxx   | xxx      | xxx      | xxx      | xx%      | xx%      |

═══════════════════════════════════════
🔴 缺口清单（Top 20）
| # | SKU | 货盘 | 预测日销 | 目标/30d | 需求库存 | 有效库存 | 库存缺口 | 在单 | 标记 |
|---|-----|------|----------|----------|----------|----------|----------|------|------|
```

## 渠道交付策略

> 共享交付模块：`~/workspace/pmc-agents/scripts/pmc_delivery.py`

### 渠道判断
- **飞书 / Telegram**：支持文件附件 → 生成 PDF 报告 + Excel 明细
- **终端 / TUI**：纯文本 → 输出 Markdown

### PDF 报告映射

| PDF 板块 | 数据来源 | 布局说明 |
|:---|:---|---|
| **KPI 卡片区**（顶部4卡片） | 概览数据 | 卡片1：已设目标SKU数、卡片2：总需求库存量、卡片3：总库存缺口（红色）、卡片4：缺口SKU数 + 占比 + 在途覆盖率 |
| **货盘缺口分布表** | 货盘汇总SQL | 表格：货盘 \| SKU数 \| 需求库存 \| 有效库存 \| 库存缺口 \| 缺口占比 \| 在途覆盖。S/A/B/C/N各一行，合计行粗体。 |
| **🔴 缺口异常清单（Top 30）** | 缺口清单SQL | 表格：序号 \| SKU编码 \| 品名 \| 货盘 \| 预测日销 \| 需求库存 \| 有效库存 \| 库存缺口 \| 在单 \| 异常标记（色标：🔴红/⚠️橙/🟢绿） |
| **异常分布饼图/条形** | flag 聚合 | 异常标记分布计数：缺口无覆盖 / 在途不足 / 充足 各自SKU数 |

### Excel 明细映射

| Sheet | 内容 | 关键列 |
|:---|:---|---|
| 缺口总表 | 所有SKU完整缺口明细 | sku_code, product_name, tier, forecast_daily, sales_target, daily_gap, safety_days, required_inv, effective_inv, sellable_inv, onway_inv, on_order_qty, inventory_gap, flag |
| 异常汇总 | 按异常标记聚合 | flag, sku_count, total_gap, total_required_inv |
| 货盘汇总 | 按货盘聚合 | tier, sku_count, total_required_inv, total_effective_inv, total_gap, gap_pct, coverage_pct |

### 执行流程
1. 运行场景02分析SQL，得到 `inventory_gap_result` DataFrame
2. 查询聚合：货盘汇总 + 异常标记分布
3. 调用 `pmc_delivery.detect_channel()` 判断渠道
4. 若支持附件：
   - 调用 `pmc_delivery.render_html_to_pdf()` 生成 PDF（含KPI卡片 + 货盘表 + 异常清单 + 异常分布）
   - 调用 `pmc_delivery.render_dataframe_to_excel()` 生成 Excel（含以上3个Sheet）
   - 发送 PDF + Excel 到当前渠道，附加 3-5 句摘要（含总缺口量、缺口SKU占比、最大异常标记类型）
5. 若不支持附件：输出 Markdown 全文
