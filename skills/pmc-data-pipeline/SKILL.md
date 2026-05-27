---
name: pmc-data-pipeline
version: 1.2.0
description: "PMC 数据接入管线：cosboard → API → Excel → DuckDB ODS 的全链路操作。当需要调试/修改/扩展数据导入、排查 SKU 关联问题、新增模板字段、理解三类文件加载模式时使用。"
metadata:
  triggers:
    - "PMC 数据导入"
    - "DuckDB ODS"
    - "Excel 模板"
    - "数据管线"
    - "cosboard → DuckDB"
    - "增量数据窗口"
    - "SKU 归一化"
    - "静态/快照/增量"
    - "管线维护"
    - "PMC cron"
    - "pmc_import"
  requires:
    bins: ["python3", "curl"]
    files: ["~/workspace/pmc-agents/pmc_template_api.py", "~/workspace/pmc-agents/scripts/pmc_import.py"]
design_docs:
  prd_v4_index: "https://xcnk9flkicyx.feishu.cn/docx/KmI9d6GTwodFhyx9uztcoi8HnZf"  # 飞书 v4 唯一权威索引
  prd_v2_deprecated: "~/workspace/pmc-agents/PMC九场景全景PRD_20260426_v2.md"  # 旧版，已过时
  wiki: "https://xcnk9flkicyx.feishu.cn/wiki/Itr2w4TF9imL76kCQ0ccBVN4nKg"
  tech_design: "~/workspace/pmc-agents/PMC九场景技术设计文档.md"
  product_req: "~/workspace/pmc-agents/PMC九场景PRD_产品需求文档.md"
  data_audit: "~/workspace/pmc-agents/00_导航页.md"
  template_spec: "~/workspace/pmc-agents/docs/excel-template-spec.md"
---

# PMC 数据接入管线

## 架构

```
cosboard ({COSBOARD_HOST}:{COSBOARD_PORT})
     │  SELECT only
     ▼
PMC Excel Template API (localhost:8765)
     │  5 端点 → 5 个 Excel 文件
     ▼
~/pmc-data/{static,snapshot,incremental}/
     │  cron 或手动触发
     ▼  scripts/pmc_import.py
DuckDB (${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb})
     10 张 ods_* 表
```

> 数据模型的业务语义按「六大板块」组织，而非按表名罗列。详见 `references/six-business-domains.md`。

## 文件命名约定 — 重要

**API 端点返回的文件名 ≠ `pmc_import.py` 期望的文件名。** curl 下载后必须 `cp` 到中文文件名：

| 端点 | curl 保存为 | 脚本期望的文件名 |
|:---|:---|:---|
| `/template/skus` | `static/skus.xlsx` | `static/商品主数据.xlsx` |
| `/template/params` | `static/params.xlsx` | `static/参数配置.xlsx` |
| `/template/msu-map` | `static/msu-map.xlsx` | `static/SKU-最小销售单元-仓库映射.xlsx` |
| `/template/inventory` | `snapshot/inventory.xlsx` | `snapshot/库存快照.xlsx` |
| `/template/daily-data` | `incremental/daily-data.xlsx` | `incremental/日增量数据.xlsx` |

> 脚本按 `static_files` 字典硬编码的中文文件名查找文件（src: `pmc_import.py` L133-L137）。

## 三类文件 + 加载模式

| 目录 | 端点 | 模式 | 说明 |
|:---|:---|:---|:---|
| `static/` | `/template/skus`, `/template/params`, `/template/msu-map` | **全量覆盖** (DROP+INSERT) | 低频变更的主数据 |
| `snapshot/` | `/template/inventory` | **全量覆盖** | 库存全貌快照（2 Sheet：国内+海外） |
| `incremental/` | `/template/daily-data` | **增量追加** (UPSERT) | 1 个 Excel 5 个 Sheet，全部取上一个自然日 |

## 增量窗口设计 — 关键原则

**三类增量数据硬编码为上一个自然日，无参数。**

