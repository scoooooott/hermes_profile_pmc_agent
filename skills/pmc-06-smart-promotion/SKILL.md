---
name: pmc-06-smart-promotion
version: 2.1.0
description: "场景06 v4：智能促销 — 库存可售天数分段（正常/关注/预警/紧急），预防呆滞。板块2 事中过程，CSP场景。"
metadata:
  triggers:
    - "促销预警"
    - "库存预警"
    - "库存积压"
    - "清仓建议"
    - "场景06"
    - "四区段预警"
  requires:
    bins: ["python3"]
    files: ["${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}"]
---

# 场景06：促销预警

## 数据源

统一消费 `dwd_sku_daily_metrics` + `dwd_params`，通过 DuckDB `${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}` 只读查询。

| 统一口径 | 关键字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name | SKU 主数据 |
| | weighted_daily | 加权日均销量（替代 ods_sales 计算） |
| | sellable_inv | 可售库存（替代 ods_inventory_domestic.inv_domestic） |
| | onway_inv | 在途/采购在单库存 |
| `dwd_params` | param_no='P13', tier, param_value | 促销触发阈值（可售天数超过此进入关注/预警区） |
| | param_no='P14', tier, param_value | 合理周转天数（正常库存上界） |
| | param_no='P5', tier, param_value | 呆滞天数阈值（最高区段边界） |

> `dwd_params` 按 `param_no + tier` 行存储，每行一个 tier 值，无需解析 JSON。`category` / `lifecycle` 等字段当前 DWD 口径不含，已从查询中移除。

## 计算逻辑

### 1. 参数读取

| 参数 | Tier | 默认值 | 含义 |
|:---|:---|:---:|:---|
| **P14** 合理周转天数 | S/A/B/C/N | 30/40/50/60/75 | 正常库存上界，低于此 = 健康 |
| **P13** 促销触发阈值 | S/A/B/C/N | 45/55/65/75/90 | 可售天数超过此进入关注/预警区 |
| **P5**  呆滞天数阈值 | S/A/B/C/N | 60/75/90/105/120 | 可售天数超过此 = 呆滞 |
| **P1**  存销比目标 | S/A/B/C/N | 1.5/1.2/1.0/0.8/1.0 | 场景02联动标记 |

### 2. 四区段划分

```
sellable_days = sellable_inv / weighted_daily

区段判定（按货盘差异化阈值）：
  正常 🟢: sellable_days ≤ P14[tier]                    → 库存健康，无需干预
  关注 🟡: P14[tier] < sellable_days ≤ P13[tier]       → 库存偏多，关注趋势
  预警 🟠: P13[tier] < sellable_days ≤ P5[tier]         → 库存积压，需启动促销准备
  呆滞 🔴: sellable_days > P5[tier]                     → 已接近或进入呆滞，立即促销
```

> **与旧版差异**：旧版用 `P13×1.5` 作为最高区段边界（"紧急"），新版对齐PRD用 `P5呆滞天数阈值` 作为"呆滞区"边界。

### 3. 核心公式

**呆滞倒计时（天）**：
```
surplus_days = MAX(0, sellable_days - P14[tier])
```

**去化目标（件）**：
```
liquidation_target = MAX(0, (sellable_days - P14[tier]) × weighted_daily)
```

**紧迫度分值**（0~1）：
```
IF sellable_days ≤ P13[tier]:
  urgency = 0  -- 未触发促销
ELIF P5[tier] == P13[tier]:
  urgency = 1  -- 特殊：阈值重合
ELSE:
  urgency = (sellable_days - P13[tier]) / (P5[tier] - P13[tier])
```

**建议折扣幅度**（方向性，具体折扣率由人工决策）：
| 偏离度 | 折扣参考 | S级修正 | C级修正 |
|:---|:---|:---|:---|
| < 30% | 10~15% | +5% | -10% |
| 30~60% | 20~30% | +5% | -10% |
| > 60% | 40~50% | +5% | -10% |

> 偏离度 = (sellable_days - P13[tier]) / P13[tier] × 100%

