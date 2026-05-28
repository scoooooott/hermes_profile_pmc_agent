---
name: pmc-data-onboarding
version: 2.0.0
description: "PMC 新客户数据接入向导：分 6 阶段逐步引导客户完成客户画像 → 板块发现 → 数据探查 → 预处理 → 管道配置 → 端到端验证。阶段 0 客户画像采用动态参数提问（查询 dwd_params 而非硬编码），自适应配置而非筛选客户。"
metadata:
  triggers:
    - "新客户接入"
    - "数据接入"
    - "PMC onboarding"
    - "客户数据导入"
    - "客户画像"
  related_skills:
    - "pmc-data-pipeline"
---

# PMC 数据接入向导

> 这是**流程引擎 Skill**，不是自动化脚本。Agent 加载后按阶段推进，每个阶段确认后才进入下一阶段。不跳步。

---

## 接入前检查：环境初始化

运行 bootstrap 完成 DuckDB 初始化。如 bootstrap 失败，按 [`references/environment-setup.md`](references/environment-setup.md) 排查。

```bash
python3 -c "import duckdb, pandas, openpyxl; print('OK')"
cd ~/workspace/pmc-agent && python3 scripts/bootstrap_pipeline.py
```

验证 9 张 ODS 表就绪后，进入阶段 0。

---

## 阶段 0 — 客户画像

### 目标

在技术接入之前，先摸清客户是谁、做什么生意、怎么做的。这一步收集的信息会直接影响后续所有阶段的参数预设和决策。

**核心原则**：此阶段目的不是「筛选」客户，而是**自适应配置**——了解客户模式后，PMC 自动调整参数预设、跳过不适用板块、给出适合该模式的分析重点。

### 分类知识库

详见 [`references/cross-border-seller-taxonomy.md`](references/cross-border-seller-taxonomy.md)，包含商业模式、平台供应链模式区别、ERP 数据导出能力速查。

### 对话流程

**Step 1：商业模式判定（第一问）**

「你们主要是做什么模式的？是自有品牌的精品/品牌卖家，还是选品铺货的模式？」

| 回答 | 判定 | PMC 自适应策略 |
|---|---|---|
| 铺货/无货源/店群 | 无国内仓 | 跳过 `ods_inventory_domestic`，海外库存+采购发货仍可服务；参数侧重发货周期 |
| 精铺（有库存但要管很多 SKU） | 多 SKU 库存 | 全板块接入，SKU 映射需仔细做 |
| 精品/自有品牌 | 深度库存 | 核心客户；如有工厂则启用生产周期参数 |
| 工贸一体/工厂直销 | 产销一体 | 启用 `production_cycle_days`、`lead_time` 实值；参数偏激进 |
| 不确定 | 追问 | 「你们有自己的库存吗？大概有多少个 SKU？」→ 有库存 → 适用 |

**Step 2：平台组合**

「主要做哪些平台？亚马逊、Temu、TikTok Shop、SHEIN、沃尔玛，还是多平台？」

根据[分类知识库](references/cross-border-seller-taxonomy.md)预判供应链模式：
- 全托管模式（Temu/SHEIN 全托管）→ 卖家无库存数据，该平台不纳入 PMC 范围
- 自备货模式（Amazon FBA/WFS/半托管）→ PMC 核心覆盖

**Step 3：体量摸底**

「大概有多少个活跃 SKU？年 GMV 在什么量级？」— 预估数据量，决定 import 脚本是否需要分批。

**Step 4：动态参数提问（先查表，再提问）**

**不要硬编码参数列表。** 先查数据库：

```sql
SELECT param_no, param_id, param_name, param_default, param_type, param_note
FROM dwd_params ORDER BY param_no, tier, sub_param;
```

逐参数判断是否需要提问：

| 判断条件 | 处理 |
|----------|------|
| 默认值通用合理（如 weighted_alpha=0.5） | 不提问，保留默认 |
| 依赖客户业务特征（如安全库存天数） | **必须提问** |
| 画像环节已给出信息可推算 | 自动推算，不重复提问 |
| 客户说「用默认就行」 | 跳过剩余参数 |

