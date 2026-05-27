---
name: pmc-03-product-demand
version: 2.2.1
description: "场景03 v4：商品需求 — 加权日均销×库存天数做散点图诊断，五套独立坐标系，纯诊断不量化。板块1 事前预测，CSP场景。"
triggers:
  - "四象限"
  - "场景03"
  - "品销深度"
  - "商品需求"
  - "quadrant"
design_docs:
  prd: "~/workspace/pmc-agents/PMC九场景全景PRD_20260426_v2.md#场景03-商品需求四象限"
  wiki: "https://xcnk9flkicyx.feishu.cn/wiki/Itr2w4TF9imL76kCQ0ccBVN4nKg"
  tech_design: "~/workspace/pmc-agents/PMC九场景技术设计文档.md"
requires:
  - duckdb
  - ${PMC_DB_PATH:-~/pmc-data/pmc_ods.duckdb}
---

# 场景03：商品需求四象限

> 纯诊断——告诉你商品在哪、该往哪走，不告诉你具体该上几个新品。

## 数据源

| 表 | 字段 | 用途 |
|:---|:---|:---|
| `dwd_sku_daily_metrics` | sku_code, tier, product_name, weighted_daily, total_inventory, inventory_days | 加权日均销（X轴）+ 库存天数（Y轴）+ 货盘分级 + 商品名称 |

> v2.2.1：`dwd_sku_daily_metrics` 已包含 `tier` 和 `product_name` 列，无需 JOIN `ods_skus`。直接消费 DWD，避免 ODS VARCHAR CAST 陷阱。

## 加权日均销公式

```
加权日均销 = 昨日销量 × 50% + 近7天日均 × 30% + 近30天日均 × 20%
```

- 昨日销量 = SUM(daily_qty) WHERE sale_date = 最新快照日 - 1
- 近7天日均 = SUM(daily_qty WHERE sale_date >= today - 7) / 7
- 近30天日均 = SUM(daily_qty WHERE sale_date >= today - 30) / 30

> 权重设计：昨日最能反映当前动销状态（50%），7天平滑短期波动（30%），30天提供趋势基线（20%）。

## 五套独立坐标系

S/A/B/C/N 各一套，互不干扰。

| 维度 | 轴 | 含义 | 参考原点 |
|:---|:---|:---|:---|
| Y | 库存天数 | 有效库存 / 加权日均销 | 货盘内中位数 |
| X | 加权日均销 | 加权日均销（件/天） | 货盘内中位数 |

### 象限解读

```
      加权日均销 →
库  ┌────────────┬────────────┐
存  │ 低销高库存  │ 高销高库存  │
天  │ 关注去化    │ 关注补货    │
数  ├────────────┼────────────┤
↓  │ 低销低库存  │ 高销低库存  │
    │ 观察/淘汰   │ 断货风险    │
    └────────────┴────────────┘
       ref_X →
```

> **注意**：Y轴=库存天数（竖向），X轴=加权日均销（横向）。参考原点两轴均使用货盘内中位数（非最小值，最小值会导致四象限退化）。

## 计算逻辑

> 加权日均销已预计算在 `dwd_sku_daily_metrics` 表中（每日 07:30 自动刷新）。DWD 已包含 `tier`/`product_name`，无需 JOIN `ods_skus`。

```sql
WITH tier_stats AS (
    SELECT
        tier,
        MEDIAN(weighted_daily) AS ref_x,          -- X轴参考 = 货盘内加权日均销中位数
        MEDIAN(inventory_days) AS ref_y            -- Y轴参考 = 货盘内库存天数中位数
    FROM dwd_sku_daily_metrics
    WHERE tier IS NOT NULL AND tier != ''
      AND weighted_daily > 0 AND inventory_days > 0
    GROUP BY tier
)
SELECT
    sku_code, tier, product_name,
    weighted_daily, total_inventory, inventory_days,
    ts.ref_x, ts.ref_y,
    CASE
        WHEN weighted_daily >= ts.ref_x AND inventory_days >= ts.ref_y THEN '高销高库存'
        WHEN weighted_daily >= ts.ref_x AND inventory_days <  ts.ref_y THEN '高销低库存'
        WHEN weighted_daily <  ts.ref_x AND inventory_days >= ts.ref_y THEN '低销高库存'
        ELSE '低销低库存'
    END AS quadrant
FROM dwd_sku_daily_metrics d
JOIN tier_stats ts ON d.tier = ts.tier
WHERE d.weighted_daily > 0 AND d.inventory_days IS NOT NULL
ORDER BY d.tier, d.weighted_daily DESC
```

## 输出格式

