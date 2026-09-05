#!/usr/bin/env python3
"""诊断运行时数据库中 normalized_intelligence_events 表的状态"""
import sqlite3
import os
import sys

def main():
    db_path = os.environ.get("DARKWEB_COLLECTOR_DB_PATH", "/root/.local/share/bishe/collector.db")
    print(f"数据库路径: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"ERROR: 数据库文件不存在!")
        sys.exit(1)
    
    print(f"文件大小: {os.path.getsize(db_path)} 字节")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 列出所有表
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    print(f"\n所有表: {tables}")
    
    # 检查关键表的记录数
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            print(f"  {table}: {count} 条记录")
        except Exception as e:
            print(f"  {table}: 查询失败 - {e}")
    
    # 特别检查 normalized_intelligence_events
    print(f"\n=== normalized_intelligence_events 详情 ===")
    if "normalized_intelligence_events" in tables:
        count = conn.execute("SELECT COUNT(*) FROM normalized_intelligence_events").fetchone()[0]
        print(f"记录数: {count}")
        if count > 0:
            row = conn.execute("SELECT * FROM normalized_intelligence_events LIMIT 1").fetchone()
            print(f"列名: {list(row.keys())}")
            # 统计 event_type
            types = conn.execute("SELECT event_type, COUNT(*) as cnt FROM normalized_intelligence_events GROUP BY event_type").fetchall()
            for t in types:
                print(f"  event_type='{t[0]}': {t[1]} 条")
        else:
            print("表为空!")
    else:
        print("表不存在!")
    
    # 检查 normalized_intelligence_cache_state
    print(f"\n=== normalized_intelligence_cache_state ===")
    if "normalized_intelligence_cache_state" in tables:
        rows = conn.execute("SELECT * FROM normalized_intelligence_cache_state").fetchall()
        print(f"记录数: {len(rows)}")
        for r in rows:
            print(f"  {dict(r)}")
    else:
        print("表不存在!")
    
    # 检查其他关键表
    for table_name in ["forum_details", "victims", "crawl_jobs", "vulnerability_events"]:
        if table_name in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
            print(f"\n{table_name}: {count} 条记录")
            if count > 0:
                row = conn.execute(f"SELECT * FROM [{table_name}] LIMIT 1").fetchone()
                print(f"  列名: {list(row.keys())}")
    
    conn.close()
    print("\n诊断完成")

if __name__ == "__main__":
    main()
