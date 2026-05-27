# PMC 背景知识

> 本文件补充 SOUL.md 和 DATA_CONTRACT.md 中未覆盖的细节知识。
> 主要面向接入方和维护者，而非场景执行引擎。

## 1. 两套 SKU 编码体系

| 来源 | 编码格式 | 示例 |
|:---|:---|:---|
| ods_skus / ods_inventory_domestic / ods_po / ods_ship / ods_inventory_overseas | 原生格式 | `DA5002AE-4P1-XL` |
| ods_sales | 归一化格式（经 cdm_skubom） | `BX451-Black-S` |
| ods_cdm_skubom.psku | 桥接（原生→归一化） | `DA5002AE-4P1-XL` |
| ods_cdm_skubom.sku_id | 桥接目标 | `BX451-Black-S` |

**关键**：DWD 表的 sku_code 来自 ods_skus（原生格式），所以 DWD JOIN ods_skus 可以匹配。但 ods_sales JOIN ods_skus 会全 NULL，因为编码体系不同。

## 2. dwd_params 展开逻辑

- ods_params 的 `param_default` 可能是 JSON blob（如 `{"S":30,"A":25,"B":20,"C":15,"N":20}`）
- DWD 引擎按 `tier` 列展开为多行，每行一个货盘值
- 全局参数（如 P3）的 tier 为空字符串
- 子参数（如 P2 的 4 段、P4 的采购/发货周期）通过 `sub_param` 列区分

## 3. weighted_daily 公式细节

**公式**：0.5×昨日销量 + 0.3×近7天日均 + 0.2×近30天日均

**口径注意**：
- `yesterday_qty` 的定义是「最新日期的前一天」，不是「昨天的自然日」
- 如果数据延迟3天，yesterday_qty 是3天前的数据
- DWD 对 ods_skus 全量 LEFT JOIN，无销售/无库存的 SKU 各列填0

**失真问题**：
- 36% 的 SKU 因「近7天零销但30天有数据」导致 weighted_daily 被系统性低估（0.02~0.06件/天）
- 连锁导致 inventory_days 虚高到数年
- 影响范围：场景01/03/06/07/08 均使用 inventory_days 做分析

## 4. 数据延迟周期

- **销售数据 1-6 天延迟**：日销量 sheet 可能连续多天空行，不是管线故障
- **采购/库存数据通常比销量新**：可用于判断是延迟还是管线故障

## 5. 场景09 三段周期全阻塞

| 周期 | 阻塞原因 |
|:---|:---|
| 采购周期 | ods_po JOIN ods_po_recv 的 po_number 编码不匹配（匹配数=0） |
| 生产周期 | ods_skus.production_cycle_days 全空（0个SKU有值） |
| 海外发货周期 | ods_ship_recv 为空表（无实际收货日期回传） |

## 6. 负库存处理不统一

| 场景 | 处理方式 |
|:---|:---|
| DWD 层 | GREATEST(..., 0) 钳位 |
| 场景03 | 已在 DWD 层处理 |
| 场景04 | **未做** GREATEST 钳位 |
| 场景05 | 每个海外库存列独立 clamp |
| 场景06 | 仅 sellable_inv 做了 clamp |
| 场景07 | 未做钳位 |

## 7. DuckDB 特有语法备忘

| 语法 | MySQL/PostgreSQL 替代 |
|:---|:---|
| `MEDIAN()` | `PERCENTILE_CONT(0.5)` |
| `FILTER (WHERE ...)` | `CASE WHEN ... END` 子查询 |
| `GREATEST(x, 0)` | 需要 `COALESCE(x, 0)` 包裹防 NULL |
| `CURRENT_DATE - 7` | `DATE_SUB(NOW(), INTERVAL 7 DAY)` |

## 8. 供需映射（ods_wmap）设计意图

每条映射记录 = `(sku_code, msu_id) → warehouse_id`

- 同一店铺的不同 SKU 可能走不同仓库（映射粒度是 SKU，不是店铺）
- 之上可抽象逻辑仓（多个物理仓库→一个逻辑仓）和逻辑店（多个店铺→一个逻辑店）
- 当前数据：29 行，sku_code 全为空，尚未填充完整
