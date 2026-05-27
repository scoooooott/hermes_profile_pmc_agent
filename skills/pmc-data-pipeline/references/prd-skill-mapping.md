# PRD v4 索引 ↔ 当前 Skill 对照表

> 权威来源：飞书 PRD v4 `KMI9d6GTwodFhyx9uztcoi8HnZf`（唯一权威索引）
> 生成/更新：2026-05-21

## 10 场景严格对齐

PRD v4 编号从 00 开始，三板块结构：

| PRD | 场景名 | Skill 名称 | 板块 | CSP? |
|:---:|------|------|------|:---:|
| 00 | 商品画像 | `pmc-00-product-profile` | 底座层 | — |
| 01 | 销量需求 | `pmc-01-sales-demand` | 板块1 事前预测 | — |
| 02 | 库存需求 | `pmc-02-inventory-demand` | 板块1 事前预测 | — |
| 03 | 商品需求 | `pmc-03-product-demand` | 板块1 事前预测 | ✅ |
| 04 | 智能备货 | `pmc-04-smart-procurement` | 板块2 事中过程 | — |
| 05 | 智能补货 | `pmc-05-smart-replenishment` | 板块2 事中过程 | — |
| 06 | 智能促销 | `pmc-06-smart-promotion` | 板块2 事中过程 | ✅ |
| 07 | 库存结构 | `pmc-07-inventory-structure` | 板块3 事后优化 | ✅ |
| 08 | 总量控制 | `pmc-08-capacity-control` | 板块3 事后优化 | ✅ |
| 09 | 周期分析 | `pmc-09-cycle-analysis` | 板块3 事后优化 | — |

## 命名规范（2026-05-21 最终版）

格式：`pmc-{两位编号}-{英文slug}`。去掉了 `v2-` 和 `scene` 前缀，目录名与 YAML `name:` 字段完全一致。

英文选词原则：用商务/供应链标准词汇，避免缩写和直译。
- `profile`（非 portrait）— 商品画像
- `inventory`（非 stock）— 库存语境
- `capacity-control`（非 otb/total）— 总量管控
- `promotion`（非 promo）— 全拼不缩写

## 01~04 场景与 PRD 的已知偏差（2026-05-21 审计）

| 场景 | 偏差项 | 处置 |
|------|--------|------|
| 01 销量需求 | 趋势解释层、数据样本不足标记 | ✅ 已修（本次会话） |
| 01 销量需求 | 异常值剔除、促销/季节性系数 | ❌ 已砍，不做 |
| 01 销量需求 | 预测基线用 weighted_daily 而非 avg_30d | ✅ 用户确认保留现状 |
| 02 库存需求 | P7 数字与 PRD 不一致（A=25 vs 35, C=15 vs 20） | ⏳ 待对齐 |
| 02 库存需求 | 缺 SKU 级安全库存天数覆盖、膨胀溯源展示 | ⏳ 待补 |
| 03 商品需求 | XY 轴命名与 PRD 互换（含义接近） | ⏳ 待统一 |
| 03 商品需求 | 缺口×象限交叉矩阵、象限迁移轨迹 | ⏳ 待补 |
| 04 智能备货 | 在单覆盖缺窗口过滤、P1 区间校验、风险归因 | ⏳ 待补 |

## 旧版 v2 PRD 说明

本地文件 `~/workspace/pmc-agents/PMC九场景全景PRD_20260426_v2.md` 已过时，其场景编号（01-09）和内容与飞书 v4 索引不一致。**任何 PRD 引用必须以飞书文档 `KMI9d6GTwodFhyx9uztcoi8HnZf` 为准。**
