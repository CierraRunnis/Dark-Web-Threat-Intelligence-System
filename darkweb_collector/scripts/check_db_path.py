#!/usr/bin/env python3
"""
检查数据库路径配置问题
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

print("=" * 80)
print("数据库路径配置检查")
print("=" * 80)
print()

# 检查环境变量
print("【环境变量】")
db_path_env = os.environ.get("DARKWEB_COLLECTOR_DB_PATH")
if db_path_env:
    print(f"  DARKWEB_COLLECTOR_DB_PATH = {db_path_env}")
else:
    print(f"  DARKWEB_COLLECTOR_DB_PATH = (未设置)")

print()

# 检查默认路径
print("【默认数据库路径】")
from darkweb_collector.runtime import default_db_path

default_path = default_db_path()
print(f"  {default_path}")
print(f"  存在: {default_path.exists()}")
if default_path.exists():
    size_mb = default_path.stat().st_size / (1024 * 1024)
    print(f"  大小: {size_mb:.2f} MB")

print()

# 查找所有可能的数据库文件
print("【查找所有collector.db文件】")
possible_locations = [
    ROOT / "data" / "collector.db",
    ROOT / "darkweb_collector" / "data" / "collector.db",
    Path("/var/anwang/bishe-codex-shujvqingxi/darkweb_collector/data/collector.db"),
    Path("/mnt/d/bishe/darkweb_collector/data/collector.db"),
    Path.home() / "darkweb_collector" / "data" / "collector.db",
]

found_dbs = []
for loc in possible_locations:
    if loc.exists():
        size_mb = loc.stat().st_size / (1024 * 1024)
        found_dbs.append((loc, size_mb))
        print(f"  ✅ {loc}")
        print(f"     大小: {size_mb:.2f} MB")

if not found_dbs:
    print("  ⚠️  未找到任何collector.db文件")

print()

# 如果找到多个数据库，检查哪个有数据
if len(found_dbs) > 1:
    print("【检查各数据库的数据量】")
    import sqlite3
    
    for db_path, size_mb in found_dbs:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM forum_details")
            forum_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM crawl_jobs")
            jobs_count = cursor.fetchone()[0]
            
            conn.close()
            
            print(f"  {db_path}")
            print(f"    forum_details: {forum_count} 条")
            print(f"    crawl_jobs: {jobs_count} 条")
            
            if forum_count > 0 or jobs_count > 0:
                print(f"    ⭐ 这个数据库有数据！")
        except Exception as e:
            print(f"  {db_path}")
            print(f"    ❌ 查询失败: {e}")
        print()

print("=" * 80)
print("诊断结论")
print("=" * 80)
print()

if len(found_dbs) > 1:
    print("⚠️  发现多个数据库文件！")
    print()
    print("这说明采集进程和API进程可能使用不同的数据库。")
    print()
    print("解决方案：")
    print("1. 找到有数据的数据库文件")
    print("2. 设置环境变量指向该文件:")
    print()
    for db_path, size_mb in found_dbs:
        if size_mb > 0.1:  # 大于100KB的可能有数据
            print(f"   export DARKWEB_COLLECTOR_DB_PATH='{db_path}'")
    print()
    print("3. 或者使用 prepare_runtime_db.py 脚本同步数据库")
elif len(found_dbs) == 1:
    print("✅ 只找到一个数据库文件")
    print()
    print("但数据库是空的，说明采集时数据没有写入。")
    print()
    print("可能原因：")
    print("1. 采集脚本使用了另一个数据库路径")
    print("2. 数据库写入权限问题")
    print("3. 采集过程中出现错误但未显示")
else:
    print("⚠️  未找到任何数据库文件")
    print()
    print("需要先初始化数据库")
