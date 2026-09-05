#!/usr/bin/env python3
"""
Ransomware.live API 连接测试脚本 v2 (优化版)

改进：
- 使用流式读取，避免大数据量超时
- 支持分块下载
- 更好的进度显示
- 自动重试机制

使用方法：
1. 在环境变量 RANSOMWARE_LIVE_API_KEY 中设置你的 API Key
2. 运行: python test_ransomware_api_v2.py
"""

import json
import os
import urllib.request
import urllib.error
import socket
from datetime import datetime
import time

# ============================================
# 配置区域 - 从环境变量读取 API Key
# ============================================
API_KEY = os.environ.get("RANSOMWARE_LIVE_API_KEY", "")

# API配置
API_URL = "https://api-pro.ransomware.live/victims/recent?order=discovered"
CONNECT_TIMEOUT = 30  # 连接超时（秒）
READ_TIMEOUT = 300    # 读取超时（秒）- 增加到5分钟
CHUNK_SIZE = 8192     # 每次读取的字节数
MAX_RETRIES = 3       # 最大重试次数

# 代理配置（TUN 模式下保持 USE_PROXY=False，直连即可）
USE_PROXY = False  # 仅在未启用 TUN 的环境才改为 True
PROXY_URL = "http://127.0.0.1:7890"  # 显式代理地址（TUN 模式下不使用）


def download_with_progress(response, chunk_size=CHUNK_SIZE):
    """流式下载并显示进度"""
    chunks = []
    total_size = 0
    start_time = time.time()
    
    print("📥 正在下载数据...")
    
    try:
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            
            chunks.append(chunk)
            total_size += len(chunk)
            elapsed = time.time() - start_time
            speed = total_size / elapsed / 1024  # KB/s
            
            # 显示进度
            print(f"\r   已下载: {total_size/1024:.1f} KB | 速度: {speed:.1f} KB/s | 用时: {elapsed:.1f}s", end='', flush=True)
    
    except socket.timeout:
        print(f"\n⚠️  读取超时，已下载 {total_size/1024:.1f} KB")
        if not chunks:
            raise
    
    print()  # 换行
    
    # 合并所有块
    data = b''.join(chunks)
    return data


