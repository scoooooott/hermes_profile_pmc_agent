---
name: pmc-01-sales-demand
version: 2.6.1
description: "场景01 v4：销量需求 — 预测vs目标对比。基于dwd_sku_daily_metrics的加权日均×30→未来30天预测→与manual_daily_sale_target对比→缺口/达成率/P3重点关注清单。板块1 事前预测。"
metadata:
  triggers:
    - "销量需求"
    - "场景01"
    - "sales forecast"
    - "预测vs目标"
    - "销量缺口"
    - "达成率"
  requires:
    bins: ["python3"]
    files: ["${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}"]
    tables: ["dwd_sku_daily_metrics", "dwd_params", "ods_skus"]
  design_docs:
    - date: "2026-05-27"
      change: "修复均值法目标计算 B/C 货盘 ROUND(AVG(wd),0) 归零陷阱。改为 GREATEST(ROUND(...),1) 确保最低目标=1。"
    - date: "2026-05-26"
      change: "修复 `sales_target` 列不存在的 BUG。ods_skus 实际无 sales_target 列，COALESCE 回退模式报 Binder Error。改为仅使用 manual_daily_sale_target 单源。更新数据源表和 WHERE 子句。新增陷阱说明：manual_daily_sale_target 可能全部为空，此时只能输出预测，无法算缺口。"
    - date: "2026-05-21"
      change: "目标值设定部分重构：原硬编码 S=3000/A=1200/B=500/C=100 替换为数据驱动法（中位数×系数）；新增均值法；新增缺口率逆向校准方法论；加入个性化目标陷阱（×1.3 数学上 100% 缺口率）。"
    - date: "2026-05-20"
      change: "ODS直读替换为DWD统一消费。ods_sales/ods_skus(tier+product_name)/ods_params → dwd_sku_daily_metrics + dwd_params。volatility降级为7d/30d偏差近似。"
---

# 场景01：销量需求 — 预测 vs 目标对比

## 核心命题

> 「预计能卖多少，和计划要卖多少，差多少？」

这是全链路起点——不是孤立的销量预测，而是**预测 vs 目标的可量化对比**，产出缺口信号，传递给下游场景02/03/04。

## 数据源

| 表 | 关键列 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name, weighted_daily, avg_30d_qty, avg_7d_qty | 日均销 + 货盘 + 趋势基线（ODS聚合层，无需自算） |
| `ods_skus` | sku_code, manual_daily_sale_target, category | 人工日均销售目标（唯一的目标值来源） |
| `dwd_params` | param_no='P3', param_value | 重点关注SKU数量N |

> **改造说明**：原ods_sales直读及ods_skus(tier/product_name)已替换为dwd_sku_daily_metrics。日均销取weighted_daily，趋势使用avg_7d_qty/avg_30d_qty。

> **⚠️ 重要坑点**：`ods_skus` 表中**不存在 `sales_target` 列**，唯一的目标值来源是 `manual_daily_sale_target`。没有回落选项。如果 `manual_daily_sale_target` 为空，则该 SKU 无目标值，不出现在 P3 清单中。不要在任何 SQL 中引用 `sk.sales_target`，会报 `Binder Error: Table "sk" does not have a column named "sales_target"`。
>
> **跨 Skill 依赖**：`manual_daily_sale_target` 的值会被 Scene04(智能备货) 通过 `MAX(weighted_daily, target_daily)` 公式消费。改变目标值会连锁影响备货建议。详见 `references/target-dependency-across-skills.md`。

## 参数

| 参数 | 含义 | 当前值 | 来源 |
|:---|:---|:---|:---|
| **P3** | 重点关注SKU数量N | 10 | `dwd_params WHERE param_no='P3'` |
| `trend_window` | 7天 vs 30天 | 7/30 | Skill硬编码 |
| `trend_threshold` | 偏离触发阈值 | 0.20 (20%) | Skill硬编码 |
| `forecast_window` | 预测窗口天数 | 30 | Skill硬编码 |

> **重要**：`weighted_daily` 已内嵌趋势（0.5×昨日 + 0.3×7d + 0.2×30d），因此**不做二次趋势系数乘法**。`forecast_daily = weighted_daily` 直接使用。趋势偏离率仅用于趋势判定标签（上升/平稳/下降）和趋势解释层展示，不修改预测值。这是 PRD 口径与 DWD 实现一致后的设计决定（详见设计文档 2026-05-20/21）。

