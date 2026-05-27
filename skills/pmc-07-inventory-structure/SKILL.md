---
name: pmc-07-inventory-structure
version: 2.1.0
description: "场景07 v4：库存结构 — 4段库存拆解（可售/在途/国内/采购在单），逐SKU计算各段天数。板块3 事后优化，CSP场景。"
triggers:
  - "库存结构"
  - "场景07"
  - "四段库存"
  - "stock structure"
  - "健康度"
  - "库存健康度"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
---

# 场景07：库存结构分析

## 数据源

统一消费 `dwd_sku_daily_metrics` + `dwd_params`，通过 DuckDB `${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}` 只读查询。

| 统一口径 | 字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier | SKU 主数据 + 货盘等级 |
| | weighted_daily | 加权日均销量（替代 ods_sales 聚合计算） |
| | sellable_inv → 国内段 + 可售段 | 国内库存段 / 可售库存段 |
| | onway_inv → 采购在单段 | 采购在单库存段 |
| `dwd_params` | param_no='P2', sub_param, tier, param_value | 各段目标天数 |

> **消费上游说明**：`dwd_sku_daily_metrics` 由 ODS 层加工而来，消费上游包括 `ods_inventory_domestic`、`ods_sales`、`ods_skus`。当前 DuckDB 仅有 `sellable_inv`（→国内段 + 可售段）和 `onway_inv`（→采购在单段）两段。在途段暂缺（标记「数据待接入」）。

> **数据限制**：当前 `dwd_sku_daily_metrics` 无独立「在途库存」段，`sellable_inv` 同时代理国内段和可售段。独立在途段数据待接入。

## P2 参数

`dwd_params` 按 `param_no='P2'` + `sub_param` 读取（4 行，当前仅配置 S 级）：

| sub_param（段名） | S 目标天数 | 对应段 |
|:---|---:|:---|
| 库存段-可售(天) | 15 | 可售 |
| 库存段-在途(天) | 20 | 在途 |
| 库存段-国内(天) | 30 | 国内 |
| 库存段-采购在单(天) | 45 | 采购在单 |

> 未配置货盘列缺省取 S 级值或最邻近货盘。读取方式：`SELECT sub_param, tier, param_value FROM dwd_params WHERE param_no = 'P2'`。

## 计算逻辑

### 1. 日均销量

直接使用 `dwd_sku_daily_metrics.weighted_daily` 作为日均销量。不再从 `ods_sales` 聚合 30 天明细。

### 2. SKU 级各段天数

```sql
WITH
-- P2 目标天数（按 sub_param 展开）
p2_params AS (
  SELECT
    sub_param,
    tier,
    CAST(param_value AS DOUBLE) AS target_days
  FROM dwd_params
  WHERE param_no = 'P2'
),
-- SKU 级各段天数计算
sku_days AS (
  SELECT
    m.sku_code,
    COALESCE(m.tier, 'N') AS tier,
    COALESCE(m.weighted_daily, 0) AS avg_daily,
    COALESCE(m.sellable_inv, 0) AS inv_sellable,
    COALESCE(m.onway_inv, 0) AS inv_onorder,
    -- 4段天数（sellable_inv 同时代理「可售段」和「国内段」）
    ROUND(m.sellable_inv / NULLIF(m.weighted_daily, 0), 1) AS days_sellable,
    NULL AS days_transit,  -- 在途段数据待接入
    ROUND(m.sellable_inv / NULLIF(m.weighted_daily, 0), 1) AS days_domestic,
    ROUND(m.onway_inv  / NULLIF(m.weighted_daily, 0), 1) AS days_onorder
  FROM dwd_sku_daily_metrics m
  WHERE m.tier IS NOT NULL AND m.tier != ''
)
SELECT * FROM sku_days
```

### 3. 货盘级加权汇总

```sql
SELECT tier,
  COUNT(*) AS sku_count,
  SUM(inv_sellable + inv_onorder) AS total_inv,
  SUM(avg_daily) AS total_avg_daily,
  -- 加权天数 = SUM(库存量) / SUM(日均销量)
  ROUND(SUM(inv_sellable) / NULLIF(SUM(avg_daily), 0), 1) AS tier_days_domestic,
  ROUND(SUM(inv_onorder)  / NULLIF(SUM(avg_daily), 0), 1) AS tier_days_onorder
FROM sku_days
GROUP BY tier
```

### 4. 偏差率

```
偏差率 = (实际天数 - P2目标天数) / P2目标天数 × 100%
```

分货盘、分段独立计算。P2 目标天数从 `dwd_params` 按 `sub_param` + `tier` 匹配。

### 5. 健康度判定矩阵（7 种，按优先级）

对每个货盘的每段实际天数与 P2 目标比较：

| 优先级 | 状态 | 判定条件 | 标记 |
|:---:|:---|:---|:---:|
| 1 | 断货风险 | 可售天 < P2_可售 (S/A级) | 🔴 |
| 2 | 结构失衡 | 可售天 < P2_可售 **且** 某段 > P2×1.5 | 🔴 |
| 3 | 在途积压 | 在途天 > P2_在途×1.5 | 🟠 |
| 4 | 国内积压 | 国内天 > P2_国内×1.5 | 🟠 |
| 5 | 采购过度 | 采购在单 > P2_采购在单×1.5 | 🟡 |
| 6 | 结构失调 | 总偏差 < ±10% 但某段偏差 > ±30% | ⚠️ |
| 7 | 健康 | 全部段在 P2 ±10% 内 | 🟢 |