| Sheet | 条件 | 理由 |
|:---|:---|:---|
| 日销量 | `saledate = curdate() - 1`，且 `pt2='亚马逊'` | 只拉亚马逊渠道，每天只拉昨天一天 |
| 采购明细 | `OrderDate = curdate() - 1` | 同上 |
| 采购收货明细 | `date(BillDate) = curdate() - 1` | 同上 |

> **`pt2='亚马逊'` 是设计意图，不是 bug。** 用户确认 PMC 系统只关注亚马逊渠道的销售数据，不要改成全渠道。如果 cosboard 的亚马逊销售数据有延迟（通常 1~6 天），这是上游数据滞后问题，不是管线过滤问题。

**不要**给日增量端点加 `?days=` 参数——增量管线的职责是吐最近一帧数据做合并，不负责"一次下够"。

### ⚠️ 致命陷阱：管线不连续运行会导致永久数据丢失

增量设计的必然推论：**API SQL 写死 `saledate = curdate() - 1`，如果连续 N 天没跑管线，中间 N-1 天的销售数据就永远丢失了。** 管线不会自动"追回"错过的日期。

**为什么？**
- 管线不是从 cosboard 全量拉取历史数据
- 它只取「昨天的」增量数据追加到 DuckDB
- 5/22 的数据只有在 5/23 跑管线时才能拉到
- 5/23 的数据只有在 5/24 跑管线时才能拉到
- 错过了某一天 → 那天的数据就断了

**历史案例**（2026-05-27 发生）：上次手动导入在 5/22，之后连续 6 天没跑管线。cosboard 在 5/22~5/25 有 13,712 条亚马逊数据，但管线只拉到 5/21。恢复手段是临时改 API SQL 的 `=` 为 `>= curdate() - 5` 全量拉，导入完成后改回 `=`。详见 `references/backfill-procedure.md`。

## SKU 归一化枢纽

`v_cdm_skubom` 是 cosboard 跨表关联的核心视图：
- `psku` = 平台 SKU（对应 `cdm_sku.sku`）
- `sku_id` = 归一化后 SKU（COALESCE(map_sku, sku)，处理组合/套装拆解）
- `sku_code` = 另一种 SKU 标识（⚠️ 经实测全部为 NULL，不可用于 JOIN）

**所有跨表 JOIN 的标准写法**：
```sql
-- 采购/入库表（平台SKU）→ 归一化SKU
LEFT JOIN v_cdm_skubom b ON t.skucode = b.psku
-- 然后用 COALESCE(b.sku_id, t.skucode) 做降级
```

各视图已内置归一化：`v_dwd_com_sell_1d.sku_id`、`v_jstskuinv.sku_id` 都已是归一化 SKU。

### ⚠️ 跨系统 SKU 编码兼容性（重要）

cosboard 内部存在**多套 SKU 编码体系**，导入 DuckDB 后直接 `JOIN` 可能不匹配：

| 来源 | 字段 | SKU 格式示例 | 说明 |
|------|------|-------------|------|
| 商品主数据 (`cdm_sku`) | `sku` | `DA5002AE-4P1-XL` | cosboard 原生 SKU |
| FBA 库存 (`dwd_sh_amz_fba_stock`) | `goods_sku` | `TTW-008-Skin-85D` | 同上体系 |
| FBA 发货 (`dwd_sh_amz_fba_shipment_sku_info`) | `commodity_sku` | `CR0908NC-7P09-M` | 同上体系 |
| 日销量表 (`v_dwd_com_sell_1d`) | `sku_id` | `BX451-Black-S` | **归一化编码**（产品-颜色-尺码） |
| 采购视图 (`v_purchase`) | `sku_code` | `DA5002AE-4P1-XL` | 与商品主数据同体系 |

**影响**：当你在 DuckDB 中 JOIN `ods_inventory_overseas.sku_code`（cosboard 原生 "DA5002AE-4P1-XL"）和 `ods_skus.sku_code`（同样来自 `cdm_sku.sku`）时，**两者格式一致，可以匹配**。但 JOIN `ods_sales.sku_code`（来自 `v_dwd_com_sell_1d.sku_id` 归一化格式 "BX451-Black-S"）时，**格式不同，JOIN 全 NULL**。