```
场景03 商品需求四象限 @ {report_date}

═══════════════════════════════════════
📊 概览
  分析 SKU 数：{n}（有销有库存）
  象限分布：
    高销高库存：{n1}（{pct}%）─ 关注补货节奏
    高销低库存：{n2}（{pct}%）─ ⚠️ 断货风险
    低销高库存：{n3}（{pct}%）─ 关注去化
    低销低库存：{n4}（{pct}%）─ 观察/淘汰

═══════════════════════════════════════
📋 货盘级象限分布
| 货盘 | 高销高库存 | 高销低库存 | 低销高库存 | 低销低库存 | 总计 |
|------|-----------|-----------|-----------|-----------|------|
| S    | xx (xx%)  | xx (xx%)  | xx (xx%)  | xx (xx%)  | xx   |
| A    | ...       |           |           |           |      |
| B    | ...       |           |           |           |      |
| C    | ...       |           |           |           |      |
| N    | ...       |           |           |           |      |

═══════════════════════════════════════
🔴 高销低库存 SKU（断货风险，Top 15）
| # | SKU | 货盘 | 加权日均销 | 库存 | 库存天数 | 象限 |
|---|-----|------|------------|------|----------|------|

🟡 低销高库存 SKU（去化关注，Top 15）
| # | SKU | 货盘 | 加权日均销 | 库存 | 库存天数 | 象限 |
|---|-----|------|------------|------|----------|------|

💡 解释
  S/A级高销低库存密集 → 爆款/畅销品库存不足，建议优先补充
  C/N级低销高库存密集 → 长尾品积压，建议关注去化
```

## 注意事项

- 纯诊断，不做量化建议（如「应上10个新品」）
- 加权日均销=0或无库存 → 跳过该SKU
- **X轴 = 加权日均销**（0.5×昨日 + 0.3×近7天日均 + 0.2×近30天日均）
- **Y轴 = 库存天数**（有效库存 / 加权日均销）
- **X/Y轴参考原点均为货盘内中位数**（v2.1 修正：原用 MIN 导致阈值≈0，四象限退化为二象限）
- 象限名称：高销高库存 / 高销低库存 / 低销高库存 / 低销低库存
- 不依赖场景02输出，独立计算（避免链路断裂）
- N级 SKU 通常无销售记录，会被自动跳过（设计意图）

### 跨引擎兼容性

- **DuckDB 陷阱**：所有 ODS 列为 VARCHAR，必须 `CAST(... AS DOUBLE)` 后才能做数值运算和聚合
- **MEDIAN()**：DuckDB 1.4 不支持 `PERCENTILE_CONT`，使用 `MEDIAN()`；迁到 MySQL/PostgreSQL 时改为 `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ...)` 或子查询模拟
- **DWD 隔离**：算法逻辑已封装在 `dwd_sku_daily_metrics` 表（由 `pmc-data-pipeline` skill 自动刷新），场景 SQL 只做 SELECT+JOIN。迁引擎时改 DWD 写入脚本即可，场景 SQL 不动。

### ECharts 可视化部署

详见本 Skill 末尾「Web 部署策略」章节。FRP 配置 **已就绪**（`~/frp/frpc.toml` 含 `pmc-quadrant` 代理），直接启动 HTTP server + FRP 即可上线。

| 方案 | URL 格式 | 适用场景 |
|:---|:---|:---|
| **FRP 公网** | `https://{name}.frp.ifnotnull.xyz/xxx.html` | 外部访问，Traefik 泛域名 HTTPS 自动签发 |
| **Tailscale 内网** | `http://100.93.193.127:8899/xxx.html` | 内网直连，零延迟 |

## 已知陷阱

| 陷阱 | 现象 | 修复 |
|------|------|------|
| **X轴用 MIN** | 只出现 2 个象限（高销高库存 59% + 低销高库存 41%），高/低库存边界消失 | v2.1 改用 MEDIAN |
| **PERCENTILE_CONT** | DuckDB 报错 `Aggregate Function with name percentile_cont does not exist` | 改用 `MEDIAN()` |
| **负库存** | `inv_domestic + inv_purchase_onway < 0` 的 754 行污染 ref_x 为负数 | `GREATEST(total_inv, 0)` |
| **C级中位数为0** | C级大部分 SKU 日均销≈0，MEDIAN(avg_daily)=0，导致「低于中位数」的 SKU 为 0，全部归入高销象限 | 正常现象，C级多为滞销品 |
| **FRP 重复启动** | 新的 frpc 实例启动后无输出，与已有进程冲突 | 先 `ps aux \| grep frpc` 检查是否已在运行；已有则直接使用 |
| **HTTP server 绑定 127.0.0.1** | 仅本地可达，Tailscale 内网无法直连 | 改为 `--bind 0.0.0.0` 使 Tailscale `100.x.x.x` 可访问 |

## 自动化脚本