提问方式：用自然语言，不扔参数编号。

> 「P1 是 A 级货盘的安全库存天数，就是你最核心的爆款需要备多少天库存。默认 30 天。你觉得偏保守还是偏激进？」

回答整理成参数覆盖表，阶段 D 统一写入。

**Step 5：数据系统**

「你们现在用什么 ERP 管库存和订单？数据能方便地导出来吗？或者有 API 吗？」— 根据 ERP 速查表预判接入难度，决定阶段 D 走哪种管道模式。

### 输出：客户画像卡片

阶段 0 完成后，整理为一张紧凑的客户画像卡片，确认后进入阶段 A：

```
╔═══════════════════════════════════════════════════╗
║  客户画像：XX公司                                  ║
╠═══════════════════════════════════════════════════╣
║  模式：精品  |  平台：Amazon FBA + Temu半托管        ║
║  SKU：约500  |  年GMV：2000万                       ║
║  国内仓：深圳自营仓  |  海外仓：FBA美东+美西          ║
║  物流：海运快船15-20天  |  供应商：8家               ║
║  ERP：领星  |  数据导出：Excel每周更新              ║
║  组合装：有，约30个套装  |  联系人：仓库主管李工      ║
╠═══════════════════════════════════════════════════╣
║  PMC 自适应配置                                     ║
║  • ods_inventory_domestic ✅ 启用                   ║
║  • ods_inventory_overseas ✅ FBA美东+美西             ║
║  • 参数：已收集参数覆盖表（N项需客户确认）           ║
║  • 接入方式：Excel导入 + 每周cron                   ║
║  • 需前置处理：组合装拆解（阶段C）                   ║
╚═══════════════════════════════════════════════════╝
```

### 调参规则速查

| 客户特征 | PMC 配置调整 |
|----------|-------------|
| 铺货/无国内仓 | 跳过 `ods_inventory_domestic`；场景07 库存结构退化「国内库存段」 |
| 全托管（Temu/SHEIN） | 卖家无库存数据，该平台暂时不可纳入场景计算 |
| 半托管（Temu/Amazon FBM） | 有海外仓但非 FBA，`warehouse_code` 用自建仓名 |
| 工贸一体 | `production_cycle_days` 和 `lead_time` 可填实值而非默认值 |
| 组合装有 BOM | 阶段 C 拆解后 `rm_qty` 总不为 1 的 SKU 不进入 ods_skus |
| 客户给了分货盘阈值 | 直接写入 `ods_params`，覆盖默认 JSON |
| ERP 不支持 API | 回退到 CSV/Excel 导入模式 + 手动 cron |

---

## 阶段 A — 板块发现

### 目标

向客户展示 PMC 系统的 6 大业务板块，逐一确认客户拥有哪块数据、数据来源是什么。

### 对话流程

**Step 1：展示全景图**

| # | 板块 | 核心表 | 内容 | 必选？ |
|---|------|--------|------|--------|
| ① | 商品档案 | ods_skus | SKU主数据（仅单品，不含组合装） | ✅ 必选 |
| ② | 每日销量 | ods_sales | 日销量 × SKU × 店铺 | ✅ 必选 |
| ③ | 库存快照 | ods_inventory_domestic + ods_inventory_overseas | 国内库存 + 海外FBA库存 | ✅ 必选 |
| ④ | 采购明细 | ods_po + ods_po_recv | 采购单 + 收货明细 | 建议 |
| ⑤ | 发货明细 | ods_ship | 国内→海外补货发货 | 建议 |
| ⑥ | 供需映射 | ods_wmap | SKU→店铺→仓库关系 | ✅ 必选 |
| ⑦ | 规则参数 | ods_params | P1-P14 业务参数 | ✅ 必选 |

**Step 2：逐一确认**

对每个板块问三件事：有这块数据吗？数据在哪？更新频率？