def test_api_connection_v2(retry_count=0):
    """测试ransomware.live API连接（优化版）"""
    
    if retry_count == 0:
        print("=" * 60)
        print("Ransomware.live API 连接测试 v2 (优化版)")
        print("=" * 60)
        print()
    
    # 检查API Key
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("❌ 错误: 请先在脚本中填入你的API Key")
        print("   找到这一行: API_KEY = \"YOUR_API_KEY_HERE\"")
        print("   替换为: API_KEY = \"你的实际API Key\"")
        return False
    
    if retry_count == 0:
        print(f"📋 配置信息:")
        print(f"   API URL: {API_URL}")
        print(f"   API Key: {API_KEY[:8]}...{API_KEY[-4:] if len(API_KEY) > 12 else '****'}")
        print(f"   连接超时: {CONNECT_TIMEOUT}秒")
        print(f"   读取超时: {READ_TIMEOUT}秒")
        print(f"   分块大小: {CHUNK_SIZE} 字节")
        print(f"   使用代理: {'是' if USE_PROXY else '否'}")
        if USE_PROXY:
            print(f"   代理地址: {PROXY_URL}")
        print()
    
    # 配置代理（如果需要）
    if USE_PROXY and retry_count == 0:
        proxy_handler = urllib.request.ProxyHandler({
            'http': PROXY_URL,
            'https': PROXY_URL
        })
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)
        print("✓ 代理已配置")
        print()
    
    # 创建请求
    if retry_count > 0:
        print(f"\n🔄 重试 {retry_count}/{MAX_RETRIES}...")
    else:
        print("🔄 正在连接API...")
    
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "bishe-threat-intel/1.0",
            "X-API-KEY": API_KEY,
        }
    )
    
    # 发送请求
    try:
        start_time = datetime.now()
        
        # 设置超时
        response = urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT)
        
        # 设置socket超时（用于读取）
        response.fp.raw._sock.settimeout(READ_TIMEOUT)
        
        print(f"✓ 连接成功 (HTTP {response.status})")
        
        # 流式读取数据
        data_bytes = download_with_progress(response)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # 解析JSON
        print("🔄 正在解析JSON...")
        data = json.loads(data_bytes.decode('utf-8'))
        
        # 显示结果
        print()
        print("=" * 60)
        print("✅ 测试成功！")
        print("=" * 60)
        print()
        print(f"📊 响应信息:")
        print(f"   HTTP状态码: {response.status}")
        print(f"   总用时: {elapsed:.2f}秒")
        print(f"   数据大小: {len(data_bytes)/1024:.1f} KB")
        print(f"   Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        print()
        
        print(f"📈 数据统计:")
        print(f"   总记录数: {data.get('count', 0)}")
        print(f"   返回受害者数: {len(data.get('victims', []))}")
        print(f"   客户端: {data.get('client', 'N/A')}")
        print(f"   排序方式: {data.get('order', 'N/A')}")
        print()
        
        # 显示前3条记录
        victims = data.get('victims', [])
        if victims:
            print(f"🎯 最新受害者（前3条）:")
            print()
            for i, victim in enumerate(victims[:3], 1):
                print(f"   {i}. {victim.get('victim', 'N/A')}")
                print(f"      勒索组织: {victim.get('group', 'N/A')}")
                print(f"      国家: {victim.get('country', 'N/A') or '未知'}")
                print(f"      行业: {victim.get('activity', 'N/A')}")
                print(f"      发现时间: {victim.get('discovered', 'N/A')}")
                print(f"      网站: {victim.get('website', 'N/A') or '未提供'}")
                
                # 显示描述（截取前100字符）
                desc = victim.get('description', '')
                if desc:
                    desc_preview = desc[:100].replace('\n', ' ') + ('...' if len(desc) > 100 else '')
                    print(f"      描述: {desc_preview}")
                print()
        
        # 保存完整响应到文件
        output_file = "ransomware_api_response.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 完整响应已保存到: {output_file}")
        print()
        
        return True
        
    except socket.timeout as e:
        print()
        print("=" * 60)
        print("❌ 超时错误")
        print("=" * 60)
        print()
        print(f"   错误信息: {e}")
        print()
        
        # 自动重试
        if retry_count < MAX_RETRIES:
            print(f"💡 将在3秒后自动重试...")
            time.sleep(3)
            return test_api_connection_v2(retry_count + 1)
        else:
            print("💡 建议:")
            print("   1. 检查网络连接稳定性")
            print("   2. 尝试配置代理（将 USE_PROXY 改为 True）")
            print("   3. 增加 READ_TIMEOUT 值（当前为 300秒）")
            print("   4. 使用更稳定的网络环境")
            print()
            return False
        
    except urllib.error.HTTPError as e:
        print()
        print("=" * 60)
        print("❌ HTTP错误")
        print("=" * 60)
        print()
        print(f"   状态码: {e.code}")
        print(f"   原因: {e.reason}")
        print()
        
        try:
            error_body = e.read().decode('utf-8')
            error_data = json.loads(error_body)
            print(f"   错误详情: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
        except:
            print(f"   错误详情: {e.read().decode('utf-8', errors='ignore')}")
        
        print()
        print("💡 常见问题:")
        if e.code == 401 or e.code == 403:
            print("   - API Key可能无效或已过期")
            print("   - 请检查API Key是否正确")
        elif e.code == 429:
            print("   - API请求频率超限")
            print("   - 请稍后再试")
        print()
        return False
        
    except urllib.error.URLError as e:
        print()
        print("=" * 60)
        print("❌ 网络连接错误")
        print("=" * 60)
        print()
        print(f"   错误类型: {type(e.reason).__name__}")
        print(f"   错误信息: {e.reason}")
        print()
        print("💡 可能的原因:")
        print("   1. 网络连接问题")
        print("   2. 需要配置代理（将脚本中 USE_PROXY 改为 True）")
        print("   3. 防火墙阻止了连接")
        print("   4. DNS解析失败")
        print()
        return False
        
    except json.JSONDecodeError as e:
        print()
        print("=" * 60)
        print("❌ JSON解析错误")
        print("=" * 60)
        print()
        print(f"   错误信息: {e}")
        print(f"   数据大小: {len(data_bytes)/1024:.1f} KB")
        print()
        print("💡 可能的原因:")
        print("   - 数据传输不完整")
        print("   - 响应格式不是有效的JSON")
        print()
        
        # 保存原始响应用于调试
        with open("ransomware_api_raw_response.txt", 'wb') as f:
            f.write(data_bytes)
        print(f"   原始响应已保存到: ransomware_api_raw_response.txt")
        print()
        return False
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ 未知错误")
        print("=" * 60)
        print()
        print(f"   错误类型: {type(e).__name__}")
        print(f"   错误信息: {e}")
        print()
        return False


def main():
    """主函数"""
    success = test_api_connection_v2()
    
    print("=" * 60)
    if success:
        print("✅ 测试完成 - API连接正常")
        print()
        print("下一步:")
        print("   1. 可以使用项目CLI同步数据:")
        print(f"      export RANSOMWARE_LIVE_API_KEY=\"{API_KEY}\"")
        print("      cd darkweb_collector")
        print("      python scripts/crawl.py sync-ransomware-live --limit 100")
        print()
        print("   2. 或通过前端控制台配置API Key并同步")
    else:
        print("❌ 测试失败 - 请根据上述提示排查问题")
    print("=" * 60)


if __name__ == "__main__":
    main()
