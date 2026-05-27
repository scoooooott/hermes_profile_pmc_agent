# DATA_CONTRACT — PMC 供应链分析系统数据接入契约

> 版本: 1.0 | 引擎: DuckDB | 最后更新: 2026-05-27

## 概述

本文档定义 PMC 供应链分析系统**标准引擎**与**客户数据管线**之间的接口契约。接入方需按本文档约定的表结构提供数据，引擎才能正常运转。

**分层加载机制：**
- **第一层（必需表）**：不提供则引擎无法工作。
- **第二层（可选表）**：有则启用对应场景能力，无则对应场景降级或不可用。

**加载模式说明：**
- **全量覆盖**：每次数据刷新时，整表替换。适用表数据量小、无增量标识的场景。
- **增量 UPSERT**：按主键（PK）插入或更新。适用需要累积历史、避免重复的场景。

**类型约定：**
- 所有字段统一用 `VARCHAR` 接入（DuckDB 无严格 Schema 约束，类型在 DWD 层转换）。数值、日期类字段以字符串形式传入。
- 特殊标注：`TIMESTAMP` 字段为 DuckDB 原生时间戳类型，接入时传 ISO 8601 格式字符串即可自动转换。

**空值约定：** 所有字段均可为 NULL（DuckDB 无 NOT NULL 约束），但标 `*` 的字段在 DWD 层计算时若为 NULL 将导致该行被跳过。

---

## 第一层：必需表

> 以下 5 张表是引擎运行的基础。缺少任何一张，DWD 层无法产出 `dwd_sku_daily_metrics`，所有下游场景全部瘫痪。

---

### 1. ods_skus — 商品档案

**用途：** 维护所有 SKU 的基础属性，是 DWD 层做货盘分级、加权日均销计算、库存天数分段的数据底座。ID-Mapping（sku_code → spu_code）亦由本表提供。

**加载模式：** 全量覆盖。每次刷新时替换全部行。

**字段清单（14 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `sku_code` | VARCHAR | \*PK | SKU 编码，全局唯一标识 | 不能为空串 |
| 2 | `spu_code` | VARCHAR | | SPU 编码，用于向上聚合到款式 | |
| 3 | `product_name` | VARCHAR | | 商品名称（中文） | |
| 4 | `category` | VARCHAR | | 品类，如 T恤/连衣裙/配件 | |
| 5 | `brand` | VARCHAR | | 品牌名称 | |
| 6 | `launch_date` | VARCHAR | | 首次上市日期 | `YYYY-MM-DD` 或空 |
| 7 | `status` | VARCHAR | | 商品状态 | 建议枚举：在售/停产/待上市 |
| 8 | `lifecycle` | VARCHAR | | 生命周期标签 | 建议枚举：导入期/成长期/成熟期/衰退期 |
| 9 | `tier` | VARCHAR | \* | 货盘分级 | **必须为 A/B/C/N**（引擎核心依赖） |
| 10 | `production_cycle_days` | VARCHAR | | 生产周期（天），用于场景09 周期分析 | 正整数或空 |
| 11 | `manual_daily_sale_target` | VARCHAR | | 人工设定的日均销售目标（件/天） | 正数或空 |
| 12 | `moq` | VARCHAR | | 最小起订量（MOQ） | 正整数或空 |
| 13 | `lead_time` | VARCHAR | | 前置时间（天） | 正整数或空 |
| 14 | `updated_at` | VARCHAR | | 最后更新时间 | `YYYY-MM-DD HH:MM:SS` |

**示例数据：**

