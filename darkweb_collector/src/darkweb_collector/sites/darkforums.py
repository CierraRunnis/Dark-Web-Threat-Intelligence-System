from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse

from darkweb_collector.normalize import content_hash


FORUM_SECTIONS = {
    "databases": "https://darkforums.su/Forum-Databases",
    "other_leaks": "https://darkforums.su/Forum-Other-Leaks", 
    "sellers_place": "https://darkforums.su/Forum-Sellers-Place"
}

# HTML cleaning
DETAIL_QUOTE_RE = re.compile(r'<blockquote[^>]*>.*?</blockquote>', re.IGNORECASE | re.DOTALL)
FIRST_POST_BLOCK_RE = re.compile(
    r'<div class="post classic .*?id="post_\d+".*?<!-- end: postbit_classic -->',
    re.IGNORECASE | re.DOTALL,
)

def _clean_html_text(value: str) -> str:
    """Clean HTML text by removing tags and normalizing whitespace"""
    if not value:
        return ""
    # Remove quotes
    value = DETAIL_QUOTE_RE.sub('', value)
    # Remove HTML tags
    value = re.sub(r"<[^>]+>", " ", value)
    # Unescape HTML entities
    value = unescape(value)
    # Normalize whitespace
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc


def parse_darkforums_list(url: str, html: str, max_topics: int = 5) -> dict:
    """
    Parse DarkForums list page to extract topic information
    
    Args:
        url: The URL of the list page
        html: The HTML content of the page
        max_topics: Maximum number of topics to extract (default: 5 for pilot testing)
    """
    start_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Starting to parse list page: {url}")
    
    # Extract page title
    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    title = _clean_html_text(title_match.group(1)) if title_match else ""
    domain = _extract_domain(url)
    
    topics = []
    
    # Find all topic links in the HTML
    # DarkForums uses MyBB forum software with specific patterns
    # Topic links look like: <a href="Thread-XXXXX-Title">Title</a>
    # or: <span class="subject_new" id="tid_XXX"><a href="Thread-XXXXX">Title</a></span>
    
    # Pattern 1: Find topic links with subject_new class (new posts)
    # Note: class attribute may have leading space: class=" subject_new"
    topic_pattern = re.compile(
        r'<span[^>]*class="[^"]*subject(?:_new)?"[^>]*id="tid_(\d+)"[^>]*>'
        r'\s*<a href="(Thread-[^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL
    )
    
    matches = topic_pattern.findall(html)
    print(f"[{time.strftime('%H:%M:%S')}] Found {len(matches)} topic matches")
    
    for tid, href, topic_title in matches:
        # Skip if already have this topic
        if any(t.get('tid') == tid for t in topics):
            continue
        
        # Clean title
        clean_title = _clean_html_text(topic_title)
        
        # Build full URL
        detail_url = urljoin(url, href)
        
        # Extract potential victim from title (for database leaks)
        victim = _extract_victim_from_title(clean_title)
        
        topic_data = {
            "tid": tid,
            "title": clean_title,
            "relative_url": href,
            "full_url": detail_url,
            "author": "",  # Will be filled from detail page
            "replies": "",
            "views": "",
            "published_at": "",
            "content_hash": content_hash(clean_title, tid),
            "potential_victim": victim
        }
        
        topics.append(topic_data)
        print(f"[{time.strftime('%H:%M:%S')}] Found topic {len(topics)}: {clean_title[:60]}...")
        
        # Limit to max_topics for pilot testing
        if len(topics) >= max_topics:
            print(f"[{time.strftime('%H:%M:%S')}] Reached limit of {max_topics} topics, stopping")
            break
    
    end_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] List parsing completed in {end_time - start_time:.2f}s, found {len(topics)} topics")
    
    return {
        "site_name": "darkforums",
        "source_url": url,
        "domain": domain,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic_count": len(topics),
        "topics": topics
    }


