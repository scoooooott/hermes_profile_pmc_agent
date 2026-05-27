# SKU编码映射：v_cdm_skubom 打通海外库存 ↔ 销量

## 背景

DWD 层 `dwd_sku_daily_metrics` 中有三套SKU编码：
- **海外库存**（`ods_inventory_overseas.sku_code`）：cosboard原生编码，如 `DA0024AD-7P1-L`、`23T13CD-6P03-L`
- **发货**（`ods_ship.sku_code`）：cosboard原生+前缀，如 `ShDE_T1584ND-6P10-L`
- **销量/国内**（`dwd_sku_daily_metrics.sku_code`）：归一化内部编码，如 `BX451-Black-S`、`BA1806TAC-1P01-M`

三者编码体系不同，无法直接JOIN。

## 映射来源

**表**：`v_cdm_skubom`（cosboard MySQL视图）→ 已导入DuckDB为 `ods_cdm_skubom`

**结构**：

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `psku` | VARCHAR | 平台SKU（cosboard原生编码，如 `01_BX451AB-1P01-S`） |
| `sku_id` | VARCHAR | 归一化内部SKU（如 `BX451-Black-S`） |
| `rm_qty` | BIGINT | 比例系数（1=1:1，3=1个psku对应3个sku_id单位） |

**行数**：302,520行（多个sku_id可对应同一个psku——颜色、规格变体）

## 映射链路

```
ods_inventory_overseas.sku_code  (= psku, 匹配率99.6%)
  → JOIN ods_cdm_skubom ON sku_code = psku
  → ods_cdm_skubom.sku_id  (= 归一化编码)
  → JOIN dwd_sku_daily_metrics ON sku_id = sku_code
```

## 关键发现

1. **海外库存不包含 `01_` 等前缀**：`ods_inventory_overseas.sku_code` 是 `DA0024AD-7P1-L`，而 `v_cdm_skubom.psku` 可能是 `01_DA0024AD-7P1-L`。但测试发现直接 `=` 匹配也能命中——说明前缀不是必须的，或者某些psku也不带前缀。

2. **一个psku→多个sku_id**（1:N）：例如 `DA0024AD-7P1-L` 映射到 `PX120-BlackBrown-L` 和 `PX120-IndigoBlue-L`。拆分库存时按 `rm_qty / SUM(rm_qty)` 比例分配。

3. **`ods_inventory_overseas` 列是 VARCHAR**：`inv_available` 和 `inv_onway` 是 VARCHAR 类型，CAST 前必须 `NULLIF('')`。

4. **ods_ship 也走psku体系**：`ods_ship.sku_code` 格式如 `ShDE_T1584ND-6P10-L`，在 `v_cdm_skubom.psku` 中可能带 `ShDE_` 前缀。当前实际匹配中 `ods_ship` 的38个SKU全部匹配到了psku，说明做了前缀归一化处理。

## 映射SQL（核心）

```sql
CREATE OR REPLACE TEMP TABLE _ov_mapped AS
WITH overseas_psku AS (
  SELECT sku_code AS psku,
    MAX(CAST(COALESCE(NULLIF(inv_available,''),'0') AS DOUBLE)) AS inv_available,
    MAX(CAST(COALESCE(NULLIF(inv_onway,''),'0') AS DOUBLE)) AS inv_onway
  FROM ods_inventory_overseas
  GROUP BY sku_code
),
ship_psku AS (
  SELECT sku_code AS psku,
    SUM(CAST(COALESCE(NULLIF(ship_qty,''),'0') AS DOUBLE)) AS ship_onway
  FROM ods_ship WHERE ship_date IS NOT NULL GROUP BY sku_code
),
mapped AS (
  SELECT o.psku, m.sku_id, m.rm_qty,
    o.inv_available, o.inv_onway, COALESCE(s.ship_onway,0) AS ship_onway
  FROM overseas_psku o
  JOIN ods_cdm_skubom m ON o.psku = m.psku
  LEFT JOIN ship_psku s ON o.psku = s.psku
),
total_rm AS (
  SELECT psku, SUM(rm_qty) AS total_rm FROM mapped GROUP BY psku
)
SELECT 
  m.sku_id,
  CAST(ROUND(m.inv_available * m.rm_qty / NULLIF(t.total_rm,0), 0) AS BIGINT) AS ov_available,
  CAST(ROUND(m.inv_onway * m.rm_qty / NULLIF(t.total_rm,0), 0) AS BIGINT) AS ov_onway,
  CAST(ROUND(m.ship_onway * m.rm_qty / NULLIF(t.total_rm,0), 0) AS BIGINT) AS ov_ship_onway
FROM mapped m
JOIN total_rm t ON m.psku = t.psku;
```

## 匹配统计（2026-05-26数据）

| 指标 | 数值 |
|:---|:---:|
| 海外库存Distinct SKU | 13,632 |
| 通过psku匹配 | 13,583（99.6%） |
| 映射后sku_id | 11,919 |
| 其中有销量 | 2,717 |
| 有销量+海外可用库存 | 7,174 |
| 之前交集（不映射） | 1 |

## ods_ship 补充说明

`ods_ship` 表有 `dest_warehouse`（FBA收货仓库如 DTM2、IND9 等57个FC代码）和 `ship_qty`、`ship_date`、`expect_arrival`。用于FC拆解——按历史发货占比分配建议补货量到各FC。

`warehouse_name` 全是"虚拟仓库"无意义，`fulfillment_center`/`dest_warehouse` 才是真实收货仓库。
