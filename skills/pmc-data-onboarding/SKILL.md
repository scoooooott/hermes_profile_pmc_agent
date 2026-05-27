     1|---
     2|name: pmc-data-onboarding
     3|version: 1.0.0
     4|description: "PMC 新客户数据接入向导：分 6 阶段逐步引导客户完成客户画像 → 板块发现 → 数据探查 → 编码归一化 → 管道配置 → 端到端验证。PMC Agent 加载此 Skill 后按流程推进，确认一步再走下一步。"
     5|metadata:
     6|  triggers:
     7|    - "新客户接入"
     8|    - "数据接入"
     9|    - "PMC onboarding"
    10|    - "数据源配置"
    11|    - "客户数据导入"
    12|  requires:
    13|    bins: ["duckdb", "python3"]
    14|    files:
    15|      - "~/pmc-data/pmc_ods.duckdb"
    16|  related_skills:
    17|    - "pmc-data-pipeline"
    18|---
    19|
    20|# PMC 数据接入向导
    21|
    22|## 这是流程引擎 Skill，不是自动化脚本
    23|
    24|本 Skill 定义了 PMC Agent 引导新客户完成数据接入的**6 阶段对话流程**。Agent 加载后按序执行，每个阶段确认后才进入下一阶段。不要跳过步骤。
    25|
    26|## 接入前检查：环境初始化
    27|
    28|PMC 系统的所有场景都需要 DuckDB 数据引擎。如果 DuckDB 未初始化，必须先完成初始化，否则后续所有阶段无法进行。
    29|
    30|### Step 1：检查 DuckDB 是否就绪
    31|
    32|```bash
    33|# 检查数据库文件是否存在且可读写
    34|duckdb $PMC_DB_PATH -c "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema='main';"
    35|```
    36|
    37|| 返回结果 | 判定 | 处理 |
    38||----------|------|------|
    39|| 文件不存在 或 无法连接 | DuckDB 未创建 | 进入 Step 2 初始化 |
    40|| 表数量 = 0 | 空库，只有文件没有表 | 进入 Step 2 |
    41|| 表数量 >= 9 | 已就绪 | 跳到「检查 API」 |
    42|| 表数量 1~8 | 部分就绪（异常状态） | DROP 所有表后进入 Step 2 |
    43|
    44|### Step 2：运行数据引擎自举脚本
    45|
    46|```bash
    47|cd ~/workspace/pmc-agent && python3 scripts/bootstrap_pipeline.py
    48|```
    49|
    50|`bootstrap_pipeline.py` 自动完成以下操作：
    51|1. 创建 `~/pmc-data/` 目录结构（static / snapshot / incremental）
    52|2. 创建 DuckDB 数据库文件
    53|3. 创建全部 ODS 表结构（9 张空壳表）
    54|4. 写入默认参数（P1-P14）到 `ods_params`
    55|5. 输出就绪检查报告
    56|
    57|**成功的输出示例**：
    58|```
    59|✓ 数据目录: ~/pmc-data
    60|✓ DuckDB 已创建: ~/pmc-data/pmc_ods.duckdb
    61|✓ ODS 表: 9/9 创建
    62|✓ DWD 视图: 2/2 创建
    63|✓ 默认参数: P1-P14 已写入
    64|```
    65|
    66|### Step 3：验证 DuckDB 就绪
    67|
    68|```bash
    69|duckdb $PMC_DB_PATH -c "
    70|SELECT table_name FROM information_schema.tables 
    71|WHERE table_schema='main' AND table_name LIKE 'ods_%' 
    72|ORDER BY table_name;
    73|"
    74|```
    75|
    76|## 接入前检查：环境初始化
    77|
    78|PMC 系统的所有场景都需要 DuckDB 数据引擎和若干 Python 依赖。如果依赖未就绪，必须先安装，否则后续所有阶段无法进行。
    79|
    80|### Step 0：检查并安装依赖
    81|
    82|在任何操作前，确认以下依赖全部就绪：
    83|
    84|**系统工具：**
    85|
    86|| 依赖 | 检查方法 | 安装方式 |
    87||------|---------|---------|
    88|| `python3` | `python3 --version` | macOS 自带；如缺失用 `brew install python` |
    89|| `duckdb` CLI | `duckdb --version` | `brew install duckdb` |
    90|| `curl` | `curl --version` | macOS 自带 |
    91|
    92|**Python 库：**
    93|
    94|```bash
    95|pip3 install duckdb pandas openpyxl playwright
    96|playwright install chromium
    97|```
    98|
    99|| 库 | 用途 | 缺失后果 |
   100||---|---|---|
   101|| `duckdb` | 数据引擎核心 | bootstrap 建库失败 |
   102|| `pandas` | DataFrame 操作 | DWD 刷新 / 场景 SQL 结果处理失败 |
   103|| `openpyxl` | Excel 生成 | PMC 报告导出失败 |
   104|| `playwright` | PDF 渲染 | PDF 报告生成失败 |
   105|
   106|**验证依赖就绪：**
   107|
   108|```bash
   109|python3 -c "import duckdb, pandas, openpyxl; print('OK')"
   110|```
   111|
   112|如果报错，先执行 `pip3 install` 再验证。通过后进入 Step 1。
   113|
   114|### Step 1：检查 DuckDB 是否就绪
   115|
   116|```bash
   117|duckdb $PMC_DB_PATH -c "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema='main';"
   118|```
   119|
   120|| 返回结果 | 判定 | 处理 |
   121||----------|------|------|
   122|| 文件不存在 或 无法连接 | DuckDB 未创建 | 进入 Step 2 初始化 |
   123|| 表数量 = 0 | 空库，只有文件没有表 | 进入 Step 2 |
   124|| 表数量 >= 9 | 已就绪 | 跳到「检查 API」 |
   125|| 表数量 1~8 | 部分就绪（异常状态） | DROP 所有表后进入 Step 2 |
   126|
   127|### Step 2：运行数据引擎自举脚本
   128|
   129|```bash
   130|cd ~/pmc-agent && python3 scripts/bootstrap_pipeline.py
   131|```
   132|
   133|`bootstrap_pipeline.py` 自动完成以下操作：
   134|1. 创建 `~/pmc-data/` 目录结构（static / snapshot / incremental）
   135|2. 创建 DuckDB 数据库文件
   136|3. 创建全部 ODS 表结构（9 张空壳表）
   137|4. 写入默认参数（P1-P14）到 `ods_params`
   138|5. 输出就绪检查报告
   139|
   140|### Step 3：验证 DuckDB 就绪
   141|
   142|```bash
   143|duckdb $PMC_DB_PATH -c "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_name LIKE 'ods_%' ORDER BY table_name;"
   144|```
   145|
   146|期望输出至少包含 9 张 ODS 表。确认后进入下一步。
   147|
   148|### Step 4：检查 API 是否运行（如有管线依赖）
   149|
   150|如果客户需要通过 API 管线对接数据，检查 API 状态：
   151|
   152|```bash
   153|curl -s http://localhost:8765/ | python3 -m json.tool
   154|```
   155|
   156|若 API 未启动：
   157|```bash
   158|cd ~/pmc-agent && nohup python3 scripts/pmc_template_api.py &
   159|```
   160|
   161|如果客户使用 CSV/Excel 导入模式（不依赖 API），跳过此步。
   162|
   163|如果客户使用 CSV/Excel 导入模式（不依赖 API），跳过此步。
   164|
   165|---
   166|
   167|## 阶段 0 — 客户画像
   168|
   169|### 目标
   170|
   171|在进入数据接入前，先建立客户画像。这决定了后续所有阶段的默认配置——不同业务模式对应不同的供应链模型，参数预设完全不同。
   172|
   173|**重要**：此阶段目的不是「筛选」客户（判断是否值得接），而是**自适应配置**——了解客户的模式后，PMC 自动调整参数预设、跳过不适用的数据板块、给出适合该模式的分析重点。
   174|
   175|### 画像维度
   176|
   177|以下提问覆盖了 PMC 需要了解的核心信息。不是必答题——客户答不上来的跳过去，有答案的记录下来，用于后续阶段智能调参。
   178|
   179|#### 1. 商业模式（决定供应链形态）
   180|
   181|| 提问 | 选项 | 对 PMC 的影响 |
   182||------|------|------|
   183|| 主要的业务模式是？ | 精品/品牌、精铺、铺货、工贸一体 | 精品偏品牌运营，库存深度大；铺货 SKU 多但无国内仓；工贸一体有生产周期数据 |
   184|| 是自己品牌还是代理/经销？ | 自有品牌 / 代理经销 / 混合 | 自有品牌可对接生产周期参数；代理无生产数据 |
   185|| 大致 SKU 数量？ | <100 / 100-1000 / 1000-10000 / >10000 | 影响 ods_skus 行数和加权计算性能 |
   186|| 年 GMV 大概量级？ | <500万 / 500万-5000万 / 5000万-2亿 / >2亿 | 影响数据量和分析频率 |
   187|
   188|#### 2. 平台组合（决定仓库体系）
   189|
   190|| 提问 | 选项 | 对 PMC 的影响 |
   191||------|------|------|
   192|| 在哪些平台卖？ | 亚马逊 / Temu / SHEIN / TikTok Shop / 沃尔玛 / 美客多 / Shopee / Lazada / 其他 | 每个平台的供应链模式不同，影响库存建模 |
   193|| 各平台主要用哪种发货模式？ | FBA / WFS / 全托管 / 半托管 / 自发货 / 混合 | FBA 需管海外库存天数；全托管卖家无库存数据；半托管需自己管海外仓 |
   194|| 有没有做独立站？ | 有 / 无 | 独立站销量需额外数据源 |
   195|
   196|#### 3. 供应链网络（决定仓库和物流参数）
   197|
   198|| 提问 | 选项 | 对 PMC 的影响 |
   199||------|------|------|
   200|| 国内有仓库吗？ | 有，自营 / 有，第三方 / 无国内仓，直发 | 无国内仓则跳过 ods_inventory_domestic 板块 |
   201|| 海外仓分布？ | FBA 美国东/西 / FBA 欧洲 / 第三方海外仓 / 无 | 决定 ods_inventory_overseas 仓库种类；影响场景05 补货的 FC 拆解 |
   202|| 主要物流方式？ | 海运快船 / 海运慢船 / 空运 / 铁路 / 混合 | 影响发货周期参数（P4），快船 15-20 天 vs 慢船 30-45 天 |
   203|| 供应商大概有多少家？ | <5 / 5-20 / >20 | 影响采购数据复杂度 |
   204|| 有没有组合装/套装？ | 有 / 无 | 有则阶段 C 需做前置拆解 |
   205|
   206|#### 4. 业务参数预期（动态参数提问）
   207|
   208|PMC 系统的规则参数表 `ods_params`（最终展开为 `dwd_params`）包含了所有可配置的参数。每个接入客户可能需要不同的参数值。
   209|
   210|**不要硬编码参数列表。** 提取参数的方法是查询数据库：
   211|
   212|```sql
   213|-- 查看所有参数及其默认值
   214|SELECT param_no, param_id, param_name, param_default, param_type, param_note
   215|FROM dwd_params
   216|ORDER BY param_no, tier, sub_param;
   217|```
   218|
   219|拿到参数表后，逐参数判断是否需要向客户提问：
   220|
   221|| 判断条件 | 处理 |
   222||----------|------|
   223|| 参数默认值是通用合理值（如 weighted_alpha=0.5）且客户无特殊需求 | 不提问，保留默认 |
   224|| 参数依赖客户业务特征（如安全库存天数、采购周期） | **必须提问**，因为不同客户差异巨大 |
   225|| 参数客户已在前面的画像环节给出信息（如物流方式→发货周期） | 基于画像自动推算，不重复提问 |
   226|| 客户主动说「这些用默认就行」 | 跳过剩余参数提问 |
   227|
   228|**提问方式**：不要扔参数编号，用自然语言解释这个参数干什么的，然后给出建议范围：
   229|
   230|> 「P1 是 A 级货盘的安全库存天数，就是你最核心的爆款需要备多少天库存。我们默认设的是 30 天。你觉得偏保守还是偏激进？或者说你有没有大概的想法？」
   231|
   232|**回答记录**：将客户的回答整理成一张参数覆盖表，阶段 D 中写入 ods_params：
   233|
   234|```
   235|客户参数覆盖记录
   236|
   237|| param_no | param_name | 默认值 | 客户值 | 原因 |
   238||----------|-----------|--------|--------|------|
   239|| P1 | A类安全库存天数 | 30天 | 45天 | 客户反馈海运周期不稳定，需更保守 |
   240|| P5 | 呆滞判定天数 | 90天 | 60天 | 客户SKU周转快，90天太长 |
   241|| ... | ... | ... | ... | ... |
   242|```
   243|
   244|> **重要**：此步骤的目标是收集客户预期，不是当场写入参数。实际写入在阶段 D 完成 ETL 管线搭建之后。
   245|
   246|#### 5. 数据系统（决定阶段 D 接入方式）
   247|
   248|| 提问 | 选项 | 对 PMC 的影响 |
   249||------|------|------|
   250|| 用什么 ERP/WMS？ | 万里牛 / 马帮 / 领星 / 积加 / 店小秘 / 自研 / 没用 ERP | 决定能否 API 直连还是走 CSV 导入 |
   251|| 数据能导出吗？是什么格式？ | Excel / CSV / 数据库直连 / API / 手动整理 | 决定阶段 D 管道选型 |
   252|| 谁负责对接数据？ | 运营 / 仓库 / IT / 老板自己 | 建立联系人和沟通节奏 |
   253|
   254|### 输出：客户画像卡片
   255|
   256|阶段 0 完成后，整理为一张紧凑的客户画像卡片，确认后进入阶段 A：
   257|
   258|```
   259|╔═══════════════════════════════════════════════════╗
   260|║  客户画像：XX公司                                  ║
   261|╠═══════════════════════════════════════════════════╣
   262|║  模式：精品  |  平台：Amazon FBA + Temu半托管        ║
   263|║  SKU：约500  |  年GMV：2000万                       ║
   264|║  国内仓：深圳自营仓  |  海外仓：FBA美东+美西          ║
   265|║  物流：海运快船15-20天  |  供应商：8家               ║
   266|║  ERP：领星  |  数据导出：Excel每周更新              ║
   267|║  组合装：有，约30个套装  |  联系人：仓库主管李工      ║
   268|╠═══════════════════════════════════════════════════╣
   269|║  PMC 自适应配置                                     ║
   270|║  • ods_inventory_domestic ✅ 启用                   ║
   271|║  • ods_inventory_overseas ✅ FBA美东+美西             ║
   272|║  • 参数：已收集参数覆盖表（N项需客户确认）           ║
   273|║  • 接入方式：Excel导入 + 每周cron                   ║
   274|║  • 需前置处理：组合装拆解（阶段C）                   ║
   275|╚═══════════════════════════════════════════════════╝
   276|```
   277|
   278|### 调参规则速查
   279|
   280|| 客户特征 | PMC 配置调整 |
   281||----------|-------------|
   282|| 铺货/无国内仓 | 跳过 `ods_inventory_domestic`；场景07 库存结构退化「国内库存段」 |
   283|| 全托管（Temu/SHEIN） | 卖家无库存数据，该平台暂时不可纳入场景计算 |
   284|| 半托管（Temu/Amazon FBM） | 有海外仓但非 FBA，`warehouse_code` 用自建仓名 |
   285|| 工贸一体 | `production_cycle_days` 和 `lead_time` 可填实值而非默认值 |
   286|| 组合装有 BOM | 阶段 C 拆解后 `rm_qty` 总不为 1 的 SKU 不进入 ods_skus |
   287|| 客户给了分货盘阈值 | 直接写入 `ods_params`，覆盖默认 JSON |
   288|| ERP 不支持 API | 回退到 CSV/Excel 导入模式 + 手动 cron |
   289|
   290|---
   291|
   292|## 阶段 A — 板块发现
   293|
   294|### 目标
   295|
   296|向客户展示 PMC 系统的 6 大业务板块，逐一确认客户拥有哪块数据、数据来源是什么。
   297|
   298|### 对话流程
   299|
   300|**Step 1：展示全景图**
   301|
   302|向客户发送以下 6 板块清单（用表格，紧凑）：
   303|
   304|| # | 板块 | 核心表 | 内容 | 必选？ |
   305||---|------|--------|------|--------|
   306|| ① | 商品档案 | ods_skus | SKU主数据（仅单品，不含组合装） | ✅ 必选 |
   307|| ② | 每日销量 | ods_sales | 日销量 × SKU × 店铺 | ✅ 必选 |
   308|| ③ | 库存快照 | ods_inventory_domestic + ods_inventory_overseas | 国内库存 + 海外FBA库存 | ✅ 必选 |
   309|| ④ | 采购明细 | ods_po + ods_po_recv | 采购单 + 收货明细 | 建议 |
   310|| ⑤ | 发货明细 | ods_ship | 国内→海外补货发货 | 建议 |
   311|| ⑥ | 供需映射 | ods_wmap | SKU→店铺→仓库关系 | ✅ 必选 |
   312|| ⑦ | 规则参数 | ods_params | P1-P14 业务参数 | ✅ 必选 |
   313|
   314|
   315|**Step 2：逐一确认**
   316|
   317|对每个板块，问清楚三件事：
   318|- 有这块数据吗？（有/无/部分有）
   319|- 数据在哪？（ERP/WMS/CSV导出/API/数据库/手工维护）
   320|- 更新频率？（实时/每日/每周/手动）
   321|
   322|若客户不确定，引导举例：「比如你们的商品主数据，是在什么系统里管理的？能导出一份吗？」
   323|
   324|**Step 3：汇总确认**
   325|
   326|汇总成一张表反馈给客户确认：
   327|
   328|```
   329|PMC 数据接入确认单
   330|
   331|| 板块 | 状态 | 来源 | 更新频率 | 备注 |
   332||------|------|------|----------|------|
   333|| 商品档案 | ✅ 有 | 万里牛ERP导出CSV | 每周 | 需确认字段映射 |
   334|| 每日销量 | ✅ 有 | 客户数据源 API | 每日T+1 | 已对接 |
   335|| ... | ... | ... | ... | ... |
   336|```
   337|
   338|客户确认后进入阶段 B。
   339|
   340|---
   341|
   342|## 阶段 B — 数据探查
   343|
   344|### 目标
   345|
   346|请客户提供每块数据的样例（前 5-10 行），与 PMC 标准 Schema 做字段匹配检查。
   347|
   348|### 标准 Schema 参考
   349|
   350|从 DuckDB ODS 表结构反查（SQL 查询获取）：
   351|
   352|```
   353|duckdb ~/pmc-data/pmc_ods.duckdb -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='ods_skus' ORDER BY ordinal_position;"
   354|```
   355|
   356|**① 商品档案 ods_skus（11 业务列 + 1 元数据列）**
   357|
   358|| # | 字段名 | 类型 | 必填 | 说明 |
   359||---|--------|------|------|------|
   360|| 1 | sku_code | VARCHAR | ✅ | SKU编码，唯一标识 |
   361|| 2 | spu_code | VARCHAR | | SPU/款式编码 |
   362|| 3 | product_name | VARCHAR | | 商品名称 |
   363|| 4 | category | VARCHAR | | 商品类目 |
   364|| 5 | brand | VARCHAR | | 品牌 |  
   365|| 6 | launch_date | VARCHAR | | 上架日期 YYYY-MM-DD |
   366|| 7 | status | VARCHAR | | 上架状态：在售/下架 |
   367|| 8 | lifecycle | VARCHAR | | 生命周期：新品/成长/成熟/衰退 |
   368|| 9 | tier | VARCHAR | | 货盘等级：S/A/B/C/N |
   369|| 10 | production_cycle_days | VARCHAR | | 生产周期天数 |
   370|| 11 | manual_daily_sale_target | VARCHAR | | 人工日均销目标值 |
   371|| 12 | moq | VARCHAR | | 最小起订量 |
   372|| 13 | lead_time | VARCHAR | | 采购交期(天) |
   373|| 14 | updated_at | VARCHAR | | 更新时间 |
   374|
   375|**② 每日销量 ods_sales（4 列）**
   376|
   377|| # | 字段名 | 类型 | 必填 | 说明 |
   378||---|--------|------|------|------|
   379|| 1 | sku_code | VARCHAR | ✅ | SKU编码（归一化后） |
   380|| 2 | sale_date | VARCHAR | ✅ | 销售日期 YYYY-MM-DD |
   381|| 3 | daily_qty | VARCHAR | ✅ | 当日销售件数 |
   382|| 4 | msu_id | VARCHAR | ✅ | 最小销售单元标识（如 CI-eu-DE） |
   383|
   384|**③ 库存快照**
   385|
   386|*ods_inventory_domestic（国内）*
   387|
   388|| # | 字段名 | 类型 | 必填 | 说明 |
   389||---|--------|------|------|------|
   390|| 1 | sku_code | VARCHAR | ✅ | SKU编码 |
   391|| 2 | inv_domestic | VARCHAR | ✅ | 国内仓库库存 |
   392|| 3 | inv_purchase_onway | VARCHAR | ✅ | 采购在途（已下单未到仓） |
   393|| 4 | snapshot_time | VARCHAR | ✅ | 快照时间戳 |
   394|
   395|*ods_inventory_overseas（海外FBA）*
   396|
   397|| # | 字段名 | 类型 | 必填 | 说明 |
   398||---|--------|------|------|------|
   399|| 1 | sku_code | VARCHAR | ✅ | SKU编码（归一化后） |
   400|| 2 | shop | VARCHAR | ✅ | 店铺（如 CI-eu） |
   401|| 3 | warehouse_code | VARCHAR | ✅ | 海外仓编码 |
   402|| 4 | inv_available | VARCHAR | ✅ | 可售库存 |
   403|| 5 | inv_onway | VARCHAR | ✅ | 在途库存 |
   404|| 6 | snapshot_time | VARCHAR | ✅ | 快照时间戳 |
   405|
   406|**④ 采购明细 ods_po（5 列）**
   407|
   408|| # | 字段名 | 类型 | 必填 | 说明 |
   409||---|--------|------|------|------|
   410|| 1 | po_number | VARCHAR | ✅ | 采购单号 |
   411|| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
   412|| 3 | order_date | VARCHAR | ✅ | 下单日期 |
   413|| 4 | order_qty | VARCHAR | ✅ | 采购数量 |
   414|| 5 | eta | VARCHAR | | 预计到货日期 |
   415|
   416|**ods_po_recv（采购收货）**
   417|
   418|| # | 字段名 | 类型 | 必填 | 说明 |
   419||---|--------|------|------|------|
   420|| 1 | po_number | VARCHAR | ✅ | 采购单号 |
   421|| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
   422|| 3 | receipt_date | VARCHAR | ✅ | 收货日期 |
   423|| 4 | receipt_qty | VARCHAR | ✅ | 收货数量 |
   424|| 5 | warehouse_id | VARCHAR | ✅ | 收货仓库 |
   425|
   426|**⑤ 发货明细 ods_ship（7 列）**
   427|
   428|| # | 字段名 | 类型 | 必填 | 说明 |
   429||---|--------|------|------|------|
   430|| 1 | tracking_number | VARCHAR | ✅ | 物流单号 |
   431|| 2 | sku_code | VARCHAR | ✅ | SKU编码 |
   432|| 3 | ship_date | VARCHAR | ✅ | 发货日期 |
   433|| 4 | ship_qty | VARCHAR | ✅ | 发货数量 |
   434|| 5 | dest_warehouse | VARCHAR | ✅ | 目的仓库 |
   435|| 6 | expect_arrival | VARCHAR | | 预计到达日期 |
   436|| 7 | shop | VARCHAR | | 店铺 |
   437|
   438|**⑥ 供需映射 ods_wmap（4 列）**
   439|
   440|| # | 字段名 | 类型 | 必填 | 说明 |
   441||---|--------|------|------|------|
   442|| 1 | sku_code | VARCHAR | ✅ | SKU编码 |
   443|| 2 | msu_id | VARCHAR | ✅ | 最小销售单元ID |
   444|| 3 | warehouse_id | VARCHAR | | 供给仓库ID |
   445|| 4 | updated_at | VARCHAR | | 更新时间 |
   446|
   447|**⑦ 规则参数 ods_params（6 列）**
   448|
   449|| # | 字段名 | 类型 | 必填 | 说明 |
   450||---|--------|------|------|------|
   451|| 1 | param_no | VARCHAR | ✅ | 参数编号 P1-P14 |
   452|| 2 | param_id | VARCHAR | ✅ | 参数英文标识 |
   453|| 3 | param_name | VARCHAR | | 参数中文名称 |
   454|| 4 | param_type | VARCHAR | | 数据类型/取值范围 |
   455|| 5 | param_default | VARCHAR | | 默认值（JSON） |
   456|| 6 | param_note | VARCHAR | | 备注 |
   457|
   458|### 比对检查清单
   459|
   460|拿到客户样例数据后，逐表做以下检查：
   461|
   462|1. **必填字段是否齐全**：缺失必填字段 → 标记为「阻断」，需客户补充
   463|2. **字段名能否映射**：客户字段名和标准字段名是否一致，不一致则记录映射关系
   464|3. **数据类型是否一致**：日期是否统一 YYYY-MM-DD、数量是否为数字
   465|4. **编码体系是否一致**：同一 SKU 在不同数据源里编码是否相同（这是下一阶段的重点）
   466|5. **数据质量粗略检查**：是否有全 NULL 列、异常值、日期跳跃
   467|
   468|### 输出：字段匹配报告
   469|
   470|```
   471|┌─ 商品档案 ods_skus ──────────────────────────────────────┐
   472|│ 标准字段          │ 客户字段       │ 状态  │ 备注              │
   473|│ sku_code          │ SKU编码        │ ✅ 匹配│                   │
   474|│ spu_code          │ 款式编码       │ ✅ 匹配│                   │
   475|│ product_name      │ 商品名称       │ ✅ 匹配│                   │
   476|│ category          │ (无)           │ ⚠️ 缺失│ 可从类目表补充     │
   477|│ brand             │ (无)           │ ⚠️ 缺失│ 需客户手动填写     │
   478|│ tier              │ 等级           │ ⚡ 映射│ S/A/B/C vs 1/2/3/4│
   479|│ production_cycle  │ 生产周期       │ ✅ 匹配│                   │
   480|│ lead_time         │ (无)           │ ⚠️ 缺失│ 可设默认值30       │
   481|└────────────────────────────────────────────────────────────┘
   482|```
   483|
   484|| 图例 | 含义 |
   485||------|------|
   486|| ✅ | 可直接映射 |
   487|| ⚡ | 需要值转换映射 |
   488|| ⚠️ | 客户缺失，需补充或取默认值 |
   489|| 🚫 | 阻断：核心字段缺失，无法接入 |
   490|
   491|---
   492|
   493|## 阶段 C — 数据前置预处理
   494|
   495|### 目标
   496|
   497|确认客户是否需要对原始数据做前置处理，确保数据进入 PMC 系统前已满足标准要求。
   498|
   499|### 预处理规则
   500|
   501|PMC 标准体系只接收**单品级**数据。以下情况必须在数据导入 PMC 前完成预处理：
   502|
   503|#### 规则 1：组合装/套装 → 单品拆解
   504|
   505|如果客户的销售数据中包含组合装（如「A款+B款 套装」），必须在前置环节将组合装销量拆解为单品销量。
   506|
   507|**拆解方式**：
   508|1. 客户提供组合装 BOM（物料清单），列出每个组合装 SKU 包含哪些子 SKU 及各子 SKU 的数量
   509|2. 客户在 ETL 层将组合装销量按 BOM 拆解为单品销量（`组合装销量 × 子SKU数量`）
   510|3. 拆解后的单品销量再导入 `ods_sales`
   511|
   512|**示例**：
   513|
   514|| 组合装 SKU | 销量 | 子 SKU | 用量 | 拆解后单品销量 |
   515||-----------|------|--------|------|-------------|
   516|| SET-A | 10件 | SKU001 | 2 | 20件 |
   517|| SET-A | 10件 | SKU002 | 1 | 10件 |
   518|
   519|> **关键约束**：`ods_skus` 商品档案中**只能包含单品 SKU**，不得出现组合装 SKU。如果一个 SKU 对应多个子 SKU，说明它是组合装，不应出现在商品档案中。
   520|
   521|#### 规则 2：商品SKU → 产品SKU 映射（关键）
   522|
   523|大多数客户存在**两套天然不同的 SKU 编码体系**，但两者必须建立严格关联：
   524|
   525|| 编码体系 | 含义 | 出现位置 | 示例 |
   526||---------|------|---------|------|
   527|| **商品SKU** | 平台销售侧标识——上架售卖的商品编码 | 销售数据（ods_sales）、平台后台 | `BX451-Black-S` |
   528|| **产品SKU** | 库存/仓储侧标识——实物管理的产品编码 | 商品档案（ods_skus）、库存（ods_inventory）、采购（ods_po）、发货（ods_ship） | `DA5002AE-4P1-XL` |
   529|
   530|**为什么必须关联**：
   531|- 销售数据进来的是商品SKU，库存数据进来的是产品SKU，两者直接 JOIN 会全空
   532|- 销量需求（场景01）需要按产品SKU维度汇总库存；库存结构（场景07）需要知道每个产品SKU对应哪些商品SKU的销售
   533|- PMC 系统的**数据锚点是产品SKU**——所有场景的统一消费口 `dwd_sku_daily_metrics` 以产品SKU为主键
   534|
   535|**映射关系**：
   536|- 一个产品SKU 可能对应多个商品SKU（如不同颜色变体是不同商品SKU，但在库存管同一产品SKU）
   537|- 一个商品SKU 只对应一个产品SKU
   538|
   539|**预处理要求**：
   540|1. 客户必须提供**商品SKU ↔ 产品SKU 映射表**（两列：商品SKU、产品SKU）
   541|2. 在 ETL 层将 `ods_sales.sku_code` 从商品SKU 转换为产品SKU 后再导入
   542|3. 确保转换后的 `ods_sales.sku_code` = `ods_skus.sku_code` = `ods_inventory_domestic.sku_code`（全部统一为产品SKU）
   543|
   544|**引导话术**：
   545|「你们在平台上卖的商品编码（商品SKU）和仓库里管理库存的产品编码（产品SKU）应该是不同的两套编码。我们需要知道这两个编码之间的对应关系，才能在分析时把销量和库存对到一起。请提供一份商品SKU到产品SKU的映射表。」
   546|
   547|#### 规则 3：数据格式标准化
   548|
   549|进入 PMC 前必须完成以下标准化：
   550|
   551|| 要求 | 说明 |
   552||------|------|
   553|| 日期格式 | 统一 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS` |
   554|| 数值格式 | 整数，非负。不允许 `"10件"` / `"约50"` 等含中文的数值 |
   555|| 编码去空格 | SKU 编码首尾去空格，不允许 `" SKU001 "` |
   556|| 负值处理 | 负库存 → 设为 0，负销量 → 丢弃并记录异常日志 |
   557|
   558|### 引导对话流程
   559|
   560|**Step 1：询问组合装情况**
   561|
   562|「你们的商品是否有组合装/套装/捆绑销售？如果有，请提供组合装 BOM 清单，并在数据导入前将组合装销量拆解为单品销量后再给到我们。」
   563|
   564|**Step 2：确认商品SKU → 产品SKU 映射**
   565|
   566|要求客户提供商品SKU（销售平台侧）与产品SKU（库存管理侧）之间的对应关系。如果销售数据和库存数据使用的是不同编码，必须提供映射表。
   567|
   568|对客户提供的各数据源样例，逐对交叉比对 SKU 编码匹配率。如果匹配率 < 95%，确认是否因为商品SKU/产品SKU 双层编码未完成映射。
   569|
   570|> 大部分客户一开始意识不到这是两套编码，需要主动引导：「你们在平台卖货用的编码和仓库管库存用的编码是同一套吗？如果不是，我们需要一份对应表。」
   571|
   572|**Step 3：确认预处理完成**
   573|
   574|| 检查项 | 判断标准 | 状态 |
   575||--------|---------|------|
   576|| 组合装已拆解 | ods_skus 中无组合装 SKU，ods_sales 中无组合装销量 | ☐ |
   577|| 商品SKU→产品SKU 映射完成 | 销售数据的 SKU 已全部转换为产品SKU，与商品档案/库存编码一致 | ☐ |
   578|| 格式标准化 | 日期/数值/编码格式符合要求 | ☐ |
   579|
   580|> 三项全部通过后才进入阶段 D。任何一项不通过，回到对应步骤要求客户修正。
   581|
   582|---
   583|
   584|## 阶段 D — 管道配置
   585|
   586|### 目标
   587|
   588|根据客户数据源类型，推荐接入方式，生成对应的导入模板。
   589|
   590|### 四种接入模式
   591|
   592|| 模式 | 适用场景 | 接入方式 | 模板 |
   593||------|----------|----------|------|
   594|| **API 直接拉** | 客户有 客户数据库 | `pmc_template_api.py` 新增端点 → Excel → `pmc_import.py` 导入 | 参考现有 5 个端点 |
   595|| **CSV/Excel 导入** | 客户从 ERP 导出文件 | 直接写 `pmc_import.py` 兼容的 Sheet 导入逻辑 | 见下方模板 |
   596|| **客户 API 对接** | 客户提供 RESTful API | 写 cron 定时拉取 → 转 Excel → 导入 | 需客户提供 API 文档 |
   597|| **手动维护** | 参数/映射等低频数据 | Excel 模板 + 客户定期更新 | 提供标准化 Excel 模板 |
   598|
   599|### 模板生成：CSV/Excel 导入模式（最常用）
   600|
   601|为客户的每块数据生成一个 DuckDB DDL + Python 导入函数。
   602|
   603|**DDL 模板**（以 ods_sales 为例）：
   604|
   605|```sql
   606|CREATE TABLE IF NOT EXISTS ods_sales (
   607|    sku_code VARCHAR,
   608|    sale_date VARCHAR,
   609|    daily_qty VARCHAR,
   610|    msu_id VARCHAR
   611|);
   612|```
   613|
   614|**Python 导入函数模板**（参考 `pmc_import.py` 的 `import_sheet` 函数）：
   615|
   616|```python
   617|import duckdb, os, csv
   618|
   619|DB_PATH = os.path.expanduser("~/pmc-data/pmc_ods.duckdb")
   620|
   621|def import_customer_sales(csv_path: str):
   622|    """导入客户 CSV 格式的日销量数据 → ods_sales"""
   623|    con = duckdb.connect(DB_PATH)
   624|
   625|    # 1. 读 CSV（用 DuckDB 原生 read_csv，自动推断类型）
   626|    rows = con.execute(f"""
   627|        SELECT sku_code, sale_date,
   628|               CAST(daily_qty AS INTEGER) AS daily_qty,
   629|               msu_id
   630|        FROM read_csv_auto('{csv_path}')
   631|    """).fetchall()
   632|
   633|    if not rows:
   634|        print("⚠️ CSV 无数据，跳过")
   635|        return
   636|
   637|    # 2. UPSERT（按 sku_code + sale_date + msu_id 去重）
   638|    con.executemany("""
   639|        INSERT INTO ods_sales (sku_code, sale_date, daily_qty, msu_id)
   640|        VALUES (?, ?, ?, ?)
   641|        ON CONFLICT (sku_code, sale_date, msu_id) DO UPDATE
   642|        SET daily_qty = excluded.daily_qty
   643|    """, rows)
   644|
   645|    print(f"✅ 导入了 {len(rows)} 行 → ods_sales")
   646|    con.close()
   647|```
   648|
   649|### 批量导入脚本生成
   650|
   651|为每块数据生成独立的导入函数后，组装成 `import_customer_data.py`：
   652|
   653|```python
   654|#!/usr/bin/env python3
   655|"""客户数据批量导入脚本 — 一键导入所有板块"""
   656|import sys
   657|from import_customer_sales import import_customer_sales
   658|from import_customer_skus import import_customer_skus
   659|# ... 其他导入函数
   660|
   661|def main():
   662|    print("开始导入客户数据...")
   663|
   664|    # 1. 商品档案（先导入，其他表依赖它）
   665|    import_customer_skus("/path/to/skus.csv")
   666|
   667|    # 2. 供需映射
   668|    import_customer_wmap("/path/to/wmap.csv")
   669|
   670|    # 3. 库存快照
   671|    import_customer_inventory("/path/to/inventory.csv")
   672|
   673|    # 4. 日销量
   674|    import_customer_sales("/path/to/sales_2025.csv")
   675|
   676|    # 5. 采购明细
   677|    import_customer_po("/path/to/po.csv")
   678|    import_customer_po_recv("/path/to/po_recv.csv")
   679|
   680|    # 6. 发货明细
   681|    import_customer_ship("/path/to/ship.csv")
   682|
   683|    # 7. 规则参数（如果客户有自定义参数）
   684|    import_customer_params("/path/to/params.csv")
   685|
   686|    print("\n✅ 全部导入完成")
   687|
   688|if __name__ == "__main__":
   689|    main()
   690|```
   691|
   692|### 导入顺序约束
   693|
   694|由于表之间存在依赖关系（DWD 层从多张 ODS 表聚合），推荐导入顺序：
   695|
   696|```
   697|ods_skus  →  ods_wmap  →  ods_inventory_domestic/overseas
   698|  →  ods_sales  →  ods_po/ods_po_recv  →  ods_ship  →  ods_params
   699|```
   700|
   701|### 生成交付清单
   702|
   703|阶段 D 完成后，输出给客户的交付清单：
   704|
   705|```
   706|PMC 数据接入 — 管道配置
   707|
   708|1. DuckDB DDL 脚本: /path/to/create_tables.sql  
   709|2. 导入脚本: /path/to/import_customer_data.py  
   710|3. ETL 编码映射配置（如需）: /path/to/etl_mapping.yaml  
   711|4. 参数配置模板: /path/to/params_template.xlsx  
   712|5. 每日导入 cron: 建议每天凌晨 3:00 执行 import_customer_data.py
   713|
   714|下一步：阶段 E — 端到端验证
   715|```
   716|
   717|---
   718|
   719|## 阶段 E — 验证
   720|
   721|### 目标
   722|
   723|数据导入完成后，跑一遍完整管线，确认数据能支撑场景计算。
   724|
   725|### 验证步骤
   726|
   727|**Step 1：刷新 DWD 指标层**
   728|
   729|```bash
   730|cd ~/pmc-agent && python3 scripts/refresh_dwd_metrics.py
   731|```
   732|
   733|检查输出：
   734|- `ods_sales 最新日期` 是否接近当天
   735|- `OK: N SKU, M 有销, K 有销有库存` 是否合理
   736|- 新列填充情况是否正常
   737|
   738|**Step 2：运行验证 SQL**
   739|
   740|```sql
   741|-- 验证 1：SKU 覆盖率
   742|SELECT
   743|    (SELECT COUNT(DISTINCT sku_code) FROM ods_skus) AS total_skus,
   744|    (SELECT COUNT(DISTINCT sku_code) FROM ods_sales) AS skus_with_sales,
   745|    (SELECT COUNT(DISTINCT sku_code) FROM ods_inventory_domestic) AS skus_with_inv;
   746|
   747|-- 验证 2：日期连续性（最近30天）
   748|SELECT sale_date, COUNT(DISTINCT sku_code) AS skus, SUM(CAST(daily_qty AS INTEGER)) AS total_qty
   749|FROM ods_sales
   750|WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 30
   751|GROUP BY sale_date ORDER BY sale_date DESC
   752|LIMIT 30;
   753|
   754|-- 验证 3：DWD 数据合理性
   755|SELECT
   756|    COUNT(*) AS total,
   757|    COUNT(*) FILTER (WHERE weighted_daily > 0) AS with_sales,
   758|    COUNT(*) FILTER (WHERE total_inventory > 0) AS with_inventory,
   759|    COUNT(*) FILTER (WHERE inventory_days BETWEEN 1 AND 365) AS reasonable_days,
   760|    COUNT(*) FILTER (WHERE inventory_days > 365) AS warning_slow_moving,
   761|    COUNT(*) FILTER (WHERE inventory_days < 0) AS data_error
   762|FROM dwd_sku_daily_metrics;
   763|
   764|```
   765|
   766|**Step 3：抽样场景验证**
   767|
   768|随机选一个场景 Skill 跑一遍，确认不出 SQL 错误：
   769|
   770|```bash
   771|# 在 DuckDB 中跑场景的核心 SQL（抽取几条看看）
   772|duckdb ~/pmc-data/pmc_ods.duckdb -c "
   773|SELECT sku_code, weighted_daily, total_inventory, inventory_days, tier
   774|FROM dwd_sku_daily_metrics
   775|WHERE weighted_daily > 0 AND inventory_days > 0
   776|ORDER BY inventory_days ASC
   777|LIMIT 10;
   778|"
   779|```
   780|
   781|**Step 4：输出验证报告**
   782|
   783|```
   784|PMC 数据接入 — 验证报告
   785|
   786|数据概况
   787|  SKU 总数:    1,234
   788|  有销售 SKU:   892 (72.3%)
   789|  有库存 SKU: 1,100 (89.1%)
   790|
   791|销售数据
   792|  最新日期:     2025-06-15 (延迟 1 天，正常)
   793|  覆盖天数:     180 天
   794|  日均销量:     342 件
   795|
   796|DWD 指标
   797|  有加权日均销: 892 条
   798|  库存天数 1-365: 845 条
   799|  呆滞预警 (>365天): 12 条  ← 需客户关注
   800|  数据异常 (<0天): 0 条
   801|
   802|✅ 整体判定: 通过
   803|⚠️ 关注项: 12 条 SKU 库存天数超过 365 天，建议检查是否滞销品
   804|```
   805|
   806|---
   807|
   808|## 快速接入模式（已有数据源接入经验的客户）
   809|
   810|如果客户已有数据库访问权限，可以走快速通道：
   811|
   812|```
   813|1. 数据库连接信息 → 配置到 pmc_template_api.py
   814|2. 跑标准 5 端点 → 下载 Excel
   815|3. pmc_import.py 导入 → DuckDB ODS 表
   816|4. refresh_dwd_metrics.py → DWD 指标层
   817|5. 按需导入客户自定义参数
   818|```
   819|
   820|不需要的阶段直接跳过，向客户确认即可。
   821|
   822|---
   823|
   824|## Agent 执行纪律
   825|
   826|### 对话节奏
   827|
   828|| 规则 | 说明 |
   829||------|------|
   830|| 按阶段推进 | 阶段 A 没确认完，不进阶段 B |
   831|| 主动列出下一步 | 每阶段结束告诉客户「下一步我需要您提供…」 |
   832|| 不说废话 | 不要「太棒了」「完美！」之类，直接给结论 + 下一步 |
   833|| 阻塞点明确 | 卡住了说清楚卡在哪，不要假装推进 |
   834|| 输出文件给路径 | 生成的 DDL/脚本/模板落盘后给出绝对路径 |
   835|
   836|### 常见阻塞及处理
   837|
   838|| 阻塞 | 处理 |
   839||------|------|
   840|| 客户提供不了某块数据 | 确认该板块是否必选。非必选跳过，必选则协商替代方案 |
   841|| SKU 编码无法统一 | 让客户在 ETL 层做编码映射。实在无法统一的，要求客户逐一说明原因 |
   842|| 字段完全对不上 | 回到阶段 B 重新确认，可能是客户给了错误的数据 |
   843|| 管线报错 | 逐层排查：API 可用？→ Excel 格式正确？→ DuckDB DDL 匹配？ |
   844|
   845|---
   846|
   847|## 相关文件
   848|
   849|- 管线 Skill: `~/.hermes/skills/pmc-data-pipeline/SKILL.md`
   850|- API 源码: `~/pmc-agent/scripts/pmc_template_api.py`
   851|- 导入脚本: `~/pmc-agent/scripts/pmc_import.py`
   852|- DWD 刷新: `~/pmc-agent/scripts/refresh_dwd_metrics.py`
   853|- DuckDB: `~/pmc-data/pmc_ods.duckdb`
   854|