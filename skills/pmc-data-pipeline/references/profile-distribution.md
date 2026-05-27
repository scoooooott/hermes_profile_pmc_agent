# PMC Profile 分发与环境自举

## 概述

PMC 数字人可以通过 Hermes 的 Profile Distribution 机制以 Git 仓库形式打包分发。目标环境一行命令安装，无需手动复制文件或迁移 DuckDB 数据库。

## 分发仓库结构

```
pmc-agent/                        ← Git 仓库
├── distribution.yaml             ← 分发清单（name 必填）
├── SOUL.md                       ← 人设 + 行为准则 + 业务知识
├── config.yaml                   ← 默认配置
├── .env.EXAMPLE                  ← 密钥模板
├── scripts/
│   ├── pmc_template_api.py       ← API 服务（依赖 pymysql, fastapi）
│   ├── pmc_import.py             ← ODS 导入（依赖 openpyxl, duckdb）
│   ├── refresh_dwd_metrics.py    ← DWD 刷新（依赖 duckdb）
│   ├── pmc_delivery.py           ← 交付模块
│   └── bootstrap_pipeline.py     ← 自举脚本（新增）
├── skills/
│   └── pmc-*/                    ← 11 个场景 Skill
└── knowledge/
    └── ...                       ← 参考文档
```

## 安装流程

```bash
# 1. 安装 Profile
hermes profile install github.com/<user>/pmc-agent

# 2. 填入密钥
cp .env.EXAMPLE .env  # 编辑填入 cosboard 和 LLM 凭据

# 3. 安装 Python 依赖
pip install pymysql openpyxl duckdb fastapi uvicorn

# 4. 启动 API 服务
cd ~/.hermes/profiles/pmc-agent/scripts
nohup python3 pmc_template_api.py > /tmp/pmc_api.log 2>&1 &

# 5. 运行自举脚本
python3 bootstrap_pipeline.py
```

## bootstrap_pipeline.py 执行工序

1. 环境检查：API 健康、cosboard 连通、依赖就绪
2. 创建 `~/pmc-data/{static,snapshot,incremental}/` 目录
3. 拉取 5 个 API 端点 → Excel 文件（skus ~10MB, inventory ~1.8MB, 其他 <100KB）
4. 调用 `pmc_import.py` → 创建 10 张 ODS 表
5. 调用 `refresh_dwd_metrics.py` → 创建 DWD 指标表
6. 验证：11 张表行数检查 + 唯一性
7. 可选：创建每日 cron job

**总耗时约 3 分钟**（空环境 → 全部场景可用）。

## 所有权模型（Hermes 分发机制）

| 类别 | 更新时行为 |
|:---|:---|
| SOUL.md, config.yaml, skills/, scripts/ | 从新克隆替换 |
| config.yaml | 默认保留安装者修改（`--force-config` 可重置） |
| memories/, sessions/, auth.json, .env | 永不触碰（硬性排除） |

## 与手工拷贝的区别

| | 手工拷贝 | Profile 分发 |
|:---|:---|:---|
| 安装 | 多步操作 | `hermes profile install` 一行 |
| 更新 | 重新手工复制 | `hermes profile update` 一行 |
| 多机同步 | 每台手动操作 | 统一从 Git 拉取 |
| 版本管理 | 无 | Git tag + commit SHA |

## API 服务持久化

macOS 使用 launchd plist 确保 API 在系统启动时自动拉起、挂了自动重启。

## 关键约束

- **不迁移 DuckDB 数据库文件**（41MB）— 自举脚本从零构建
- **不在 `scripts/` 中硬编码绝对路径**（`/Users/xxx/...`）— 统一使用 `os.path.expanduser("~/pmc-data/...")`
- **API 修改后必须重启进程**— FastAPI 常驻进程不自动热加载