| sku_code | spu_code | product_name | category | brand | launch_date | status | lifecycle | tier | production_cycle_days | manual_daily_sale_target | moq | lead_time | updated_at |
|----------|----------|--------------|----------|-------|-------------|--------|-----------|------|----------------------|--------------------------|-----|-----------|------------|
| SKU001 | SPU001 | 纯棉圆领T恤-白色-M | T恤 | 自有品牌A | 2025-03-15 | 在售 | 成熟期 | A | 15 | 8.5 | 100 | 7 | 2026-05-27 08:00:00 |
| SKU002 | SPU001 | 纯棉圆领T恤-白色-L | T恤 | 自有品牌A | 2025-03-15 | 在售 | 成熟期 | A | 15 | 6.0 | 100 | 7 | 2026-05-27 08:00:00 |
| SKU003 | SPU002 | 宽松牛仔裤-蓝色-均码 | 裤子 | 自有品牌B | 2026-04-01 | 在售 | 导入期 | C | 25 | 1.2 | 200 | 14 | 2026-05-27 08:00:00 |

**接入方注意事项：**
- `tier` 字段是硬依赖。引擎按 A/B/C/N 做货盘分级、散点图坐标轴、OTB 分配权重。如果接入方没有货盘分级体系，至少用「畅销品/常规品/试销品/新品」四档映射到 A/B/C/N。
- `sku_code` 必须与 ods_sales、ods_inventory_domestic、ods_inventory_overseas 等表保持一致。跨表 SKU 不匹配的行会被 DWD 层丢弃。
- `manual_daily_sale_target` 是场景01 销量需求计算的基准值之一。如果不提供，该 SKU 的「目标」维度退化为仅用历史加权日均销估算。

---

### 2. ods_sales — 每日销量

**用途：** 每日各 SKU 的销售明细（按 MSU 粒度），是 DWD 层计算加权日均销、7日/30日均销的原始输入。

**加载模式：** 增量 UPSERT（按 `(sku_code, sale_date, msu_id)` 联合主键去重）。

**字段清单（4 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `sku_code` | VARCHAR | \* | SKU 编码 | 必须能在 ods_skus 中找到 |
| 2 | `sale_date` | VARCHAR | \* | 销售日期 | `YYYY-MM-DD`，不能是未来日期 |
| 3 | `daily_qty` | VARCHAR | \* | 当日销售件数 | 非负整数，引擎会 CAST 为 DOUBLE |
| 4 | `msu_id` | VARCHAR | \* | 销售店铺/渠道标识 | 与 ods_wmap 的 msu_id 对应 |

**示例数据：**

| sku_code | sale_date | daily_qty | msu_id |
|----------|-----------|-----------|--------|
| SKU001 | 2026-05-26 | 12 | MSU01 |
| SKU001 | 2026-05-25 | 8 | MSU01 |
| SKU002 | 2026-05-26 | 5 | MSU02 |

**接入方注意事项：**
- 引擎需要**至少 30 天**的连续销售数据才能正常计算 `avg_30d_qty` 和 `weighted_daily`。数据不足 30 天时，指标会用可用天数降级计算，但准确性下降。
- 如果同一 `(sku_code, sale_date, msu_id)` 出现多条，UPSERT 会保留最后一条。建议接入方预先去重。
- `msu_id` 建议用可读标识（如 shop-xxx）而非数字 ID，便于下游场景按渠道拆分库存。

---

### 3. ods_inventory_domestic — 国内库存快照

**用途：** 国内仓库存快照，记录各 SKU 的可售库存和在途采购。DWD 层算 `total_inventory`（国内可售 + 国内在途 + 海外可售 + 海外在途 + 海外发货在途）。

**加载模式：** 增量 UPSERT（每次快照追加新行，按 `(sku_code, snapshot_time)` 去重）。

**字段清单（4 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `sku_code` | VARCHAR | \* | SKU 编码 | 必须能在 ods_skus 中找到 |
| 2 | `inv_domestic` | VARCHAR | \* | 国内仓可售库存（件） | 非负整数 |
| 3 | `inv_purchase_onway` | VARCHAR | | 国内在途采购库存（已下单未入库） | 非负整数 |
| 4 | `snapshot_time` | VARCHAR | \* | 快照时间 | `YYYY-MM-DD HH:MM:SS`，引擎取最新快照 |

**示例数据：**

