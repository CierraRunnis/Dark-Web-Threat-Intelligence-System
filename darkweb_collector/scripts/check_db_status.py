#!/usr/bin/env python3
"""检查数据库路径和数据状态"""

import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, "/var/anwang/bishe-codex-shujvqingxi/darkweb_collector/src")

from darkweb_collector.runtime import default_db_path, project_root

# 检查各种可能的数据库路径
print("=== 数据库路径检查 ===")

# 默认路径
db_path = default_db_path()
print(f"default_db_path(): {db_path}")
print(f"  exists: {db_path.exists()}")

# 源数据库路径
source_db = Path(os.environ.get("DARKWEB_COLLECTOR_SOURCE_DB_PATH", project_root() / "data" / "collector.db")).expanduser()
print(f"\nsource_db: {source_db}")
print(f"  exists: {source_db.exists()}")

# project_root
pr = project_root()
print(f"\nproject_root(): {pr}")

# 检查环境变量
print(f"\nDARKWEB_DB_PATH env: {os.environ.get('DARKWEB_DB_PATH', 'NOT SET')}")
print(f"DARKWEB_COLLECTOR_SOURCE_DB_PATH env: {os.environ.get('DARKWEB_COLLECTOR_SOURCE_DB_PATH', 'NOT SET')}")

# 列出 data 目录下的文件
data_dir = pr / "data"
print(f"\n=== data 目录内容 ({data_dir}) ===")
if data_dir.exists():
    for f in sorted(data_dir.iterdir()):
        size = f.stat().st_size if f.is_file() else 0
        print(f"  {f.name}: {size:,} bytes")
else:
    print("  data 目录不存在")

# 直接检查源数据库的内容
if source_db.exists():
    print(f"\n=== 源数据库 ({source_db}) 内容检查 ===")
    conn = sqlite3.connect(str(source_db))
    conn.row_factory = sqlite3.Row
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"表: {[t['name'] for t in tables]}")
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM [{t['name']}]").fetchone()['cnt']
            print(f"  {t['name']}: {cnt} 条")
        except:
            pass
    conn.close()

# 如果默认路径不同，也检查它
if str(db_path) != str(source_db) and db_path.exists():
    print(f"\n=== 默认数据库 ({db_path}) 内容检查 ===")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"表: {[t['name'] for t in tables]}")
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM [{t['name']}]").fetchone()['cnt']
            print(f"  {t['name']}: {cnt} 条")
        except:
            pass
    conn.close()
