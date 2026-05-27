---
name: pmc-09-cycle-analysis
version: 2.1.0
description: "场景09 v4：周期分析 — 供应链3周期（生产/采购/海外发货），SKU加权平均，按货盘汇总。板块3 事后优化。"
triggers:
  - "供应链周期"
  - "场景09"
  - "周期分析"
  - "cycle analysis"
  - "采购周期"
  - "发货周期"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
---

# 场景09：供应链周期分析

## 数据源

| 表 | 字段 | 用途 |
|:---|:---|:---|
| `ods_po` | po_number, sku_code, order_date, order_qty | 采购下单（保留标注 DWD 未来计划） |
| `ods_po_recv` | po_number, sku_code, receipt_date, receipt_qty | 采购收货（保留标注 DWD 未来计划） |
| `dwd_sku_daily_metrics` | sku_code, tier | 货盘分级（DWD统一消费口） |
| `ods_skus` | sku_code, production_cycle_days | 标准生产周期（待DWD扩充此字段后迁移） |
| `dwd_params` | param_no='P4' | 采购/海外发货周期目标 |

> **数据限制**：海外发货/收货表当前无数据，海外发货周期暂不可计算（标记「待数据接入」）。生产周期从 `ods_skus.production_cycle_days` 读取静态值（当前 0/173,187 个 SKU 有值，全部为空）。
>
> **⚠️ 核心阻塞：采购周期不可计算**：`ods_po` + `ods_po_recv` 按 `po_number + sku_code` 关联时 **匹配数为 0**（2026-05-26 验证）。`ods_po` 有 348 行（342 SKU），`ods_po_recv` 有 1,174 行，但两表的 PO 编号或 SKU 编码体系不一致，无法关联。在修复编码映射前，采购周期 SQL 的 `LEFT JOIN ... WHERE receipt_date IS NOT NULL` 条件永远不成立，结果集为空。
>
> **当前三段周期均不可用**。执行前应检查数据就绪状态，若匹配为 0 则提前说明并输出诊断报告，而非执行 SQL 后返回空结果。
>
> **DWD 计划**：`ods_po` + `ods_po_recv` 双表关联未来将封装为 DWD 采购周期宽表，当前保留直读。`ods_skus.production_cycle_days` 待 DWD 扩充字段后迁移。

## P4 参数

从 `dwd_params WHERE param_no = 'P4'` 读取（展开为 sub_param × tier 多行）：

```sql
SELECT sub_param, tier, CAST(param_value AS DOUBLE) AS target_days
FROM dwd_params
WHERE param_no = 'P4'
ORDER BY sub_param, CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2
                               WHEN 'B' THEN 3 WHEN 'C' THEN 4 WHEN 'N' THEN 5 END;
```

| sub_param | S | A | B | C | N |
|:---|---|---:|---:|---:|---:|
| 周期目标-采购(天) | 15 | 20 | - | - | - |
| 周期目标-海外发货(天) | 25 | 30 | - | - | - |

## 计算逻辑

### 1. 采购周期（下单→收货）

> **注意**：`ods_po` + `ods_po_recv` 双表关联保留直读，未来封装为 DWD 采购周期宽表后迁移。货盘分级通过 `dwd_sku_daily_metrics.tier` 消费。

```sql
WITH po_cycle AS (
  SELECT
    p.sku_code,
    p.po_number,
    CAST(p.order_qty AS DOUBLE) AS order_qty,
    CAST(p.order_date AS DATE) AS order_date,
    MIN(CAST(r.receipt_date AS DATE)) AS first_recv_date
  FROM ods_po p
  LEFT JOIN ods_po_recv r ON p.po_number = r.po_number AND p.sku_code = r.sku_code
  WHERE CAST(p.order_date AS DATE) IS NOT NULL
    AND CAST(r.receipt_date AS DATE) IS NOT NULL
  GROUP BY p.sku_code, p.po_number, p.order_qty, p.order_date
),
-- 异常值过滤：排除周期 > 180 天的异常批次
filtered AS (
  SELECT *,
    (first_recv_date - order_date) AS cycle_days
  FROM po_cycle
  WHERE (first_recv_date - order_date) BETWEEN 1 AND 180
)
-- SKU级加权平均
SELECT
  f.sku_code,
  d.tier,
  COUNT(*) AS batch_count,
  ROUND(SUM(f.order_qty * f.cycle_days) / NULLIF(SUM(f.order_qty), 0), 1) AS wavg_procurement_days
FROM filtered f
JOIN dwd_sku_daily_metrics d ON f.sku_code = d.sku_code
WHERE d.tier IS NOT NULL AND d.tier != ''
GROUP BY f.sku_code, d.tier
```