| sku_code | inv_domestic | inv_purchase_onway | snapshot_time |
|----------|-------------|---------------------|---------------|
| SKU001 | 250 | 100 | 2026-05-27 08:00:00 |
| SKU002 | 180 | 80 | 2026-05-27 08:00:00 |
| SKU003 | 0 | 200 | 2026-05-27 08:00:00 |

**接入方注意事项：**
- 引擎**只取最新的快照**（按 `snapshot_time DESC LIMIT 1 PER sku_code`）。历史快照保留用于审计，但计算只用最新一条。
- 建议每日至少一次快照，且快照时间统一（所有 SKU 同一批次）。
- `inv_purchase_onway` 可为空（接入方若无采购在途数据），但会丧失「采购在途占用 OTB」的可见性。

---

### 4. ods_inventory_overseas — 海外库存快照

**用途：** 海外仓库存快照，按 `店铺 × 仓库` 粒度记录可售库存和在途库存。

**加载模式：** 增量 UPSERT（按 `(sku_code, shop, warehouse_code, snapshot_time)` 去重）。

**字段清单（6 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `sku_code` | VARCHAR | \* | SKU 编码 | 必须能在 ods_skus 中找到 |
| 2 | `shop` | VARCHAR | \* | 海外店铺标识 | 与 ods_sales 的 msu_id 对应 |
| 3 | `warehouse_code` | VARCHAR | \* | 海外仓库编码（FBA/FBW 等） | |
| 4 | `inv_available` | VARCHAR | \* | 海外可售库存（件） | 非负整数 |
| 5 | `inv_onway` | VARCHAR | | 海外在途库存（已发货未入仓） | 非负整数 |
| 6 | `snapshot_time` | VARCHAR | \* | 快照时间 | `YYYY-MM-DD HH:MM:SS` |

**示例数据：**

| sku_code | shop | warehouse_code | inv_available | inv_onway | snapshot_time |
|----------|------|----------------|---------------|-----------|---------------|
| SKU001 | MSU01 | FBA-US-East | 500 | 120 | 2026-05-27 08:00:00 |
| SKU001 | MSU02 | FBW-UK | 300 | 0 | 2026-05-27 08:00:00 |
| SKU002 | MSU01 | FBA-US-East | 200 | 80 | 2026-05-27 08:00:00 |

**接入方注意事项：**
- 一个 SKU 在多个海外店铺/仓库有库存时，**每个 (sku_code, shop, warehouse_code) 单独一行**。不要在单行聚合多个仓。
- 与 ods_inventory_domestic 同理，引擎只取每个分组的最新快照。
- `shop` 字段的值必须与 ods_sales.msu_id 一致，否则场景05 智能补货的「海外库存天数」计算会错位。

---

### 5. ods_params — 规则参数

**用途：** 定义所有可配置的系统参数（安全库存天数、预警阈值、OTB 系数等），DWD 层展开为 `dwd_params` 供各场景消费。

**加载模式：** 全量覆盖。

**字段清单（7 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `param_no` | VARCHAR | \* | 参数编号 | P1 ~ P14 |
| 2 | `param_id` | VARCHAR | \* | 参数标识 | 英文标识，如 `safety_stock_days` |
| 3 | `param_name` | VARCHAR | \* | 参数中文名 | 如「安全库存天数」 |
| 4 | `param_default` | VARCHAR | \* | 默认值 | 引擎启动时的回退值 |
| 5 | `param_type` | VARCHAR | | 参数类型 | string / number / days / ratio |
| 6 | `param_note` | VARCHAR | | 参数说明 | |
| 7 | `sync_time` | TIMESTAMP | | 同步时间 | DuckDB 自动类型推断 |

**示例数据：**

