# 验证 SQL 查询

> 阶段 E Step 2 执行验证时按需加载。

## 验证 1：SKU 覆盖率

```sql
SELECT
    (SELECT COUNT(DISTINCT sku_code) FROM ods_skus) AS total_skus,
    (SELECT COUNT(DISTINCT sku_code) FROM ods_sales) AS skus_with_sales,
    (SELECT COUNT(DISTINCT sku_code) FROM ods_inventory_domestic) AS skus_with_inv;
```

**判读**：`skus_with_sales / total_skus` 应 > 50%；`skus_with_inv` 应接近 `total_skus`。

## 验证 2：日期连续性（最近 30 天）

```sql
SELECT sale_date, COUNT(DISTINCT sku_code) AS skus,
       SUM(CAST(daily_qty AS INTEGER)) AS total_qty
FROM ods_sales
WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 30
GROUP BY sale_date ORDER BY sale_date DESC
LIMIT 30;
```

**判读**：应有连续日期无大段断裂；日均 SKU 数波动不超过 50%。

## 验证 3：DWD 数据合理性

```sql
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE weighted_daily > 0) AS with_sales,
    COUNT(*) FILTER (WHERE total_inventory > 0) AS with_inventory,
    COUNT(*) FILTER (WHERE inventory_days BETWEEN 1 AND 365) AS reasonable_days,
    COUNT(*) FILTER (WHERE inventory_days > 365) AS warning_slow_moving,
    COUNT(*) FILTER (WHERE inventory_days < 0) AS data_error
FROM dwd_sku_daily_metrics;
```

**判读**：
- `with_sales` 应 > 0
- `data_error` 应 = 0
- `warning_slow_moving` 是预警项，不阻断但需客户关注

## 验证 4：抽样场景验证

```sql
SELECT sku_code, weighted_daily, total_inventory, inventory_days, tier
FROM dwd_sku_daily_metrics
WHERE weighted_daily > 0 AND inventory_days > 0
ORDER BY inventory_days ASC
LIMIT 10;
```

**判读**：返回结果应有合理的 `weighted_daily` 和 `inventory_days` 分布。