### 2. 生产周期（静态参考）

> **注意**：`ods_skus.production_cycle_days` 待 DWD 扩充字段后迁移。

```sql
SELECT sku_code,
  CAST(production_cycle_days AS DOUBLE) AS production_days
FROM ods_skus
WHERE production_cycle_days IS NOT NULL AND production_cycle_days != ''
```

### 3. 货盘级汇总与偏差

```
加权平均天数 = Σ(SKU采购量 × SKU周期) / Σ(SKU采购量)

偏差率 = (实际 − P4目标) / P4目标 × 100%
```

P4 目标从 `dwd_params` 查询：

```sql
-- 采购周期目标（按货盘）
SELECT tier, CAST(param_value AS DOUBLE) AS target_days
FROM dwd_params
WHERE param_no = 'P4' AND sub_param = '周期目标-采购(天)';

-- 海外发货周期目标（按货盘）
SELECT tier, CAST(param_value AS DOUBLE) AS target_days
FROM dwd_params
WHERE param_no = 'P4' AND sub_param = '周期目标-海外发货(天)';
```

### 4. 三段周期偏差矩阵

以货盘为行、三段为列的偏差率矩阵：

| 货盘 | 生产周期 | 采购周期 | 海外发货 |
|:---:|:---:|:---:|:---:|
| S | ±X% | ±X% | N/A |
| A | ±X% | ±X% | N/A |
| B | ±X% | ±X% | N/A |

着色规则：
- 🔴 偏差 ≥ ±20%
- 🟡 偏差 ±10~20%
- 🟢 偏差 < ±10%

### 5. 异常SKU清单

采购周期严重异常（偏差率 ≥ 50%）的 SKU，按偏差降序。

## 输出格式

### 概览面板

```
场景09 供应链周期分析 @ {report_date}

数据覆盖：{N} 个 SKU（{pct}% 有采购周期数据）
警告：海外发货周期数据待接入
```

### 三段周期偏差矩阵（核心输出）

```
┌──────┬──────────┬──────────┬──────────┐
│ 货盘 │ 生产周期  │ 采购周期  │ 海外发货  │
│      │实际/目标  │实际/目标  │实际/目标  │
├──────┼──────────┼──────────┼──────────┤
│  S   │ 18/15    │ 14/15    │  N/A     │
│      │ 🟡(+20%) │ 🟢(-7%)  │          │
│  A   │ 22/20    │ 18/20    │  N/A     │
│      │ 🟢(+10%) │ 🟢(-10%) │          │
└──────┴──────────┴──────────┴──────────┘

最大瓶颈：{tier}盘 {segment}段，偏差 {pct}%
```

### 优化建议（方向性）

- 采购周期超标 → 建议压缩下单审批流程 / 优化供应商 Lead Time
- 生产周期超标 → 静态参考值可能过时，建议与供应商重新确认
- 某 SKU 连续恶化 → 建议核查承运商或调整航线
- 数据覆盖率 < 50% → 提示补数据后再下结论

## 注意事项
## 注意事项

- VARCHAR → CAST
- 采购周期排除 > 180 天异常值
- 批次 < 3 的 SKU 加权平均置信度低，标注「数据不足」
- 海外发货周期当前阻塞：海外发货/收货表无数据
- 生产周期依赖 ods_skus.production_cycle_days（当前多数为空，需客户填）
- **DWD 隔离**：货盘分级通过 `dwd_sku_daily_metrics.tier` 消费，P4 参数通过 `dwd_params` 查询。`ods_po` + `ods_po_recv` 双表关联和 `ods_skus.production_cycle_days` 待 DWD 封装。

