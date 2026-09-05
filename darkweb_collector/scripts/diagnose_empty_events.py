#!/usr/bin/env python3
"""诊断 normalized_events 为空的原因"""

import sys
sys.path.insert(0, "/var/anwang/bishe-codex-shujvqingxi/darkweb_collector/src")

from darkweb_collector.db import get_db_connection, list_vulnerability_records
from darkweb_collector.normalized_intelligence import load_normalized_events, ensure_normalized_intelligence

with get_db_connection() as conn:
    # 检查数据库表中的原始数据
    print("=== 数据库原始数据检查 ===")
    
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"数据库表: {[t['name'] for t in tables]}")
    
    for table_name in ['forum_details', 'victim_rows', 'crawl_jobs', 'normalized_intelligence']:
        try:
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()['cnt']
            print(f"  {table_name}: {count} 条记录")
        except Exception as e:
            print(f"  {table_name}: 表不存在或查询失败 - {e}")
    
    # 检查 normalized_intelligence 表
    print("\n=== normalized_intelligence 表检查 ===")
    try:
        ni_rows = conn.execute("SELECT COUNT(*) as cnt FROM normalized_intelligence").fetchone()['cnt']
        print(f"  总记录数: {ni_rows}")
        if ni_rows > 0:
            sample = conn.execute("SELECT event_id, event_type, title FROM normalized_intelligence LIMIT 3").fetchall()
            for row in sample:
                print(f"  样例: event_id={row['event_id']}, type={row['event_type']}, title={row['title'][:30]}")
    except Exception as e:
        print(f"  查询失败: {e}")
    
    # 尝试 ensure_normalized_intelligence
    print("\n=== 尝试 ensure_normalized_intelligence ===")
    try:
        ensure_normalized_intelligence(conn, force=False)
        print("  ✓ ensure_normalized_intelligence 完成")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
    
    # 再次检查
    try:
        ni_rows = conn.execute("SELECT COUNT(*) as cnt FROM normalized_intelligence").fetchone()['cnt']
        print(f"  ensure 后 normalized_intelligence: {ni_rows} 条记录")
    except Exception as e:
        print(f"  查询失败: {e}")
    
    # 检查 load_normalized_events
    print("\n=== load_normalized_events 检查 ===")
    events = load_normalized_events(conn)
    print(f"  返回事件数: {len(events)}")
    if events:
        event_types = set(e.get("event_type") for e in events)
        print(f"  事件类型: {event_types}")
        for et in event_types:
            count = sum(1 for e in events if e.get("event_type") == et)
            print(f"    {et}: {count} 条")
    
    # 检查 vulnerability_records
    print("\n=== vulnerability_records 检查 ===")
    vuln_rows = list_vulnerability_records(conn)
    print(f"  漏洞记录数: {len(vuln_rows)}")

print("\n=== 诊断完成 ===")