**处理方法**：
- 所有数据源必须在 ETL 层统一为同一套 SKU 编码后再导入 DuckDB
- 不允许在 DuckDB 内做编码映射桥接（如 `ods_cdm_skubom`）
- 如果 `ods_sales` 的 SKU 格式和 `ods_skus` 不一致，说明 `ods_sales` 已内置归一化而 `ods_skus` 还是原生的——这是已知差异，应在 ETL 层统一，而非在各场景 SQL 中做映射补偿

## DuckDB 注意

- **CREATE TABLE 必须带类型**：`CREATE TABLE t (col VARCHAR)`，不能像 SQLite 省略类型
- **INSERT OR IGNORE 需要 UNIQUE 约束**：改用 `ON CONFLICT (cols) DO NOTHING` 或先建唯一索引
- **Excel 控制字符**：`0x00-0x08, 0x0B-0x0C, 0x0E-0x1F` 会导致 openpyxl 报 `IllegalCharacterError`，写入前必须 `re.sub` 过滤
- **DuckDB `-ui` 不可用（v1.5.2）**：`duckdb -ui` 打印启动信息后立即退出，端口不监听。需用 Python HTTP Server 替代（见下方「远程访问」）

## DuckDB 远程访问

DuckDB 无 server/client 协议，远程可视化需自建 HTTP 层。详见 `references/duckdb-remote-access.md`。

快速启动 Tailscale Web UI：

```bash
python3 ~/pmc-data/duckdb_webui.py
# → http://100.93.193.127:8766/
```

脚本：`scripts/duckdb_webui.py`。也可用 FRP 暴露（`references/duckdb-remote-access.md` 中有 FRP 配置）。

## 导入脚本

```bash
cd ~/workspace/pmc-agents
python3 scripts/pmc_import.py
```

输出 10 张表：ods_skus, ods_params, ods_wmap, ods_inventory_domestic, ods_sales, ods_po, ods_po_recv, **ods_inventory_overseas, ods_ship, ods_ship_recv**。幂等——增量表去重（ods_ship/ods_ship_recv 用 upsert），全量表覆盖（ods_inventory_overseas 用 overwrite）。

> `ods_inventory_overseas`（海外库存快照）和 `ods_ship`（海外发货明细）的数据来自 cosboard 的 FBA 表，经 `pmc_template_api.py` 管线填充。`ods_ship_recv`（海外收货明细）因 cosboard 无实际收货日期字段，仍为空表——详见下方「已知问题·海外收货明细无数据」。

### DWD 指标层（导入后自动触发）

导入完成后自动执行 `scripts/refresh_dwd_metrics.py`，重建 `dwd_sku_daily_metrics` 表：

| 字段 | 含义 | 公式 |
|:---|:---|:---|
| `weighted_daily` | 加权日均销 | `0.5×昨日销量 + 0.3×近7天日均 + 0.2×近30天日均` |
| `total_inventory` | 有效库存 | `GREATEST(inv_domestic + inv_purchase_onway, 0)`（负库存 clamp 为 0） |
| `inventory_days` | 库存天数 | `total_inventory / weighted_daily`（weighted_daily > 0 时） |

> 该表为各场景 Skill 的统一消费口——所有需要日均销/库存天数的场景直接 JOIN 此表，不再各自计算。**这是 DuckDB 迁移到 MySQL 的关键隔离层：DWD 表结构和公式与数据库引擎无关，迁移时只需改变数据写入路径，场景 SQL 不动。**

## 日常维护 SOP（cron 任务执行清单）

> **自动定时任务已配置**：cron job ID `4cafd184eecb`（名「PMC每日数据导入」），每天 **03:00 (Asia/Shanghai)** 自动执行此 SOP。启用 `terminal` toolset，静默执行（deliver=local，不向用户发消息）。用 `cronjob action=list` 查看 last_status 确认是否正常跑。
>
> **为什么是凌晨 3 点？** cosboard 销售数据通常有 1~2 天延迟，凌晨跑可以覆盖前一天可能新增的滞缓数据，同时避免与日间业务高峰冲突。

### 1. 检查 API 可用性
```bash
curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8765/template/daily-data
```
期望 200，否则中止并报告。