| param_no | param_id | param_name | param_default | param_type | param_note | sync_time |
|----------|----------|------------|---------------|------------|------------|-----------|
| P1 | safety_stock_days_level_A | A类安全库存天数 | 30 | days | A级货盘安全库存天数 | 2026-05-27 08:00:00 |
| P2 | safety_stock_days_level_B | B类安全库存天数 | 45 | days | B级货盘安全库存天数 | 2026-05-27 08:00:00 |
| P3 | weighted_alpha | 加权日均销衰减系数 | 0.5 | ratio | 介于 0~1，越大越偏向近期 | 2026-05-27 08:00:00 |

**接入方注意事项：**
- 引擎默认按货盘分级（A/B/C/N）分别配置安全库存天数。如果接入方没有货盘概念，至少提供全局默认值（用 `param_no` 区分）。
- `param_default` 是引擎的「出厂设置」，接入方可按自身业务修改。引擎会读取本表覆盖内置值。
- 本表写入后，DWD 层自动展开为 `dwd_params`（按 `sub_param` / `tier` 展开）。不要直接写 dwd_params。

---

## 第二层：可选表

> 以下表不提供时引擎仍可运行，但对应场景能力降级或关闭。

---

### 6. ods_po — 采购订单

**用途：** 采购单明细，记录已下采购单但未到货的数量。配合 ods_po_recv 可追踪采购履约率。

**加载模式：** 增量 UPSERT（按 `(po_number, sku_code)` 去重）。

**字段清单（5 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `po_number` | VARCHAR | \* | 采购订单号 | |
| 2 | `sku_code` | VARCHAR | \* | SKU 编码 | 必须在 ods_skus 中存在 |
| 3 | `order_date` | VARCHAR | | 下单日期 | `YYYY-MM-DD` |
| 4 | `order_qty` | VARCHAR | \* | 下单数量（件） | 正整数 |
| 5 | `eta` | VARCHAR | | 预计到货日期 | `YYYY-MM-DD` |

**示例数据：**

| po_number | sku_code | order_date | order_qty | eta |
|-----------|----------|------------|-----------|-----|
| PO-20260501 | SKU001 | 2026-05-01 | 500 | 2026-06-15 |
| PO-20260501 | SKU002 | 2026-05-01 | 300 | 2026-06-15 |
| PO-20260515 | SKU003 | 2026-05-15 | 200 | 2026-06-30 |

**接入方注意事项：**
- 本表应与 ods_po_recv 配套使用。仅有订单没有收货数据时，引擎无法判断到货进度。
- 采购在途（`inv_purchase_onway`）由本表与 ods_po_recv 推算（`order_qty - 已收货量`），不再冗余存储。

---

### 7. ods_po_recv — 采购收货明细

**用途：** 采购单的实际到货记录，追踪每笔采购单的收货进度。

**加载模式：** 增量 UPSERT（按 `(po_number, sku_code, receipt_date, warehouse_id)` 去重）。

**字段清单（5 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `po_number` | VARCHAR | \* | 采购订单号 | 必须在 ods_po 中存在 |
| 2 | `sku_code` | VARCHAR | \* | SKU 编码 | |
| 3 | `receipt_date` | VARCHAR | \* | 收货日期 | `YYYY-MM-DD` |
| 4 | `receipt_qty` | VARCHAR | \* | 本次收货数量（件） | 非负整数 |
| 5 | `warehouse_id` | VARCHAR | | 收货仓库 | 国内仓库标识 |

**示例数据：**

| po_number | sku_code | receipt_date | receipt_qty | warehouse_id |
|-----------|----------|-------------|-------------|--------------|
| PO-20260501 | SKU001 | 2026-06-14 | 500 | WH-SZ-01 |
| PO-20260501 | SKU002 | 2026-06-14 | 200 | WH-SZ-01 |
| PO-20260501 | SKU002 | 2026-06-18 | 100 | WH-SZ-01 |

**接入方注意事项：**
- 一个采购单可能分多次收货（分批到货），每次收货单独一行。
- 如果接入方无法提供到货明细，本表可留空，场景08 OTB 的「采购在单占用」改用 ods_po.order_qty 全量计入。

---

### 8. ods_ship — 发货明细（国内→海外补货）

