# cosboard 数据管线参考实现

> 本目录包含一个针对特定客户（cosboard MySQL 数据源）的数据管线实现，作为接入范例参考。
> **不打包进 Profile 分发**——仅在 GitHub 仓库中可见，供接入方了解"一个完整的接入实现在做什么"。

## 架构

```
cosboard MySQL (8.134.131.227:3630)
  ↓ SELECT only
pmc_template_api.py (localhost:8765, FastAPI)
  ↓ 5 个端点 → 5 个 Excel 文件
~/pmc-data/{static,snapshot,incremental}/
  ↓ pmc_import.py
DuckDB ODS (10 张表)
  ↓ refresh_dwd_metrics.py
DWD (dwd_sku_daily_metrics)
```

## 文件说明

| 文件 | 作用 |
|:---|:---|
| `pmc_template_api.py` | FastAPI 服务，5 个端点从 cosboard 拉数据生成 Excel |
| `pmc_import.py` | 读 Excel 文件导入 DuckDB，支持全量覆盖和增量 UPSERT |

## 端点说明

| 端点 | 输出 | 加载模式 |
|:---|:---|:---|
| `/template/skus` | 商品主数据.xlsx | 全量覆盖 |
| `/template/params` | 参数配置.xlsx | 全量覆盖 |
| `/template/msu-map` | SKU-MSU映射.xlsx | 全量覆盖 |
| `/template/inventory` | 库存快照.xlsx（国内+海外） | 全量覆盖 |
| `/template/daily-data` | 日增量数据.xlsx（5 Sheet） | 增量 UPSERT |

## 接入方参考要点

1. **编码归一化在 API 层完成**：`v_cdm_skubom` 视图的 JOIN + `rm_qty` 乘法在 SQL 查询中执行，Excel 中已经是归一化后的 SKU
2. **增量窗口 = 上一个自然日**：管线每天只拉 `curdate()-1`，N 天没跑中间数据需手动回填
3. **库存快照是全量覆盖**：每次下载覆盖旧文件，DuckDB 用 `MAX(snapshot_time)` 取最新
4. **超时处理**：msu-map 端点常超时 120s+，允许用旧文件；库存快照 `--max-time 300`
5. **API 修改后必须重启**：FastAPI 常驻进程，修改代码后需 kill + 重启才生效
