#!/usr/bin/env python3
"""
修复 api_data.py 中的所有问题
- P0: 删除损坏的 _recent_problem_rows 函数 (lines 314-361)
- P0: 删除重复的损坏的 _build_executive_priority_events 函数 (lines 1383-1415)
- P1: 在 build_intelligence_payload 中添加缓存命中逻辑
- P2: 修复 INDUSTRY_LABELS 中的乱码中文字符
"""

from pathlib import Path

def fix_api_data():
    api_data_path = Path(__file__).parent.parent / "src" / "darkweb_collector" / "api_data.py"
    
    print(f"读取文件: {api_data_path}")
    with open(api_data_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    print(f"原始文件共 {len(lines)} 行")
    
    # 修复 1: 删除损坏的 _recent_problem_rows 函数 (lines 314-361, 0-indexed: 313-360)
    # 保留正确的版本 (lines 363-369, 0-indexed: 362-368)
    print("\n修复 1: 删除损坏的 _recent_problem_rows 函数 (lines 314-361)")
    del lines[313:361]  # 删除 48 行
    print(f"删除后剩余 {len(lines)} 行")
    
    # 修复 2: 删除重复的损坏的 _build_executive_priority_events 函数
    # 原来在 lines 1383-1415，删除 48 行后，新位置是 1383-48=1335 开始
    # 需要找到第二个定义并删除它（包含乱码的版本）
    print("\n修复 2: 查找并删除重复的 _build_executive_priority_events 函数")
    
    # 查找第二个 _build_executive_priority_events 定义
    first_def_idx = None
    second_def_idx = None
    for i, line in enumerate(lines):
        if "def _build_executive_priority_events(" in line:
            if first_def_idx is None:
                first_def_idx = i
                print(f"  找到第一个定义在 line {i+1}")
            else:
                second_def_idx = i
                print(f"  找到第二个定义在 line {i+1}")
                break
    
    if second_def_idx is not None:
        # 找到第二个函数的结束位置（下一个函数定义或文件结束）
        end_idx = second_def_idx + 1
        while end_idx < len(lines):
            if lines[end_idx].startswith("def ") and not lines[end_idx].startswith("    "):
                break
            end_idx += 1
        
        lines_to_delete = end_idx - second_def_idx
        print(f"  删除 lines {second_def_idx+1}-{end_idx} (共 {lines_to_delete} 行)")
        del lines[second_def_idx:end_idx]
        print(f"删除后剩余 {len(lines)} 行")
    
    # 修复 3: 修复 INDUSTRY_LABELS 中的乱码（lines 60-73）
    print("\n修复 3: 修复 INDUSTRY_LABELS 中的乱码")
    industry_labels_fix = {
        "鏀垮簻": "政府",
        "閲戣瀺": "金融", 
        "鍐滀笟": "农业",
        "闆跺敭": "零售",
        "閫氫俊": "通信",
        "浜ら€?": "交通",
        "鏂囧ū": "文娱",
        "鍒堕€犱笟": "制造业",
        "鍏朵粬": "其他",
    }
    
    for i, line in enumerate(lines):
        for garbled, correct in industry_labels_fix.items():
            if garbled in line:
                lines[i] = line.replace(garbled, correct)
                print(f"  Line {i+1}: 替换 '{garbled}' -> '{correct}'")
    
    # 修复 4: 在 build_intelligence_payload 中添加缓存命中逻辑
    print("\n修复 4: 在 build_intelligence_payload 中添加缓存命中逻辑")
    
    # 查找 build_intelligence_payload 函数
    func_start_idx = None
    for i, line in enumerate(lines):
        if "def build_intelligence_payload(" in line:
            func_start_idx = i
            print(f"  找到 build_intelligence_payload 在 line {i+1}")
            break
    
    if func_start_idx is not None:
        # 查找 cache_key 计算后的位置
        cache_key_idx = None
        for i in range(func_start_idx, min(func_start_idx + 50, len(lines))):
            if "cache_key = _payload_cache_key" in lines[i]:
                cache_key_idx = i
                print(f"  找到 cache_key 计算在 line {i+1}")
                break
        
        if cache_key_idx is not None:
            # 在 cache_key 计算后插入缓存命中检查
            indent = "    "
            cache_check_lines = [
                f"\n",
                f"{indent}# 检查缓存命中\n",
                f"{indent}cached = _get_cached_payload('intelligence', cache_key)\n",
                f"{indent}if cached is not None:\n",
                f"{indent}    return cached\n",
                f"\n",
            ]
            
            insert_pos = cache_key_idx + 1
            print(f"  在 line {insert_pos+1} 后插入缓存检查代码")
            lines[insert_pos:insert_pos] = cache_check_lines
    
    # 写回文件
    output_path = api_data_path
    print(f"\n写入修复后的文件: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    print(f"✓ 修复完成！最终文件共 {len(lines)} 行")
    print("\n修复摘要:")
    print("  ✓ P0: 删除损坏的 _recent_problem_rows 函数")
    print("  ✓ P0: 删除重复的损坏的 _build_executive_priority_events 函数")
    print("  ✓ P1: 添加缓存命中逻辑到 build_intelligence_payload")
    print("  ✓ P2: 修复 INDUSTRY_LABELS 中的乱码中文字符")

if __name__ == "__main__":
    fix_api_data()
