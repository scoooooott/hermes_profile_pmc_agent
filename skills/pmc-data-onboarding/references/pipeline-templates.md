# 管道配置模板

> 阶段 D 确认接入方式后，按需加载对应模板。

## 四种接入模式

| 模式 | 适用场景 | 接入方式 |
|------|----------|----------|
| **API 直接拉** | 客户有可访问的数据库 | `pmc_template_api.py` 新增端点 → Excel → `pmc_import.py` |
| **CSV/Excel 导入** | 客户从 ERP 导出文件 | 写 `pmc_import.py` 兼容的导入逻辑 |
| **客户 API 对接** | 客户提供 RESTful API | 写 cron 定时拉取 → 转 Excel → 导入 |
| **手动维护** | 参数/映射等低频数据 | Excel 模板 + 客户定期更新 |

## DDL 模板（以 ods_sales 为例）

```sql
CREATE TABLE IF NOT EXISTS ods_sales (
    sku_code VARCHAR,
    sale_date VARCHAR,
    daily_qty VARCHAR,
    msu_id VARCHAR
);
```

实际 DDL 由 `bootstrap_pipeline.py` 统一创建，无需手动执行。此模板仅用于理解表结构。

## Python 导入函数模板

参考 `pmc_import.py` 的 `import_sheet` 函数：

```python
import duckdb, os

DB_PATH = os.path.expanduser("~/pmc-data/pmc_ods.duckdb")

def import_customer_sales(csv_path: str):
    """导入客户 CSV 格式的日销量数据 → ods_sales"""
    con = duckdb.connect(DB_PATH)

    # 1. 读 CSV（DuckDB 原生 read_csv，自动推断类型）
    rows = con.execute(f"""
        SELECT sku_code, sale_date,
               CAST(daily_qty AS INTEGER) AS daily_qty,
               msu_id
        FROM read_csv_auto('{csv_path}')
    """).fetchall()

    if not rows:
        print("⚠️ CSV 无数据，跳过")
        return

    # 2. UPSERT（按 sku_code + sale_date + msu_id 去重）
    con.executemany("""
        INSERT INTO ods_sales (sku_code, sale_date, daily_qty, msu_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (sku_code, sale_date, msu_id) DO UPDATE
        SET daily_qty = excluded.daily_qty
    """, rows)

    print(f"✅ 导入了 {len(rows)} 行 → ods_sales")
    con.close()
```

## 批量导入脚本框架

组装成 `import_customer_data.py`，按依赖顺序导入：

```python
#!/usr/bin/env python3
"""客户数据批量导入脚本"""
from import_customer_sales import import_customer_sales
from import_customer_skus import import_customer_skus
# ... 其他导入函数

def main():
    print("开始导入客户数据...")
    import_customer_skus("/path/to/skus.csv")         # 1. 商品档案（最先）
    import_customer_wmap("/path/to/wmap.csv")          # 2. 供需映射
    import_customer_inventory("/path/to/inventory.csv") # 3. 库存
    import_customer_sales("/path/to/sales.csv")         # 4. 日销量
    import_customer_po("/path/to/po.csv")               # 5. 采购
    import_customer_ship("/path/to/ship.csv")           # 6. 发货
    import_customer_params("/path/to/params.csv")       # 7. 参数
    print("\n✅ 全部导入完成")

if __name__ == "__main__":
    main()
```

## 导入顺序约束

由于表之间存在依赖关系（DWD 层从多张 ODS 表聚合），必须按序导入：

```
ods_skus → ods_wmap → ods_inventory_domestic/overseas
  → ods_sales → ods_po/ods_po_recv → ods_ship → ods_params
```