> 若某段 P2 未配置（tier 列在 dwd_params 中无对应行），该段跳过判定。

## 输出格式

### 概览面板（货盘级）

```
场景07 库存结构分析 @ {report_date}

┌──────────┬──────────┬──────────┬──────────┬──────────┐
│  货盘    │ 可售天   │ 在途天   │ 国内天   │采购在单天│
│          │实际/目标  │实际/目标  │实际/目标  │实际/目标  │
├──────────┼──────────┼──────────┼──────────┼──────────┤
│    S     │ 12/15    │  N/A     │ 12/30    │ 55/45    │
│          │ 🟢(-20%) │          │ 🔴(-60%) │ 🟡(+22%) │
│    A     │  ...     │  ...     │  ...     │  ...     │
└──────────┴──────────┴──────────┴──────────┴──────────┘

总体健康度：⚠️ 结构失调 — 国内段偏低 + 采购在单偏高
```

### 段偏差热力图方向

```
  🔴 ≥ ±20% 偏差 → 紧急
  🟡 ±10~20%   → 关注
  🟢 < ±10%     → 正常
```

### 结构调整建议（方向性）

- 国内段持续偏低 → 建议加快发运/压缩安全库存
- 采购在单持续偏高 → 建议审查采购计划/推迟新单
- 某段积压 → 建议排查在途批次/仓库周转瓶颈

## 执行步骤

1. `import duckdb; con = duckdb.connect('${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}')`
2. 从 `dwd_params` 读取 P2 参数（4 行，按 sub_param + tier 展开）
3. 从 `dwd_sku_daily_metrics` 读取各 SKU 的加权日均销 + 可售库存 + 在途库存
4. 计算各 SKU 4 段天数
5. 按货盘加权汇总
6. 执行 7 种健康度判定（使用 dwd_params 中的 P2 目标值）
7. 输出概览面板 + 热力图方向 + 结构调整建议
8. `con.close()`

## 注意事项

- 所有列 VARCHAR → 必须 CAST
- 在途段暂缺数据源，标记「N/A」
- 未配置货盘的 P2 值跳过判定
- N 货盘（无销量 SKU）仅做总量统计，不参与分段天数计算
- 加权日均销=0 的 SKU 分段天数列为 NULL

## 升级说明（v2.0.0 → v2.1.0）

- **ODS 直读全部替换为 DWD 统一消费**
- `ods_inventory_domestic` → `dwd_sku_daily_metrics.sellable_inv`（国内段/可售段）、`onway_inv`（采购在单段）
- `ods_sales` 聚合计算 → `dwd_sku_daily_metrics.weighted_daily` 直接消费
- `ods_skus` → `dwd_sku_daily_metrics.tier`
- `ods_params` JSON 解析 → `dwd_params` 行式消费（`param_no='P2'` + `sub_param` + `tier`）
- 明确标注消费上游为 `dwd_sku_daily_metrics`（CSP 上游消费链）

---

## 渠道交付策略

### 1. 输出形态判断

| 渠道 | 是否适合 | 理由 |
|:---|:---:|:---|
| PDF | ✅ | 货盘级概览面板（4段天数实际/目标 + 热力图）+ 健康度判定结果适合一页报告 |
| Excel | ✅ | SKU级4段天数明细 + 偏差率便于深层排查和根因分析 |

### 2. 渠道自动检测

```python
from pmc_delivery import detect_channel, should_use_attachments, render_html_to_pdf, render_dataframe_to_excel

channel = detect_channel()
if should_use_attachments(channel):
    pdf_path = render_html_to_pdf(html_stock_report, 'scene07-stock-structure')
    xlsx_path = render_dataframe_to_excel(
        df_stock_detail,
        sheet_name='库存结构',
        output_name='scene07-stock-detail',
    )
    print(f"MEDIA:{pdf_path}")
    print(f"MEDIA:{xlsx_path}")
else:
    print(markdown_output)
```

### 3. HTML 数据→板块映射

| 数据内容 | HTML 板块 | 输出形态 |
|:---|:---|:---:|
| 报告标题 + 生成时间 | 页眉 | PDF |
| 总体健康度结论 | 醒目提示条（红/黄/绿色块） | PDF |
| 货盘级概览面板 | 4列货盘卡片（每卡片含4段实际/目标/偏差） | PDF |
| 段偏差热力图方向 | 图例说明条（🔴≥±20% / 🟡±10~20% / 🟢<±10%） | PDF |
| 结构调整建议 | 建议卡片 `.rec`（按优先级排列） | PDF |
| SKU级4段明细 | 大表格（含days_sellable/days_transit/days_domestic/days_onorder） | Excel（全量）+ PDF（Top 20） |
| 健康度判定分布 | 小统计表 | PDF |

### 4. 执行策略

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "workspace/pmc-agents/scripts"))
from pmc_delivery import (
    detect_channel, should_use_attachments,
    render_html_to_pdf, render_dataframe_to_excel,
)

def deliver_scene07(
    html_report: str,
    df_detail: "pd.DataFrame",
    markdown_text: str,
):
    channel = detect_channel()
    if not should_use_attachments(channel):
        print(markdown_text)
        return

    pdf = render_html_to_pdf(html_report, 'scene07-stock-structure')
    xlsx = render_dataframe_to_excel(
        df_detail,
        sheet_name='库存结构明细',
        output_name='scene07-stock-detail',
        wrap_columns=['product_name'],
    )
    print(f"📊 库存结构分析报告已生成")
    print(f"MEDIA:{pdf}")
    print(f"MEDIA:{xlsx}")
```