### 2. 下载 5 个端点（并行）
```bash
curl -sS --connect-timeout 10 --max-time 120 -o ~/pmc-data/incremental/daily-data.xlsx http://localhost:8765/template/daily-data
curl -sS --connect-timeout 10 --max-time 300 -o ~/pmc-data/snapshot/inventory.xlsx     http://localhost:8765/template/inventory
curl -sS --connect-timeout 15 --max-time 120 -o ~/pmc-data/static/skus.xlsx http://localhost:8765/template/skus
curl -sS --connect-timeout 10 -o ~/pmc-data/static/params.xlsx          http://localhost:8765/template/params
curl -sS --connect-timeout 15 --max-time 120 -o ~/pmc-data/static/msu-map.xlsx http://localhost:8765/template/msu-map
```
> 库存快照拉久（`--max-time 300`）是因为 JOIN v_cdm_skubom 进行编码映射+数量拆解可能长达 100s（实测 98s 全表过滤），再加 Excel 序列化和网络传输时间，120s 容易卡线。msu-map 和 skus 超时 120s+ 是可接受的（数据量大）；其他端点通常在 10s 内完成。

### 3. 桥接文件名（API 端点名 → 脚本期望的中文名）
```bash
cp ~/pmc-data/incremental/daily-data.xlsx ~/pmc-data/incremental/日增量数据.xlsx
cp ~/pmc-data/snapshot/inventory.xlsx      ~/pmc-data/snapshot/库存快照.xlsx
cp ~/pmc-data/static/skus.xlsx             ~/pmc-data/static/商品主数据.xlsx
cp ~/pmc-data/static/params.xlsx           ~/pmc-data/static/参数配置.xlsx
```
msu-map 下载成功时：
```bash
cp ~/pmc-data/static/msu-map.xlsx          ~/pmc-data/static/SKU-最小销售单元-仓库映射.xlsx
```
超时时跳过此步，使用已有旧文件。

### 4. 运行导入
```bash
cd ~/workspace/pmc-agents && python3 scripts/pmc_import.py
```

### 5. 刷新 DWD 指标层
```bash
cd ~/workspace/pmc-agents && python3 scripts/refresh_dwd_metrics.py
```
> ODS 导入完成后立即重算 `dwd_sku_daily_metrics`（加权日均销 + 库存天数）。幂等操作，DROP + CREATE + INSERT 全量重建。若失败则中止后续抽检，报告错误。

### 6. 抽查 Skill SQL（每次轮换 3 个不同的 scene）
从 10 个 scene skill 中轮换抽检，运行其核心 SQL 验证无报错。当前轮次记录见 `references/maintenance-rotation.md`。

### 7. 输出报告

> **注意**：`ods_params` 表中参数编号存在 `param_no` 列（值为 `'P3'`, `'P5'` 等），描述性名称存在 `param_id` 列（值为 `'forecast_params'`, `'slow_moving_days'` 等）。抽检 SQL 中查参数时用 `WHERE param_no = 'P3'`，不要误用 `param_id`。

### 6. 输出报告
- ods_sales 累计天数、最新日期
- 各表行数变化（导入前 → 导入后）
- 异常项说明
- 周末/节假日增量 Sheet 为空属正常，不视作异常

**报告格式**：只汇报有变化或异常的情况，一切正常则输出简表 + "OK 无异常"。

## 已知问题

### msu-map 端点超时

`/template/msu-map` 端点因 cosboard 联表查询繁重，常超时 120s+（`curl: (28) Operation timed out`）。**处理方式**：保留上次成功下载的 `SKU-最小销售单元-仓库映射.xlsx`，超时时跳过重试直接使用旧文件。此表为低频变更的静态主数据，数周不更新不影响正确性。

### skus 端点下载超时（Hermes 前台 terminal 限制）

`/template/skus` 数据量最大（~10MB），部分 cron 环境配置 `--max-time 600`。**Hermes terminal 前台 timeout 硬上限为 600s**，若 curl 的 `--max-time` 接近或等于 600s，前台调用必定被拒。**处理方式**：将 skus 下载改为 `background=true` + `notify_on_complete=true`，后台运行完成后再继续后续步骤。

