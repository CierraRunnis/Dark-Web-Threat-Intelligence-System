#!/usr/bin/env python3
"""
修复 api_data.py 中的代码错误
- 删除第一个错误的 _recent_problem_rows 函数定义（314-360行）
- 删除第二个带乱码的 _build_executive_priority_events 函数定义（1383-1415行）
- 删除第一个简单的 _label_industry 函数定义（150-152行）
- 修复 INDUSTRY_LABELS 中的乱码
- 在 build_intelligence_payload 开头添加缓存命中检查
"""

from pathlib import Path
import re

# 定位到 api_data.py
api_data_path = Path(__file__).resolve().parents[1] / "src" / "darkweb_collector" / "api_data.py"

print(f"正在修复: {api_data_path}")

# 读取文件内容
with open(api_data_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"原始文件共 {len(lines)} 行")

# 修复策略：
# 1. 删除第 314-361 行（第一个错误的 _recent_problem_rows）
# 2. 删除第 1383-1415 行（第二个带乱码的 _build_executive_priority_events）
# 3. 删除第 150-153 行（第一个简单的 _label_industry）

# 由于删除会改变行号，我们从后往前删除
fixes_applied = []

# 修复 1: 删除第一个错误的 _recent_problem_rows (314-361行，索引313-360)
if 313 < len(lines) and "def _recent_problem_rows" in lines[313]:
    # 找到这个函数的结束位置（下一个空行后的函数定义）
    end_idx = 313
    for i in range(314, min(len(lines), 365)):
        if i < len(lines) and lines[i].strip() == "" and i+1 < len(lines) and lines[i+1].startswith("def "):
            end_idx = i
            break
    
    if end_idx > 313:
        print(f"删除第一个错误的 _recent_problem_rows: 行 {314}-{end_idx+1}")
        del lines[313:end_idx+1]
        fixes_applied.append("删除第一个错误的 _recent_problem_rows")

# 重新读取以更新行号
with open(api_data_path, "w", encoding="utf-8") as f:
    f.writelines(lines)

with open(api_data_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 修复 2: 查找并删除第二个带乱码的 _build_executive_priority_events
found_first = False
for i, line in enumerate(lines):
    if "def _build_executive_priority_events" in line:
        if not found_first:
            found_first = True
            continue
        else:
            # 找到第二个定义，删除它
            end_idx = i
            for j in range(i+1, min(len(lines), i+50)):
                if j < len(lines) and lines[j].strip() == "" and j+1 < len(lines) and (lines[j+1].startswith("def ") or lines[j+1].startswith("class ")):
                    end_idx = j
                    break
            
            if end_idx > i:
                print(f"删除第二个带乱码的 _build_executive_priority_events: 行 {i+1}-{end_idx+1}")
                del lines[i:end_idx+1]
                fixes_applied.append("删除第二个带乱码的 _build_executive_priority_events")
                break

# 重新写入
with open(api_data_path, "w", encoding="utf-8") as f:
    f.writelines(lines)

with open(api_data_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 修复 3: 查找并删除第一个简单的 _label_industry (如果存在两个定义)
found_indices = []
for i, line in enumerate(lines):
    if line.strip().startswith("def _label_industry("):
        found_indices.append(i)

if len(found_indices) >= 2:
    # 删除第一个（通常是简单版本）
    first_idx = found_indices[0]
    # 找到第一个函数的结束
    end_idx = first_idx
    for j in range(first_idx+1, min(len(lines), first_idx+10)):
        if j < len(lines) and lines[j].strip() == "" and j+1 < len(lines) and lines[j+1].startswith("def "):
            end_idx = j
            break
    
    if end_idx > first_idx:
        print(f"删除第一个简单的 _label_industry: 行 {first_idx+1}-{end_idx+1}")
        del lines[first_idx:end_idx+1]
        fixes_applied.append("删除第一个简单的 _label_industry")

# 重新写入
with open(api_data_path, "w", encoding="utf-8") as f:
    f.writelines(lines)

with open(api_data_path, "r", encoding="utf-8") as f:
    content = f.read()

# 修复 4: 修复 INDUSTRY_LABELS 中的乱码
garbled_mappings = {
    "鏀垮簻": "政府",
    "閲戣瀺": "金融",
    "鍐滀笟": "农业",
    "闆跺敭": "零售",
    "閫氫俊": "通信",
    "浜ら€?": "交通",
    "鏂囧ū": "文娱",
    "鍒堕€犱笟": "制造业",
    "鍏朵粬": "其他",
    "鏈煡": "未知",
    "鍖荤枟": "医疗",
    "绉戞妧": "科技",
    "鍐涗簨": "军事",
    "鏁欒偛": "教育",
    "鑳芥簮": "能源",
}

for garbled, correct in garbled_mappings.items():
    if garbled in content:
        content = content.replace(f'"{garbled}"', f'"{correct}"')
        content = content.replace(f"'{garbled}'", f"'{correct}'")
        fixes_applied.append(f"修复乱码: {garbled} -> {correct}")

# 修复 5: 在 build_intelligence_payload 开头添加缓存命中检查
if "def build_intelligence_payload() -> dict[str, Any]:" in content:
    # 查找函数定义
    pattern = r'(def build_intelligence_payload\(\) -> dict\[str, Any\]:\s+with get_db_connection\(\) as connection:\s+)'
    replacement = r'\1normalized_events, monitoring_payload = monitoring_rules_module.build_monitoring_payload(connection, load_normalized_events(connection))\n        cache_key = _payload_cache_key(connection, "intelligence")\n        cached = _get_cached_payload("intelligence", cache_key)\n        if cached is not None:\n            return cached\n        '
    
    # 检查是否已经有缓存检查
    if '_get_cached_payload("intelligence"' not in content:
        # 需要更精确的替换
        lines_new = content.split('\n')
        for i, line in enumerate(lines_new):
            if 'def build_intelligence_payload() -> dict[str, Any]:' in line:
                # 找到 with get_db_connection() 行
                for j in range(i+1, min(len(lines_new), i+5)):
                    if 'with get_db_connection() as connection:' in lines_new[j]:
                        # 在下一行插入缓存检查
                        indent = '        '
                        cache_check_lines = [
                            f'{indent}cache_key = _payload_cache_key(connection, "intelligence")',
                            f'{indent}cached = _get_cached_payload("intelligence", cache_key)',
                            f'{indent}if cached is not None:',
                            f'{indent}    return cached',
                            ''
                        ]
                        # 插入到 normalized_events 行之前
                        for k in range(j+1, min(len(lines_new), j+5)):
                            if 'normalized_events' in lines_new[k]:
                                lines_new[k:k] = cache_check_lines
                                fixes_applied.append("添加 build_intelligence_payload 缓存命中检查")
                                break
                        break
                break
        content = '\n'.join(lines_new)

# 写入修复后的内容
with open(api_data_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\n修复完成！应用了 {len(fixes_applied)} 个修复:")
for fix in fixes_applied:
    print(f"  ✓ {fix}")

print(f"\n修复后文件共 {len(content.splitlines())} 行")