### 4. 核心 SQL

```sql
WITH
params AS (
  SELECT
    p13.tier,
    CAST(p13.param_value AS BIGINT) AS promo_trigger_days,
    CAST(p14.param_value AS BIGINT) AS reasonable_days,
    CAST(p5.param_value  AS BIGINT) AS slow_moving_days
  FROM dwd_params p13
  JOIN dwd_params p14 USING (tier)
  JOIN dwd_params p5  USING (tier)
  WHERE p13.param_no = 'P13'
    AND p14.param_no = 'P14'
    AND p5.param_no  = 'P5'
),
combined AS (
  SELECT
    m.sku_code,
    m.product_name,
    COALESCE(m.tier, 'N') AS tier,
    COALESCE(m.weighted_daily, 0) AS avg_daily_sales,
    GREATEST(COALESCE(m.sellable_inv, 0), 0) AS inv_qty,  -- 负库存归零
    COALESCE(m.onway_inv, 0) AS inv_purchase_onway,
    p.promo_trigger_days,
    p.reasonable_days,
    p.slow_moving_days
  FROM dwd_sku_daily_metrics m
  LEFT JOIN params p ON COALESCE(m.tier, 'N') = p.tier
)
SELECT
  sku_code, product_name, tier,
  ROUND(avg_daily_sales, 2) AS avg_daily_sales,
  inv_qty, inv_purchase_onway,
  CASE WHEN avg_daily_sales > 0 THEN ROUND(inv_qty / avg_daily_sales, 1) ELSE NULL END AS sellable_days,
  reasonable_days, promo_trigger_days, slow_moving_days,
  -- 区段判定（对齐PRD：正常/关注/预警/呆滞）
  CASE
    WHEN avg_daily_sales = 0 OR inv_qty = 0 THEN '无数据'
    WHEN (inv_qty / avg_daily_sales) <= reasonable_days THEN '正常'
    WHEN (inv_qty / avg_daily_sales) <= promo_trigger_days THEN '关注'
    WHEN (inv_qty / avg_daily_sales) <= slow_moving_days THEN '预警'
    ELSE '呆滞'
  END AS alert_zone,
  -- 呆滞倒计时（天）
  CASE WHEN avg_daily_sales > 0
    THEN GREATEST(0, ROUND(inv_qty / avg_daily_sales - reasonable_days, 1))
    ELSE 0 END AS surplus_days,
  -- 去化目标（件）
  CASE WHEN avg_daily_sales > 0
    THEN GREATEST(0, ROUND((inv_qty / avg_daily_sales - reasonable_days) * avg_daily_sales, 0))
    ELSE 0 END AS liquidation_target,
  -- 紧迫度分值（0~1）
  CASE
    WHEN avg_daily_sales = 0 THEN 0
    WHEN (inv_qty / avg_daily_sales) <= promo_trigger_days THEN 0
    WHEN slow_moving_days = promo_trigger_days THEN 1
    ELSE ROUND((inv_qty / avg_daily_sales - promo_trigger_days)
      / NULLIF(slow_moving_days - promo_trigger_days, 0), 2)
  END AS urgency_score,
  -- 建议折扣方向
  CASE
    WHEN avg_daily_sales = 0 OR inv_qty = 0 THEN '—'
    WHEN (inv_qty / avg_daily_sales) <= reasonable_days THEN '库存健康'
    WHEN (inv_qty / avg_daily_sales) <= promo_trigger_days THEN '关注库存趋势'
    WHEN (inv_qty / avg_daily_sales) <= slow_moving_days THEN '建议启动促销准备'
    ELSE '⚠️ 呆滞风险，立即制定促销/清仓方案'
  END AS suggestion
FROM combined
WHERE avg_daily_sales > 0 OR inv_qty > 0
ORDER BY
  CASE
    WHEN avg_daily_sales = 0 THEN 5
    WHEN (inv_qty / avg_daily_sales) <= reasonable_days THEN 4
    WHEN (inv_qty / avg_daily_sales) <= promo_trigger_days THEN 3
    WHEN (inv_qty / avg_daily_sales) <= slow_moving_days THEN 2
    ELSE 1
  END,
  inv_qty DESC;
```