### 两种下载模式

**模式 A（SOP 标准 — 需要桥接）**：curl 下载到英文文件名，再 `cp` 到中文名。适合手动执行，文件名保持一致。

**模式 B（cron 直写 — 免桥接）**：curl 直接 `-o` 到中文文件名，跳过 `cp` 步骤。适合 cron job，减少命令数。两者等效，脚本按中文文件名查找。

### 周末/节假日的增量数据

增量端点硬编码 `curdate() - 1`，若前一日为周日或节假日，日销量/采购明细/海外发货明细等 Sheet 可能无数据。此时导入脚本会输出 `⚠️ Sheet '日销量' 无数据，跳过` —— 这是正常行为，**不是异常**。只有「所有增量 Sheet 均无数据」才需要排查（API 故障的可能信号）。海外发货并非每天都有记录（通常 38 条/天），偶尔为空也属正常。

### cosboard 销售数据延迟（非管线问题）

cosboard 的日销量数据（`v_dwd_com_sell_1d` 视图，`pt2='亚马逊'`）可能存在 **1~6 天的入库延迟**。这意味着：
- API 的 `日销量` sheet 可能连续多天返回空行（即使采购/库存 sheet 已更新）
- 这不是管线故障，是 cosboard 侧销售数据未录入
- 检查方法：对比 `ods_sales` 最新日期 vs `ods_po`/`ods_inventory_domestic` 最新日期
- 采购明细和库存快照通常比日销量新，不要因此误判管线问题
- **不要**因为日销量为空就怀疑 `pt2='亚马逊'` 条件是错的——这已被用户确认为设计意图

### 增量数据丢失后的回填

当连续 N 天没跑管线导致中间 N-1 天数据丢失时，执行以下回填步骤：

1. 编辑 `~/workspace/pmc-agents/pmc_template_api.py`，将日销量 SQL 的 `saledate = curdate() - interval 1 day` 改为 `saledate >= curdate() - interval {N+1} day`
2. 重启 API（kill 旧进程 + 启动新进程，必须验证 200）
3. 重新下载 daily-data.xlsx 并检查行数是否包含缺失日期
4. 运行 `pmc_import.py` 导入
5. 运行 `refresh_dwd_metrics.py` 刷新 DWD
6. **立即**将 SQL 改回 `= curdate() - interval 1 day`
7. 再次重启 API

> 完成后确认 `ods_sales` 最新日期已推进。不要忘记第 6 步——忘记改回会导致后续每天重复拉取 N+1 天数据。

### 导入输出表数量

当前稳定输出的表为 10 张：
- 静态：ods_skus, ods_params, ods_wmap（3 张）
- 快照：ods_inventory_domestic, **ods_inventory_overseas**（2 张，海外库存现已填充）
- 增量：ods_sales, ods_po, ods_po_recv, **ods_ship**, ods_ship_recv（5 张，ods_ship 现已填充）

> `ods_ship_recv`（海外收货明细）因 cosboard 无实际收货日期回传字段，仍保持为空。不要误以为管线故障。

### 常见的陷阱

#### DBA 提供的 SQL 不要拆散到本地处理

当 cosboard DBA 给出一个带 JOIN + 计算的 SQL（如 `JOIN v_cdm_skubom ... * rm_qty`），它已经封装了标准的编码映射和组合装拆解逻辑。**直接用在 API 查询中**，不要拆成「API 拉两套原始数据 → Python 本地做 JOIN 和乘法」——那是在 cosboard 侧已经做好的事，拆散后既降低可维护性又违反原始口径权威性。

✅ 正确做法：
```python
# API 里直接执行 DBA 给的 SQL
data = query("""
    SELECT b.sku_id, a.shipping_quantity * b.rm_qty, ...
    FROM dwd_sh_amz_fba_shipment_sku_info a
    JOIN v_cdm_skubom b ON a.commodity_sku = b.psku
""")
```

❌ 错误做法：
```python
# API 拉两套原始数据，Python 本地拼
raw = query("SELECT * FROM dwd_sh_amz_fba_shipment_sku_info")
bom = query("SELECT * FROM v_cdm_skubom")
# 然后 Python 里做 JOIN + map + rm_qty 乘法
```

