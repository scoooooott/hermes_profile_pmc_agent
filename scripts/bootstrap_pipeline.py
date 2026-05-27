#!/usr/bin/env python3
"""PMC 数据引擎自举脚本 — 从零构建完整数据环境

用法: python3 bootstrap_pipeline.py [--db-path PATH]

功能:
  1. 创建 ~/pmc-data/ 目录结构
  2. 创建 DuckDB 数据库 + 全部 ODS/DWD 表结构（空壳）
  3. 写入默认参数（P1-P14）
  4. 运行 DWD 刷新（ODS 空时跳过）
  5. 输出就绪检查报告
"""

import os
import sys
import duckdb
from pathlib import Path

DB_PATH = os.path.expanduser(
    os.environ.get("PMC_DB_PATH", "~/pmc-data/pmc_ods.duckdb")
)
PMC_DIR = os.path.dirname(DB_PATH)


def create_directories():
    """创建数据目录结构"""
    dirs = ["static", "snapshot", "incremental"]
    for d in dirs:
        os.makedirs(os.path.join(PMC_DIR, d), exist_ok=True)
    print(f"✓ 数据目录: {PMC_DIR}")


def create_tables(con):
    """创建全部 ODS/DWD 表结构（空壳）"""
    ddl = [
        # ① 商品档案
        """CREATE TABLE IF NOT EXISTS ods_skus (
            sku_code VARCHAR PRIMARY KEY,
            spu_code VARCHAR,
            product_name VARCHAR,
            category VARCHAR,
            brand VARCHAR,
            launch_date VARCHAR,
            status VARCHAR,
            lifecycle VARCHAR,
            tier VARCHAR,
            production_cycle_days VARCHAR,
            manual_daily_sale_target VARCHAR,
            moq VARCHAR,
            lead_time VARCHAR,
            updated_at VARCHAR
        )""",
        """CREATE TABLE IF NOT EXISTS ods_cdm_skubom (
            psku VARCHAR,
            sku_id VARCHAR,
            rm_qty BIGINT
        )""",
        # ② 每日销量
        """CREATE TABLE IF NOT EXISTS ods_sales (
            sku_code VARCHAR,
            sale_date VARCHAR,
            daily_qty VARCHAR,
            msu_id VARCHAR
        )""",
        # ③ 库存快照
        """CREATE TABLE IF NOT EXISTS ods_inventory_domestic (
            sku_code VARCHAR,
            inv_domestic VARCHAR,
            inv_purchase_onway VARCHAR,
            snapshot_time VARCHAR
        )""",
        """CREATE TABLE IF NOT EXISTS ods_inventory_overseas (
            sku_code VARCHAR,
            shop VARCHAR,
            warehouse_code VARCHAR,
            inv_available VARCHAR,
            inv_onway VARCHAR,
            snapshot_time VARCHAR
        )""",
        # ④ 采购明细
        """CREATE TABLE IF NOT EXISTS ods_po (
            po_number VARCHAR,
            sku_code VARCHAR,
            order_date VARCHAR,
            order_qty VARCHAR,
            eta VARCHAR
        )""",
        """CREATE TABLE IF NOT EXISTS ods_po_recv (
            po_number VARCHAR,
            sku_code VARCHAR,
            receipt_date VARCHAR,
            receipt_qty VARCHAR,
            warehouse_id VARCHAR
        )""",
        # ⑤ 发货明细
        """CREATE TABLE IF NOT EXISTS ods_ship (
            tracking_number VARCHAR,
            sku_code VARCHAR,
            ship_date VARCHAR,
            ship_qty VARCHAR,
            dest_warehouse VARCHAR,
            expect_arrival VARCHAR,
            shop VARCHAR
        )""",
        """CREATE TABLE IF NOT EXISTS ods_ship_recv (
            tracking_number VARCHAR,
            sku_code VARCHAR,
            receipt_date VARCHAR,
            receipt_qty VARCHAR,
            warehouse_id VARCHAR
        )""",
        # ⑥ 供需映射
        """CREATE TABLE IF NOT EXISTS ods_wmap (
            sku_code VARCHAR,
            msu_id VARCHAR,
            warehouse_id VARCHAR,
            updated_at VARCHAR
        )""",
        # 规则参数
        """CREATE TABLE IF NOT EXISTS ods_params (
            param_no VARCHAR,
            param_id VARCHAR,
            param_name VARCHAR,
            param_default VARCHAR,
            param_type VARCHAR,
            param_note VARCHAR,
            sync_time TIMESTAMP
        )""",
    ]

    for stmt in ddl:
        con.execute(stmt)
    print(f"✓ 创建 {len(ddl)} 张 ODS 表结构")