### 5. 区段分布统计

```sql
WITH zone_stats AS (
  SELECT
    CASE
      WHEN avg_daily_sales = 0 OR inv_qty = 0 THEN '无数据'
      WHEN (inv_qty / avg_daily_sales) <= reasonable_days THEN '正常'
      WHEN (inv_qty / avg_daily_sales) <= promo_trigger_days THEN '关注'
      WHEN (inv_qty / avg_daily_sales) <= slow_moving_days THEN '预警'
      ELSE '呆滞'
    END AS alert_zone,
    COUNT(*) AS sku_count,
    SUM(inv_qty) AS total_inventory,
    SUM(liquidation_target) AS total_liquidation
  FROM combined
  GROUP BY 1
)
SELECT * FROM zone_stats ORDER BY
  CASE alert_zone
    WHEN '正常' THEN 1 WHEN '关注' THEN 2 WHEN '预警' THEN 3 WHEN '呆滞' THEN 4 WHEN '无数据' THEN 5
  END;
```

## 执行步骤

1. `duckdb.connect('${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}')` 连接
2. 从 `dwd_params` 读取 P5（呆滞天数）/ P13（促销触发）/ P14（合理周转），按 tier 匹配
3. 从 `dwd_sku_daily_metrics` 读取加权日均销 + 可售库存 + 在途库存
4. 计算可售天数，按 tier 匹配 P13/P14/P5 阈值
5. 四区段判定
6. 输出促销预警清单 + 区段分布统计

## 输出格式

```
==============================
场景06：促销预警报告
生成时间：{report_date}
==============================

预警参数：
  P14 合理周转天数: S=30  A=40  B=50  C=60   N=75
  P13 促销触发阈值: S=45  A=55  B=65  C=75   N=90
  P5  呆滞天数阈值: S=60  A=75  B=90  C=105 N=120

📊 概览面板
  预警SKU数: {n}  |  去化总量: {qty} 件  |  平均紧迫度: {score}
  
各区段SKU分布
| 区段 | SKU数 | 库存总量 | 去化目标 | 占比 |
|------|-------|----------|----------|------|
| 🟢 正常 | ... | ... | ... | ...% |
| 🟡 关注 | ... | ... | ... | ...% |
| 🟠 预警 | ... | ... | ... | ...% |
| 🔴 呆滞 | ... | ... | ... | ...% |
| ⚪ 无数据 | ... | ... | ... | ...% |

🚨 预警&呆滞SKU清单（按紧迫度降序，关注区不限N全部列出）
| SKU | 品名 | 货盘 | 日均销 | 库存 | 可售天 | P14 | P13 | P5 | 区段 | 紧迫度 | 去化目标 | 建议折扣方向 |
|-----|------|------|--------|------|--------|-----|-----|----|------|--------|----------|------------|
| ... | ...  |  S   |  2.0   |  200 |  100.0 |  30 |  45 | 60 | 🔴呆滞 | 0.67 | 140件 | 40~50% |
| ... | ...  |  A   |  5.0   |  300 |   60.0 |  40 |  55 | 75 | 🟠预警 | 0.25 | 100件 | 10~15% |
```

## 常见问题

### 1. 库存负值
`dwd_sku_daily_metrics.sellable_inv` 存在负值时，**自动归零**处理。

### 2. 无销售数据的SKU
加权日均销=0的SKU无法计算可售天数，归入"无数据"区段。建议参考同类SKU周转率，并按固定规则使用目标值：manual_daily_sale_target 非空优先，否则回落 sales_target。

### 3. 呆滞区段定义
"呆滞"区段使用 **P5 呆滞天数阈值** 作为边界（`sellable_days > P5[tier]`），对齐 PRD 定义。旧版曾用 `P13×1.5` 作为"紧急"边界，已废弃。

### 4. 在途库存
`dwd_sku_daily_metrics.onway_inv` 记录了在途采购库存。当前仅展示，不参与可售天数计算。如需纳入，可将分母改为 `sellable_inv + onway_inv`。