> 这个原则的前提是：SQL 是 cosboard DBA 给的权威口径。自己瞎拼的直连 SQL 仍被禁止。

#### API 层 pymysql 必须配 read_timeout

`get_conn()` 如果只设 `connect_timeout` 不设 `read_timeout`，碰到大 JOIN（如 `JOIN v_cdm_skubom` 的全表库存快照），查询阶段没有超时兜底。配合 MySQL 服务端默认 `net_read_timeout=30s`，长查询极易被杀。

**实测数据**（cosboard 服务器 `{COSBOARD_HOST}`）：
| 查询 | 耗时 |
|:---|:---:|
| 库存 JOIN（限定当天快照，24k行） | **0.72s** |
| 库存 JOIN（全表 5.6M 行无过滤） | **98s** |

**修复方案 — `get_conn()` 加 read_timeout + session 级超时**：
```python
def get_conn():
    conn = pymysql.connect(connect_timeout=10, read_timeout=600, **COSBOARD)
    with conn.cursor() as cur:
        cur.execute("SET SESSION net_read_timeout = 600")
        cur.execute("SET SESSION net_write_timeout = 600")
    return conn
```
- `read_timeout=600`：pymysql 侧给查询执行 10 分钟
- `net_read_timeout = 600`：MySQL 服务端不会因为 10 分钟以内没读完数据就杀连接

**curl 下载超时同步调整**（见下方 SOP 第2步）：
- 库存快照 `--max-time` 从 120 提到 **300**
- 其他端点（sku/msu-map）维持 120+——msu-map 有单独的静默降级机制，不在此列

#### 脚本中禁止硬编码用户路径

`refresh_dwd_metrics.py` 当前存在可移植性问题：`DB_PATH = "~/pmc-data/pmc_ods.duckdb"` 硬编码了特定用户的 home 目录。这在 Profile 分发到其他环境时会直接炸。

✅ 正确写法：
```python
DB_PATH = os.path.expanduser("${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}")
```

同理，所有脚本中涉及 `~/pmc-data/` 的路径都必须用 `os.path.expanduser()` 而非硬编码绝对路径。

#### API 修改后必须重启进程

`pmc_template_api.py` 是常驻 FastAPI 进程（`:8765`），**修改代码后不会自动生效**。即使文件有多旧、修改时间多新，进程只加载启动时的版本。

```bash
# 1. 找到 PID
ps aux | grep pmc_template_api

# 2. 重启
kill <PID> && cd ~/workspace/pmc-agents && nohup python3 pmc_template_api.py &

# 3. 验证新代码生效
curl -s http://localhost:8765/
# 然后下载某个端点，检查数据是否反映最新代码改动
```

**验证方法**：下载 Excel 并用 openpyxl 检查行数，不要只看文件修改时间。

```python
import openpyxl
wb = openpyxl.load_workbook('/tmp/test.xlsx')
ws = wb['海外库存快照']
print(f"数据行数: {ws.max_row - 2}")  # 减去表头+解释行
# 如果行数 > 0，证明 API 已加载新代码
```

#### 不要直连 cosboard 写 SQL 到场景 Skill

cosboard 是客户的原始数据源，不是分析的直接消费层。所有 cosboard 数据必须经过 `pmc_template_api.py` → 标准 Excel → `pmc_import.py` → DuckDB 的管线。禁止在场景 skill 里写 cosboard 直连 SQL，即使数据看起来已经存在。

## 外部 Excel 数据导入（非管线端点）

当收到非管线端点产出的 Excel（如亚马逊 MSKU 库存关系表、第三方导出文件等）时，走独立的导入流程：

1. 分析 Excel 结构（Sheet、列名、行数）
2. 对比 ods_skus.sku_code 做批量精确匹配（分批 500 条/次）
3. 建表时加 `match_status` + `match_note` 列标记清洗状态
4. 生成清洗明细报告

详见 `references/amazon-msku-import.md`。

## 场景 Skill 执行纪律（⚠️ 铁律）