## 目标值批量更新

场景01 消费 `ods_skus.manual_daily_sale_target` 作为目标值。**按货盘批量更新目标值**是前置操作。

### 数据驱动法：中位数×系数（默认）

每个货盘的 `weighted_daily` **中位数** × `2.5`，按货盘阶梯设定。系数可调。

```python
import duckdb
con = duckdb.connect('${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}')

tiers = con.execute('''
SELECT tier, MEDIAN(weighted_daily) as median_wd,
       ROUND(MEDIAN(weighted_daily) * 2.5, 0) as target
FROM dwd_sku_daily_metrics
WHERE weighted_daily > 0 AND tier IN ('S','A','B','C')
GROUP BY tier
ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 END
''').fetchall()

con.execute("UPDATE ods_skus SET manual_daily_sale_target = NULL, updated_at = NOW() WHERE tier IN ('S','A','B','C')")
for tier, median, target in tiers:
    con.execute(f"UPDATE ods_skus SET manual_daily_sale_target = '{int(target)}', updated_at = NOW() WHERE tier = '{tier}'")
```

典型值参考（历史数据，实际随数据刷新变动）：

| 货盘 | median_wd | target(×2.5) |
|:---|---:|---:|
| S | 16.6 | 42 |
| A | 3.3 | 8 |
| B | 0.9 | 2 |
| C | 0.4 | 1 |

### 均值法（「有可能达成，稍微有点挑战」）

当用户要求推荐平衡的目标值时使用。每个货盘的 `weighted_daily` **均值**作为目标值。均值介于中位数和 p75 之间，代表 tier 平均水平。

```python
tiers = con.execute('''
SELECT tier, GREATEST(ROUND(AVG(weighted_daily), 0), 1) as target
FROM dwd_sku_daily_metrics
WHERE weighted_daily > 0 AND tier IN ('S','A','B','C')
GROUP BY tier ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 END
''').fetchall()

con.execute("UPDATE ods_skus SET manual_daily_sale_target = NULL, updated_at = NOW() WHERE tier IN ('S','A','B','C')")
for tier, target in tiers:
    con.execute(f"UPDATE ods_skus SET manual_daily_sale_target = '{int(target)}', updated_at = NOW() WHERE tier = '{tier}'")
```

| 货盘 | 均值 | 目标/日 | 
|:---|---:|---:|
| S | 24.9 | 25 |
| A | 4.1 | 4 |
| B | 1.2 | 1 |
| C | 0.6 | 1 |

> **⚠️ 陷阱**：`ROUND(AVG(weighted_daily), 0)` 对 B/C 货盘可能归零（如 avg=0.35→0），导致该货盘所有 SKU 不设目标。**必须用 `GREATEST(ROUND(...), 1)` 兜底最低目标=1**。典型场景：当销售数据稀疏（仅30天窗口）时，B 货盘 avg_wd 可能降至 0.3~0.5。

### 目标校准：用缺口率逆向定系数

当用户要求「调优目标值」时，用以下方法找到「约 20~30% SKU 有缺口」的系数：

```python
for tier in ['S','A','B','C']:
    vals = con.execute(f"SELECT weighted_daily FROM dwd_sku_daily_metrics WHERE weighted_daily > 0 AND tier='{tier}'").fetchdf()['weighted_daily']
    median = vals.median()
    for mult in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]:
        gap_pct = (vals * 30 < median * mult * 30).mean() * 100
        # ● 标记 20~33% 区间
```

**陷阱**：不要用「each SKU 的目标 = 自己的 × 系数」。这会导致数学上 100% 缺口率（forecast = wd × 30 < target = wd × 系数 × 30 对任何系数 > 1 永远成立）。目标必须是 tier 统一值。

### 通用注意事项

- `manual_daily_sale_target` 是 VARCHAR 列，**必须用单引号包裹值**
- 更新后需重新运行场景01 才能看到新目标下的缺口
- DuckDB 没有 `changes()` 函数，可通过对比更新前后的 AVG/MIN/MAX 验证
- N 级 SKU 通常无销售数据，不给目标

## 计算逻辑

### 1. 主公式（对齐 PRD 6.1）

