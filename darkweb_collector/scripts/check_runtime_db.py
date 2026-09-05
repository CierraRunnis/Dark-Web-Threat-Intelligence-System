#!/usr/bin/env python3
"""检查 runtime 数据库路径"""

import os
import sqlite3
from pathlib import Path

# 检查 ~/.local/share/bishe/collector.db
home = Path.home()
runtime_db = home / ".local" / "share" / "bishe" / "collector.db"
print(f"Runtime DB path: {runtime_db}")
print(f"  exists: {runtime_db.exists()}")

if runtime_db.exists():
    print(f"  size: {runtime_db.stat().st_size:,} bytes")
    conn = sqlite3.connect(str(runtime_db))
    conn.row_factory = sqlite3.Row
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"  表: {[t['name'] for t in tables]}")
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM [{t['name']}]").fetchone()[0]
            if cnt > 0:
                print(f"    {t['name']}: {cnt} 条 ✓")
            else:
                print(f"    {t['name']}: {cnt} 条")
        except Exception as e:
            print(f"    {t['name']}: 错误 {e}")
    conn.close()

# 检查 API 进程实际使用的环境变量
print(f"\nDARKWEB_DB_PATH: {os.environ.get('DARKWEB_DB_PATH', 'NOT SET')}")
print(f"DARKWEB_COLLECTOR_DB_PATH: {os.environ.get('DARKWEB_COLLECTOR_DB_PATH', 'NOT SET')}")
print(f"DARKWEB_COLLECTOR_SOURCE_DB_PATH: {os.environ.get('DARKWEB_COLLECTOR_SOURCE_DB_PATH', 'NOT SET')}")

# 检查进程命令行
try:
    import subprocess
    result = subprocess.run(["pgrep", "-a", "uvicorn"], capture_output=True, text=True)
    if result.stdout.strip():
        print(f"\nuvicorn 进程:\n{result.stdout.strip()}")
    else:
        print("\n未找到 uvicorn 进程")
    
    # 检查 /proc 中的环境变量
    result2 = subprocess.run(["pgrep", "-f", "uvicorn"], capture_output=True, text=True)
    pids = result2.stdout.strip().split()
    for pid in pids[:1]:
        env_path = f"/proc/{pid}/environ"
        if Path(env_path).exists():
            with open(env_path, 'r') as f:
                env_content = f.read()
            for var in env_content.split('\0'):
                if 'DARKWEB' in var or 'DB_PATH' in var:
                    print(f"  进程环境变量: {var}")
except Exception as e:
    print(f"\n进程检查失败: {e}")
