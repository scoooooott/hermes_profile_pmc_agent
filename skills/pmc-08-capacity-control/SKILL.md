---
name: pmc-08-capacity-control
version: 3.0.0
description: "场景08 v4：总量控制 — OTB使用率监控，6级预警判定，按货盘拆解OTB占用与分配。板块3 事后优化，CSP场景。"
triggers:
  - "场景08"
  - "总量控制"
  - "库存健康"
  - "capacity control"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
---

# 场景08：总量健康控制

> 本场景基于库存总量与周转效率做健康监控。

## 数据源

| 表 | 字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, total_inventory, sellable_inv, onway_inv, weighted_daily, inventory_days | 库存总量、周转和货盘分层 |
| `ods_po` | sku_code, order_qty | 在单总量参考 |

## 核心指标

```text
total_inventory = Σ(total_inventory)
total_on_order  = Σ(ods_po.order_qty)
total_occupied  = total_inventory + total_on_order
avg_inventory_days = AVG(inventory_days where inventory_days is not null)
turnover_efficiency = Σ(weighted_daily) / NULLIF(total_inventory, 0)
```

## 核心 SQL

```sql
WITH inv AS (
  SELECT
    SUM(total_inventory) AS total_inventory,
    SUM(sellable_inv) AS total_sellable,
    SUM(onway_inv) AS total_onway,
    AVG(inventory_days) FILTER (WHERE inventory_days IS NOT NULL) AS avg_inventory_days,
    SUM(weighted_daily) AS total_weighted_daily
  FROM dwd_sku_daily_metrics
),
po AS (
  SELECT COALESCE(SUM(CAST(order_qty AS DOUBLE)), 0) AS total_on_order
  FROM ods_po
)
SELECT
  i.total_inventory,
  p.total_on_order,
  i.total_inventory + p.total_on_order AS total_occupied,
  ROUND(i.avg_inventory_days, 1) AS avg_inventory_days,
  ROUND(i.total_weighted_daily / NULLIF(i.total_inventory, 0), 4) AS turnover_efficiency
FROM inv i, po p;
```

### 货盘拆解

```sql
SELECT
  tier,
  COUNT(DISTINCT sku_code) AS sku_count,
  SUM(total_inventory) AS tier_inventory,
  ROUND(AVG(inventory_days) FILTER (WHERE inventory_days IS NOT NULL), 1) AS tier_avg_days,
  ROUND(SUM(weighted_daily) / NULLIF(SUM(total_inventory), 0), 4) AS tier_efficiency
FROM dwd_sku_daily_metrics
WHERE tier IS NOT NULL AND tier != ''
GROUP BY tier
ORDER BY tier;
```

## 预警规则（无参数版）

| 优先级 | 状态 | 条件 | 标记 |
|:---:|:---|:---|:---:|
| 1 | 总量挤压 | avg_inventory_days >= 120 | 🔴 |
| 2 | 高库存风险 | avg_inventory_days >= 90 | 🟠 |
| 3 | 结构偏高 | 任一货盘 `tier_avg_days` >= 100 | 🟡 |
| 4 | 周转偏低 | turnover_efficiency < 0.02 | ⚠️ |
| 5 | 健康 | 其余情况 | 🟢 |

## 输出格式

### 概览面板

```text
场景08 总量健康控制 @ {report_date}

总库存量: {total_inventory}
在单总量: {total_on_order}
总占用量: {total_occupied}
平均库存天数: {avg_inventory_days}
周转效率: {turnover_efficiency}
预警状态: {alert_level}
```

### 货盘明细

| 货盘 | SKU数 | 库存量 | 平均库存天数 | 周转效率 | 预警 |
|:---:|---:|---:|---:|---:|:---:|
| S | ... | ... | ... | ... | ... |
| A | ... | ... | ... | ... | ... |
| B | ... | ... | ... | ... | ... |
| C | ... | ... | ... | ... | ... |
| N | ... | ... | ... | ... | ... |

## 注意事项

- 已移除历史预算参数依赖。
- 本场景仅做总量健康监控，不输出采购额度分配。
- 如后续恢复预算控制，建议单独新增预算场景，不复用本场景口径。

---

## 渠道交付策略

### 1. 输出形态判断

| 渠道 | 是否适合 | 理由 |
|:---|:---:|:---|
| PDF | ✅ | 总量 KPI 卡片（库存量/在单/占用/周转）+ 货盘明细表 + 预警状态，适合一页全局透视 |
| Excel | ✅ | 货盘拆解明细便于分层追踪和历史对比 |

### 2. 渠道自动检测

```python
from pmc_delivery import detect_channel, should_use_attachments, render_html_to_pdf, render_dataframe_to_excel

channel = detect_channel()
if should_use_attachments(channel):
    pdf_path = render_html_to_pdf(html_otb_report, 'scene08-otb-control')
    xlsx_path = render_dataframe_to_excel(
        df_tier_detail,
        sheet_name='总量健康',
        output_name='scene08-otb-detail',
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
| 总库存量/在单总量/总占用量/平均周转效率 | 4 格 KPI 卡片（`total_inventory/total_on_order/total_occupied/turnover_efficiency`） | PDF |
| 平均库存天数 + 预警状态 | 独立醒目卡片（带 🔴/🟠/🟡/🟢 色标） | PDF |
| 货盘明细表（SKU数/库存量/平均天数/周转效率/预警） | HTML 表格 | PDF + Excel |
| 预警规则说明 | 页脚注解 | PDF |

### 4. 执行策略

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "workspace/pmc-agents/scripts"))
from pmc_delivery import (
    detect_channel, should_use_attachments,
    render_html_to_pdf, render_dataframe_to_excel,
)

def deliver_scene08(
    html_report: str,
    df_tier_detail: "pd.DataFrame",
    markdown_text: str,
):
    channel = detect_channel()
    if not should_use_attachments(channel):
        print(markdown_text)
        return

    pdf = render_html_to_pdf(html_report, 'scene08-otb-control')
    xlsx = render_dataframe_to_excel(
        df_tier_detail,
        sheet_name='总量健康',
        output_name='scene08-otb-detail',
    )
    print(f"📊 总量健康控制报告已生成")
    print(f"MEDIA:{pdf}")
    print(f"MEDIA:{xlsx}")
```
