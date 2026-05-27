# 亚马逊 MSKU 库存关系导入

## 数据来源

亚马逊 MSKU 库存关系 Excel，通常含 3 个 Sheet：

| Sheet | 结构 | 说明 |
|---|---|---|
| 数据源 | MSKU, 仓库, 店铺 (逐行展开) | 明细版，一条 MSKU-仓库-店铺 一行 |
| Sheet2 | MSKU, 店铺(逗号分隔), 仓库(逗号分隔) | 聚合版，一条 MSKU 一行，店/仓用逗号合并 |
| Sheet1 | (同数据源格式) | 另一份明细 |

## 关键发现：MSKU = 产品 SKU（99.4% 精确匹配）

亚马逊 MSKU 的命名格式就是产品 SKU 的格式（如 `ZLCSDA-PX928-07P01-XL`、`DA5028-Black-M`），**不需要通过 `v_cdm_skubom` 做 psku→sku_id 归一化**。直接拿 MSKU 和 `ods_skus.sku_code` 做精确匹配即可。

13000+ MSKU 中 99.4% 精确命中，仅 86 条不匹配，全部属于以下三类。

## 未匹配分类

| 类型 | 典型 MSKU | 原因 | 处理 |
|---|---|---|---|
| 新品未录入 | `BA1806AB-1P01-S`、`BF1581RA-1PRA-L`、`PH1444RA-5PRA-L` | ods_skus 中无此产品 | 标记，需补录到 cosboard |
| Amazon.Found | `Amazon.Found.B0D41W8TK3` | 亚马逊找到的无主库存货件 | 标记为异常，建议删除 |
| 平台前缀残留 | `ShDE_A1021DC-3P03-M` | 多了 `ShDE_` 前缀，实际产品 SKU 为 `A1021DC-3P03-M` | 剥离前缀后匹配 |

注意：806 条 `ShDE_*` MSKU 是精确匹配 ods_skus 的——说明 ods_skus 中已存有带 ShDE_ 前缀的产品 SKU，这不是问题。

## 导入模式

```sql
-- 建表（明细版）
CREATE TABLE ods_amazon_msku_map (
    msku VARCHAR,
    warehouse VARCHAR,
    store VARCHAR,
    match_status VARCHAR,      -- 'matched' / 'unmatched'
    match_note VARCHAR          -- 清洗说明
);

-- 建表（聚合版）
CREATE TABLE ods_amazon_msku_agg (
    msku VARCHAR,
    store_group VARCHAR,        -- 逗号分隔的店群
    warehouse_group VARCHAR,    -- 逗号分隔的仓群
    store_count INTEGER,
    warehouse_count INTEGER,
    match_status VARCHAR,
    match_note VARCHAR
);
```

## 批量匹配技巧

DuckDB 对大批量 IN 查询友好，但 13000+ 参数可能超限制。分批匹配：

```python
all_sku = set(r[0] for r in con.execute(
    "SELECT DISTINCT sku_code FROM ods_skus WHERE sku_code IS NOT NULL"
).fetchall())

exact = set()
for i in range(0, len(msku_list), 500):
    batch = msku_list[i:i+500]
    ph = ','.join(['?' for _ in batch])
    exact.update(r[0] for r in con.execute(
        f"SELECT sku_code FROM ods_skus WHERE sku_code IN ({ph})", batch
    ).fetchall())
```

## 匹配后的清洗 SQL

```sql
-- 标记 Amazon.Found
UPDATE ods_amazon_msku_agg 
SET match_note = '【需清洗】Amazon找到的无主库存货件，非正常MSKU'
WHERE msku = 'Amazon.Found.B0D41W8TK3';

-- 标记平台前缀残留（仅未匹配的）
UPDATE ods_amazon_msku_agg 
SET match_note = '【需清洗】含SH欧洲平台前缀ShDE_，需剥离前缀后匹配产品SKU'
WHERE msku LIKE 'ShDE_%' AND match_status = 'unmatched';
```