```
近30天日均 = dwd_sku_daily_metrics.avg_30d_qty      -- DWD预计算
近7天日均  = dwd_sku_daily_metrics.avg_7d_qty        -- DWD预计算

趋势偏离率 = (近7天日均 / 近30天日均) − 1

趋势调整系数 = CASE
  WHEN 趋势偏离率 ≥ +trend_threshold THEN boost_rise       -- 🔺上升 → ×1.2
  WHEN 趋势偏离率 ≤ −trend_threshold THEN boost_fall       -- 🔻下降 → ×0.8
  ELSE 1.0                                                  -- ➡️平稳
END

预测日均 = weighted_daily                                -- DWD加权日均（已含趋势权重）
预测30天销量 = 预测日均 × 30
```

### 2. 缺口 & 达成率

```
销量缺口 = sales_target − 预测30天销量      -- 正=不够, 负=超额
达成率   = 预测30天销量 / sales_target × 100%
缺口占比 = 销量缺口 / sales_target × 100%    -- 仅缺口>0时展示
```

### 3. P3 重点关注清单（PRD 6.3）

候选集 = 所有 `sales_target IS NOT NULL AND 销量缺口 > 0` 的 SKU。
排序规则：`ORDER BY 销量缺口 DESC, 缺口占比 DESC, tier_priority, 波动率 DESC`，取前 P3/N 条。

```
tier_priority = CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
波动率 = ABS(avg_7d_qty − avg_30d_qty) / GREATEST(avg_7d_qty, avg_30d_qty, 0.01)   -- DWD无stddev，偏差近似
```

### 4. 趋势判定（PRD 6.4）

| 条件 | 趋势 |
|:---|:---:|
| 偏离率 ≥ +20% | 🔺 上升 |
| −20% < 偏离率 < +20% | ➡️ 平稳 |
| 偏离率 ≤ −20% | 🔻 下降 |
| 近7天数据avg_7d_qty=0 | 👁️ 观察 |
| 近30天数据avg_30d_qty=0 | ⚠️ 数据不足 |

> **趋势判定不等同于预测调整**：趋势判定标签仅用于 P3 重点关注清单给采购/运营看。实际的预测值 `forecast_daily` 已由 `weighted_daily`（0.5×昨日+0.3×7d+0.2×30d）内嵌了趋势信息，不再额外乘系数。

### 5. 预测置信度（PRD 6.6）

| 置信度 | 条件（DWD适配） |
|:---:|:---|
| 🔵 高 | avg_30d_qty > 0 且 7d/30d偏差率<50% |
| 🟡 中 | avg_30d_qty > 0 且 7d/30d偏差率<100% |
| 🔴 低 | avg_30d_qty = 0 或 偏差率≥100% |

> 注：原置信度依赖 days_30d 计数和 std_7d。DWD无日级明细，以降级后的偏差率近似替代。

## 核心 SQL