### ⚠️ 采购周期阻塞：po_number编码体系不匹配

`ods_po`（348行）和 `ods_po_recv`（1,174行）按 `po_number + sku_code` 双键关联时，匹配数为 **0**。原因：两表的 `po_number` 编码格式不同。

示例：
- `ods_po.po_number` 格式如 `MO2026051614942`
- `ods_po_recv.po_number` 格式待检查（与po表不同，可能是系统自动生成或含前缀）

**影响**：无法计算下单→收货的实际周期天数。采购周期一节在数据修复前不可用。

**修复方法**：比对两表po_number格式差异，清洗其中一套使之统一，或通过 `sku_code + 时间范围` 做近似匹配。

### 数据就绪检查（执行前必须跑）

在执行场景09之前（或作为报告一部分输出），先验证三段周期的数据就绪状态：

```python
# 检查采购-收货匹配
match_count = con.execute("""
SELECT COUNT(*) FROM ods_po p
JOIN ods_po_recv r ON p.po_number = r.po_number AND p.sku_code = r.sku_code
""").fetchone()[0]
# match_count = 0 → 采购周期不可算

# 检查生产周期
prod_count = con.execute("""
SELECT COUNT(*) FROM ods_skus
WHERE production_cycle_days IS NOT NULL AND production_cycle_days != ''
""").fetchone()[0]
# prod_count = 0 → 生产周期不可算

# 检查海外周期（待接入）
# 当前无数据 → 海外周期不可算
```

如果三段都不可算，输出数据就绪状态报告而非执行 SQL。这样避免用户看到空报告。

---

## 渠道交付策略

### 1. 输出形态判断

| 渠道 | 是否适合 | 理由 |
|:---|:---:|:---|
| PDF | ✅ | 三段周期偏差矩阵（核心输出）+ 最大瓶颈标注 + 优化建议适合一页管理报告 |
| Excel | ✅ | SKU级采购周期明细 + 异常清单便于供应链团队逐单排查 |

### 2. 渠道自动检测

```python
from pmc_delivery import detect_channel, should_use_attachments, render_html_to_pdf, render_dataframe_to_excel

channel = detect_channel()
if should_use_attachments(channel):
    pdf_path = render_html_to_pdf(html_cycle_report, 'scene09-cycle-analysis')
    xlsx_path = render_dataframe_to_excel(
        df_cycle_detail,
        sheet_name='周期分析',
        output_name='scene09-cycle-detail',
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
| 数据覆盖统计（SKU数/覆盖率%） | KPI 卡片 | PDF |
| 数据缺失警告（海外发货/生产周期） | 警告横幅 | PDF |
| 三段周期偏差矩阵（货盘×周期 + 偏差率 + 🔴🟡🟢 着色） | 核心表格（<thead> 格式 + 条件色背景） | PDF |
| 最大瓶颈标注 | 醒目提示卡片 | PDF |
| 异常SKU清单（偏差率≥50%） | 表格 | PDF（Top 10）+ Excel（全量） |
| 优化建议 | 建议卡片 `.rec`（按货盘排列） | PDF |
| SKU级采购周期加权平均值 | 大表格 | Excel |

### 4. 执行策略

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "workspace/pmc-agents/scripts"))
from pmc_delivery import (
    detect_channel, should_use_attachments,
    render_html_to_pdf, render_dataframe_to_excel,
)

def deliver_scene09(
    html_report: str,
    df_cycle_detail: "pd.DataFrame",
    markdown_text: str,
):
    channel = detect_channel()
    if not should_use_attachments(channel):
        print(markdown_text)
        return

    pdf = render_html_to_pdf(html_report, 'scene09-cycle-analysis')
    xlsx = render_dataframe_to_excel(
        df_cycle_detail,
        sheet_name='周期分析',
        output_name='scene09-cycle-detail',
        wrap_columns=['product_name'],
    )
    print(f"📊 供应链周期分析报告已生成")
    print(f"MEDIA:{pdf}")
    print(f"MEDIA:{xlsx}")
```
