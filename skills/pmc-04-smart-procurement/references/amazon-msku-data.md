# 亚马逊 MSKU 数据结构参考

> 最后更新：2026-05-22
> 来源：本会话分析验证

## 表结构

### `ods_amazon_msku_map`（28,597 行，含仓库/店铺维度）

| 列 | 类型 | 示例 | 说明 |
|---|---|---|---|
| msku | varchar | `A1021AB-3P01-S-1` | 亚马逊平台 SKU ID，可直接当作 `sku_code` 使用 |
| warehouse | varchar | `SH-na-北美仓` | 仓库 |
| store | varchar | `SH-na-US` | 店铺 |
| match_status | varchar | `matched` / `unmatched` | 匹配状态 |
| match_note | varchar | `【需清洗】...` | 未匹配原因的说明 |

### `ods_amazon_msku_agg`（13,467 行，按 MSKU 去重）

| 列 | 类型 | 示例 | 说明 |
|---|---|---|---|
| msku | varchar | `A1021AB-3P01-S-1` | 亚马逊 MSKU （唯一键） |
| store_group | varchar | `SH-na-US,SH-na-CA` | 所售店铺列表，逗号分隔 |
| warehouse_group | varchar | `SH-na-北美仓` | 发货仓库 |
| store_count | integer | `2` | 覆盖店铺数 |
| warehouse_count | integer | `1` | 发货仓库数 |
| match_status | varchar | `matched` / `unmatched` | 匹配状态 |

## 匹配状态分布

| 状态 | 唯一 MSKU 数 | 总行数 | 说明 |
|---|---|---|---|
| `matched` | 13,381 | 28,489 | 已成功匹配，msku 可直接作为 sku_code 使用 |
| `unmatched` | 86 | 108 | 未匹配，原因见 match_note |

## 未匹配原因（match_note）

| 原因类型 | 示例 MSKU | 说明 |
|---|---|---|
| 无主库存 | `Amazon.Found.B0D41W8TK3` | Amazon找到的无主库存货件，非正常MSKU |
| 前缀需剥离 | `ShDE_A1021DC-3P03-M` | 含 SH欧洲平台前缀 `ShDE_`，需剥离前缀后匹配产品SKU |
| 新品未录入 | — | ods_skus中无此SKU（新品未录入） |

## 关键发现

### 1. MSKU 直接等于 SKU_CODE

所有 `match_status='matched'` 的 MSKU 可以直接作为 `sku_code` 查询下游表（`dwd_sku_daily_metrics`, `ods_skus` 等），无需额外映射。

验证 SQL：
```sql
SELECT COUNT(*) as total, 
       SUM(CASE WHEN d.sku_code IS NOT NULL THEN 1 ELSE 0 END) as in_dwd
FROM (SELECT DISTINCT msku as sku_code FROM ods_amazon_msku_agg WHERE match_status='matched') a
LEFT JOIN dwd_sku_daily_metrics d ON a.sku_code = d.sku_code;
-- 结果：13,381 / 13,381 (100% 匹配)
```

### 2. 亚马逊 MSKU 在 DWD 层无销售数据

全部 13,381 个 matched MSKU 在 `dwd_sku_daily_metrics.weighted_daily` 中为 0：

```sql
SELECT COUNT(*) as total_in_dwd,
       SUM(CASE WHEN weighted_daily > 0 THEN 1 ELSE 0 END) as has_sales
FROM dwd_sku_daily_metrics
WHERE sku_code IN (SELECT DISTINCT msku FROM ods_amazon_msku_agg WHERE match_status='matched');
-- 结果：13,381 / 0
```

`ods_sales` 表也查询不到亚马逊 MSKU 的销售记录（0 行匹配）。

### 3. 两套编码体系

| 体系 | 示例 | 数据来源 |
|---|---|---|
| 内部 SKU | `PY1203-Light Camel-M` | dwd_sku_daily_metrics（有销售数据） |
| 亚马逊 MSKU | `A1021AB-3P01-S-1` | ods_amazon_msku_map/agg（无销售数据） |

内部 SKU 格式：`{产品代码}-{颜色}-{尺码}`
亚马逊 MSKU 格式：`{产品代码}{颜色代码}-{款式}-{尺码}[-{变体}]`

两者通过产品代码（如 `A1021` 对应 `BA1045` 等）可能存在映射关系，但当前数据库中没有现成的映射表。
