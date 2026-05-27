# PMC 六大业务数据板块

## 板块概览

PMC 分析引擎的标准数据模型由六个业务板块组成，外加一个独立的规则参数体系。这个分类是业务语义层面的，不是数据库表层面的 —— 同一个板块可能由多张 DuckDB 表承载。

| 板块 | DuckDB 表 | 加载模式 | 本质 |
|:---|:---|:---|:---|
| ① 商品档案 | `ods_skus` + `ods_cdm_skubom` | 全量覆盖 | 商品主数据 + SKU编码归一化映射 + 货盘等级（场景00动态刷新） |
| ② 每日销量 | `ods_sales` | 增量 UPSERT | SKU × 日期 × 渠道粒度的日销量统计 |
| ③ 库存快照 | `ods_inventory_domestic` + `ods_inventory_overseas` | 全量覆盖 | 国内仓 + 海外仓的每日终态统计 |
| ④ 采购明细 | `ods_po` + `ods_po_recv` | 增量 UPSERT | 采购单中每个 SKU 的采购量/预计到货/入仓 |
| ⑤ 发货明细 | `ods_ship` | 增量 UPSERT | 从国内仓紧急补货到海外的明细 |
| ⑥ 供需映射 | `ods_wmap` | 全量覆盖 | 店铺 ↔ 仓库的多对多关系（按 SKU 粒度） |
| 规则参数 | `ods_params` | 全量覆盖 | 各场景可变阈值 P1-P14 |

## 板块①：商品档案

**组成**：`ods_skus`（商品主数据）+ `ods_cdm_skubom`（SKU编码归一化映射）

**关键字段**：
- `sku_code`：内部统一 SKU 编码（归一化后），全系统唯一锚点
- `tier`：货盘等级 S/A/B/C/N，由场景00动态计算并回写
- `lifecycle`：生命周期阶段（新品/成长/成熟/衰退）
- `spu_code`：款式编码（同一款式可能对应多个尺码/颜色 SKU）

**SKU 编码归一化**（`ods_cdm_skubom`）：
- 这是商品档案板块的标准组成部分，不是某个客户特有的
- 不同客户有不同的源系统 SKU 编码规则（ERP、WMS、亚马逊等），归一化映射规则因人而异
- 字段：`psku`（源系统编码）→ `sku_id`（归一化编码），`rm_qty`（组合装拆解比例）
- 编码归一化必须在接入管线侧完成，引擎不做编码转换

## 板块②：每日销量

**组成**：`ods_sales`（单表）

**粒度**：SKU × 日期 × msu_id（最小销售单元）

**关键字段**：
- `sale_date`：YYYY-MM-DD 格式
- `daily_qty`：当日销售件数
- `msu_id`：渠道标识（如 `CI-eu-DE德国`），由 `concat(shop, site)` 生成

**加载模式**：增量 UPSERT —— 每天只追加昨天的新增数据，不覆盖历史。

## 板块③：库存快照

**组成**：`ods_inventory_domestic`（国内库存）+ `ods_inventory_overseas`（海外库存）

**国内库存**：
- `inv_domestic`：国内仓可售库存
- `inv_purchase_onway`：采购在途（已下单未入库）
- `snapshot_time`：快照时间戳，引擎取 MAX(snapshot_time)

**海外库存**：
- `inv_available`：FBA 可售库存
- `inv_onway`：FBA 在途库存
- `warehouse_code`：FBA 仓库代码
- `shop`：仓库所属店铺（从仓库名解析）

**加载模式**：全量覆盖 —— 每天拉最新全量快照，覆盖前一日数据。引擎始终取 `MAX(snapshot_time)` 的最新版本。

## 板块④：采购明细

**组成**：`ods_po`（采购单）+ `ods_po_recv`（收货回传）

**采购单**：
- `po_number`：采购单号
- `order_date`：下单日期
- `order_qty`：采购数量
- `eta`：预计到货日期

**收货回传**：
- `receipt_date`：实际收货日期
- `receipt_qty`：实际收货数量
- `warehouse_id`：入仓仓库

**加载模式**：增量 UPSERT。消费方：场景04（备货）、场景09（周期分析）。

## 板块⑤：发货明细

**组成**：`ods_ship`（单表）

**定义**：特指从国内仓库紧急补货到海外的行为，不是销售发货。

**关键字段**：
- `tracking_number`：物流单号
- `ship_date`：发货日期
- `ship_qty`：发货数量
- `dest_warehouse`：目标仓库（FBA 仓库代码）
- `expect_arrival`：预计到达日期

**加载模式**：增量 UPSERT。消费方：场景05（海外补货）、DWD 的 `overseas_ship_onway` 计算。

## 板块⑥：供需映射

**组成**：`ods_wmap`（单表）

**核心纠正**：映射粒度是 **按 SKU**，不是按店铺。

> 一个店铺不是只走一条供给链路。同一个店铺卖的 SKU A 可能由 A 仓供货，SKU B 可能由 B 仓供货。

**每条记录 = (sku_code, msu_id) → warehouse_id**

```
SKU: 蓝牙耳机-Black-S  ×  msu: CI-eu-DE  →  仓: FBA-DE1
SKU: 充电头-White-M     ×  msu: CI-eu-DE  →  仓: FBA-DE2  ← 同一店铺，不同SKU走不同仓
```

**之上的抽象层**：
- **逻辑仓**：多个物理仓库视为一个整体（如 `FBA-DE1` + `FBA-DE2` → `EU-Logical`）
- **逻辑店**：同批 SKU 从同一逻辑仓拉货的多个店铺，捆为一个需求单元

**加载模式**：全量覆盖。此表为低频变更的静态配置，数周不更新不影响正确性。

## 与 DWD 层的关系

六大板块数据通过 `refresh_dwd_metrics.py` 统一汇聚到 `dwd_sku_daily_metrics` 表，该表是 10 个场景 Skill 的统一消费口。场景 Skill 不再直接 JOIN 多张 ODS 表，而是 JOIN 一张 DWD 表。只有 `ods_params`（规则参数）和部分场景特需表（如 `ods_po` 被场景04直接消费）例外。