### 5. 季节性商品
当前算法为通用模型，未考虑季节性波动。对于强季节性品类，可临时调整 P13/P14 参数值。

### 6. 升级说明（v2.0.0 → v2.1.0）
- ODS 直读替换为 `dwd_sku_daily_metrics` + `dwd_params` 统一消费
- 日均销量改为直接消费 `weighted_daily`，不再从 `ods_sales` 计算
- 库存改为消费 `sellable_inv`（可售）+ `onway_inv`（在途）
- 参数改为按 `param_no + tier` 行式消费，不再解析 JSON
- `category` / `lifecycle` 字段当前 DWD 口径不含，已移除

---

## 渠道交付策略

### 1. 输出形态判断

| 渠道 | 是否适合 | 理由 |
|:---|:---:|:---|
| PDF | ✅ | 区段分布统计（KPI 卡片 + 分布表）+ 预警&呆滞 SKU 清单（Top N）适合一页纸总览报告 |
| Excel | ✅ | SKU 级明细（预警清单含紧迫度/去化/折扣方向）适合下游筛选与人工决策 |

### 2. 渠道自动检测

非 TUI 渠道（飞书/Telegram）下自动启用附件交付：

```python
from pmc_delivery import detect_channel, should_use_attachments, render_html_to_pdf, render_dataframe_to_excel

channel = detect_channel()
if should_use_attachments(channel):
    # PDF 报告
    pdf_path = render_html_to_pdf(html_promo_report, 'scene06-promo-alert')
    # Excel 明细
    xlsx_path = render_dataframe_to_excel(
        df_promo_detail,
        sheet_name='促销预警',
        output_name='scene06-promo-detail',
    )
    # 通过飞书/Telegram 发送附件
    print(f"MEDIA:{pdf_path}")
    print(f"MEDIA:{xlsx_path}")
else:
    # TUI 终端 → 打印 Markdown
    print(markdown_output)
```

### 3. HTML 数据→板块映射

| 数据内容 | HTML 板块 | 输出形态 |
|:---|:---|:---:|
| 报告标题 + 生成时间 | 页眉 | PDF |
| 预警参数（P13/P14/P5 按 tier） | KPI 元信息卡片 | PDF |
| 概览面板（SKU数/去化总量/紧迫度） | 4 格 KPI 卡片 `.kpi-grid` | PDF |
| 区段分布统计表 | HTML 表格（`<thead>` 格式） | PDF + Excel |
| 预警&呆滞 SKU 清单（紧迫度降序） | 大表格（危急行 `.crit-row`） | PDF（Top 30）+ Excel（全量） |
| 紧迫度 <= 0.3 的预警 SKU | 单独危急项网格 `.crit-list` | PDF |
| 去化目标 + 折扣方向 | 表格列 | Excel（便于排序筛选） |

### 4. 执行策略

```python
# 非 TUI 渠道下的完整交付流程
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "workspace/pmc-agents/scripts"))

from pmc_delivery import (
    detect_channel, should_use_attachments,
    render_html_to_pdf, render_dataframe_to_excel,
    get_output_path,
)

def deliver_scene06(
    html_report: str,
    df_detail: "pd.DataFrame",
    markdown_text: str,
):
    channel = detect_channel()
    if not should_use_attachments(channel):
        print(markdown_text)
        return

    pdf = render_html_to_pdf(html_report, 'scene06-promo-alert')
    xlsx = render_dataframe_to_excel(
        df_detail,
        sheet_name='促销预警',
        output_name='scene06-promo-detail',
        danger_column='紧迫度',
        danger_threshold=0.01,   # 任何紧迫度 > 0 的标记
        warning_threshold=0.3,   # 紧迫度 0~0.3 为关注
        wrap_columns=['product_name'],  # 商品名称自动换行
    )
    print(f"📊 促销预警报告已生成")
    print(f"MEDIA:{pdf}")
    print(f"MEDIA:{xlsx}")
```
