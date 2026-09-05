#!/usr/bin/env python3
"""直接调用 build_intelligence_payload() 诊断超时问题"""
import os
import sys
import time
import traceback

# 确保使用正确的数据库
os.environ["DARKWEB_COLLECTOR_DB_PATH"] = "/root/.local/share/bishe/collector.db"

sys.path.insert(0, "/var/anwang/bishe-codex-shujvqingxi/darkweb_collector/src")

def main():
    print("开始诊断 build_intelligence_payload...")
    print(f"DB_PATH: {os.environ.get('DARKWEB_COLLECTOR_DB_PATH')}")
    
    # Step 1: 测试数据库连接
    print("\n=== Step 1: 测试数据库连接 ===")
    t0 = time.time()
    try:
        from darkweb_collector.db import get_db_connection
        with get_db_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM normalized_intelligence_events").fetchone()[0]
            print(f"  normalized_intelligence_events: {count} 条 ({time.time()-t0:.2f}s)")
    except Exception as e:
        print(f"  数据库连接失败: {e}")
        traceback.print_exc()
        return
    
    # Step 2: 测试 load_normalized_events
    print("\n=== Step 2: 测试 load_normalized_events ===")
    t1 = time.time()
    try:
        from darkweb_collector.normalized_intelligence import load_normalized_events
        with get_db_connection() as conn:
            events = load_normalized_events(conn)
            print(f"  返回 {len(events)} 条事件 ({time.time()-t1:.2f}s)")
            if events:
                print(f"  第一条: event_type={events[0].get('event_type')}, title={events[0].get('title', '')[:50]}")
    except Exception as e:
        print(f"  load_normalized_events 失败: {e}")
        traceback.print_exc()
        return
    
    # Step 3: 测试 monitoring_rules
    print("\n=== Step 3: 测试 build_monitoring_payload ===")
    t2 = time.time()
    try:
        import darkweb_collector.monitoring_rules as monitoring_rules_module
        with get_db_connection() as conn:
            events_copy = list(events)  # 使用上面加载的事件
            normalized_events, monitoring_payload = monitoring_rules_module.build_monitoring_payload(conn, events_copy)
            print(f"  返回 {len(normalized_events)} 条事件, monitoring_payload keys={list(monitoring_payload.keys())} ({time.time()-t2:.2f}s)")
    except Exception as e:
        print(f"  build_monitoring_payload 失败: {e}")
        traceback.print_exc()
        return
    
    # Step 4: 测试完整的 build_intelligence_payload
    print("\n=== Step 4: 测试 build_intelligence_payload ===")
    t3 = time.time()
    try:
        from darkweb_collector.api_data import build_intelligence_payload
        payload = build_intelligence_payload()
        elapsed = time.time() - t3
        print(f"  成功! 耗时 {elapsed:.2f}s")
        print(f"  payload keys: {list(payload.keys())[:10]}...")
        print(f"  ransomwareEvents: {len(payload.get('ransomwareEvents', []))} 条")
        print(f"  dataLeakEvents: {len(payload.get('dataLeakEvents', []))} 条")
        print(f"  vulnerabilityEvents: {len(payload.get('vulnerabilityEvents', []))} 条")
    except Exception as e:
        elapsed = time.time() - t3
        print(f"  build_intelligence_payload 失败 (耗时 {elapsed:.2f}s): {e}")
        traceback.print_exc()
    
    total = time.time() - t0
    print(f"\n总耗时: {total:.2f}s")

if __name__ == "__main__":
    main()