```sql
WITH dwd_base AS (
  SELECT
    d.sku_code,
    d.tier,
    d.product_name,
    d.avg_30d_qty,
    d.avg_7d_qty,
    d.weighted_daily,
    d.total_inventory,
    d.sellable_inv,
    d.onway_inv,
    d.inventory_days,
    -- 日均目标：仅 manual_daily_sale_target（⚠️ ods_skus 没有 sales_target 列）
    CAST(NULLIF(sk.manual_daily_sale_target, '') AS DOUBLE) AS sales_target,
    sk.category
  FROM dwd_sku_daily_metrics d
  LEFT JOIN ods_skus sk ON d.sku_code = sk.sku_code
  WHERE d.weighted_daily > 0
     OR (sk.manual_daily_sale_target IS NOT NULL AND sk.manual_daily_sale_target != '')
),
p3 AS (
  SELECT CAST(param_value AS INTEGER) AS n FROM dwd_params
  WHERE param_no = 'P3' AND (tier IS NULL OR tier = '')
  LIMIT 1
),
forecast AS (
  SELECT
    d.sku_code,
    d.product_name,
    d.category,
    COALESCE(d.tier, 'N') AS tier,
    d.avg_30d_qty,
    d.avg_7d_qty,
    d.weighted_daily AS forecast_daily,
    -- 趋势偏离率
    CASE WHEN d.avg_30d_qty > 0
      THEN (d.avg_7d_qty / NULLIF(d.avg_30d_qty, 0)) - 1
      ELSE 0 END AS trend_deviation,
    -- 趋势判断
    CASE
      WHEN d.avg_30d_qty = 0 THEN '⚠️数据样本不足'
      WHEN d.avg_7d_qty  = 0 THEN '👁️观察'
      WHEN (d.avg_7d_qty / NULLIF(d.avg_30d_qty, 0)) - 1 >= 0.20 THEN '🔺上升'
      WHEN (d.avg_7d_qty / NULLIF(d.avg_30d_qty, 0)) - 1 <= -0.20 THEN '🔻下降'
      ELSE '➡️平稳'
    END AS trend_judgment,
    -- 波动率（DWD无stddev，使用7d/30d偏差近似）
    CASE WHEN d.avg_30d_qty > 0
      THEN ABS(d.avg_7d_qty - d.avg_30d_qty) / NULLIF(GREATEST(d.avg_7d_qty, d.avg_30d_qty), 0)
      ELSE 0 END AS volatility_approx,
    -- 预测置信度
    CASE
      WHEN d.avg_30d_qty > 0
        AND ABS(d.avg_7d_qty - d.avg_30d_qty) / NULLIF(GREATEST(d.avg_7d_qty, d.avg_30d_qty), 0.01) < 0.50
        THEN '🔵高'
      WHEN d.avg_30d_qty > 0
        AND ABS(d.avg_7d_qty - d.avg_30d_qty) / NULLIF(GREATEST(d.avg_7d_qty, d.avg_30d_qty), 0.01) < 1.00
        THEN '🟡中'
      ELSE '🔴低'
    END AS confidence,
    d.sales_target
  FROM dwd_base d
)
SELECT
  *,
  ROUND(forecast_daily * 30, 0) AS forecast_30d,
  ROUND(sales_target - forecast_daily * 30, 0) AS sales_gap,
  CASE WHEN sales_target > 0
    THEN ROUND(forecast_daily * 30 / sales_target * 100, 1)
    ELSE NULL END AS achievement_pct,
  CASE WHEN sales_target > 0 AND sales_target - forecast_daily * 30 > 0
    THEN ROUND((sales_target - forecast_daily * 30) / sales_target * 100, 1)
    ELSE NULL END AS gap_ratio_pct,
  -- 波动率（百分比展示）
  ROUND(volatility_approx * 100, 1) AS volatility_pct
FROM forecast
WHERE avg_30d_qty IS NOT NULL OR sales_target IS NOT NULL
ORDER BY sales_gap DESC NULLS LAST
```

## P3 重点关注清单 SQL

```sql
WITH forecast_result AS ( /* 上述 CTE */ ),
p3 AS (SELECT CAST(param_value AS INTEGER) AS n FROM dwd_params WHERE param_no='P3' AND (tier IS NULL OR tier = '') LIMIT 1)
SELECT * FROM forecast_result
WHERE sales_target IS NOT NULL
  AND sales_gap > 0
ORDER BY
  sales_gap DESC,
  gap_ratio_pct DESC,
  CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END,
  volatility_pct DESC
LIMIT (SELECT n FROM p3)
```

`P3` 从 `dwd_params WHERE param_no='P3'` 读出整数 N，默认 10。

## 输出格式

```
场景01 销量需求分析 @ {report_date}
数据窗口：{min_date} → {max_date}（{days}天）

═══════════════════════════════════════
📊 概览
  有销售记录 SKU：{n}    已设目标 SKU：{m}
  总体预测30天：{qty}     总体目标：{target}
  总体缺口：{gap}（{pct}%）

═══════════════════════════════════════
📈 趋势分布
  🔺上升 xxx  |  ➡️平稳 xxx  |  🔻下降 xxx  |  👁️观察 xxx  |  ⚠️数据样本不足 xxx

═══════════════════════════════════════
📋 货盘汇总
| 货盘 | SKU数 | 预测30天 | 目标总量 | 缺口总量 | 平均达成率 |
|------|-------|----------|----------|----------|-----------|
| S    | xxx   | xxx      | xxx      | xxx      | xx%       |
| A    | ...   |          |          |          |           |

═══════════════════════════════════════
🔴 P3 重点关注清单（Top {N}）
| # | SKU | 品名 | 货盘 | 预测30天 | 目标 | 缺口 | 达成率 | 趋势 | 置信度 | 关注理由 |
|---|-----|------|------|----------|------|------|--------|------|--------|----------|
| 1 | ... | ...  |  S   | 500      | 800  | -300 | 62.5%  | 🔺上升 | 🟡中   | 缺口最大 |
```