**用途：** 记录国内仓库向海外仓库的发货/补货记录，用于追踪在途库存和预计到仓时间。

**加载模式：** 增量 UPSERT（按 `tracking_number` 去重）。

**字段清单（7 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `tracking_number` | VARCHAR | \*PK | 物流单号/跟踪号 | 全局唯一 |
| 2 | `sku_code` | VARCHAR | \* | SKU 编码 | |
| 3 | `ship_date` | VARCHAR | \* | 发货日期 | `YYYY-MM-DD` |
| 4 | `ship_qty` | VARCHAR | \* | 发货数量（件） | 正整数 |
| 5 | `dest_warehouse` | VARCHAR | | 目的仓库 | 与 ods_inventory_overseas.warehouse_code 对应 |
| 6 | `expect_arrival` | VARCHAR | | 预计到达日期 | `YYYY-MM-DD` |
| 7 | `shop` | VARCHAR | | 目的店铺 | 与 ods_inventory_overseas.shop 对应 |

**示例数据：**

| tracking_number | sku_code | ship_date | ship_qty | dest_warehouse | expect_arrival | shop |
|-----------------|----------|-----------|----------|----------------|----------------|------|
| TRK-20260527-001 | SKU001 | 2026-05-27 | 300 | FBA-US-East | 2026-06-15 | MSU01 |
| TRK-20260527-002 | SKU002 | 2026-05-27 | 150 | FBA-US-East | 2026-06-15 | MSU01 |
| TRK-20260527-003 | SKU001 | 2026-05-25 | 200 | FBW-UK | 2026-06-12 | MSU02 |

**接入方注意事项：**
- 本表是 DWD 层 `overseas_ship_onway` 的来源。不提供时，海外发货在途维度缺失，场景07 库存结构中的在途分段不完整。
- `dest_warehouse` 和 `shop` 的值应与 ods_inventory_overseas 保持一致。

---

### 9. ods_wmap — 供需映射（仓库-店铺-SKU 映射）

**用途：** 定义每个 SKU 在哪些店铺（MSU）售卖给哪些仓库，用于库存需求和智能补货的精确指向。

**加载模式：** 全量覆盖。

**字段清单（4 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `sku_code` | VARCHAR | \* | SKU 编码 | |
| 2 | `msu_id` | VARCHAR | \* | 销售店铺标识 | 与 ods_sales.msu_id 对应 |
| 3 | `warehouse_id` | VARCHAR | \* | 供应仓库标识 | 与 ods_inventory_overseas.warehouse_code 对应 |
| 4 | `updated_at` | VARCHAR | | 最后更新时间 | `YYYY-MM-DD HH:MM:SS` |

**示例数据：**

| sku_code | msu_id | warehouse_id | updated_at |
|----------|--------|--------------|------------|
| SKU001 | MSU01 | FBA-US-East | 2026-05-27 08:00:00 |
| SKU001 | MSU02 | FBW-UK | 2026-05-27 08:00:00 |
| SKU002 | MSU01 | FBA-US-East | 2026-05-27 08:00:00 |

**接入方注意事项：**
- 粒度是 `sku_code × msu_id → warehouse_id`。一个 SKU 可能卖给多个店铺，一个店铺可能从多个仓库发货。
- 如果接入方的业务模型是「全店 → 仓库」（不区分 SKU），需扩展为本表的粒度（每个 SKU 一行）。
- 不提供本表时，引擎退化为「全店平均分配」模式，补货准确性会下降。

---

### 10. ods_cdm_skubom — 商品 BOM（物料清单）

**用途：** 定义组合装/套装 SKU 的拆解关系（父 SKU → 子 SKU + 用量）。用于场景06 智能促销中组合装库存折算。

**加载模式：** 全量覆盖。

**字段清单（3 列）：**

