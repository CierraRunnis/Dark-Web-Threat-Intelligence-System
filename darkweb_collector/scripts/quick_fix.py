#!/usr/bin/env python3
"""
快速修复脚本：执行标准化情报处理
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

print("正在执行标准化情报处理...")
print()

try:
    from darkweb_collector.db import get_db_connection
    from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
    
    conn = get_db_connection()
    events = ensure_normalized_intelligence(conn, force=True)
    conn.close()
    
    print(f"✅ 标准化处理完成！")
    print(f"   生成事件数: {len(events)}")
    print()
    
    # 统计事件类型
    from collections import Counter
    event_types = Counter(e.get("event_type") for e in events)
    
    print("事件类型分布:")
    for event_type, count in event_types.items():
        print(f"  - {event_type}: {count}")
    
    print()
    print("下一步:")
    print("1. 重启API服务（如果正在运行）")
    print("2. 刷新前端页面")
    
except Exception as e:
    print(f"❌ 标准化处理失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
