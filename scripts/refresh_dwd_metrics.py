#!/usr/bin/env python3
"""
DWD 层刷新脚本：重建 dwd_sku_daily_metrics 表
用法: python3 refresh_dwd_metrics.py [--duckdb PATH]
- 幂等：每次全量 DROP + CREATE + INSERT
- 消费 ODS 层：ods_sales, ods_inventory_domestic, ods_skus
- 下游场景直接 JOIN 此表，无需各自计算日均销
- 向后兼容：旧 SELECT 语句仍可正常运行（只加列不删不改）
"""

import os
import duckdb
import sys
from datetime import datetime

DB_PATH = os.path.expanduser(os.environ.get("PMC_DB_PATH", "~/pmc-data/pmc_ods.duckdb"))

def refresh(db_path=DB_PATH):
    con = duckdb.connect(db_path)
    start = datetime.now()
    
    print(f"[{start.isoformat()}] 开始刷新 dwd_sku_daily_metrics ...")
    
    # 1. DROP old
    con.execute("DROP TABLE IF EXISTS dwd_sku_daily_metrics")
    
    # 2. CREATE (向后兼容：只加列不删不改原有列)
    con.execute("""
        CREATE TABLE dwd_sku_daily_metrics (
            sku_code        VARCHAR PRIMARY KEY,
            yesterday_qty   DOUBLE,
            avg_7d_qty      DOUBLE,
            avg_30d_qty     DOUBLE,
            weighted_daily  DOUBLE,
            total_inventory DOUBLE,
            inventory_days  DOUBLE,
            tier            VARCHAR,
            product_name    VARCHAR,
            sellable_inv    DOUBLE,
            onway_inv       DOUBLE,
            overseas_inv_available DOUBLE,
            overseas_inv_onway DOUBLE,
            overseas_ship_onway DOUBLE,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Check data freshness
    r = con.execute("SELECT MAX(sale_date) FROM ods_sales").fetchone()
    print(f"  ods_sales 最新日期: {r[0]}")
    r = con.execute("SELECT MAX(snapshot_time) FROM ods_inventory_domestic").fetchone()
    print(f"  ods_inventory 最新快照: {r[0]}")
    
    # 3. INSERT (全量刷新)
    con.execute("""
        INSERT INTO dwd_sku_daily_metrics
        WITH yesterday_sales AS (
            SELECT sku_code,
                SUM(CAST(daily_qty AS DOUBLE)) AS yesterday_qty
            FROM ods_sales
            WHERE CAST(sale_date AS DATE) = (SELECT MAX(CAST(sale_date AS DATE)) - 1 FROM ods_sales)
            GROUP BY sku_code
        ),
        avg_7d AS (
            SELECT sku_code,
                SUM(CAST(daily_qty AS DOUBLE)) / 7.0 AS avg_7d_qty
            FROM ods_sales
            WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 7
            GROUP BY sku_code
        ),
        avg_30d AS (
            SELECT sku_code,
                SUM(CAST(daily_qty AS DOUBLE)) / 30.0 AS avg_30d_qty
            FROM ods_sales
            WHERE CAST(sale_date AS DATE) >= CURRENT_DATE - 30
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
            SELECT sku_code,
                SUM(CAST(ship_qty AS DOUBLE)) AS ship_onway
            FROM ods_ship
            WHERE CAST(ship_date AS DATE) <= CURRENT_DATE
              AND CAST(expect_arrival AS DATE) > CURRENT_DATE
            GROUP BY sku_code
        )
        SELECT
            sk.sku_code,
            COALESCE(y.yesterday_qty, 0) AS yesterday_qty,
            COALESCE(a7.avg_7d_qty, 0) AS avg_7d_qty,
            COALESCE(a30.avg_30d_qty, 0) AS avg_30d_qty,
            ROUND(
                COALESCE(y.yesterday_qty, 0) * 0.5 +
                COALESCE(a7.avg_7d_qty, 0) * 0.3 +
                COALESCE(a30.avg_30d_qty, 0) * 0.2, 2
            ),
            COALESCE(i.total_inv, 0),
            CASE WHEN COALESCE(y.yesterday_qty, 0) * 0.5 +
                      COALESCE(a7.avg_7d_qty, 0) * 0.3 +
                      COALESCE(a30.avg_30d_qty, 0) * 0.2 > 0
                THEN ROUND(COALESCE(i.total_inv, 0) / (
                    COALESCE(y.yesterday_qty, 0) * 0.5 +
                    COALESCE(a7.avg_7d_qty, 0) * 0.3 +
                    COALESCE(a30.avg_30d_qty, 0) * 0.2
                ), 1)
            END,
            -- 新增列：tier / product_name / sellable_inv / onway_inv
            sk.tier,
            sk.product_name,
            COALESCE(i.sellable_inv, 0),
            COALESCE(i.onway_inv, 0),
            -- 新增海外库存列
            COALESCE(ovs.ovs_available, 0) AS overseas_inv_available,
            COALESCE(ovs.ovs_onway, 0) AS overseas_inv_onway,
            COALESCE(ship.ship_onway, 0) AS overseas_ship_onway,
            CURRENT_TIMESTAMP
        FROM ods_skus sk
        LEFT JOIN yesterday_sales y ON sk.sku_code = y.sku_code
        LEFT JOIN avg_7d a7 ON sk.sku_code = a7.sku_code
        LEFT JOIN avg_30d a30 ON sk.sku_code = a30.sku_code
        LEFT JOIN latest_inv i ON sk.sku_code = i.sku_code
        LEFT JOIN overseas_inv ovs ON sk.sku_code = ovs.sku_code
        LEFT JOIN overseas_ship ship ON sk.sku_code = ship.sku_code
    """)
    
    # 4. Verify
    stats = con.execute("""
        SELECT COUNT(*),
            COUNT(*) FILTER (WHERE weighted_daily > 0),
            COUNT(*) FILTER (WHERE weighted_daily > 0 AND inventory_days > 0)
        FROM dwd_sku_daily_metrics
    """).fetchone()
    
    # 5. 新列填充情况
    col_stats = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE tier IS NOT NULL AND tier != '') AS tier_filled,
            COUNT(*) FILTER (WHERE product_name IS NOT NULL AND product_name != '') AS name_filled,
            COUNT(*) FILTER (WHERE sellable_inv > 0) AS sellable_pos,
            COUNT(*) FILTER (WHERE onway_inv > 0) AS onway_pos,
            COUNT(*) FILTER (WHERE overseas_inv_available > 0) AS ovs_avail_pos,
            COUNT(*) FILTER (WHERE overseas_inv_onway > 0) AS ovs_onway_pos,
            COUNT(*) FILTER (WHERE overseas_ship_onway > 0) AS ship_onway_pos
        FROM dwd_sku_daily_metrics
    """).fetchone()
    
    elapsed = (datetime.now() - start).total_seconds()
    print(f"  OK: {stats[0]} SKU, {stats[1]} 有销, {stats[2]} 有销有库存")
    print(f"  新列: tier={col_stats[0]} 填充, product_name={col_stats[1]} 填充, sellable_inv>0={col_stats[2]}条, onway_inv>0={col_stats[3]}条, 海外可售>0={col_stats[4]}条, 海外在途>0={col_stats[5]}条, 海运在途>0={col_stats[6]}条")
    print(f"  耗时: {elapsed:.1f}s")
    
    con.close()
    return True

if __name__ == "__main__":
    db_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--duckdb" else DB_PATH
    refresh(db_path)