| # | 字段名 | 类型 | 必需 | 语义说明 | 值域约束 |
|---|--------|------|------|----------|----------|
| 1 | `psku` | VARCHAR | \* | 父 SKU 编码（套装/组合装） | |
| 2 | `sku_id` | VARCHAR | \* | 子 SKU 编码（组成组件） | |
| 3 | `rm_qty` | BIGINT | \* | 用量（子 SKU 在套装中的数量） | 正整数 |

**示例数据：**

| psku | sku_id | rm_qty |
|------|--------|--------|
| COMBO-001 | SKU001 | 2 |
| COMBO-001 | SKU002 | 1 |
| COMBO-002 | SKU003 | 1 |

**接入方注意事项：**
- 本表仅用于组合装/套装场景。如无套装业务可不提供。
- `rm_qty` 是 BIGINT（DuckDB 原生整数类型），区别于其他表的 VARCHAR 数值字段。
- 数据来源通常为 ERP 的 BOM 表或商品管理系统的组合关系表。

---

## DWD 层（引擎自动生成，无需接入方提供）

> 以下 2 张表由引擎从 ODS 表自动加工生成，接入方**不需要**提供。此处列出仅供参考，帮助理解数据流转。

### dwd_params（8 列）

ODS `ods_params` 按 `tier` 和 `sub_param` 展开后的规则参数表。每个 SKU 可消费对应 `tier` 的参数值。

### dwd_sku_daily_metrics（15 列）

统一消费口，整合 6 大板块数据：商品档案 + 销量加权 + 库存汇总（国内可售/在途 + 海外可售/在途 + 发货在途）+ 货盘分级。

---

## 如何接入你的数据

PMC 引擎对数据源**没有类型限制**——可以是 MySQL、PostgreSQL、MongoDB、Excel、CSV、API 或任何其他数据源。引擎只关心最终进入 DuckDB 的表结构是否符合本契约。

### 接入步骤

1. **确认数据源覆盖**
   - 对照「第一层：必需表」，逐表确认你的数据源能否产出对应字段。
   - 对于可选表，按业务需求决定是否接入。

2. **构建 ETL 管线**
   - 从你的数据源提取原始数据，清洗/转换为本契约约定的字段名和格式。
   - 特别注意：数值类字段统一转为字符串（VARCHAR），日期用 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS`。

3. **落地到 DuckDB**
   - 以表名（`ods_skus`、`ods_sales` 等）在 DuckDB 中建表，字段顺序和名称与本契约一致。
   - 字段名区分大小写，建议全小写。
   - 引擎不依赖外键约束（DuckDB 不支持 ENFORCED FK），所有跨表一致性由引擎在 DWD 层用 JOIN 和 FILTER 兜底。

4. **配置数据刷新策略**
   - 全量覆盖表：按你的业务周期（每日/每小时）TRUNCATE + INSERT。
   - 增量 UPSERT 表：用 `INSERT OR REPLACE` 或按主键 MERGE。

5. **验证**
   - 写入后运行引擎自检脚本，确认 DWD 层能正常产出 `dwd_sku_daily_metrics`。
   - 检查各场景（01~09）数据是否齐全、指标是否合理。

### 常见问题

**Q: 我的数据源字段名和契约不一致怎么办？**
A: 在 ETL 层做字段重命名（alias），不要修改契约中的字段名。

**Q: 表中的某些字段我确实没有，能空着吗？**
A: 必需表中标 `*` 的字段不能为空，否则该行在 DWD 层会被丢弃。其他字段可空，但会影响对应场景的计算完整性。

**Q: 加载模式用全量覆盖还是增量 UPSERT？**
A: 严格按每张表的标注执行。全量覆盖用于参数表、档案表、映射表（行数少、无历史累积需求）；增量 UPSERT 用于销量、库存、订单等持续追加的表。

**Q: 我的 DuckDB 版本有要求吗？**
A: 建议 DuckDB ≥ 1.0.0。引擎使用了 CTE、WINDOW、LIST 聚合、PIVOT 等特性。

---

> 本契约的任何变更需经双方确认。引擎版本升级时契约可能追加新字段（向后兼容），但不会删除或重命名已有字段。
