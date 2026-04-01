#!/usr/bin/env python3
"""
Verify DarkForums parser functionality
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'darkweb_collector', 'src'))

from darkweb_collector.sites.darkforums import parse_darkforums_list, get_darkforums_sections

print("Testing DarkForums parser...")
print("\n1. Testing get_darkforums_sections()")
sections = get_darkforums_sections()
print(f"Found {len(sections)} sections:")
for section, url in sections.items():
    print(f"  - {section}: {url}")

print("\n2. Testing parse_darkforums_list()")
# Create a simple test HTML
 test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>DarkForums - Databases</title>
</head>
<body>
    <li class="threadbit">
        <a class="title" href="/threads/test-thread.123/">Test Thread Title</a>
        <a class="username">TestUser</a>
        <a class="thread-count">5</a>
        <a class="view-count">100</a>
        <span class="DateTime">2026-03-01</span>
        <span class="DateTime">2026-03-02</span>
    </li>
</body>
</html>
"""

test_url = "https://darkforums.su/forums/databases.38/"
try:
    result = parse_darkforums_list(test_url, test_html)
    print(f"Parser returned: {result}")
    print(f"  Site name: {result.get('site_name')}")
    print(f"  Title: {result.get('title')}")
    print(f"  Topic count: {result.get('topic_count')}")
    if result.get('topics'):
        print(f"  First topic: {result['topics'][0]['title']}")
    print("Parser test passed!")
except Exception as e:
    print(f"Parser test failed: {e}")
    import traceback
    traceback.print_exc()

print("\nVerification completed!")