## 数据样本不足降级

当 DWD 中 `avg_30d_qty = 0`（即近30天无任何销售记录，意味着可用数据天数 < 7）时视为数据样本不足：
- 趋势置「⚠️数据样本不足」，不参与预测，不输出趋势系数
- 置信度降为🔴低
- `avg_7d_qty = 0` 但 `avg_30d_qty > 0` 时置「👁️观察」（近期无销但历史有数据，可能处于间歇性销售状态）

## 已知问题与边角处理

### 1. CAST 失败（manual_daily_sale_target 是 VARCHAR）

`ods_skus.manual_daily_sale_target` 是 VARCHAR 列，CAST 为 DOUBLE 时可能失败：
```sql
-- 正确写法
CAST(NULLIF(sk.manual_daily_sale_target, '') AS DOUBLE)
-- NULLIF('', ...) 将空字符串转 NULL → CAST 安全返回 NULL
```
如遇到 `Binder Error: No function matches the given name` 检查列名是否写对。

### 2. 极值达成率
当 `target_total` 远小于 `forecast_total` 时（如均值目标下达成率 2,717%），直接展示百分比没有意义。输出时应对 `achievement_rate > 500%` 统一显示为「超额完成」而不是具体数字：
```python
if achievement_rate > 500:
    achievement_display = '超额完成'
else:
    achievement_display = f'{achievement_rate:.1f}%'
```

### 3. P3 查询为空
如果 `dwd_params` 中没有 tier 为空的 P3 记录，`p3` CTE 返回空行导致 LIMIT 子句失效。执行时需检查：
```python
p3_n = 10  # 默认值
p3_val = con.execute("SELECT CAST(param_value AS INTEGER) FROM dwd_params WHERE param_no='P3' AND (tier IS NULL OR tier = '') LIMIT 1").fetchone()
if p3_val: p3_n = p3_val[0]
```

### 4. N 级 SKU 无目标 + manual_daily_sale_target 为空时

N 级 SKU 通常无销售数据，不给目标值。场景01 的 `WHERE` 子句已通过 `d.weighted_daily > 0` 过滤掉无销量的 SKU，因此 N 级不会出现在报告中。

### 5. weighted_daily 对稀疏数据SKU的失真（库存天数虚高至数年）

`weighted_daily = 0.5×昨日 + 0.3×7d均 + 0.2×30d均` 在销售稀疏的SKU上会**系统性地低估日均销**，连锁导致 `inventory_days` 虚高到数月甚至数年。

**根因**：约35%（具体数字随数据窗口变动）的SKU"近7天零销但30天内有数据"（avg_7d_qty=0, avg_30d_qty>0）。对这些SKU：
- `昨日=0`, `7d均=0`, `30d均≈0.1~0.3` → wd ≈ **0.02~0.06件/天**
- 而实际是"偶尔卖1件的长尾品"，不是"每天稳定卖0.02件"
- 库存100件 ÷ 0.02 = **5,000天 ≈ 13年**

**实际影响量化**（数据窗口31天时）：
| 数据画像 | SKU占比 | 中位数wd |
|:---|:---:|:---:|
| 近7天+30天都有销售 | 64% | 0.35 |
| **近7天零销，仅30天有数据** | **36%** | **0.14** |

**缓解措施**（二选一，推荐方案①）：
1. **过滤先于计算**：只在 `avg_30d_qty > 0` 且 `avg_7d_qty > 0` 的SKU上做库存天数分析，过滤掉"偶发销售"的长尾品
2. **调权重**：将公式改为 `0.2×昨日 + 0.3×7d均 + 0.5×30d均`，降低对"昨日"的过度依赖，平滑稀疏SKU的波动。**副作用**：对热销SKU的敏感度也会下降（昨日大促的影响被稀释）

> ⚠️ 随着数据窗口积累（60天→90天），此问题会自然减轻——30d均覆盖更多有效样本，稀疏比例下降。

**重要**：`manual_daily_sale_target` 在生产环境可能全部为空（无人设定目标值）。此时场景01 只能输出预测数据，缺口和 P3 都会被跳过。如需出含缺口的完整报告，必须先通过「目标值批量更新」章节写入目标值。

## 趋势解释层

