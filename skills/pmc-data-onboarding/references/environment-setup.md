# 环境初始化 — 详细步骤

> 仅在 `bootstrap_pipeline.py` 执行失败或环境异常时按需加载。正常流程下运行 bootstrap 即可完成全部初始化。

## Step 0：检查并安装 Python 依赖

```bash
python3 -c "import duckdb, pandas, openpyxl; print('OK')"
```

若报错，执行：

```bash
pip3 install duckdb pandas openpyxl
# PDF 渲染需要 playwright（可选，按需安装）
pip3 install playwright
playwright install chromium
```

| 库 | 用途 | 缺失后果 |
|---|---|---|
| `duckdb` | 数据引擎核心 | bootstrap 建库失败 |
| `pandas` | DataFrame 操作 | DWD 刷新 / 场景 SQL 结果处理失败 |
| `openpyxl` | Excel 生成 | PMC 报告导出失败 |
| `playwright` | PDF 渲染 | PDF 报告生成失败 |

## Step 1：检查系统工具

| 依赖 | 检查方法 | 安装方式 |
|------|---------|---------|
| `python3` | `python3 --version` | macOS 自带；如缺失用 `brew install python` |
| `duckdb` CLI | `duckdb --version` | `brew install duckdb` |

## Step 2：运行 bootstrap

```bash
cd ~/workspace/pmc-agent && python3 scripts/bootstrap_pipeline.py
```

成功输出：
```
✓ 数据目录: ~/pmc-data
✓ DuckDB 已创建: ~/pmc-data/pmc_ods.duckdb
✓ ODS 表: 10/10 创建
✓ DWD 视图: 2/2 创建
✓ 默认参数: P1-P14 已写入
```

## Step 3：验证 DuckDB

```bash
duckdb ~/pmc-data/pmc_ods.duckdb -c "
SELECT table_name FROM information_schema.tables
WHERE table_schema='main' AND table_name LIKE 'ods_%'
ORDER BY table_name;"
```

| 返回结果 | 判定 | 处理 |
|----------|------|------|
| 文件不存在 或 无法连接 | DuckDB 未创建 | 重跑 Step 2 |
| 表数量 = 0 | 空库 | 重跑 Step 2 |
| 表数量 >= 10 | 已就绪 | ✅ |
| 表数量 1~8 | 部分就绪 | DROP 所有表后重跑 Step 2 |

## Step 4：检查 API（仅管道模式）

如果客户需要通过 API 管线对接：

```bash
curl -s http://localhost:8765/ | python3 -m json.tool
```

若未启动：
```bash
cd ~/workspace/pmc-agent && nohup python3 scripts/pmc_template_api.py &
```

CSV/Excel 导入模式跳过此步。