`scripts/scene03-echarts-generator.py` 是本场景的完整自动化生成器，一步完成数据查询、ECharts HTML 生成。直接运行：

```bash
python3 ~/.hermes/skills/pmc-skills/pmc-03-product-demand/scripts/scene03-echarts-generator.py
```

## ECharts 可视化（可选）

执行后通过 Python 直接生成交互式 HTML 图表（5 tab：全量 + S/A/B/C，X/Y 对数刻度，参考中位线标注，CDN 加载 ECharts 5.5）。生成模式见 `references/echarts-scatter-pattern.md`。

## Web 部署策略

场景03的输出形式为**交互式网页**（ECharts 散点图 + 四象限 + 图表切换），不做 PDF/Excel 静态度量交付。

### 1. 架构

```text
┌──────────────────────────────────────────────────┐
│  Python 脚本 → gen_scene03_echarts.html           │
│   （生成 ECharts 5.5 交互式 HTML）                  │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│  python3 -m http.server 8899                      │
│  （本地 HTTP server，绑定 127.0.0.1）               │
└───────────────────────┬──────────────────────────┘
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
┌──────────────────┐    ┌──────────────────────────┐
│  FRP 公网穿透      │    │  Tailscale 内网直连       │
│  pmc-quadrant     │    │  http://100.xx.xx.xx:8899│
│  frp.ifnotnull.xyz│    └──────────────────────────┘
└──────────────────┘
```

### 2. FRP 配置（已就绪 ✅）

`~/frp/frpc.toml` 已包含 `pmc-quadrant` 代理：

```toml
[[proxies]]
name = "pmc-quadrant"
type = "http"
localIP = "127.0.0.1"
localPort = 8899
subdomain = "pmc-quadrant"
```

- 域名：**`https://pmc-quadrant.frp.ifnotnull.xyz`**
- FRP 服务端：`ifnotnull.xyz:7000`，Traefik 自动签发 HTTPS
- 状态检查：`process(action='poll', session_id=...)` 查看 FRP 连接日志

### 3. 启动命令

```bash
# Step 1: 检查 FRP 是否已在运行
ps aux | grep frpc | grep -v grep

# Step 2a: 如果 FRP 已运行（有旧进程），直接启动 HTTP server
cd /tmp/hermes-pmc-output/html && python3 -m http.server 8899 --bind 0.0.0.0

# Step 2b: 如果 FRP 未运行，同时启动 FRP
~/frp/frpc -c ~/frp/frpc.toml
```

> 如果 `~/frp/frpc` 已在运行（可通过 `process(action='list')` 检查），直接跳过 Step 2。

### 4. 渠道交付

飞书/Telegram 渠道下直接发送 FRP 链接：

```python
def deliver_scene03_web(html_filename: str = "gen_scene03_echarts.html"):
    """启动 HTTP server + FRP，返回公网链接"""
    url = f"https://pmc-quadrant.frp.ifnotnull.xyz/{html_filename}"
    print(f"📊 商品需求四象限已上线")
    print(f"🌐 在线查看：{url}")
    print(f"💡 支持五套独立坐标系切换（全量 / S / A / B / C 货盘标签页）")
    print(f"   可缩放、悬停查看SKU名称、参考中位线标注")
```

### 5. 图表切换增强建议

当前 HTML 支持 **5 个 Tab 切换**（全量 + S/A/B/C 各一套独立坐标系），通过 JS `switchTab(tier)` 实现。建议继续增强：

| 增强项 | 实现方式 | 优先级 |
|:---|:---|:---:|
| 象限计数标注 | 每个 Tab 顶部显示「高销高库存 N 个 / 高销低库存 N 个 / 低销高库存 N 个 / 低销低库存 N 个」 | ⭐ 建议立即加上 |
| 搜索高亮 | 添加输入框，输入 SKU 编码后图表中高亮对应散点 | ⭐ 建议立即加上 |
| 象限切换动画 | 切换 Tab 时 enable `animation: true` + `animationDuration: 500` | ✅ 可选 |
| 导出截图 | 添加「导出为 PNG」按钮（`chart.getDataURL({type: 'png'})` + `<a download>`） | ✅ 可选 |
| 全屏查看 | 添加全屏按钮（`Fullscreen API`） | ✅ 可选 |
| 对数/线性切换 | 添加切换按钮，ECharts 两套 axis 配置互换 | 🔄 如用户需要 |
| 按货盘着色增强 | 全量图中 S/A/B/C/N 各用不同色调，不仅按象限分色 | 🔄 如用户需要 |

> 当前 `references/echarts-scatter-pattern.md` 已涵盖 Tab 切换、对数轴、中位参考线、缩放滑块等核心功能。如需实现增强项，直接修改 Python 生成脚本即可。