**适用范围**：所有趋势判定为「🔺上升」或「🔻下降」的 SKU。

对这类 SKU，输出时必须展示完整的计算依据链，不得仅给出「上升/下降」结论：

```
每个被趋势修正的 SKU 输出：
  近7天日均：{avg_7d_qty} 件
  近30天日均：{avg_30d_qty} 件
  偏离率：(avg_7d / avg_30d − 1) = {trend_deviation%}
  触发阈值：20%
  趋势标签：{上升/下降}
  预测日均 = weighted_daily = {forecast_daily}
  说明：「近7天日均 {avg_7d_qty} 较近30天日均 {avg_30d_qty} 
             上升/下降 {deviation}%，超过 20% 阈值，
             标记为 {趋势标签}
             预测日均 = weighted_daily = {forecast_daily}」
```

**展示位置**：趋势解释层放在输出报告的末尾，以可折叠或独立段落呈现。若没有任何 SKU 触发趋势修正，该段不输出。

**HTML/PDF 报告中的呈现**：趋势解释层单独作为一个表格插入 PDF，列为 `SKU | 7d日均 | 30d日均 | 偏离率 | 阈值 | 趋势标签 | 预测日均`。仅在趋势非平稳的 SKU 出现时才渲染此表。

## 渠道交付策略

> 共享交付模块：`~/workspace/pmc-agents/scripts/pmc_delivery.py`

### 渠道判断
- **飞书 / Telegram**：支持文件附件 → 生成 PDF 报告 + Excel 明细
- **终端 / TUI**：纯文本 → 输出 Markdown

### PDF 报告映射

| PDF 板块 | 数据来源 | 布局说明 |
|:---|:---|---|
| **KPI 卡片区**（顶部4卡片） | 概览数据 | 卡片1：有销售SKU数、卡片2：总体预测30天、卡片3：总体目标、卡片4：总体缺口+缺口率（红色=缺口>0） |
| **趋势分布条** | 趋势统计 | 5段水平的进度条：🔺上升 / ➡️平稳 / 🔻下降 / 👁️观察 / ⚠️数据样本不足 |
| **货盘缺口分布表** | 货盘汇总SQL | 表格：货盘 \| SKU数 \| 预测30天 \| 目标总量 \| 缺口总量 \| 平均达成率。S/A/B/C/N 各一行，合计行粗体。缺口列为正时红色标注。 |
| **P3 重点关注清单** | P3 SQL（Top N） | 表格：序号 \| SKU编码 \| 品名 \| 货盘 \| 预测30天 \| 目标 \| 缺口 \| 达成率 \| 趋势 \| 置信度。危急行（达成率<50%）浅红背景高亮。 |
| **趋势解释层**（条件渲染） | 趋势≠平稳的SKU | 表格：SKU \| 7d日均 \| 30d日均 \| 偏离率 \| 阈值 \| 系数 \| 修正说明。仅在存在系数≠1.0的SKU时渲染，否则整节跳过。 |

### Excel 明细映射

| Sheet | 内容 | 关键列 |
|:---|:---|---|
| 预测总表 | 所有SKU的完整预测结果 | sku_code, product_name, tier, category, avg_30d_qty, avg_7d_qty, forecast_daily, forecast_30d, sales_target, sales_gap, achievement_pct, gap_ratio_pct, trend_judgment, confidence, volatility_pct |
| P3重点关注 | Top N 缺口SKU | 同上，仅缺口>0的SKU，按优先级排序 |
| 货盘汇总 | 按货盘聚合 | tier, sku_count, total_forecast_30d, total_target, total_gap, avg_achievement_pct |

### 执行流程
1. 运行场景01分析SQL，得到 `forecast_result` DataFrame
2. 查询聚合：趋势分布 + 货盘汇总
3. 调用 `pmc_delivery.detect_channel()` 判断渠道
4. 若支持附件：
   - 调用 `pmc_delivery.render_html_to_pdf()` 生成 PDF（含KPI卡片 + 趋势条 + 货盘表 + P3清单）
   - 调用 `pmc_delivery.render_dataframe_to_excel()` 生成 Excel（含以上3个Sheet）
   - 发送 PDF + Excel 到当前渠道，附加 3-5 句摘要（含总体缺口、达成率、Top 1 SKU）
5. 若不支持附件：输出 Markdown 全文
