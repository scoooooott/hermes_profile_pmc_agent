# PMC 数据架构

## 管线全链路

```
数据源 → 管线（API/CSV/DB/Excel）→ DuckDB ODS（9张表）
  → refresh_dwd_metrics.py → dwd_sku_daily_metrics（统一消费口）
    → 10 个场景 Skill 消费
```

## 六大业务板块

### ① 商品档案
- **ods_skus**（14列）：商品主数据（仅单品），全量覆盖。字段：sku_code(PK), spu_code, product_name, category, tier(S/A/B/C/N), lifecycle(新品/成长/成熟/衰退), production_cycle_days, manual_daily_sale_target, lead_time, moq
- **加载模式**：全量覆盖（DROP + INSERT）
- **场景00** 写入 tier 和 lifecycle，经 DWD 同步到所有下游场景

### ② 每日销量
- **ods_sales**（4列）：日销量增量，增量 UPSERT。字段：sku_code, sale_date(YYYY-MM-DD), daily_qty, msu_id(最小销售单元ID)
- **约束**：`sku_code + sale_date + msu_id` 联合主键去重
- **场景00** 按 tier 分层聚合日均销，场景01-08 通过 DWD 消费

### ③ 库存快照
- **ods_inventory_domestic**（4列）：国内库存，全量覆盖。字段：sku_code, inv_domestic, inv_purchase_onway, snapshot_time
- **ods_inventory_overseas**（6列）：海外 FBA 库存，全量覆盖。字段：sku_code, shop, warehouse_code, inv_available, inv_onway, snapshot_time
- **加载模式**：全量覆盖。引擎取 `MAX(snapshot_time)` 的最新快照
- **DWD 层** 聚合海外库存为 `overseas_inv_available` 和 `overseas_inv_onway`

### ④ 采购明细
- **ods_po**（5列）：采购单明细，增量 UPSERT。字段：po_number, sku_code, order_date, order_qty, eta
- **ods_po_recv**（5列）：采购收货回传，增量 UPSERT。字段：po_number, sku_code, receipt_date, receipt_qty, warehouse_id
- **场景04** 消费 ods_po 计算在单覆盖量，场景09 消费两者计算采购周期

### ⑤ 发货明细
- **ods_ship**（7列）：国内→海外补货发货，增量 UPSERT。字段：tracking_number, sku_code, ship_date, ship_qty, dest_warehouse, expect_arrival, shop
- **DWD 层** 按 `ship_date ≤ CURRENT_DATE AND expect_arrival > CURRENT_DATE` 过滤在途
- **场景05** 按 `dest_warehouse` 拆解 FC（Fulfillment Center）发货计划

### ⑥ 供需映射
- **ods_wmap**（4列）：SKU×店铺×仓库映射，全量覆盖。字段：sku_code, msu_id, warehouse_id, updated_at
- **映射粒度**：按 SKU（同一店铺的不同 SKU 可能走不同仓库）
- **逻辑仓/逻辑店**：多个物理仓库→一个逻辑仓，多个店铺→一个逻辑店

### 规则参数
- **ods_params**（7列）：原始参数表。字段：param_no(P1-P14), param_id, param_name, param_default(JSON), param_type, param_note, sync_time
- **dwd_params**（8列）：参数统一消费口，由 DWD 引擎从 ods_params 展开。字段：param_no, param_id, param_name, param_type, param_note, sub_param, tier, param_value
- **消费方式**：`WHERE param_no = 'P7' AND tier = 'S'`

## DWD 统一消费口

**dwd_sku_daily_metrics**（15列，173,187 行）：
- `sku_code` VARCHAR PK — 来自 ods_skus
- `yesterday_qty` DOUBLE — 最新日期前一天的销量
- `avg_7d_qty` DOUBLE — 近7天日均
- `avg_30d_qty` DOUBLE — 近30天日均
- `weighted_daily` DOUBLE — 0.5×昨日 + 0.3×7d + 0.2×30d
- `total_inventory` DOUBLE — GREATEST(inv_domestic + inv_purchase_onway, 0)
- `inventory_days` DOUBLE — total_inventory / weighted_daily
- `tier` VARCHAR — S/A/B/C/N（场景00写入，经DWD同步）
- `product_name` VARCHAR — 来自 ods_skus
- `sellable_inv` DOUBLE — GREATEST(inv_domestic, 0)
- `onway_inv` DOUBLE — GREATEST(inv_purchase_onway, 0)
- `overseas_inv_available` DOUBLE — FBA 可售库存（SUM）
- `overseas_inv_onway` DOUBLE — FBA 在途库存（SUM）
- `overseas_ship_onway` DOUBLE — 海运在途（SUM，过滤条件：ship_date≤今天, expect_arrival>今天）
- `updated_at` TIMESTAMP — 刷新时间戳

## 场景消费矩阵

| 列 | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 |
|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| weighted_daily | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | |
| tier | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ |
| total_inventory | | | | ◉ | | | | | ◉ | |
| inventory_days | | | | ◉ | | | | | ◉ | |
| sellable_inv | | | ◉ | | ◉ | | ◉ | ◉ | | |
| onway_inv | | | ◉ | | ◉ | | ◉ | ◉ | | |
| overseas_inv_available | | | | | | ◉ | | | | |
| overseas_ship_onway | | | | | | ◉ | | | | |
| ods_po.order_qty | | | ◉ | | ◉ | | | | ◉ | ◉ |
| ods_ship.* | | | | | | ◉ | | | | |
| ods_wmap.msu_id | | | | | | ◉ | | | | |