阶段 0 摸底过的 ERP 信息直接填入，减少重复提问。

**Step 3：汇总确认**

汇总成一张接入确认单反馈给客户确认，客户确认后进入阶段 B。

---

## 阶段 B — 数据探查

### 目标

请客户提供每块数据的样例（前 5-10 行），与 PMC 标准 Schema 做字段匹配检查。

### Schema 查询

ODS 表结构的权威定义见 `DATA_CONTRACT.md`。运行时也可从 DuckDB 反查：

```bash
duckdb ~/pmc-data/pmc_ods.duckdb -c "
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='ods_skus' ORDER BY ordinal_position;"
```

### 比对检查清单

拿到客户样例后，逐表做以下检查：

1. **必填字段是否齐全**：缺失 → 标记「阻断」，需客户补充
2. **字段名能否映射**：不一致则记录映射关系
3. **数据类型是否一致**：日期 YYYY-MM-DD、数量为数字
4. **编码体系是否一致**：同一 SKU 在不同数据源编码是否相同
5. **数据质量粗略检查**：全 NULL 列、异常值、日期跳跃

### 输出：字段匹配报告

```
┌─ 商品档案 ods_skus ──────────────────────────────────────┐
│ 标准字段          │ 客户字段       │ 状态  │ 备注              │
│ sku_code          │ SKU编码        │ ✅ 匹配│                   │
│ category          │ (无)           │ ⚠️ 缺失│ 可从类目表补充     │
│ tier              │ 等级           │ ⚡ 映射│ S/A/B/C vs 1/2/3/4│
└────────────────────────────────────────────────────────────┘
```

| 图例 | 含义 |
|------|------|
| ✅ | 可直接映射 |
| ⚡ | 需要值转换映射 |
| ⚠️ | 客户缺失，需补充或取默认值 |
| 🚫 | 阻断：核心字段缺失，无法接入 |

---

## 阶段 C — 数据前置预处理

### 目标

确保数据进入 PMC 系统前已满足标准要求。**PMC 标准体系只接收单品级数据。**

### 预处理规则

**规则 1：组合装/套装 → 单品拆解**

有组合装的客户必须在数据导入前完成拆解：
1. 客户提供 BOM（物料清单）
2. ETL 层按 `组合装销量 × 子SKU数量` 拆解为单品销量
3. `ods_skus` 只能包含**单品 SKU**，组合装 SKU 不入库

> **关键约束**：`ods_skus` 中不得出现组合装 SKU。`rm_qty` 总不为 1 的 SKU 不进入商品档案。

**规则 2：商品SKU → 产品SKU 映射（关键）**

大多数客户存在两套 SKU 编码体系：

| 编码体系 | 含义 | 出现位置 |
|---------|------|---------|
| **商品SKU** | 平台销售侧标识 | 销售数据（ods_sales）、平台后台 |
| **产品SKU** | 库存/仓储侧标识 | 商品档案、库存、采购、发货 |

**为什么必须关联**：销量进来的是商品SKU，库存进来的是产品SKU，直接 JOIN 会全空。PMC 的数据锚点是产品SKU。

**预处理要求**：
1. 客户提供「商品SKU ↔ 产品SKU」映射表
2. ETL 层将 `ods_sales.sku_code` 从商品SKU 转换为产品SKU
3. 确保 `ods_sales.sku_code` = `ods_skus.sku_code` = `ods_inventory*.sku_code`

> 引导话术：「你们在平台上卖的商品编码和仓库里管理库存的产品编码应该是不同的两套编码。我们需要知道这两个编码之间的对应关系。」

**规则 3：数据格式标准化**

| 要求 | 说明 |
|------|------|
| 日期格式 | 统一 `YYYY-MM-DD` |
| 数值格式 | 整数，非负 |
| 编码去空格 | SKU 编码首尾去空格 |
| 负值处理 | 负库存→0，负销量→丢弃并记录 |

### 引导对话流程