def write_default_params(con):
    """写入默认 P1-P14 参数（仅当 ods_params 为空时）"""
    count = con.execute("SELECT COUNT(*) FROM ods_params").fetchone()[0]
    if count > 0:
        print(f"  ods_params 已有 {count} 条参数，跳过默认值写入")
        return

    defaults = [
        ("P1", "stock_sale_ratio", "存销比目标", '{"S":1.5,"A":1.2,"B":1.0,"C":0.8,"N":1.0}', "float", "安全库存覆盖月数"),
        ("P3", "top_n_sku_count", "重点关注SKU数量N", "10", "int", "场景01 TopN"),
        ("P5", "slow_moving_days", "呆滞天数阈值", '{"S":60,"A":75,"B":90,"C":105,"N":120}', "int", "场景06呆滞判定"),
        ("P7", "safety_stock_days", "安全库存天数", '{"S":30,"A":25,"B":20,"C":15,"N":20}', "int", "场景02/04膨胀基准"),
        ("P9", "replenish_trigger_threshold", "补货触发阈值", '{"S":15,"A":12,"B":10,"C":8,"N":10}', "int", "场景05海外库存天数"),
        ("P10", "target_overseas_inv_days", "目标海外库存天数", '{"S":30,"A":25,"B":20,"C":15,"N":20}', "int", "场景05补货目标"),
        ("P13", "promo_trigger_threshold", "促销触发阈值", '{"S":45,"A":55,"B":65,"C":75,"N":90}', "int", "场景06四区段预警"),
        ("P14", "reasonable_turnover_days", "合理周转天数", '{"S":30,"A":40,"B":50,"C":60,"N":75}', "int", "场景06正常/关注边界"),
    ]

    for row in defaults:
        con.execute(
            "INSERT INTO ods_params (param_no, param_id, param_name, param_default, param_type, param_note) VALUES (?, ?, ?, ?, ?, ?)",
            row,
        )
    print(f"✓ 写入 {len(defaults)} 条默认参数（P1/P3/P5/P7/P9/P10/P13/P14）")


def run_dwd_refresh(con):
    """运行 DWD 刷新（ODS 空时跳过）"""
    sku_count = con.execute("SELECT COUNT(*) FROM ods_skus").fetchone()[0]
    if sku_count == 0:
        print("⚠ ods_skus 为空，跳过 DWD 刷新（需先导入商品档案）")
        return

    # 内联 DWD 刷新逻辑（避免依赖外部脚本路径）
    con.execute("DROP TABLE IF EXISTS dwd_sku_daily_metrics")
    con.execute("""
        CREATE TABLE dwd_sku_daily_metrics (
            sku_code VARCHAR PRIMARY KEY,
            yesterday_qty DOUBLE,
            avg_7d_qty DOUBLE,
            avg_30d_qty DOUBLE,
            weighted_daily DOUBLE,
            total_inventory DOUBLE,
            inventory_days DOUBLE,
            tier VARCHAR,
            product_name VARCHAR,
            sellable_inv DOUBLE,
            onway_inv DOUBLE,
            overseas_inv_available DOUBLE,
            overseas_inv_onway DOUBLE,
            overseas_ship_onway DOUBLE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        INSERT INTO dwd_sku_daily_metrics
        WITH yesterday_sales AS (
            SELECT sku_code, SUM(CAST(daily_qty AS DOUBLE)) AS yesterday_qty
            FROM ods_sales
            WHERE CAST(sale_date AS DATE) = (SELECT MAX(CAST(sale_date AS DATE)) - 1 FROM ods_sales)
            GROUP BY sku_code
        ),
        avg_7d AS (
            SELECT sku_code, SUM(CAST(daily_qty AS DOUBLE)) / 7.0 AS avg_7d_qty
            FROM ods_sales WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 7
            GROUP BY sku_code
        ),
        avg_30d AS (
            SELECT sku_code, SUM(CAST(daily_qty AS DOUBLE)) / 30.0 AS avg_30d_qty
            FROM ods_sales WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 30
            GROUP BY sku_code
        ),
        latest_inv AS (
            SELECT sku_code,
                GREATEST(CAST(inv_domestic AS DOUBLE) + CAST(inv_purchase_onway AS DOUBLE), 0) AS total_inv,
                GREATEST(CAST(inv_domestic AS DOUBLE), 0) AS sellable_inv,
                GREATEST(CAST(inv_purchase_onway AS DOUBLE), 0) AS onway_inv
            FROM ods_inventory_domestic
            WHERE snapshot_time = (SELECT MAX(snapshot_time) FROM ods_inventory_domestic)
        ),
        overseas_inv AS (
            SELECT sku_code,
                SUM(CAST(inv_available AS DOUBLE)) AS ovs_available,
                SUM(CAST(inv_onway AS DOUBLE)) AS ovs_onway
            FROM ods_inventory_overseas
            WHERE snapshot_time = (SELECT MAX(snapshot_time) FROM ods_inventory_overseas)
            GROUP BY sku_code
        ),
        overseas_ship AS (
            SELECT sku_code, SUM(CAST(ship_qty AS DOUBLE)) AS ship_onway
            FROM ods_ship
            WHERE CAST(ship_date AS DATE) <= CURRENT_DATE
              AND CAST(expect_arrival AS DATE) > CURRENT_DATE
            GROUP BY sku_code
        )
        SELECT
            sk.sku_code,
            COALESCE(y.yesterday_qty, 0),
            COALESCE(a7.avg_7d_qty, 0),
            COALESCE(a30.avg_30d_qty, 0),
            ROUND(COALESCE(y.yesterday_qty, 0) * 0.5 + COALESCE(a7.avg_7d_qty, 0) * 0.3 + COALESCE(a30.avg_30d_qty, 0) * 0.2, 2),
            COALESCE(i.total_inv, 0),
            CASE WHEN COALESCE(y.yesterday_qty, 0) * 0.5 + COALESCE(a7.avg_7d_qty, 0) * 0.3 + COALESCE(a30.avg_30d_qty, 0) * 0.2 > 0
                THEN ROUND(COALESCE(i.total_inv, 0) / (COALESCE(y.yesterday_qty, 0) * 0.5 + COALESCE(a7.avg_7d_qty, 0) * 0.3 + COALESCE(a30.avg_30d_qty, 0) * 0.2), 1)
            END,
            sk.tier, sk.product_name,
            COALESCE(i.sellable_inv, 0), COALESCE(i.onway_inv, 0),
            COALESCE(ovs.ovs_available, 0), COALESCE(ovs.ovs_onway, 0),
            COALESCE(ship.ship_onway, 0),
            CURRENT_TIMESTAMP
        FROM ods_skus sk
        LEFT JOIN yesterday_sales y ON sk.sku_code = y.sku_code
        LEFT JOIN avg_7d a7 ON sk.sku_code = a7.sku_code
        LEFT JOIN avg_30d a30 ON sk.sku_code = a30.sku_code
        LEFT JOIN latest_inv i ON sk.sku_code = i.sku_code
        LEFT JOIN overseas_inv ovs ON sk.sku_code = ovs.sku_code
        LEFT JOIN overseas_ship ship ON sk.sku_code = ship.sku_code
    """)

    dwd_count = con.execute("SELECT COUNT(*) FROM dwd_sku_daily_metrics").fetchone()[0]
    print(f"✓ DWD 刷新完成: {dwd_count} SKU")


