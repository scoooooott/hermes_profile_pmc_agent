# Amazon 数据架构

## 背景

ODS 层中存在两套与 Amazon 相关的数据，编码体系不同，需要正确区分。

## 两套编码体系

### 1. Amazon MSKU（`ods_amazon_msku_agg` / `ods_amazon_msku_map`）

| 来源 | 格式示例 | 说明 |
|------|---------|------|
| `ods_amazon_msku_agg.msku` | `A1021AB-3P01-S-1` | Amazon 平台产品编号（产品-颜色-款式-尺码-变体） |
| `ods_amazon_msku_map.msku` | `KJ310FB-7P01-S` | 同上，含 Amazon 仓库/店铺映射 |

**关键特征**：
- 全部 13,381 个 `match_status='matched'` 的 MSKU **作为 `sku_code` 存在于 `dwd_sku_daily_metrics`**
- 但 `weighted_daily` **全部为 0**（无销售数据）
- 有库存的仅 1 个：`BX538-Black-M`（1,004 件，C 级）
- 商品名称以 "SH亚马逊-" 开头

**结论**：Amazon MSKU 是内码 SKU 之外的独立编码体系，与内码 SKU **无直接映射关系**（无 BOM 表关联）。

### 2. 内码 SKU（`ods_skus` / `dwd_sku_daily_metrics`）

| 格式示例 | 说明 |
|---------|------|
| `PY1203-Light Camel-M` | 产品-颜色-尺码 格式 |
| `BA1045-Skin-L` | 同上 |
| `B2106D002A-Black-M` | 组合装 / 套装格式（也出现在 ods_sales 中） |

**关键特征**：
- 有完整的 `weighted_daily` 销售数据（93,246 个短码 SKU 中 1,993 个有销售）
- 库存数据完备（sellable_inv + onway_inv）
- **这些 SKU 也通过 Amazon 渠道销售**

## Amazon 渠道销售数据

内码 SKU 在 Amazon 北美/欧洲等渠道的销售记录在 `ods_sales` 表中，通过 `msu_id` 区分渠道：

```sql
-- 亚马逊北美渠道（美国/加拿大/墨西哥）
SELECT DISTINCT s.sku_code
FROM ods_sales s
WHERE (s.msu_id LIKE '%US%' OR s.msu_id LIKE '%na-%' 
       OR s.msu_id LIKE '%北美%' OR s.msu_id LIKE '%CA%' 
       OR s.msu_id LIKE '%MX%')
```

| `msu_id` 值 | 含义 |
|------------|------|
| `SH-na-US美国仓` | 北美美国 |
| `SH-na-CA加拿大仓` | 北美加拿大 |
| `DA-na-US美国` | 北美美国 |
| `DA-na-CA加拿大` | 北美加拿大 |
| `DA-na-MX墨西哥` | 北美墨西哥 |
| `CI-US美国` | 美国 |
| `TTW-US美国` | 美国 |
| `ZB-US美国` | 美国 |
| `SH-eu-*` | 欧洲各国 |
| `DA-eu-*` | 欧洲各国 |

`ods_sales` 共计 71,733 行，其中 51,058 行是传统短码，4,741 行是 Amazon 格式（169 个 SKU）。

## 如何查询"亚马逊库存"

要查询在 Amazon 平台销售的商品的库存情况，标准的查询路径是：

1. 从 `ods_sales` 中找出在 Amazon 渠道有销售记录的内码 SKU
2. JOIN `dwd_sku_daily_metrics` 获取库存和销售数据
3. 计算可售天数 = `(sellable_inv + onway_inv) / weighted_daily`

```sql
WITH amazon_na_skus AS (
  SELECT DISTINCT s.sku_code
  FROM ods_sales s
  WHERE (s.msu_id LIKE '%US%' OR s.msu_id LIKE '%na-%' OR s.msu_id LIKE '%北美%'
         OR s.msu_id LIKE '%CA%' OR s.msu_id LIKE '%MX%')
)
SELECT 
  d.sku_code, d.product_name, COALESCE(d.tier, 'N') AS tier,
  ROUND(d.weighted_daily, 2) AS daily_sales,
  GREATEST(COALESCE(d.sellable_inv, 0), 0) AS sellable_inv,
  GREATEST(COALESCE(d.onway_inv, 0), 0) AS onway_inv,
  GREATEST(COALESCE(d.sellable_inv, 0), 0) + GREATEST(COALESCE(d.onway_inv, 0), 0) AS total_inv,
  ROUND((GREATEST(COALESCE(d.sellable_inv, 0), 0) + GREATEST(COALESCE(d.onway_inv, 0), 0)) 
        / NULLIF(d.weighted_daily, 0), 1) AS days_on_hand
FROM amazon_na_skus a
JOIN dwd_sku_daily_metrics d ON a.sku_code = d.sku_code
WHERE d.weighted_daily > 0;
```

## 已知数据质量

### Amazon MSKU 零销售

Amazon MSKU（`A1021AB-3P01-S-1` 格式）在 `dwd_sku_daily_metrics` 中 `weighted_daily` 全部为 0。原因推测：
- 亚马逊平台销售使用的是内码 SKU（如 `BA1045-Skin-L`），而非 MSKU
- MSKU 仅用于亚马逊内部库存管理，销售结算走内码 SKU

### 历史发现：全量预警规模

2026-05-22 对亚马逊北美渠道的分析发现：
- 1,955 个内码 SKU 可售天数 > 150 天
- 1,343 个 SKU 可卖 1 年+，148 个可卖 10 年+（最高 203 年）
- 积压库存总量约 142 万件
- C 级长尾品占大头（721 个 SKU，44.6 万件）
- S 级中也有 202 个 SKU 积压（23.1 万件），多为极端尺码（XXL/XXXL）或冷门颜色
