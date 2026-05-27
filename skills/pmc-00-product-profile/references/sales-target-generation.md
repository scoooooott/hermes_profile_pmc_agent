# 日均销售目标值生成方法

## 统一字段

`ods_skus` 的目标值消费规则为：

- `manual_daily_sale_target` 非空时，优先使用人工目标值
- `manual_daily_sale_target` 为空时，回落使用 `sales_target`（系统目标值）

所有下游场景（01 销量需求、02 库存缺口、04 智能备货）统一按上述规则读取目标值，SQL 别名保持 `sales_target`：

```sql
COALESCE(
  CAST(NULLIF(sk.manual_daily_sale_target, '') AS DOUBLE),
  CAST(NULLIF(sk.sales_target, '') AS DOUBLE)
) AS sales_target
```

## 生成公式：量级缩放（2026-05-20 定稿）

基于 `dwd_sku_daily_metrics.weighted_daily`（加权日均销）按量级向上取整：

| 加权日均销范围 | 目标值 | 公式 |
|:---|---:|:---|
| 0 < WD < 10 | 10 | `CEIL(WD / 10) * 10` |
| 10 ≤ WD < 100 | 100 | `CEIL(WD / 100) * 100` |
| WD ≥ 100 | 1000 | `CEIL(WD / 1000) * 1000` |
| WD = 0 | 留空 | — |

### 例

| weighted_daily | manual_daily_sale_target |
|:---|---:|
| 0.20 | 10 |
| 9.99 | 10 |
| 10.0 | 100 |
| 98.6 | 100 |
| 161.07 | 1000 |

## 执行 SQL

```sql
UPDATE ods_skus o
SET manual_daily_sale_target = t.target_str
FROM (
  SELECT d.sku_code,
    CASE 
      WHEN d.weighted_daily <= 0 THEN NULL
      WHEN d.weighted_daily < 10 THEN CAST(CEIL(d.weighted_daily / 10) * 10 AS INTEGER)::VARCHAR
      WHEN d.weighted_daily < 100 THEN CAST(CEIL(d.weighted_daily / 100) * 100 AS INTEGER)::VARCHAR
      ELSE CAST(CEIL(d.weighted_daily / 1000) * 1000 AS INTEGER)::VARCHAR
    END as target_str
  FROM dwd_sku_daily_metrics d
  WHERE d.weighted_daily > 0
) t
WHERE o.sku_code = t.sku_code
```

## 数据规模

| 量级 | SKU数 | 占比 |
|:---|---:|---:|
| target=10 | 2,218 | 92.4% |
| target=100 | 179 | 7.5% |
| target=1000 | 4 | 0.2% |
| 留空(WD=0) | 169,951 | — |
| **有目标合计** | **2,401** | **1.4% of 172K** |

## 覆盖规则说明

覆盖规则已固化为业务规则，不再依赖参数控制。

## 变更历史

| 日期 | 变更 |
|:---|:---|
| 2026-05-20 | 初始生成：量级缩放，写 `manual_daily_sale_target`。下游场景统一采用固定覆盖规则：`manual_daily_sale_target` 非空优先，空值回落 `sales_target`。场景01/02/04升级 v2.2.0。 |
| 2026-05-21 | 新增「中位数×系数」方法（替代方案）。来源：杨宁实际使用中发现量级缩放的旧值不切实际，指定用货盘中位数×2.5。 |

---

## 方法二：中位数×系数（杨宁偏好，2026-05-21）

基于 DWD 加权日均销，按**货盘层级**设定统一目标，而不是逐SKU按量级缩放。

### 公式

```
tier_target = MEDIAN(weighted_daily WHERE tier = 'X') × multiplier

multiplier = 2.5（默认值，可调）
```

### 执行 SQL（Python + DuckDB 实现）

```python
import duckdb
con = duckdb.connect('${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}')

# 查询每个货盘中位数
tiers = con.execute('''
SELECT tier, MEDIAN(weighted_daily) as median_wd,
       ROUND(MEDIAN(weighted_daily) * 2.5, 0) as target
FROM dwd_sku_daily_metrics
WHERE weighted_daily > 0 AND tier IN ('S','A','B','C')
GROUP BY tier
ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 END
''').fetchall()

# 清旧目标
con.execute("UPDATE ods_skus SET manual_daily_sale_target = NULL, updated_at = NOW() WHERE tier IN ('S','A','B','C')")

# 设新目标
for tier, median, target in tiers:
    con.execute(f"UPDATE ods_skus SET manual_daily_sale_target = '{int(target)}', updated_at = NOW() WHERE tier = '{tier}'")

# 验证
print(con.execute('''
SELECT tier, COUNT(*) as cnt,
       AVG(CAST(NULLIF(manual_daily_sale_target,'') AS DOUBLE)) as avg_target
FROM ods_skus WHERE tier IN ('S','A','B','C')
GROUP BY tier ORDER BY CASE tier WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 END
''').fetchall())
```

### 典型值

| 货盘 | median_wd | ×2.5 = target |
|:---|---:|---:|
| S | 16.6 | 42 |
| A | 3.3 | 8 |
| B | 0.9 | 2 |
| C | 0.4 | 1 |

### 与量级缩放法的区别

| 维度 | 量级缩放（方法一） | 中位数×系数（方法二） |
|:---|:---|:---|
| 粒度 | 逐SKU | 按货盘统一 |
| 数据源 | 每个SKU的weighted_daily | 货盘中位数 |
| 目标差异 | 同一货盘内SKU目标值参差不齐 | 同一货盘内SKU目标统一 |
| 激进程度 | 偏激进（低销量SKU目标偏高） | 偏保守（基于中位数×系数） |
| 适用场景 | 希望激励低销量SKU提升 | 目标务实，关注缺口可控 |
