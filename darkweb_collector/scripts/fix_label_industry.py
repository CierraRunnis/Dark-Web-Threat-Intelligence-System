#!/usr/bin/env python3
"""
修复 api_data.py 中重复的 _label_industry 函数定义
删除第一个简单版本，保留并清理第二个完整版本
"""

from pathlib import Path

def fix_label_industry():
    api_data_path = Path(__file__).parent.parent / "src" / "darkweb_collector" / "api_data.py"
    
    print(f"读取文件: {api_data_path}")
    with open(api_data_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    print(f"原始文件共 {len(lines)} 行")
    
    # 查找两个 _label_industry 定义
    first_def_idx = None
    second_def_idx = None
    
    for i, line in enumerate(lines):
        if "def _label_industry(" in line:
            if first_def_idx is None:
                first_def_idx = i
                print(f"找到第一个 _label_industry 定义在 line {i+1}")
            else:
                second_def_idx = i
                print(f"找到第二个 _label_industry 定义在 line {i+1}")
                break
    
    if first_def_idx is not None and second_def_idx is not None:
        # 删除第一个简单版本（包括前后的空行）
        # 第一个函数通常是 3 行 + 2 个空行
        print(f"\n删除第一个简单版本 (lines {first_def_idx+1}-{first_def_idx+5})")
        del lines[first_def_idx:first_def_idx+5]
        
        print(f"删除后剩余 {len(lines)} 行")
        
        # 重新查找第二个定义（现在变成了第一个）
        new_def_idx = None
        for i, line in enumerate(lines):
            if "def _label_industry(" in line:
                new_def_idx = i
                print(f"\n找到 _label_industry 定义在新位置 line {i+1}")
                break
        
        if new_def_idx is not None:
            # 清理函数中的乱码 token 检查
            print("\n清理函数中的乱码字符...")
            
            # 找到函数结束位置
            func_end = new_def_idx + 1
            while func_end < len(lines):
                if lines[func_end].startswith("def ") and not lines[func_end].startswith("    "):
                    break
                func_end += 1
            
            # 重写整个函数
            new_function = '''def _label_industry(value: str | None) -> str:
    """标准化行业标签，支持中英文映射"""
    raw = (value or "").strip()
    lowered = raw.lower()
    
    # 英文关键词映射
    if "manufact" in lowered or "construction" in lowered:
        return "制造业"
    if "business services" in lowered:
        return "其他"
    if "consumer services" in lowered or "retail" in lowered:
        return "零售"
    if "transport" in lowered or "logistics" in lowered:
        return "交通"
    if "hospitality" in lowered or "tourism" in lowered or "entertainment" in lowered:
        return "文娱"
    if "public sector" in lowered or "government" in lowered:
        return "政府"
    if "financial services" in lowered or "finance" in lowered:
        return "金融"
    if "healthcare" in lowered:
        return "医疗"
    if "technology" in lowered:
        return "科技"
    if "agriculture" in lowered:
        return "农业"
    if "telecommunication" in lowered:
        return "通信"
    if "energy" in lowered:
        return "能源"
    if "education" in lowered:
        return "教育"
    
    # 回退到字典查找
    return INDUSTRY_LABELS.get(lowered, INDUSTRY_LABELS.get(raw, raw or "未知"))


'''
            
            print(f"替换 lines {new_def_idx+1}-{func_end} 为清理后的函数")
            lines[new_def_idx:func_end] = [new_function]
    
    # 写回文件
    print(f"\n写入修复后的文件: {api_data_path}")
    with open(api_data_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    print(f"✓ 修复完成！最终文件共 {len(lines)} 行")
    print("\n修复摘要:")
    print("  ✓ P3: 删除重复的 _label_industry 函数定义")
    print("  ✓ P3: 清理函数中的乱码字符")

if __name__ == "__main__":
    fix_label_industry()
