#!/usr/bin/env python3
"""
检查数据库状态
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.chdir(ROOT)

from darkweb_collector.db import get_db_connection

print("=" * 80)
print("数据库状态检查")
print("=" * 80)
print()

conn = get_db_connection()
cursor = conn.cursor()

# 检查各表记录数
tables = [
    ("forum_topics", "论坛主题"),
    ("forum_details", "论坛详情"),
    ("forum_victims", "论坛受害者"),
    ("victims", "受害者记录"),
    ("victim_details", "受害者详情"),
    ("ransomware_live_victims", "ransomware.live受害者"),
    ("vulnerability_records", "漏洞记录"),
    ("normalized_intelligence_events", "标准化情报事件"),
    ("crawl_jobs", "采集任务"),
]

print("表记录统计:")
for table_name, display_name in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        status = "✅" if count > 0 else "⚠️ "
        print(f"  {status} {display_name:30s} {count:6d} 条")
    except Exception as e:
        print(f"  ❌ {display_name:30s} 查询失败: {e}")

print()
print("=" * 80)
print("最近的采集任务:")
print("=" * 80)

try:
    cursor.execute("""
        SELECT site_name, job_type, status, 
               datetime(finished_at, 'localtime') as finished_local
        FROM crawl_jobs
        ORDER BY finished_at DESC
        LIMIT 10
    """)
    jobs = cursor.fetchall()
    if jobs:
        for site, job_type, status, finished in jobs:
            print(f"  {site:20s} | {job_type:10s} | {status:10s} | {finished}")
    else:
        print("  ⚠️  没有采集任务记录")
except Exception as e:
    print(f"  ❌ 查询失败: {e}")

print()
print("=" * 80)
print("论坛详情样本（最近5条）:")
print("=" * 80)

try:
    cursor.execute("""
        SELECT site_name, section, title, 
               datetime(fetched_at, 'localtime') as fetched_local
        FROM forum_details
        ORDER BY fetched_at DESC
        LIMIT 5
    """)
    details = cursor.fetchall()
    if details:
        for site, section, title, fetched in details:
            title_short = (title[:50] + '...') if len(title) > 50 else title
            print(f"  {site} | {section} | {title_short}")
            print(f"    采集时间: {fetched}")
    else:
        print("  ⚠️  没有论坛详情记录")
except Exception as e:
    print(f"  ❌ 查询失败: {e}")

conn.close()

print()
print("=" * 80)
print("诊断结论:")
print("=" * 80)
print()
print("如果所有表都为空，说明需要先运行采集任务:")
print("  python scripts/crawl.py run-site --site chaos --once")
print("  python scripts/crawl.py run-site --site dragonforceblog --once")
print()