**Step 1**：询问组合装情况，有则要求提供 BOM
**Step 2**：确认商品SKU → 产品SKU 映射（逐对交叉比对编码匹配率，< 95% 则排查双层编码）
**Step 3**：确认预处理完成（三项检查全部通过后才进阶段 D）

---

## 阶段 D — 管道配置

### 目标

根据客户数据源类型，选择接入方式，生成导入模板。

### 接入模式选择

| 模式 | 适用场景 |
|------|----------|
| API 直接拉 | 客户有可访问的数据库 |
| CSV/Excel 导入 | 客户从 ERP 导出文件（最常用） |
| 客户 API 对接 | 客户提供 RESTful API |
| 手动维护 | 参数/映射等低频数据 |

详细模板见 [`references/pipeline-templates.md`](references/pipeline-templates.md)。

### 参数写入

将阶段 0 收集的参数覆盖表写入 `ods_params`：

```sql
UPDATE ods_params SET param_default = '新值'
WHERE param_no = 'P1';
```

### 导入顺序

```
ods_skus → ods_wmap → ods_inventory → ods_sales → ods_po → ods_ship → ods_params
```

### 输出：交付清单

```
PMC 数据接入 — 管道配置
1. DuckDB DDL 脚本: 已由 bootstrap 创建
2. 导入脚本: /path/to/import_customer_data.py
3. ETL 编码映射配置（如需）: /path/to/etl_mapping.yaml
4. 参数配置: 已写入 ods_params
5. 每日导入 cron: 建议每天凌晨 3:00 执行
```

---

## 阶段 E — 验证

### 目标

数据导入完成后，跑完整管线确认数据能支撑场景计算。

### 验证步骤

**Step 1：刷新 DWD 指标层**

```bash
cd ~/workspace/pmc-agent && python3 scripts/refresh_dwd_metrics.py
```

检查输出：最新日期是否接近当天，SKU 数是否合理。

**Step 2：运行验证 SQL**

详见 [`references/verification-queries.md`](references/verification-queries.md)，包含 SKU 覆盖率、日期连续性、DWD 数据合理性、抽样验证共 4 段 SQL。

**Step 3：输出验证报告**

```
PMC 数据接入 — 验证报告

数据概况
  SKU 总数:    1,234
  有销售 SKU:   892 (72.3%)
  有库存 SKU: 1,100 (89.1%)

DWD 指标
  有加权日均销: 892 条
  库存天数 1-365: 845 条
  呆滞预警 (>365天): 12 条  ← 需客户关注
  数据异常 (<0天): 0 条

✅ 整体判定: 通过
```

---

## 快速接入模式

已有数据库访问权限的客户可走快速通道：

```
1. 数据库连接信息 → 配置到 pmc_template_api.py
2. 跑标准 5 端点 → 下载 Excel
3. pmc_import.py 导入 → DuckDB ODS 表
4. refresh_dwd_metrics.py → DWD 指标层
5. 按需导入客户自定义参数
```

---

## 相关文件

- 数据契约: `DATA_CONTRACT.md`
- 管线 Skill: `pmc-data-pipeline`
- API 源码: `~/workspace/pmc-agent/scripts/pmc_template_api.py`
- 导入脚本: `~/workspace/pmc-agent/scripts/pmc_import.py`
- DWD 刷新: `~/workspace/pmc-agent/scripts/refresh_dwd_metrics.py`
- Bootstrap: `~/workspace/pmc-agent/scripts/bootstrap_pipeline.py`
- DuckDB: `~/pmc-data/pmc_ods.duckdb`

## 陷阱笔记

常见陷阱和纠正方法详见 [`references/trap-notes.md`](references/trap-notes.md)。核心三条：

1. **不要拒绝客户**——PMC 自适应配置，不筛选淘汰
2. **不要硬编码参数提问**——先查 `dwd_params` 再动态提问
3. **删除敏感文件要用 filter-branch**——`git rm` 的 delete diff 仍泄露内容
