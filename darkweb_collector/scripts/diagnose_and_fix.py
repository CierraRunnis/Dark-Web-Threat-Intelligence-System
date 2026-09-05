#!/usr/bin/env python3
"""
前端数据加载问题诊断和修复脚本
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 添加src到路径
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.chdir(ROOT)

print("=" * 80)
print("前端数据加载问题诊断和修复工具")
print("=" * 80)
print()

# 步骤1: 检查数据库文件
print("【步骤1】检查数据库文件...")
from darkweb_collector.runtime import default_db_path

db_path = default_db_path()
print(f"  数据库路径: {db_path}")

if db_path.exists():
    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ 数据库文件存在，大小: {size_mb:.2f} MB")
else:
    print(f"  ❌ 数据库文件不存在！")
    print(f"  正在初始化数据库...")
    from darkweb_collector.db import get_db_connection
    conn = get_db_connection()
    conn.close()
    print(f"  ✅ 数据库初始化完成")

print()

# 步骤2: 检查数据库表数据
print("【步骤2】检查数据库表数据...")
from darkweb_collector.db import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

# 检查各表记录数
tables_to_check = [
    ("forum_topics", "论坛主题"),
    ("forum_details", "论坛详情"),
    ("victims", "受害者记录"),
    ("vulnerability_records", "漏洞记录"),
    ("normalized_intelligence_events", "标准化情报事件"),
    ("crawl_jobs", "采集任务"),
]

table_counts = {}
for table_name, display_name in tables_to_check:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        table_counts[table_name] = count
        status = "✅" if count > 0 else "⚠️"
        print(f"  {status} {display_name} ({table_name}): {count} 条记录")
    except Exception as e:
        print(f"  ❌ {display_name} ({table_name}): 查询失败 - {e}")
        table_counts[table_name] = 0

print()

# 步骤3: 检查最近的采集任务
print("【步骤3】检查最近的采集任务...")
try:
    cursor.execute("""
        SELECT site_name, job_type, status, finished_at
        FROM crawl_jobs
        ORDER BY finished_at DESC
        LIMIT 5
    """)
    jobs = cursor.fetchall()
    if jobs:
        print("  最近5次任务:")
        for site, job_type, status, finished_at in jobs:
            print(f"    - {site} | {job_type} | {status} | {finished_at}")
    else:
        print("  ⚠️ 没有采集任务记录")
except Exception as e:
    print(f"  ❌ 查询失败: {e}")

conn.close()
print()

# 步骤4: 诊断问题
print("【步骤4】问题诊断...")
issues = []

if table_counts.get("forum_details", 0) == 0 and table_counts.get("victims", 0) == 0:
    issues.append("数据未入库：forum_details 和 victims 表都为空")
    
if table_counts.get("normalized_intelligence_events", 0) == 0:
    if table_counts.get("forum_details", 0) > 0 or table_counts.get("victims", 0) > 0:
        issues.append("标准化处理未执行：有原始数据但 normalized_intelligence_events 为空")
    else:
        issues.append("无原始数据：需要先运行采集任务")

if table_counts.get("crawl_jobs", 0) == 0:
    issues.append("无采集任务记录：可能从未运行过采集")

if issues:
    print("  发现以下问题:")
    for i, issue in enumerate(issues, 1):
        print(f"    {i}. {issue}")
else:
    print("  ✅ 未发现明显问题")

print()

# 步骤5: 执行修复
print("【步骤5】执行修复...")

# 5.1 如果有原始数据但没有标准化数据，执行标准化
if table_counts.get("normalized_intelligence_events", 0) == 0:
    if table_counts.get("forum_details", 0) > 0 or table_counts.get("victims", 0) > 0:
        print("  正在执行标准化处理...")
        try:
            from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
            conn = get_db_connection()
            events = ensure_normalized_intelligence(conn, force=True)
            conn.close()
            print(f"  ✅ 标准化处理完成，生成 {len(events)} 个事件")
        except Exception as e:
            print(f"  ❌ 标准化处理失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("  ⚠️ 没有原始数据，无法执行标准化处理")
        print("  建议先运行采集任务:")
        print("    python scripts/crawl.py run-site --site chaos --once")
else:
    print(f"  ✅ 已有 {table_counts['normalized_intelligence_events']} 个标准化事件，跳过")

print()

# 步骤6: 验证修复结果
print("【步骤6】验证修复结果...")
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM normalized_intelligence_events")
final_count = cursor.fetchone()[0]

if final_count > 0:
    print(f"  ✅ 标准化事件数量: {final_count}")
    
    # 显示事件类型分布
    cursor.execute("""
        SELECT event_type, COUNT(*) as count
        FROM normalized_intelligence_events
        GROUP BY event_type
    """)
    event_types = cursor.fetchall()
    print("  事件类型分布:")
    for event_type, count in event_types:
        print(f"    - {event_type}: {count}")
else:
    print(f"  ⚠️ 标准化事件仍为0")

conn.close()
print()

# 步骤7: 测试API
print("【步骤7】测试API数据生成...")
try:
    from darkweb_collector.api_data import build_intelligence_payload
    payload = build_intelligence_payload()
    
    data_leak_count = len(payload.get("dataLeakEvents", []))
    ransomware_count = len(payload.get("ransomwareEvents", []))
    vulnerability_count = len(payload.get("vulnerabilityEvents", []))
    
    print(f"  数据泄露事件: {data_leak_count}")
    print(f"  勒索事件: {ransomware_count}")
    print(f"  漏洞事件: {vulnerability_count}")
    
    if data_leak_count > 0 or ransomware_count > 0:
        print("  ✅ API数据生成正常")
    else:
        print("  ⚠️ API返回的事件数据为空")
except Exception as e:
    print(f"  ❌ API数据生成失败: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("诊断和修复完成")
print("=" * 80)
print()
print("下一步操作:")
print("1. 如果标准化事件数量 > 0，重启API服务:")
print("   python scripts/serve_api.py")
print()
print("2. 如果标准化事件数量 = 0，先运行采集:")
print("   python scripts/crawl.py run-site --site chaos --once")
print("   python scripts/crawl.py run-site --site dragonforceblog --once")
print("   然后重新运行本脚本")
print()
print("3. 刷新前端页面查看数据是否显示")