def verify(con):
    """输出就绪检查报告"""
    tables = {
        "ods_skus": ("商品档案", True),
        "ods_cdm_skubom": ("SKU编码映射", False),
        "ods_sales": ("每日销量", True),
        "ods_inventory_domestic": ("国内库存", True),
        "ods_inventory_overseas": ("海外库存", True),
        "ods_po": ("采购明细", False),
        "ods_po_recv": ("采购收货", False),
        "ods_ship": ("发货明细", False),
        "ods_wmap": ("供需映射", False),
        "ods_params": ("规则参数", True),
        "dwd_sku_daily_metrics": ("DWD指标", True),
    }

    print("\n" + "=" * 50)
    print("PMC 数据引擎就绪检查")
    print("=" * 50)

    ready_scenes = set(range(10))  # 假设全部可用
    for table, (desc, required) in tables.items():
        try:
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            status = "✅" if count > 0 else ("❌" if required else "⚠️ ")
            print(f"  {status} {table:30s} {count:>8,} 行  ← {desc}")
            if count == 0 and required:
                # 标记依赖此表的场景为不可用
                if table == "ods_inventory_overseas" or table == "ods_ship":
                    ready_scenes.discard(5)
                if table == "ods_po":
                    ready_scenes.discard(4)
                    ready_scenes.discard(9)
        except Exception as e:
            print(f"  ❌ {table:30s} 不存在  ← {desc}")

    print("=" * 50)
    available = sorted(ready_scenes)
    unavailable = sorted(set(range(10)) - ready_scenes)
    print(f"  可用场景: {', '.join(f'{s:02d}' for s in available)}")
    if unavailable:
        print(f"  暂不可用: {', '.join(f'{s:02d}' for s in unavailable)}（缺少必需数据）")
    print("=" * 50)


def main():
    db_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--db-path" else DB_PATH

    print(f"PMC 数据引擎自举")
    print(f"  数据库: {db_path}")
    print()

    create_directories()

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = duckdb.connect(db_path)

    create_tables(con)
    write_default_params(con)
    run_dwd_refresh(con)
    verify(con)

    con.close()
    print(f"\n✅ 自举完成。PMC 数字人可执行已就绪的场景。")


if __name__ == "__main__":
    main()