def _extract_victim_from_title(title: str) -> str:
    """Extract potential victim name from topic title"""
    # Common patterns in database leak titles
    patterns = [
        r'([^|]+)\s*Database',
        r'([^|]+)\s*Leak',
        r'([^|]+)\s*Breached',
        r'([^|]+)\s*Dump',
        r'([^|]+)\s*Data',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            victim = match.group(1).strip()
            # Clean up common prefixes/suffixes
            victim = re.sub(r'^(?:The|A|An)\s+', '', victim, flags=re.IGNORECASE)
            return victim
    
    return ""


def parse_darkforums_detail(url: str, html: str) -> dict:
    """
    Parse DarkForums detail page to extract post content and metadata
    """
    start_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Parsing detail page: {url}")
    
    # Extract page title
    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    title = _clean_html_text(title_match.group(1)) if title_match else ""
    domain = _extract_domain(url)
    
    post_block_match = FIRST_POST_BLOCK_RE.search(html)
    post_block = post_block_match.group(0) if post_block_match else html

    content_match = re.search(
        r'<div[^>]*class="[^"]*post_body[^"]*"[^>]*>(.*?)</div>\s*<div class="post_meta"',
        post_block,
        re.IGNORECASE | re.DOTALL,
    )
    if not content_match:
        content_match = re.search(
            r'<div[^>]*class="[^"]*post_body[^"]*"[^>]*>(.*?)</div>\s*<div class="post_controls"',
            post_block,
            re.IGNORECASE | re.DOTALL,
        )
    if not content_match:
        fallback_selectors = [
            r'<div[^>]*class="[^"]*post_content[^"]*"[^>]*>(.*?)</div>\s*(?:<div|<footer|<div class="post_controls")',
            r'<div[^>]*class="[^"]*messageContent[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*post_body[^"]*"[^>]*>(.*?)</div>',
        ]
        for selector in fallback_selectors:
            fallback_match = re.search(selector, post_block, re.IGNORECASE | re.DOTALL)
            if fallback_match:
                content_match = fallback_match
                break
    content = _clean_html_text(content_match.group(1)) if content_match else ""

    print(f"[{time.strftime('%H:%M:%S')}] Extracted content length: {len(content)} chars")
    
    # Extract author information
    author_match = re.search(
        r'<a[^>]*class="[^"]*username[^"]*"[^>]*>(.*?)</a>',
        post_block, re.IGNORECASE | re.DOTALL
    )
    if not author_match:
        author_match = re.search(
            r'<div class="post_user-profile[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
            post_block, re.IGNORECASE | re.DOTALL
        )
    author = _clean_html_text(author_match.group(1)) if author_match else "Unknown"
    
    print(f"[{time.strftime('%H:%M:%S')}] Author: {author}")
    
    # Extract post date/timestamp
    timestamp_match = re.search(
        r'<span class="post_date">(.*?)</span>',
        post_block, re.IGNORECASE | re.DOTALL
    )
    if not timestamp_match:
        timestamp_match = re.search(
            r'<span[^>]*class="[^"]*DateTime[^"]*"[^>]*>(.*?)</span>',
            post_block,
            re.IGNORECASE | re.DOTALL,
        )
    if not timestamp_match:
        timestamp_match = re.search(
            r'>(\d{2}-\d{2}-\d{2},\s*\d{2}:\d{2}\s*(?:AM|PM))<',
            post_block, re.IGNORECASE
        )
    timestamp = _clean_html_text(timestamp_match.group(1)) if timestamp_match else ""
    
    print(f"[{time.strftime('%H:%M:%S')}] Timestamp: {timestamp}")
    
    # Extract victims from content and title
    victims = extract_victims_from_content(content, title)
    print(f"[{time.strftime('%H:%M:%S')}] Found {len(victims)} victims")
    
    # Extract attackers
    attackers = extract_attackers_from_content(content)
    print(f"[{time.strftime('%H:%M:%S')}] Found {len(attackers)} attackers")
    
    # Build victim information with industry and region
    victim_info = []
    for victim in victims:
        industry = determine_industry(victim)
        region = determine_region(victim)
        victim_info.append({
            'name': victim,
            'industry': industry,
            'region': region
        })
        print(f"[{time.strftime('%H:%M:%S')}] Victim: {victim} | Industry: {industry} | Region: {region}")
    
    # Extract attachments/links
    attachment_matches = re.findall(
        r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*attachment[^"]*"[^>]*>',
        post_block, re.IGNORECASE
    )
    attachments = [urljoin(url, match) for match in attachment_matches]
    
    end_time = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Detail parsing completed in {end_time - start_time:.2f}s")
    
    return {
        "site_name": "darkforums",
        "source_url": url,
        "domain": domain,
        "title": title,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "author": author,
        "timestamp": timestamp,
        "attachments": attachments,
        "victims": victim_info,
        "attackers": attackers,
        "content_hash": content_hash(content[:1000], author)
    }


def extract_victims_from_content(content: str, title: str = "") -> list:
    """
    Extract victim information from post content and title
    
    For database leaks, victims are often mentioned in:
    1. Title (e.g., "CompanyName Database")
    2. Content (e.g., "Victim: Company Name", "Target: Organization")
    """
    victims = []
    
    # Extract from title first
    if title:
        title_victim = _extract_victim_from_title(title)
        if title_victim and len(title_victim) > 2:
            victims.append(title_victim)
    
    # Patterns to find victims in content
    victim_patterns = [
        # Explicit victim mentions
        r'[Vv]ictim[s]?[:\s]+(.+?)(?=\s+[Gg]roup:|\s+[Aa]ttacker:|[.,]|$)',
        r'[Tt]arget[:\s]+(.+?)(?=\s+[Gg]roup:|\s+[Aa]ttacker:|[.,]|$)',
        r'[Aa]ffected[:\s]+(.+?)(?=\s+[Gg]roup:|\s+[Aa]ttacker:|[.,]|$)',
    ]
    
    text_to_search = f"{title} {content}"
    
    for pattern in victim_patterns:
        matches = re.findall(pattern, text_to_search, re.IGNORECASE)
        for match in matches:
            victim = _clean_html_text(match)
            # Filter out common false positives
            if victim and len(victim) > 2 and len(victim) < 100:
                # Skip if it's just generic text
                generic_terms = ['the', 'this', 'that', 'these', 'those', 'database', 'data', 'unknown']
                if victim.lower() not in generic_terms and not any(
                    phrase in victim.lower()
                    for phrase in [
                        "this post",
                        "full database",
                        "most posts",
                        "processed database",
                        "private database",
                        "website",
                    ]
                ):
                    victims.append(victim)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_victims = []
    for v in victims:
        v_lower = v.lower()
        if v_lower not in seen:
            seen.add(v_lower)
            unique_victims.append(v)
    
    return unique_victims[:10]  # Limit to top 10 victims


def extract_attackers_from_content(content: str) -> list:
    """
    Extract attacker/threat actor information from content
    """
    attackers = []
    
    patterns = [
        r'[Aa]ttacker[s]?[:\s]+(.+?)(?=[.,]|$)',
        r'[Hh]acker[s]?[:\s]+(.+?)(?=[.,]|$)',
        r'[Gg]roup[:\s]+(.+?)(?=\s+[Tt]his\s+[Pp]ost|[.,]|$)',
        r'[Tt]hreat [Aa]ctor[s]?[:\s]+(.+?)(?=[.,]|$)',
        r'[Aa]ctor[s]?[:\s]+(.+?)(?=[.,]|$)',
        r'[Cc]redit[s]?\s+(?:to|goes to)[:\s]+(.+?)(?=[.,]|$)',
        r'[Bb]y[:\s]+(.+?)(?:\s+(?:group|team|gang))',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            attacker = _clean_html_text(match)
            if attacker and len(attacker) > 2 and len(attacker) < 50:
                attackers.append(attacker)
    
    # Remove duplicates
    seen = set()
    unique_attackers = []
    for a in attackers:
        a_lower = a.lower()
        if a_lower not in seen:
            seen.add(a_lower)
            unique_attackers.append(a)
    
    return unique_attackers[:5]  # Limit to top 5 attackers


def determine_industry(victim: str) -> str:
    """Determine industry based on victim name/description"""
    victim_lower = victim.lower()
    
    industries = {
        'finance': ['bank', 'financial', 'banking', 'credit', 'insurance', 'payment', 'finance', 'investment', 'capital'],
        'healthcare': ['health', 'hospital', 'medical', 'healthcare', 'pharmaceutical', 'clinic', 'patient'],
        'government': ['government', 'military', 'army', 'navy', 'air force', 'police', 'fbi', 'cia', 'federal', 'state', 'ministry', 'agency', 'department', 'gov', 'public', 'tsa', 'transportation security'],
        'technology': ['tech', 'technology', 'software', 'hardware', 'internet', 'social media', 'cloud', 'cyber', 'digital', 'app', 'platform'],
        'retail': ['retail', 'ecommerce', 'shop', 'store', 'market', 'commerce', 'mall'],
        'education': ['university', 'college', 'school', 'education', 'academy', 'institute', 'student'],
        'telecommunications': ['telecom', 'telecommunication', 'mobile', 'phone', 'wireless', 'isp', 'internet service', 'broadband'],
        'energy': ['energy', 'oil', 'gas', 'electric', 'power', 'utility', 'renewable'],
        'transportation': ['airline', 'airport', 'transport', 'logistics', 'shipping', 'railway', 'aviation'],
        'entertainment': ['entertainment', 'gaming', 'game', 'media', 'streaming', 'movie', 'music'],
    }
    
    for industry, keywords in industries.items():
        for keyword in keywords:
            if keyword in victim_lower:
                return industry
    
    return 'other'


def determine_region(victim: str) -> str:
    """Determine region based on victim name/description"""
    victim_lower = victim.lower()
    
    regions = {
        'north_america': ['us', 'usa', 'united states', 'america', 'canada', 'mexico', 'north america', 'california', 'texas', 'florida', 'new york'],
        'europe': ['europe', 'uk', 'britain', 'england', 'germany', 'france', 'italy', 'spain', 'russia', 'netherlands', 'sweden', 'norway', 'poland', 'turkey', 'turkish'],
        'asia': ['asia', 'china', 'japan', 'korea', 'india', 'singapore', 'malaysia', 'thailand', 'vietnam', 'indonesia', 'philippines', 'pakistan', 'bangladesh'],
        'middle_east': ['middle east', 'saudi arabia', 'iran', 'iraq', 'israel', 'uae', 'dubai', 'qatar', 'kuwait', 'lebanon', 'jordan', 'syria'],
        'africa': ['africa', 'nigeria', 'south africa', 'egypt', 'kenya', 'morocco', 'ghana', 'ethiopia'],
        'oceania': ['oceania', 'australia', 'new zealand', 'fiji', 'papua new guinea'],
        'south_america': ['brazil', 'argentina', 'colombia', 'chile', 'peru', 'venezuela', 'ecuador', 'bolivia', 'uruguay', 'paraguay'],
    }
    
    for region, keywords in regions.items():
        for keyword in keywords:
            if keyword in victim_lower:
                return region
    
    return 'unknown'


def get_darkforums_sections() -> dict:
    """Get the list of forum sections to crawl"""
    return FORUM_SECTIONS
