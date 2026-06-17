from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import public_vulnerabilities


def _nvd_item(
    cve_id: str,
    *,
    published: str,
    last_modified: str,
    severity_score: float,
    vendor: str,
    product: str,
    description: str,
) -> dict:
    return {
        "cve": {
            "id": cve_id,
            "published": published,
            "lastModified": last_modified,
            "descriptions": [{"lang": "en", "value": description}],
            "metrics": {
                "cvssMetricV31": [
                    {
                        "cvssData": {
                            "baseScore": severity_score,
                        }
                    }
                ]
            },
            "configurations": [
                {
                    "nodes": [
                        {
                            "cpeMatch": [
                                {
                                    "criteria": f"cpe:2.3:a:{vendor}:{product}:1.0:*:*:*:*:*:*:*",
                                    "vulnerable": True,
                                }
                            ]
                        }
                    ]
                }
            ],
            "references": [{"url": f"https://example.org/{cve_id.lower()}"}],
            "weaknesses": [{"description": [{"value": "CWE-287"}]}],
        }
    }


class PublicVulnerabilityFeedTests(unittest.TestCase):
    def test_live_feed_combines_kev_and_recent_nvd_and_filters_duplicate_cves(self) -> None:
        kev_payload = {
            "vulnerabilities": [
                {
                    "cveID": "CVE-2026-24001",
                    "vendorProject": "Palo Alto Networks",
                    "product": "PAN-OS GlobalProtect",
                    "vulnerabilityName": "unauthenticated command execution",
                    "dateAdded": "2026-04-10T09:00:00+00:00",
                    "requiredAction": "apply updates",
                    "shortDescription": "Critical KEV entry.",
                    "notes": "https://example.org/kev/cve-2026-24001",
                    "cwes": ["CWE-287"],
                }
            ]
        }

        def fake_fetch_json(url: str, *, timeout: int = 20):
            if url == public_vulnerabilities.KEV_FEED_URL:
                return kev_payload
            if "cveId=CVE-2026-24001" in url:
                return {
                    "vulnerabilities": [
                        _nvd_item(
                            "CVE-2026-24001",
                            published="2026-04-09T08:00:00.000",
                            last_modified="2026-04-10T10:00:00.000",
                            severity_score=9.8,
                            vendor="palo_alto_networks",
                            product="pan_os_globalprotect",
                            description="KEV NVD enrichment.",
                        )
                    ]
                }
            if "cvssV3Severity=CRITICAL" in url:
                return {
                    "vulnerabilities": [
                        _nvd_item(
                            "CVE-2026-99991",
                            published="2026-04-12T10:00:00.000",
                            last_modified="2026-04-12T10:30:00.000",
                            severity_score=9.9,
                            vendor="apache",
                            product="tomcat",
                            description="Critical recent NVD issue.",
                        )
                    ]
                }
            if "cvssV3Severity=HIGH" in url:
                return {
                    "vulnerabilities": [
                        _nvd_item(
                            "CVE-2026-24001",
                            published="2026-04-10T08:00:00.000",
                            last_modified="2026-04-10T10:00:00.000",
                            severity_score=8.8,
                            vendor="palo_alto_networks",
                            product="pan_os_globalprotect",
                            description="Duplicate NVD record for KEV item.",
                        ),
                        _nvd_item(
                            "CVE-2026-88881",
                            published="2026-04-11T11:00:00.000",
                            last_modified="2026-04-11T11:30:00.000",
                            severity_score=8.1,
                            vendor="nginx",
                            product="ingress_controller",
                            description="High recent NVD issue.",
                        ),
                    ]
                }
            raise AssertionError(f"unexpected URL: {url}")

        with patch("darkweb_collector.public_vulnerabilities._fetch_json", side_effect=fake_fetch_json), patch(
            "darkweb_collector.public_vulnerabilities._load_nvd_enrichment_cache",
            return_value={},
        ), patch("darkweb_collector.public_vulnerabilities._save_nvd_enrichment_cache") as mocked_save, patch(
            "darkweb_collector.public_vulnerabilities._fetch_recent_github_advisories",
            return_value=[],
        ):
            records = public_vulnerabilities.fetch_live_public_vulnerability_feed(limit=10)

        mocked_save.assert_called_once()
        self.assertEqual(
            ["CVE-2026-99991", "CVE-2026-88881", "CVE-2026-24001"],
            [item["cve_id"] for item in records],
        )
        self.assertEqual(
            ["nvd_recent", "nvd_recent", "cisa_kev"],
            [item["source_name"] for item in records],
        )

    def test_live_feed_includes_recent_github_advisories(self) -> None:
        def fake_fetch_json(url: str, *, timeout: int = 20):
            if url == public_vulnerabilities.KEV_FEED_URL:
                return {"vulnerabilities": []}
            if "cvssV3Severity=CRITICAL" in url or "cvssV3Severity=HIGH" in url:
                return {"vulnerabilities": []}
            if "cveId=CVE-2026-55551" in url:
                return {
                    "vulnerabilities": [
                        _nvd_item(
                            "CVE-2026-55551",
                            published="2026-04-12T08:30:00.000",
                            last_modified="2026-04-12T09:30:00.000",
                            severity_score=9.8,
                            vendor="demo_vendor",
                            product="demo_package",
                            description="GitHub advisory NVD enrichment.",
                        )
                    ]
                }
            raise AssertionError(f"unexpected URL: {url}")

        github_payload = [
            {
                "ghsa_id": "GHSA-aaaa-bbbb-cccc",
                "cve_id": "CVE-2026-55551",
                "html_url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
                "url": "https://api.github.com/advisories/GHSA-aaaa-bbbb-cccc",
                "summary": "Remote code execution in demo package",
                "description": "A recent critical advisory for an npm package.",
                "severity": "critical",
                "published_at": "2026-04-12T08:00:00Z",
                "updated_at": "2026-04-12T09:00:00Z",
                "nvd_published_at": "2026-04-12T08:30:00Z",
                "references": ["https://example.org/github/cve-2026-55551"],
                "cvss": {"score": 9.8},
                "cwes": [{"cwe_id": "CWE-94"}],
                "vulnerabilities": [
                    {
                        "package": {"ecosystem": "npm", "name": "demo-package"},
                        "first_patched_version": "1.2.3",
                        "vulnerable_version_range": "< 1.2.3",
                    }
                ],
            }
        ]

        class _Headers:
            def __init__(self) -> None:
                self._values = {"Link": ""}

            def get(self, key: str, default: str = "") -> str:
                return self._values.get(key, default)

        def fake_fetch_json_with_headers(url: str, *, timeout: int = 20, headers: dict[str, str] | None = None):
            if url.startswith(public_vulnerabilities.GITHUB_ADVISORIES_API_URL):
                return github_payload, _Headers()
            raise AssertionError(f"unexpected URL: {url}")

        with patch("darkweb_collector.public_vulnerabilities._fetch_json", side_effect=fake_fetch_json), patch(
            "darkweb_collector.public_vulnerabilities._fetch_json_with_headers",
            side_effect=fake_fetch_json_with_headers,
        ), patch(
            "darkweb_collector.public_vulnerabilities._load_nvd_enrichment_cache",
            return_value={},
        ), patch("darkweb_collector.public_vulnerabilities._save_nvd_enrichment_cache"):
            records = public_vulnerabilities.fetch_live_public_vulnerability_feed(limit=10)

        self.assertEqual(["CVE-2026-55551"], [item["cve_id"] for item in records])
        self.assertEqual(["github_advisories"], [item["source_name"] for item in records])
