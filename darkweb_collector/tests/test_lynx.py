"""Tests for Lynx site parser and adapter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from darkweb_collector.sites.lynx import parse_lynx_list_page, parse_lynx_detail_page


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "Lynx"


def test_parse_lynx_list_page():
    """Test parsing Lynx list page from sample HTML."""
    list_html_path = SAMPLES_DIR / "list.html"
    if not list_html_path.exists():
        pytest.skip(f"Sample file not found: {list_html_path}")

    html = list_html_path.read_text(encoding="utf-8")
    url = "http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks"

    result = parse_lynx_list_page(url, html)

    # Verify structure
    assert result["site_name"] == "lynx"
    assert result["source_url"] == url
    assert "collected_at_utc" in result
    assert "victim_count" in result
    assert "victims" in result

    # Verify victims exist
    assert result["victim_count"] > 0
    assert len(result["victims"]) > 0

    # Verify victim fields (database compatible format)
    first_victim = result["victims"][0]
    assert "name" in first_victim
    assert "source_url" in first_victim
    assert "domain" in first_victim
    assert "status" in first_victim
    assert "content_hash" in first_victim

    # Verify source_url is absolute (detail_url transformed to source_url)
    assert first_victim["source_url"].startswith("http")

    print(f"\nParsed {result['victim_count']} victims from list page")
    print(f"First victim name: {first_victim['name'][:50]}...")


def test_parse_lynx_detail_page():
    """Test parsing Lynx detail page from sample HTML."""
    detail_html_path = SAMPLES_DIR / "detail_1.html"
    if not detail_html_path.exists():
        pytest.skip(f"Sample file not found: {detail_html_path}")

    html = detail_html_path.read_text(encoding="utf-8")
    url = "http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks/69ab22c69c439c5f45a86b32"

    result = parse_lynx_detail_page(url, html)

    # Verify structure
    assert result["site_name"] == "lynx"
    assert result["source_url"] == url
    assert "parsed_at_utc" in result

    # Verify fields
    assert "content" in result
    assert "timestamp" in result
    assert "victims" in result
    assert "attackers" in result
    assert "attachments" in result
    assert "content_hash" in result

    print(f"\nParsed detail page")
    print(f"Content length: {len(result['content'])}")


def test_parse_lynx_detail_page_2():
    """Test parsing second Lynx detail page sample."""
    detail_html_path = SAMPLES_DIR / "detail_2.html"
    if not detail_html_path.exists():
        pytest.skip(f"Sample file not found: {detail_html_path}")

    html = detail_html_path.read_text(encoding="utf-8")
    url = "http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks/69ab23879c439c5f45a87b2a"

    result = parse_lynx_detail_page(url, html)

    assert result["site_name"] == "lynx"
    assert "content" in result
    assert "content_hash" in result

    print(f"\nParsed detail page 2")
    print(f"Content length: {len(result['content'])}")


def test_list_page_victims_consistency():
    """Verify that list page victims have consistent structure."""
    list_html_path = SAMPLES_DIR / "list.html"
    if not list_html_path.exists():
        pytest.skip(f"Sample file not found: {list_html_path}")

    html = list_html_path.read_text(encoding="utf-8")
    url = "http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks"

    result = parse_lynx_list_page(url, html)

    # All victims should have required fields for database
    required_fields = [
        "site_name",
        "source_url",
        "name",
        "domain",
        "status",
        "content_hash",
    ]

    for victim in result["victims"]:
        for field in required_fields:
            assert field in victim, f"Missing field '{field}' in victim: {victim.get('name', 'unknown')}"

        # source_url should be a valid URL
        assert victim["source_url"].startswith("http://") or victim["source_url"].startswith("https://")

    print(f"\nAll {len(result['victims'])} victims have consistent structure")


def test_content_hash_uniqueness():
    """Verify that content hashes are unique for different victims."""
    list_html_path = SAMPLES_DIR / "list.html"
    if not list_html_path.exists():
        pytest.skip(f"Sample file not found: {list_html_path}")

    html = list_html_path.read_text(encoding="utf-8")
    url = "http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7aomjad.onion/leaks"

    result = parse_lynx_list_page(url, html)

    hashes = [victim["content_hash"] for victim in result["victims"] if victim.get("content_hash")]
    unique_hashes = set(hashes)

    # All hashes should be unique
    assert len(hashes) == len(unique_hashes), "Duplicate content hashes found"

    print(f"\nAll {len(hashes)} content hashes are unique")


if __name__ == "__main__":
    # Run tests manually
    print("Running Lynx parser tests...")

    try:
        test_parse_lynx_list_page()
        print("✓ test_parse_lynx_list_page passed")
    except Exception as e:
        print(f"✗ test_parse_lynx_list_page failed: {e}")

    try:
        test_parse_lynx_detail_page()
        print("✓ test_parse_lynx_detail_page passed")
    except Exception as e:
        print(f"✗ test_parse_lynx_detail_page failed: {e}")

    try:
        test_parse_lynx_detail_page_2()
        print("✓ test_parse_lynx_detail_page_2 passed")
    except Exception as e:
        print(f"✗ test_parse_lynx_detail_page_2 failed: {e}")

    try:
        test_list_page_victims_consistency()
        print("✓ test_list_page_victims_consistency passed")
    except Exception as e:
        print(f"✗ test_list_page_victims_consistency failed: {e}")

    try:
        test_content_hash_uniqueness()
        print("✓ test_content_hash_uniqueness passed")
    except Exception as e:
        print(f"✗ test_content_hash_uniqueness failed: {e}")

    print("\nAll tests completed!")