> 用户反馈：PMC 场景执行过程发送大量中间进度汇报（"正在跑 SQL → "PDF 生成成功" → "现在生成 Excel" → "发给你"），体验极差。

### 静默执行规则

**触发任一 PMC 场景 Skill 时，全程静默执行，只发最后一条消息。**

| 规则 | 说明 |
|:---|:---|
| 🚫 **禁止中间汇报** | 不发送「正在跑 SQL」「PDF 生成成功」「现在生成 Excel」「两份文件都好了，发给你」等进度消息 |
| ✅ **允许的唯一消息** | 最终摘要（3-5 句文字 + 附件链接）。中间所有 tool call 结果自行消费，不转发给用户 |
| 🛠️ **出错自行消化** | SQL 报错 → 自己修了重试；Playwright 没装 → 自动切 Chrome CLI 备选。不要告诉用户「Playwright 没装，我换方案」 |
| 🆘 **求助条件** | 仅在**所有备选方案都失败**时才联系用户说明卡在哪里 |

### 相关

- 共享交付模块：`~/workspace/pmc-agents/scripts/pmc_delivery.py` — 封装渠道检测 + HTML→PDF + Excel 生成，统一写入 `/tmp/hermes-pmc-output/`
- ⚠️ `pmc_delivery.py` 有已知 bug：`detect_channel()` docstring 未闭合导致 `SyntaxError`，详见 `references/pmc-delivery-known-bugs.md`
- 临时绕过：`execute_code` 中手写 `get_output_path()` / `now_iso()` 替代 import
- 启动方式：`launchd` com.pmc.output-cleanup（每天 03:00 清理 7 天前文件）
- 场景 PRD 权威文档：飞书 `KMI9d6GTwodFhyx9uztcoi8HnZf`（唯一权威索引）
- 当前 Skill ↔ PRD 场景编号存在偏差（Skill 从 00 起，PRD 从 01 起；内容也不完全对齐），参见 `references/prd-skill-mapping.md`

## Amazon 数据架构

Amazon 数据在 ODS 中有两套独立的编码体系。详见 `references/amazon-data-architecture.md`：

| 体系 | 格式示例 | 销售数据 | 用途 |
|------|---------|---------|------|
| Amazon MSKU (`ods_amazon_msku_agg`) | `A1021AB-3P01-S-1` | `weighted_daily` 全部为 0 | Amazon 平台产品编号 |
| 内码 SKU (`dwd_sku_daily_metrics`) | `BA1045-Skin-L` | 完整 | 通过 `ods_sales.msu_id` 过滤渠道 |

**核心结论**：查询 Amazon 渠道库存时，从 `ods_sales` 按 `msu_id` 匹配 US/NA/CA/MX 渠道找出有销售的内码 SKU，再 JOIN `dwd_sku_daily_metrics` 获取库存和销售数据。⚠️ 不要直接使用 Amazon MSKU 作为 SKU 代码查询销售数据——它们无销售记录。

## 相关文件

- API 源码: `~/workspace/pmc-agents/pmc_template_api.py`
- 导入脚本: `~/workspace/pmc-agents/scripts/pmc_import.py`
- 管线验证报告: `~/workspace/pmc-agents/docs/管线验证报告.md`
- 数据链路盘点: `~/workspace/pmc-agents/docs/数据接入链路盘点.md`
- 模板规格书: `~/workspace/pmc-agents/docs/excel-template-spec.md`
- cosboard 表结构与 SKU 关联参考: `references/cosboard-schema.md`
- 维护抽检轮换记录: `references/maintenance-rotation.md`
- 亚马逊 MSKU 导入: `references/amazon-msku-import.md`
- 亚马逊数据架构: `references/amazon-data-architecture.md`
- DuckDB 远程访问: `references/duckdb-remote-access.md`
- DuckDB Web UI 脚本: `scripts/duckdb_webui.py`
- 增量回填操作手册: `references/backfill-procedure.md`
- Profile 分发与环境自举: `references/profile-distribution.md`
- 六大业务板块数据架构: `references/six-business-domains.md`
- 任务拆解方法论: `references/task-decomposition.md`
