from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.api_actions as api_actions
from darkweb_collector.code_monitoring import (
    _candidate_signature,
    _classify_code_hit,
    _gitee_blob_content,
    _gitee_repo_candidates_to_code_results,
    _collect_gitee_repo_search_window,
    _collect_search_results_across_pages,
    _collect_search_results_incremental,
    _evaluate_enterprise_match,
    _extract_code_lines,
    _gitee_repo_code_search_incremental,
    _gitlab_repo_candidates_to_code_results,
    _gitlab_repo_fallback_code_search,
    _http_get_json,
    _repo_seed_queries,
    build_code_monitoring_summary,
    delete_code_watchlist_payload,
    list_code_hits_payload,
    _payload_enterprise_profile,
    _search_page_url,
    build_code_hit_detail,
    list_code_scan_runs_payload,
    save_code_watchlist_payload,
)
from darkweb_collector.db import (
    get_code_search_state,
    get_db_connection,
    insert_code_hit_snapshot,
    insert_code_scan_run,
    list_code_search_states,
    update_code_hit_last_snapshot,
    upsert_code_search_state,
    upsert_code_hit,
)
from darkweb_collector.document_exposure_platforms import get_exposure_platform


class CodeMonitoringTests(unittest.TestCase):
    def _env(self, db_path: Path, output_root: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
        }

    def _write_empty_sites(self, path: Path) -> None:
        path.write_text(json.dumps({"sites": []}, ensure_ascii=False), encoding="utf-8")

    def test_extract_code_lines_keeps_full_github_line(self) -> None:
        html = """
        <div id="LC31" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
          <span class="pl-s">'password'</span> : <span class="pl-s1">PASSWORD</span> ,
        </div>
        <div id="LC32" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
          <span class="pl-s">'search_query'</span>: [<span class="pl-s">'FROM'</span>, <span class="pl-s">'ibanking.alert@dbs.com'</span>, <span class="pl-s">'SUBJECT'</span>]
        </div>
        """

        rows = _extract_code_lines(html)

        self.assertEqual(2, len(rows))
        self.assertEqual(31, rows[0][0])
        self.assertIn("'password' : PASSWORD ,", rows[0][1])
        self.assertEqual(32, rows[1][0])
        self.assertIn("ibanking.alert@dbs.com", rows[1][1])
        self.assertIn("'search_query'", rows[1][1])

    def test_extract_code_lines_supports_embedded_raw_lines(self) -> None:
        html = """
        <script type="application/json" data-target="react-app.embeddedData">
        {"payload":{"codeViewBlobLayoutRoute.StyledBlob":{"rawLines":["const admin = 'admin@dbs.com';","const password = 'Sup3rSecretValue123';"]}}}
        </script>
        """

        rows = _extract_code_lines(html)

        self.assertEqual([(1, "const admin = 'admin@dbs.com';"), (2, "const password = 'Sup3rSecretValue123';")], rows)

    def test_search_page_url_builds_follow_up_pages(self) -> None:
        self.assertEqual(
            "https://github.com/search?q=dbs&type=code&p=3",
            _search_page_url("github", "https://github.com/search?q=dbs&type=code", 3),
        )
        self.assertEqual(
            "https://gitlab.com/search?search=dbs&nav_source=navbar&type=blobs&page=2",
            _search_page_url("gitlab", "https://gitlab.com/search?search=dbs&nav_source=navbar&type=blobs", 2),
        )

    def test_repo_seed_queries_include_domain_root_and_profile_aliases(self) -> None:
        profile = {
            "official_names": ["DBS Bank"],
            "brand_aliases": [],
            "english_aliases": ["dbs"],
            "root_domains": ["dbs.com"],
            "trusted_subdomain_patterns": ["*.dbs.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["dbs"],
        }

        queries = _repo_seed_queries("dbs.com", "domain", profile)

        self.assertEqual("dbs.com", queries[0])
        self.assertIn("dbs", queries)
        self.assertIn("DBS Bank", queries)

    def test_classify_code_hit_supports_clue_and_sensitive_layers(self) -> None:
        clue = _classify_code_hit(
            "DBS.com",
            "app.py",
            "config = {'search_query': ['FROM', 'ibanking.alert@dbs.com']}\nmail_client.send('ibanking.alert@dbs.com')",
            ["password", "token"],
        )
        self.assertIsNotNone(clue)
        self.assertEqual("clue", clue["result_layer"])
        self.assertEqual("clue", clue["sensitive_type"])

        sensitive = _classify_code_hit(
            "DBS.com",
            "app.py",
            "token = 'abcdefghijklmnop123456'\nPASSWORD = os.getenv('PASSWORD')",
            ["password", "token"],
        )
        self.assertIsNotNone(sensitive)
        self.assertEqual("sensitive", sensitive["result_layer"])
        self.assertIn(sensitive["sensitive_type"], {"token", "password"})

    def test_payload_enterprise_profile_uses_terms_as_fallback(self) -> None:
        profile = _payload_enterprise_profile(
            {
                "organization_name": "宁德时代",
                "terms": [
                    {"term": "宁德时代", "term_type": "company_name", "enabled": True},
                    {"term": "catl.com", "term_type": "domain", "enabled": True},
                    {"term": "catl", "term_type": "custom", "enabled": True},
                ],
                "enterprise_profile": {},
            }
        )

        self.assertIn("宁德时代", profile["official_names"])
        self.assertIn("catl.com", profile["root_domains"])
        self.assertIn("catl", profile["english_aliases"])
        self.assertIn("catl", profile["short_alias_guard"])

    def test_enterprise_match_rejects_short_alias_without_anchor(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": ["zabbix", "eicc"],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "hasscc",
            "repositoryName": "catlink",
            "repositoryUrl": "https://github.com/hasscc/catlink",
            "filePath": "custom_components/catlink/config_flow.py",
            "fileUrl": "https://github.com/hasscc/catlink/blob/main/custom_components/catlink/config_flow.py",
            "title": "config_flow.py",
        }

        match = _evaluate_enterprise_match(profile, "catl", candidate, "password = user_input\nconfig flow")

        self.assertFalse(match["valid"])
        self.assertEqual("none", match["level"])

    def test_enterprise_match_accepts_subdomain_anchor(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": ["zabbix", "eicc"],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "DengMingXi777GZ",
            "repositoryName": "GPU_Monitor",
            "repositoryUrl": "https://github.com/DengMingXi777GZ/GPU_Monitor",
            "filePath": "app_red.py",
            "fileUrl": "https://github.com/DengMingXi777GZ/GPU_Monitor/blob/main/app_red.py",
            "title": "app_red.py",
        }
        code_text = 'ZABBIX_SERVER = "https://biz-eicc.catl.com"\nzapi.login(api_token=API_TOKEN)'

        match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        self.assertTrue(match["valid"])
        self.assertEqual("strong", match["level"])
        self.assertTrue(any(item["type"] == "subdomain" for item in match["anchors"]))

    def test_classify_code_hit_promotes_enterprise_token_and_system_access_to_high(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": ["zabbix", "eicc"],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "DengMingXi777GZ",
            "repositoryName": "GPU_Monitor",
            "repositoryUrl": "https://github.com/DengMingXi777GZ/GPU_Monitor",
            "filePath": "app_red.py",
            "fileUrl": "https://github.com/DengMingXi777GZ/GPU_Monitor/blob/main/app_red.py",
            "title": "app_red.py",
        }
        code_text = (
            'ZABBIX_SERVER = "https://biz-eicc.catl.com"\n'
            'API_TOKEN = "8b55d051c0b07beadbdf72c16482fe77350d93f0efcbdb6653b9bfe3b917ea23"\n'
            'zapi.login(api_token=API_TOKEN)'
        )
        enterprise_match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        result = _classify_code_hit(
            "catl.com",
            "app_red.py",
            code_text,
            ["token"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertEqual("high", result["severity"])
        self.assertTrue(result["credential_literal_detected"])
        self.assertTrue(result["system_access_detected"])

    def test_classify_code_hit_drops_false_positive_without_enterprise_anchor(self) -> None:
        result = _classify_code_hit(
            "catl",
            "creds.txt",
            "[default]\naws_secret_access_key=e7c19b6nXzRBeO1F5OtshpZLIL3bRuAA8hCti8HQ\naws_session_token=FwoGZXIvYXdzEEUaDBnB/jCATLI+W1vxCyLMAU3LHOf9uvcc66x2mVc",
            ["token", "ak_sk"],
            term_type="custom",
            enterprise_match={"valid": False, "level": "none", "anchors": [], "system_keywords": []},
        )

        self.assertIsNone(result)

    def test_classify_code_hit_downgrades_public_market_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "stock-tools",
            "repositoryUrl": "https://github.com/demo/stock-tools",
            "filePath": "tickers.py",
            "fileUrl": "https://github.com/demo/stock-tools/blob/main/tickers.py",
            "title": "tickers.py",
        }
        code_text = 'SYMBOL_MAP = {"宁德时代": "300750.SZ", "贵州茅台": "600519.SS"}\n# stock symbol mappings'
        enterprise_match = _evaluate_enterprise_match(profile, "宁德时代", candidate, code_text)

        result = _classify_code_hit(
            "宁德时代",
            "tickers.py",
            code_text,
            ["token", "password"],
            term_type="company_name",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])

    def test_classify_code_hit_downgrades_domain_inventory_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catlbattery.com"],
            "trusted_subdomain_patterns": ["*.catlbattery.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "cn-domain-list",
            "repositoryUrl": "https://github.com/demo/cn-domain-list",
            "filePath": "site/4.json",
            "fileUrl": "https://github.com/demo/cn-domain-list/blob/main/site/4.json",
            "title": "site/4.json",
        }
        code_text = '"casdk.cn",\n"catlbattery.com",\n"cb.com.cn",\n"example.org",\n"sample.net",'
        enterprise_match = _evaluate_enterprise_match(profile, "catlbattery.com", candidate, code_text)

        result = _classify_code_hit(
            "catlbattery.com",
            "site/4.json",
            code_text,
            ["token", "password"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])
        self.assertIn("域名清单/站点列表上下文", result["suppression_reasons"])

    def test_classify_code_hit_downgrades_public_company_directory_context(self) -> None:
        profile = {
            "official_names": ["星展银行"],
            "brand_aliases": [],
            "english_aliases": ["dbs"],
            "root_domains": ["dbs.com"],
            "trusted_subdomain_patterns": ["*.dbs.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["dbs"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "company-dir",
            "repositoryUrl": "https://github.com/demo/company-dir",
            "filePath": "data/preloadedData.js",
            "fileUrl": "https://github.com/demo/company-dir/blob/main/data/preloadedData.js",
            "title": "data/preloadedData.js",
        }
        code_text = (
            '"Standard Chartered@@www.standardchartered.com@http://www.glassdoor.com/Salary/Standard-Chartered-Salaries-E10238.htm",\n'
            '"DBS Group Holdings@@www.dbs.com@http://www.glassdoor.com/Salary/DBS-Group-Holdings-Salaries-E9444.htm",\n'
            '"Michelin@@www.michelin.com@http://www.glassdoor.com/Salary/Michelin-Salaries-E3294.htm",'
        )
        enterprise_match = _evaluate_enterprise_match(profile, "DBS.com", candidate, code_text)

        result = _classify_code_hit(
            "DBS.com",
            "data/preloadedData.js",
            code_text,
            ["token", "password"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])
        self.assertIn("公开参考数据集/字典上下文", result["suppression_reasons"])

    def test_classify_code_hit_downgrades_reference_catalog_context(self) -> None:
        profile = {
            "official_names": ["星展银行"],
            "brand_aliases": [],
            "english_aliases": ["dbs"],
            "root_domains": ["dbs.com"],
            "trusted_subdomain_patterns": ["*.dbs.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["dbs"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "bankcard",
            "repositoryUrl": "https://github.com/demo/bankcard",
            "filePath": "src/data/banks.ts",
            "fileUrl": "https://github.com/demo/bankcard/blob/main/src/data/banks.ts",
            "title": "src/data/banks.ts",
        }
        code_text = "{ code: 'ABC', name: '农业银行' },\n{ code: 'DBS', name: '星展银行' },\n{ code: 'ICBC', name: '工商银行' },"
        enterprise_match = _evaluate_enterprise_match(profile, "星展银行", candidate, code_text)

        result = _classify_code_hit(
            "星展银行",
            "src/data/banks.ts",
            code_text,
            ["token", "password"],
            term_type="company_name",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])
        self.assertIn("公开参考数据集/字典上下文", result["suppression_reasons"])

    def test_classify_code_hit_downgrades_location_reference_context(self) -> None:
        profile = {
            "official_names": ["星展银行"],
            "brand_aliases": [],
            "english_aliases": ["dbs"],
            "root_domains": ["dbs.com"],
            "trusted_subdomain_patterns": ["*.dbs.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["dbs"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "poi-map",
            "repositoryUrl": "https://github.com/demo/poi-map",
            "filePath": "js/app.js",
            "fileUrl": "https://github.com/demo/poi-map/blob/main/js/app.js",
            "title": "js/app.js",
        }
        code_text = (
            "{ title: '外滩', place_id: 'abc', location: { lat: 31.23, lng: 121.48 } },\n"
            "{ title: '星展银行', place_id: 'def', location: { lat: 31.24, lng: 121.50 } },\n"
            "{ title: '凯宾斯基酒店', place_id: 'ghi', location: { lat: 31.25, lng: 121.49 } },"
        )
        enterprise_match = _evaluate_enterprise_match(profile, "星展银行", candidate, code_text)

        result = _classify_code_hit(
            "星展银行",
            "js/app.js",
            code_text,
            ["token", "password"],
            term_type="company_name",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])
        self.assertIn("公开参考数据集/字典上下文", result["suppression_reasons"])

    def test_classify_code_hit_downgrades_keyword_corpus_context(self) -> None:
        profile = {
            "official_names": ["星展银行"],
            "brand_aliases": [],
            "english_aliases": ["dbs"],
            "root_domains": ["dbs.com"],
            "trusted_subdomain_patterns": ["*.dbs.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["dbs"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "keyword-corpus",
            "repositoryUrl": "https://github.com/demo/keyword-corpus",
            "filePath": "code/additional.py",
            "fileUrl": "https://github.com/demo/keyword-corpus/blob/main/code/additional.py",
            "title": "code/additional.py",
        }
        code_text = (
            "tags = [\n"
            "['暴雪娱乐'],\n"
            "['中信银行', '中信'],\n"
            "['星展银行', '星展银行香港分行'],\n"
            "['wind'],\n"
            "]"
        )
        enterprise_match = _evaluate_enterprise_match(profile, "星展银行", candidate, code_text)

        result = _classify_code_hit(
            "星展银行",
            "code/additional.py",
            code_text,
            ["token", "password"],
            term_type="company_name",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])
        self.assertIn("公开参考数据集/字典上下文", result["suppression_reasons"])

    def test_classify_code_hit_downgrades_contact_directory_email_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "seed-data",
            "repositoryUrl": "https://github.com/demo/seed-data",
            "filePath": "seed_demo_data.py",
            "fileUrl": "https://github.com/demo/seed-data/blob/main/seed_demo_data.py",
            "title": "seed_demo_data.py",
        }
        code_text = '"13800001002",\n"ligang@catl.com",\n"A",\n"13800001003",\n"hanmei@catl.com",\n"B",\ncontact = "email"'
        enterprise_match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        result = _classify_code_hit(
            "catl.com",
            "seed_demo_data.py",
            code_text,
            ["token", "password"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["suppressed"])
        self.assertEqual("suppressed", result["display_bucket"])
        self.assertEqual("low", result["severity"])

    def test_classify_code_hit_downgrades_auth_flow_variable_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "arjunz21",
            "repositoryName": "CATLPython",
            "repositoryUrl": "https://github.com/arjunz21/CATLPython",
            "filePath": "main.py",
            "fileUrl": "https://github.com/arjunz21/CATLPython/blob/main/main.py",
            "title": "main.py",
        }
        code_text = (
            'support = "support@catl.com"\n'
            'access_token = authenticapi.create_access_token(data={"sub": user["email"]})\n'
            'token = access_token\n'
            'password = user_input\n'
            'raise HTTPException(detail="Incorrect Username or Password")'
        )
        enterprise_match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        result = _classify_code_hit(
            "catl.com",
            "main.py",
            code_text,
            ["token", "password"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertEqual("low", result["severity"])
        self.assertLessEqual(result["risk_score"], 28)

    def test_classify_code_hit_downgrades_config_flow_password_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "hasscc",
            "repositoryName": "catlink",
            "repositoryUrl": "https://github.com/hasscc/catlink",
            "filePath": "custom_components/catlink/config_flow.py",
            "fileUrl": "https://github.com/hasscc/catlink/blob/main/custom_components/catlink/config_flow.py",
            "title": "config_flow.py",
        }
        code_text = (
            'class CatlinkConfigFlow(ConfigFlow):\n'
            '    async def async_step_user(self, user_input=None):\n'
            '        password = user_input[CONF_PASSWORD]\n'
            '        region = await discover_region(self.hass, phone_iac, phone_number, password)'
        )
        enterprise_match = _evaluate_enterprise_match(profile, "catl", candidate, code_text)

        result = _classify_code_hit(
            "catl",
            "custom_components/catlink/config_flow.py",
            code_text,
            ["password"],
            term_type="custom",
            enterprise_match=enterprise_match,
        )

        self.assertIsNone(result)

    def test_classify_code_hit_downgrades_hashed_password_seed_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "0ye0m",
            "repositoryName": "nexus-mes",
            "repositoryUrl": "https://github.com/0ye0m/nexus-mes",
            "filePath": "src/lib/db.ts",
            "fileUrl": "https://github.com/0ye0m/nexus-mes/blob/main/src/lib/db.ts",
            "title": "db.ts",
        }
        code_text = (
            "async function seedDatabase() {\n"
            " const hashedPassword = await bcrypt.hash('password123', 10)\n"
            " await db.user.createMany({ data: [{ email: 'info@catl.com', password: hashedPassword }] })\n"
            "}"
        )
        enterprise_match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        result = _classify_code_hit(
            "catl.com",
            "src/lib/db.ts",
            code_text,
            ["password"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertEqual("low", result["severity"])
        self.assertLessEqual(result["risk_score"], 24)

    def test_classify_code_hit_downgrades_local_default_config(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "gshkuang",
            "repositoryName": "agent_demo",
            "repositoryUrl": "https://github.com/gshkuang/agent_demo",
            "filePath": "api/main.py",
            "fileUrl": "https://github.com/gshkuang/agent_demo/blob/main/api/main.py",
            "title": "main.py",
        }
        code_text = 'REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")\ncompany = "宁德时代"'
        enterprise_match = _evaluate_enterprise_match(profile, "宁德时代", candidate, code_text)

        result = _classify_code_hit(
            "宁德时代",
            "api/main.py",
            code_text,
            ["redis_url"],
            term_type="company_name",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertEqual("low", result["severity"])
        self.assertLessEqual(result["risk_score"], 24)

    def test_classify_code_hit_downgrades_readme_context(self) -> None:
        profile = {
            "official_names": ["宁德时代"],
            "brand_aliases": [],
            "english_aliases": ["catl"],
            "root_domains": ["catl.com"],
            "trusted_subdomain_patterns": ["*.catl.com"],
            "internal_system_keywords": [],
            "negative_aliases": [],
            "short_alias_guard": ["catl"],
        }
        candidate = {
            "repositoryOwner": "demo",
            "repositoryName": "docs",
            "repositoryUrl": "https://github.com/demo/docs",
            "filePath": "README.md",
            "fileUrl": "https://github.com/demo/docs/blob/main/README.md",
            "title": "README.md",
        }
        code_text = 'Set API_KEY="example-token-value"\nContact support@catl.com for enterprise onboarding.'
        enterprise_match = _evaluate_enterprise_match(profile, "catl.com", candidate, code_text)

        result = _classify_code_hit(
            "catl.com",
            "README.md",
            code_text,
            ["api_key"],
            term_type="domain",
            enterprise_match=enterprise_match,
        )

        self.assertIsNotNone(result)
        self.assertEqual("low", result["severity"])
        self.assertLessEqual(result["risk_score"], 24)

    def test_collect_search_results_across_pages_merges_multiple_pages(self) -> None:
        platform = get_exposure_platform("github")

        with patch(
            "darkweb_collector.code_monitoring._fetch_code_search_page",
            side_effect=[
                {"html": "page-1", "url": "https://github.com/search?q=dbs&type=code"},
                {"html": "page-2", "url": "https://github.com/search?q=dbs&type=code&p=2"},
                {"html": "page-3", "url": "https://github.com/search?q=dbs&type=code&p=3"},
            ],
        ), patch(
            "darkweb_collector.code_monitoring._detect_code_search_issue",
            return_value="",
        ), patch(
            "darkweb_collector.code_monitoring._parse_code_search_results",
            side_effect=[
                [
                    {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "a.py", "fileUrl": "https://github.com/acme/repo/blob/main/a.py"},
                ],
                [
                    {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "a.py", "fileUrl": "https://github.com/acme/repo/blob/main/a.py"},
                    {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "b.py", "fileUrl": "https://github.com/acme/repo/blob/main/b.py"},
                ],
                [],
            ],
        ):
            rows, issue = _collect_search_results_across_pages(
                platform,
                "https://github.com/search?q=dbs&type=code",
                None,
                page_limit=3,
            )

        self.assertEqual("", issue)
        self.assertEqual(2, len(rows))
        self.assertEqual("a.py", rows[0]["filePath"])
        self.assertEqual("b.py", rows[1]["filePath"])

    def test_collect_search_results_incremental_advances_from_last_page(self) -> None:
        platform = get_exposure_platform("github")
        first_rows = [
            {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "a.py", "fileUrl": "https://github.com/acme/repo/blob/main/a.py"},
        ]
        previous_state = {
            "last_page_scanned": 2,
            "last_candidate_signature": _candidate_signature(first_rows),
            "last_candidate_keys_json": json.dumps(["https://github.com/acme/repo|main|a.py|https://github.com/acme/repo/blob/main/a.py"], ensure_ascii=False),
            "last_repository_urls_json": json.dumps(["https://github.com/acme/repo"], ensure_ascii=False),
        }

        with patch(
            "darkweb_collector.code_monitoring._fetch_code_search_page",
            side_effect=[
                {"html": "page-1", "url": "https://github.com/search?q=dbs&type=code"},
                {"html": "page-3", "url": "https://github.com/search?q=dbs&type=code&p=3"},
                {"html": "page-4", "url": "https://github.com/search?q=dbs&type=code&p=4"},
            ],
        ), patch(
            "darkweb_collector.code_monitoring._detect_code_search_issue",
            return_value="",
        ), patch(
            "darkweb_collector.code_monitoring._parse_code_search_results",
            side_effect=[
                first_rows,
                [
                    {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "b.py", "fileUrl": "https://github.com/acme/repo/blob/main/b.py"},
                ],
                [
                    {"repositoryUrl": "https://github.com/acme/new-repo", "branch": "main", "filePath": "c.py", "fileUrl": "https://github.com/acme/new-repo/blob/main/c.py"},
                ],
            ],
        ):
            rows, issue, next_state = _collect_search_results_incremental(
                platform,
                "https://github.com/search?q=dbs&type=code",
                None,
                page_limit=2,
                previous_state=previous_state,
            )

        self.assertEqual("", issue)
        self.assertEqual("incremental", next_state["cursor_mode"])
        self.assertEqual(4, next_state["last_page_scanned"])
        self.assertEqual(["b.py", "c.py"], [row["filePath"] for row in rows])
        self.assertIn("https://github.com/acme/new-repo", next_state["last_repository_urls_json"])

    def test_collect_search_results_incremental_resets_when_signature_changes(self) -> None:
        platform = get_exposure_platform("github")
        first_rows = [
            {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "a.py", "fileUrl": "https://github.com/acme/repo/blob/main/a.py"},
        ]

        with patch(
            "darkweb_collector.code_monitoring._fetch_code_search_page",
            side_effect=[
                {"html": "page-1", "url": "https://github.com/search?q=dbs&type=code"},
                {"html": "page-2", "url": "https://github.com/search?q=dbs&type=code&p=2"},
            ],
        ), patch(
            "darkweb_collector.code_monitoring._detect_code_search_issue",
            return_value="",
        ), patch(
            "darkweb_collector.code_monitoring._parse_code_search_results",
            side_effect=[
                first_rows,
                [
                    {"repositoryUrl": "https://github.com/acme/repo", "branch": "main", "filePath": "b.py", "fileUrl": "https://github.com/acme/repo/blob/main/b.py"},
                ],
            ],
        ):
            rows, issue, next_state = _collect_search_results_incremental(
                platform,
                "https://github.com/search?q=dbs&type=code",
                None,
                page_limit=2,
                previous_state={"last_page_scanned": 9, "last_candidate_signature": "outdated"},
            )

        self.assertEqual("", issue)
        self.assertEqual("full", next_state["cursor_mode"])
        self.assertEqual(2, next_state["last_page_scanned"])
        self.assertEqual(["a.py", "b.py"], [row["filePath"] for row in rows])

    def test_code_search_state_persists_by_query_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_code_search_state(
                        connection,
                        {
                            "watchlist_id": 7,
                            "platform": "github",
                            "term": "dbs.com",
                            "query_key": "base",
                            "last_page_scanned": 12,
                            "last_candidate_signature": "sig-base",
                            "last_candidate_keys_json": json.dumps(["base-key"], ensure_ascii=False),
                            "last_repository_urls_json": json.dumps(["https://github.com/acme/base"], ensure_ascii=False),
                            "last_run_started_at": "2026-06-11T00:00:00+00:00",
                            "last_run_finished_at": "2026-06-11T00:01:00+00:00",
                            "updated_at": "2026-06-11T00:01:00+00:00",
                        },
                    )
                    upsert_code_search_state(
                        connection,
                        {
                            "watchlist_id": 7,
                            "platform": "github",
                            "term": "dbs.com",
                            "query_key": "query:expanded1",
                            "last_page_scanned": 3,
                            "last_candidate_signature": "sig-expanded",
                            "last_candidate_keys_json": json.dumps(["expanded-key"], ensure_ascii=False),
                            "last_repository_urls_json": json.dumps(["https://github.com/acme/expanded"], ensure_ascii=False),
                            "last_run_started_at": "2026-06-11T00:02:00+00:00",
                            "last_run_finished_at": "2026-06-11T00:03:00+00:00",
                            "updated_at": "2026-06-11T00:03:00+00:00",
                        },
                    )
                    connection.commit()

                    base_state = get_code_search_state(
                        connection,
                        watchlist_id=7,
                        platform="github",
                        term="dbs.com",
                        query_key="base",
                    )
                    states = list_code_search_states(
                        connection,
                        watchlist_id=7,
                        platform="github",
                        term="dbs.com",
                    )

                self.assertIsNotNone(base_state)
                self.assertEqual(12, base_state["last_page_scanned"])
                self.assertEqual(2, len(states))
                self.assertEqual({"base", "query:expanded1"}, {row["query_key"] for row in states})

    def test_gitee_incremental_search_advances_from_previous_page(self) -> None:
        first_repo_rows = [
            {
                "repositoryUrl": "https://gitee.com/acme/repo-a",
                "branch": "",
                "filePath": "",
                "fileUrl": "https://gitee.com/acme/repo-a",
                "repositoryOwner": "acme",
                "repositoryName": "repo-a",
            }
        ]
        with patch(
            "darkweb_collector.code_monitoring._collect_gitee_repo_search_window",
            side_effect=[
                (first_repo_rows, 1),
                (
                    [
                        {
                            "repositoryUrl": "https://gitee.com/acme/repo-b",
                            "branch": "",
                            "filePath": "",
                            "fileUrl": "https://gitee.com/acme/repo-b",
                            "repositoryOwner": "acme",
                            "repositoryName": "repo-b",
                        }
                    ],
                    4,
                ),
            ],
        ) as collect_mock, patch(
            "darkweb_collector.code_monitoring._gitee_repo_candidates_to_code_results",
            return_value=[
                {
                    "repositoryUrl": "https://gitee.com/acme/repo-b",
                    "branch": "main",
                    "filePath": "b.py",
                    "fileUrl": "https://gitee.com/acme/repo-b/blob/main/b.py",
                }
            ],
        ):
            _, next_state = _gitee_repo_code_search_incremental(
                "dbs.com",
                ["py"],
                ["password"],
                page_limit=2,
                previous_state={
                    "last_page_scanned": 2,
                    "last_candidate_signature": _candidate_signature(first_repo_rows),
                    "last_candidate_keys_json": json.dumps([], ensure_ascii=False),
                    "last_repository_urls_json": json.dumps(["https://gitee.com/acme/repo-a"], ensure_ascii=False),
                },
            )

        self.assertEqual("incremental", next_state["cursor_mode"])
        self.assertEqual(4, next_state["last_page_scanned"])
        self.assertEqual(2, collect_mock.call_args_list[1].kwargs["page_count"])
        self.assertEqual(3, collect_mock.call_args_list[1].kwargs["start_page"])

    def test_http_get_json_retries_gitlab_ssl_transport_error(self) -> None:
        class FakeResponse:
            def __init__(self, body: str, url: str) -> None:
                self._body = body
                self._url = url

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return self._body.encode("utf-8")

            def geturl(self) -> str:
                return self._url

        with patch(
            "darkweb_collector.code_monitoring.urlopen",
            side_effect=[
                ssl.SSLError("EOF occurred in violation of protocol"),
                FakeResponse("[]", "https://gitlab.com/api/v4/projects?search=dbs"),
            ],
        ) as urlopen_mock:
            payload = _http_get_json(
                "https://gitlab.com/api/v4/projects?search=dbs",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=60,
                platform_key="gitlab",
                retries=1,
            )

        self.assertEqual([], payload)
        self.assertEqual(2, urlopen_mock.call_count)

    def test_collect_gitee_repo_search_window_raises_on_first_page_captcha(self) -> None:
        with patch(
            "darkweb_collector.code_monitoring._http_get_json",
            side_effect=RuntimeError("captcha_or_security_verification"),
        ):
            with self.assertRaisesRegex(RuntimeError, "captcha_or_security_verification"):
                _collect_gitee_repo_search_window("dbs.com", start_page=1, page_count=1)

    def test_gitee_blob_content_prefers_raw_endpoint(self) -> None:
        with patch(
            "darkweb_collector.code_monitoring._http_get_text",
            return_value='API_TOKEN = "abcdefghijklmnop123456"',
        ) as text_mock, patch(
            "darkweb_collector.code_monitoring._http_get_json",
        ) as json_mock:
            text = _gitee_blob_content("acme", "repo-a", "main", "src/app.py")

        self.assertIn("API_TOKEN", text)
        self.assertEqual(1, text_mock.call_count)
        self.assertEqual(0, json_mock.call_count)

    def test_gitee_repo_candidates_to_code_results_uses_branch_probe_and_raw_fetch(self) -> None:
        repo_candidate = {
            "repositoryOwner": "acme",
            "repositoryName": "repo-a",
            "repositoryUrl": "https://gitee.com/acme/repo-a",
            "branch": "",
        }
        with patch(
            "darkweb_collector.code_monitoring._gitee_repo_tree_with_branch",
            return_value=(
                "main",
                [
                    {"type": "blob", "path": "src/app.py"},
                    {"type": "blob", "path": "README.md"},
                ],
            ),
        ), patch(
            "darkweb_collector.code_monitoring._gitee_blob_content",
            side_effect=[
                'API_TOKEN = "abcdefghijklmnop123456"\nBASE_URL = "https://biz-eicc.catl.com"',
                "# readme",
            ],
        ):
            rows = _gitee_repo_candidates_to_code_results(
                [repo_candidate],
                "catl.com",
                ["py", "md"],
                ["token"],
            )

        self.assertEqual(1, len(rows))
        self.assertEqual("src/app.py", rows[0]["filePath"])
        self.assertEqual("https://gitee.com/acme/repo-a/blob/main/src/app.py", rows[0]["fileUrl"])

    def test_gitlab_repo_candidates_to_code_results_uses_public_tree_and_raw_api(self) -> None:
        repo_candidate = {
            "repositoryOwner": "acme",
            "repositoryName": "repo-a",
            "repositoryUrl": "https://gitlab.com/acme/repo-a",
            "projectId": 101,
            "branch": "main",
        }
        with patch(
            "darkweb_collector.code_monitoring._gitlab_repo_tree",
            return_value=[
                {"type": "blob", "path": "src/app.py"},
                {"type": "blob", "path": "README.md"},
            ],
        ), patch(
            "darkweb_collector.code_monitoring._gitlab_blob_content",
            side_effect=[
                'API_TOKEN = "abcdefghijklmnop123456"\nBASE_URL = "https://biz-eicc.catl.com"',
                "# readme",
            ],
        ):
            rows = _gitlab_repo_candidates_to_code_results(
                [repo_candidate],
                "catl.com",
                ["py", "md"],
                ["token"],
                10,
            )

        self.assertEqual(1, len(rows))
        self.assertEqual("src/app.py", rows[0]["filePath"])
        self.assertEqual("https://gitlab.com/acme/repo-a/-/blob/main/src/app.py", rows[0]["fileUrl"])

    def test_gitlab_repo_fallback_code_search_uses_alias_query_candidates(self) -> None:
        repo_candidate = {
            "repositoryOwner": "acme",
            "repositoryName": "repo-a",
            "repositoryUrl": "https://gitlab.com/acme/repo-a",
            "projectId": 101,
            "branch": "main",
        }
        with patch(
            "darkweb_collector.code_monitoring._gitlab_repo_search",
            side_effect=lambda query, page_limit=1: [repo_candidate] if query == "catl" else [],
        ) as repo_search_mock, patch(
            "darkweb_collector.code_monitoring._gitlab_repo_candidates_to_code_results",
            return_value=[
                {
                    "repositoryOwner": "acme",
                    "repositoryName": "repo-a",
                    "repositoryUrl": "https://gitlab.com/acme/repo-a",
                    "branch": "main",
                    "filePath": "src/app.py",
                    "fileUrl": "https://gitlab.com/acme/repo-a/-/blob/main/src/app.py",
                }
            ],
        ):
            rows = _gitlab_repo_fallback_code_search(
                "catl.com",
                None,
                ["py"],
                ["token"],
                10,
                query_terms=["catl.com", "catl"],
                page_limit=1,
            )

        self.assertEqual(1, len(rows))
        self.assertEqual(["catl.com", "catl"], [call.args[0] for call in repo_search_mock.call_args_list])

    def test_gitlab_repo_fallback_code_search_raises_ssl_issue_when_no_results(self) -> None:
        with patch(
            "darkweb_collector.code_monitoring._gitlab_repo_search",
            return_value=[
                {
                    "repositoryOwner": "acme",
                    "repositoryName": "repo-a",
                    "repositoryUrl": "https://gitlab.com/acme/repo-a",
                }
            ],
        ), patch(
            "darkweb_collector.code_monitoring._gitlab_repo_candidates_to_code_results",
            side_effect=RuntimeError("ssl_transport_error"),
        ), patch(
            "darkweb_collector.code_monitoring._gitlab_project_blob_search",
            side_effect=RuntimeError("ssl_transport_error"),
        ):
            with self.assertRaisesRegex(RuntimeError, "ssl_transport_error"):
                _gitlab_repo_fallback_code_search(
                    "dbs.com",
                    None,
                    ["py"],
                    ["token"],
                    10,
                    page_limit=1,
                )

    def test_scan_run_payload_exposes_clue_and_sensitive_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "Scan Payload Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py"],
                        "search_page_limit": 2,
                        "detail_fetch": True,
                        "enabled_rule_keys": ["password"],
                        "terms": [{"term": "Acme", "term_type": "company_name", "enabled": True}],
                    }
                )
                with get_db_connection() as connection:
                    insert_code_scan_run(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platforms_json": json.dumps(["github"], ensure_ascii=False),
                            "requested_terms_json": json.dumps(["Acme"], ensure_ascii=False),
                            "candidate_count": 12,
                            "hit_count": 5,
                            "clue_hit_count": 3,
                            "sensitive_hit_count": 2,
                            "error_count": 1,
                            "status": "partial",
                            "errors_json": json.dumps(["demo"], ensure_ascii=False),
                            "started_at": "2026-06-10T00:00:00+00:00",
                            "finished_at": "2026-06-10T00:10:00+00:00",
                        },
                    )
                    connection.commit()

                payloads = list_code_scan_runs_payload(int(watchlist["id"]), limit=5)
                self.assertEqual(1, len(payloads))
                self.assertEqual(3, payloads[0]["clueHitCount"])
                self.assertEqual(2, payloads[0]["sensitiveHitCount"])

    def test_delete_code_watchlist_payload_removes_related_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "Delete Me",
                        "organization_name": "Acme",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["token"],
                        "terms": [{"term": "acme.com", "term_type": "domain", "enabled": True}],
                        "enterprise_profile": {"root_domains": ["acme.com"]},
                    }
                )
                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "repo",
                            "repository_owner": "owner",
                            "repository_url": "https://github.com/owner/repo",
                            "file_path": "main.py",
                            "branch": "main",
                            "file_url": "https://github.com/owner/repo/blob/main/main.py",
                            "visibility": "public",
                            "language": "Python",
                            "sensitive_type": "token",
                            "matched_rule": "访问 Token",
                            "matched_term": "acme.com",
                            "result_layer": "sensitive",
                            "risk_score": 66,
                            "severity": "high",
                            "first_seen_at": "2026-06-12T00:00:00+00:00",
                            "last_seen_at": "2026-06-12T00:00:00+00:00",
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    snapshot_id = insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-12T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=acme.com&type=code",
                            "page_url": "https://github.com/owner/repo/blob/main/main.py",
                            "html_path": "",
                            "screenshot_path": "",
                            "code_fragment": "TOKEN='abc12345678901234567890'",
                            "masked_fragment": "TOKEN='abc***7890'",
                            "raw_artifact_path": "",
                            "line_start": 1,
                            "line_end": 1,
                            "language": "Python",
                            "findings_json": json.dumps([], ensure_ascii=False),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    update_code_hit_last_snapshot(connection, hit_id, snapshot_id)
                    insert_code_scan_run(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platforms_json": json.dumps(["github"], ensure_ascii=False),
                            "requested_terms_json": json.dumps(["acme.com"], ensure_ascii=False),
                            "candidate_count": 1,
                            "hit_count": 1,
                            "clue_hit_count": 0,
                            "sensitive_hit_count": 1,
                            "error_count": 0,
                            "status": "succeeded",
                            "errors_json": json.dumps([], ensure_ascii=False),
                            "started_at": "2026-06-12T00:00:00+00:00",
                            "finished_at": "2026-06-12T00:00:01+00:00",
                        },
                    )
                    upsert_code_search_state(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "term": "acme.com",
                            "query_key": "base",
                            "last_page_scanned": 3,
                            "last_candidate_signature": "sig",
                            "last_candidate_keys_json": json.dumps([], ensure_ascii=False),
                            "last_repository_urls_json": json.dumps([], ensure_ascii=False),
                            "last_run_started_at": "2026-06-12T00:00:00+00:00",
                            "last_run_finished_at": "2026-06-12T00:00:01+00:00",
                            "updated_at": "2026-06-12T00:00:01+00:00",
                        },
                    )
                    connection.commit()

                result = delete_code_watchlist_payload(int(watchlist["id"]))
                self.assertTrue(result["removed"])

                with get_db_connection() as connection:
                    self.assertIsNone(connection.execute("select id from code_watchlists where id=?", (int(watchlist["id"]),)).fetchone())
                    self.assertIsNone(connection.execute("select id from code_watch_terms where watchlist_id=?", (int(watchlist["id"]),)).fetchone())
                    self.assertIsNone(connection.execute("select id from code_hits where watchlist_id=?", (int(watchlist["id"]),)).fetchone())
                    self.assertIsNone(connection.execute("select id from code_hit_snapshots where hit_id=?", (hit_id,)).fetchone())
                    self.assertIsNone(connection.execute("select id from code_scan_runs where watchlist_id=?", (int(watchlist["id"]),)).fetchone())
                    self.assertIsNone(connection.execute("select id from code_search_states where watchlist_id=?", (int(watchlist["id"]),)).fetchone())

    def test_list_code_hits_payload_can_include_suppressed_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "Suppressed View Watch",
                        "organization_name": "宁德时代",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["token", "password"],
                        "terms": [{"term": "catl.com", "term_type": "domain", "enabled": True}],
                        "enterprise_profile": {
                            "official_names": ["宁德时代"],
                            "english_aliases": ["catl"],
                            "root_domains": ["catl.com"],
                            "trusted_subdomain_patterns": ["*.catl.com"],
                            "short_alias_guard": ["catl"],
                        },
                    }
                )
                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "seed-data",
                            "repository_owner": "demo",
                            "repository_url": "https://github.com/demo/seed-data",
                            "file_path": "seed_demo_data.py",
                            "branch": "main",
                            "file_url": "https://github.com/demo/seed-data/blob/main/seed_demo_data.py",
                            "visibility": "public",
                            "language": "Python",
                            "sensitive_type": "clue",
                            "matched_rule": "关键词线索",
                            "matched_term": "catl.com",
                            "result_layer": "clue",
                            "risk_score": 69,
                            "severity": "high",
                            "first_seen_at": "2026-06-15T00:00:00+00:00",
                            "last_seen_at": "2026-06-15T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "repositoryOwner": "demo",
                                        "repositoryName": "seed-data",
                                        "repositoryUrl": "https://github.com/demo/seed-data",
                                        "filePath": "seed_demo_data.py",
                                        "fileUrl": "https://github.com/demo/seed-data/blob/main/seed_demo_data.py",
                                        "title": "seed_demo_data.py",
                                    },
                                    "code_text": '"13800001002",\n"ligang@catl.com",\n"A",\ncontact = "email"',
                                    "term_type": "domain",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-15T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=catl.com&type=code",
                            "page_url": "https://github.com/demo/seed-data/blob/main/seed_demo_data.py",
                            "html_path": "",
                            "screenshot_path": "",
                            "code_fragment": "",
                            "masked_fragment": "",
                            "raw_artifact_path": "",
                            "line_start": 1,
                            "line_end": 4,
                            "language": "Python",
                            "findings_json": json.dumps([], ensure_ascii=False),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    connection.commit()

                primary = list_code_hits_payload(watchlist_id=int(watchlist["id"]), include_suppressed=False, limit=20)
                with_suppressed = list_code_hits_payload(watchlist_id=int(watchlist["id"]), include_suppressed=True, limit=20)

                self.assertEqual([], primary)
                self.assertEqual(1, len(with_suppressed))
                self.assertTrue(with_suppressed[0]["suppressed"])
                self.assertEqual("suppressed", with_suppressed[0]["displayBucket"])

    def test_build_code_monitoring_summary_counts_suppressed_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "Summary Watch",
                        "organization_name": "宁德时代",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py", "json"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["token", "password"],
                        "terms": [{"term": "catl.com", "term_type": "domain", "enabled": True}],
                        "enterprise_profile": {
                            "official_names": ["宁德时代"],
                            "english_aliases": ["catl"],
                            "root_domains": ["catl.com", "catlbattery.com"],
                            "trusted_subdomain_patterns": ["*.catl.com"],
                            "short_alias_guard": ["catl"],
                        },
                    }
                )
                with get_db_connection() as connection:
                    primary_hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "GPU_Monitor",
                            "repository_owner": "demo",
                            "repository_url": "https://github.com/demo/GPU_Monitor",
                            "file_path": "app_red.py",
                            "branch": "main",
                            "file_url": "https://github.com/demo/GPU_Monitor/blob/main/app_red.py",
                            "visibility": "public",
                            "language": "Python",
                            "sensitive_type": "token",
                            "matched_rule": "访问 Token",
                            "matched_term": "catl.com",
                            "result_layer": "sensitive",
                            "risk_score": 76,
                            "severity": "high",
                            "first_seen_at": "2026-06-15T00:00:00+00:00",
                            "last_seen_at": "2026-06-15T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "repositoryOwner": "demo",
                                        "repositoryName": "GPU_Monitor",
                                        "repositoryUrl": "https://github.com/demo/GPU_Monitor",
                                        "filePath": "app_red.py",
                                        "fileUrl": "https://github.com/demo/GPU_Monitor/blob/main/app_red.py",
                                        "title": "app_red.py",
                                    },
                                    "code_text": 'ZABBIX_SERVER="https://biz-eicc.catl.com"\nAPI_TOKEN="secret-token-value"\nzapi.login(api_token=API_TOKEN)',
                                    "term_type": "domain",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": primary_hit_id,
                            "fetched_at": "2026-06-15T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=catl.com&type=code",
                            "page_url": "https://github.com/demo/GPU_Monitor/blob/main/app_red.py",
                            "html_path": "",
                            "screenshot_path": "",
                            "code_fragment": "",
                            "masked_fragment": "",
                            "raw_artifact_path": "",
                            "line_start": 1,
                            "line_end": 3,
                            "language": "Python",
                            "findings_json": json.dumps([], ensure_ascii=False),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )

                    suppressed_hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "cn-domain-list",
                            "repository_owner": "demo",
                            "repository_url": "https://github.com/demo/cn-domain-list",
                            "file_path": "site/4.json",
                            "branch": "main",
                            "file_url": "https://github.com/demo/cn-domain-list/blob/main/site/4.json",
                            "visibility": "public",
                            "language": "JSON",
                            "sensitive_type": "clue",
                            "matched_rule": "关键词线索",
                            "matched_term": "catlbattery.com",
                            "result_layer": "clue",
                            "risk_score": 18,
                            "severity": "low",
                            "first_seen_at": "2026-06-15T00:00:00+00:00",
                            "last_seen_at": "2026-06-15T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "repositoryOwner": "demo",
                                        "repositoryName": "cn-domain-list",
                                        "repositoryUrl": "https://github.com/demo/cn-domain-list",
                                        "filePath": "site/4.json",
                                        "fileUrl": "https://github.com/demo/cn-domain-list/blob/main/site/4.json",
                                        "title": "site/4.json",
                                    },
                                    "code_text": '"casdk.cn",\n"catlbattery.com",\n"cb.com.cn",\n"example.org",\n"sample.net",',
                                    "term_type": "domain",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": suppressed_hit_id,
                            "fetched_at": "2026-06-15T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=catlbattery.com&type=code",
                            "page_url": "https://github.com/demo/cn-domain-list/blob/main/site/4.json",
                            "html_path": "",
                            "screenshot_path": "",
                            "code_fragment": "",
                            "masked_fragment": "",
                            "raw_artifact_path": "",
                            "line_start": 1,
                            "line_end": 5,
                            "language": "JSON",
                            "findings_json": json.dumps([], ensure_ascii=False),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    connection.commit()

                payload = build_code_monitoring_summary()

                self.assertEqual(2, payload["totalHits"])
                self.assertEqual(1, payload["primaryHitCount"])
                self.assertEqual(1, payload["suppressedHitCount"])
                self.assertEqual(1, payload["sensitiveSnippetCount"])
                self.assertEqual(1, payload["clueHitCount"])
                self.assertEqual(2, payload["platformDistribution"][0]["value"])

    def test_code_monitoring_continuous_dispatch_start_and_stop(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_code_watchlists_payload",
            return_value=[{"id": 7, "name": "定向对象", "enabled": True}],
        ), patch(
            "darkweb_collector.api_actions._run_code_monitoring_once_for_watchlist",
            return_value={"watchlist_count": 1, "candidate_count": 0, "hit_count": 0, "clue_hit_count": 0, "sensitive_hit_count": 0, "errors": [], "results": []},
        ):
            started = api_actions.start_code_monitoring_dispatch(interval_seconds=1, watchlist_id=7)
            time.sleep(0.1)
            status = api_actions.get_code_monitoring_continuous_status(watchlist_id=7)
            stopped = api_actions.stop_code_monitoring_dispatch(watchlist_id=7)

        self.assertTrue(started["enabled"])
        self.assertTrue(status["enabled"] or started["enabled"])
        self.assertEqual(7, started["target_watchlist_id"])
        self.assertEqual("定向对象", started["target_watchlist_name"])
        self.assertFalse(stopped["enabled"])

    def test_code_monitoring_continuous_run_scopes_to_selected_watchlist(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_code_watchlists_payload",
            return_value=[
                {"id": 1, "name": "对象一", "enabled": True, "platforms": ["github"], "file_extensions": ["py"], "detail_fetch": True, "enabled_rule_keys": ["token"]},
                {"id": 2, "name": "对象二", "enabled": True, "platforms": ["gitlab"], "file_extensions": ["js"], "detail_fetch": False, "enabled_rule_keys": ["password"]},
            ],
        ), patch(
            "darkweb_collector.api_actions.scan_code_watchlist_once",
            return_value={"candidates": 3, "hits": 1, "clue_hits": 1, "sensitive_hits": 0, "errors": []},
        ) as scan_mock:
            result = api_actions._run_code_monitoring_once_for_watchlist(2)

        self.assertEqual(1, result["watchlist_count"])
        scan_mock.assert_called_once()
        self.assertEqual(2, scan_mock.call_args.args[0])

    def test_code_monitoring_continuous_dispatch_supports_multiple_watchlists(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_code_watchlists_payload",
            return_value=[
                {"id": 1, "name": "对象一", "enabled": True},
                {"id": 3, "name": "对象三", "enabled": True},
            ],
        ), patch(
            "darkweb_collector.api_actions._run_code_monitoring_once_for_watchlist",
            return_value={"watchlist_count": 1, "candidate_count": 0, "hit_count": 0, "clue_hit_count": 0, "sensitive_hit_count": 0, "errors": [], "results": []},
        ):
            started_one = api_actions.start_code_monitoring_dispatch(interval_seconds=1, watchlist_id=1)
            started_two = api_actions.start_code_monitoring_dispatch(interval_seconds=1, watchlist_id=3)
            time.sleep(0.1)
            status_one = api_actions.get_code_monitoring_continuous_status(watchlist_id=1)
            status_two = api_actions.get_code_monitoring_continuous_status(watchlist_id=3)
            api_actions.stop_code_monitoring_dispatch(watchlist_id=1)
            api_actions.stop_code_monitoring_dispatch(watchlist_id=3)

        self.assertTrue(started_one["enabled"])
        self.assertTrue(started_two["enabled"])
        self.assertEqual(2, status_one["active_watchlist_count"])
        self.assertEqual(2, status_two["active_watchlist_count"])
        self.assertEqual(1, status_one["target_watchlist_id"])
        self.assertEqual(3, status_two["target_watchlist_id"])

    def test_candidate_snippet_reclassifies_clue_when_snapshot_text_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "星展银行",
                        "organization_name": "星展银行",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["js"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["password"],
                        "terms": [
                            {"term": "DBS.com", "term_type": "domain", "enabled": True},
                        ],
                    }
                )

                snippet_text = "const admin = 'admin@dbs.com';\nconst password = 'Sup3rSecretValue123';"
                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "chromeExt_BH_ShowMeOffer",
                            "repository_owner": "binghuan",
                            "repository_url": "https://github.com/binghuan/chromeExt_BH_ShowMeOffer",
                            "file_path": "data/preloadedData.js",
                            "branch": "main",
                            "file_url": "https://github.com/binghuan/chromeExt_BH_ShowMeOffer/blob/main/data/preloadedData.js",
                            "visibility": "public",
                            "language": "JavaScript",
                            "sensitive_type": "clue",
                            "matched_rule": "关键词线索",
                            "matched_term": "DBS.com",
                            "result_layer": "clue",
                            "risk_score": 16,
                            "severity": "low",
                            "first_seen_at": "2026-06-15T00:00:00+00:00",
                            "last_seen_at": "2026-06-15T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "platform": "github",
                                        "platformLabel": "GitHub",
                                        "fileUrl": "https://github.com/binghuan/chromeExt_BH_ShowMeOffer/blob/main/data/preloadedData.js",
                                        "title": "data/preloadedData.js",
                                        "repositoryOwner": "binghuan",
                                        "repositoryName": "chromeExt_BH_ShowMeOffer",
                                        "repositoryUrl": "https://github.com/binghuan/chromeExt_BH_ShowMeOffer",
                                        "branch": "main",
                                        "filePath": "data/preloadedData.js",
                                        "snippetText": snippet_text,
                                    },
                                    "term_type": "domain",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    connection.commit()

                detail = build_code_hit_detail(int(hit_id))
                rows = list_code_hits_payload(watchlist_id=int(watchlist["id"]), include_suppressed=True, limit=20)

                self.assertEqual("sensitive", detail["resultLayer"])
                self.assertEqual("password", detail["sensitiveType"])
                self.assertTrue(detail["findings"])
                self.assertIn("admin@dbs.com", detail["codePreview"])
                self.assertEqual("sensitive", rows[0]["resultLayer"])
                self.assertEqual("password", rows[0]["sensitiveType"])

    def test_build_code_hit_detail_rebuilds_preview_and_context_from_snapshot_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            html_path = output_root / "code_monitoring" / "watchlist" / "github" / "DBS.com" / "AutoMoneyCollection-app.py.html"
            artifact_path = output_root / "code_monitoring" / "watchlist" / "github" / "DBS.com" / "AutoMoneyCollection-app.py.json"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                """
                <html><body>
                <div id="LC31" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'password'</span> : <span class="pl-s1">PASSWORD</span> ,
                </div>
                <div id="LC32" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'search_query'</span> : [ <span class="pl-s">'FROM'</span> , <span class="pl-s">'ibanking.alert@dbs.com'</span> , <span class="pl-s">'SUBJECT'</span> , <span class="pl-s">'Transaction Alerts'</span> , <span class="pl-s">'SINCE'</span> , <span class="pl-s1">collection_date</span> ],
                </div>
                <div id="LC33" class="react-code-text react-code-line-contents-no-virtualization react-file-line html-div ">
                  <span class="pl-s">'output_file_path'</span> : <span class="pl-s">f'{{excel_filename}}.xlsx'</span>
                </div>
                </body></html>
                """,
                encoding="utf-8",
            )
            artifact_path.write_text(
                json.dumps(
                    {
                        "candidate": {
                            "platform": "github",
                            "platformLabel": "GitHub",
                            "fileUrl": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "title": "app.py",
                            "repositoryOwner": "keithgzx",
                            "repositoryName": "AutoMoneyCollection",
                            "repositoryUrl": "https://github.com/keithgzx/AutoMoneyCollection",
                            "branch": "main",
                            "filePath": "app.py",
                            "lineStart": 32,
                            "lineEnd": 32,
                        },
                        "findings": [
                            {
                                "ruleKey": "password",
                                "label": "账号口令",
                                "secretLike": True,
                                "weight": 20,
                                "start": 100,
                                "end": 121,
                                "value": "PASSWORD = os.getenv(",
                                "excerpt": "PASSWORD = os.getenv(",
                            }
                        ],
                        "code_fragment": "featureFlags and layout shell noise",
                        "masked_fragment": "featureFlags and layout shell noise",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_code_watchlist_payload(
                    {
                        "name": "星展银行",
                        "organization_name": "星展银行",
                        "enabled": True,
                        "notes": "",
                        "platforms": ["github"],
                        "file_extensions": ["py"],
                        "detail_fetch": True,
                        "enabled_rule_keys": ["password"],
                        "terms": [
                            {"term": "DBS.com", "term_type": "domain", "enabled": True},
                        ],
                    }
                )

                with get_db_connection() as connection:
                    hit_id = upsert_code_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "github",
                            "repository_name": "AutoMoneyCollection",
                            "repository_owner": "keithgzx",
                            "repository_url": "https://github.com/keithgzx/AutoMoneyCollection",
                            "file_path": "app.py",
                            "branch": "main",
                            "file_url": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "visibility": "public",
                            "language": "Python",
                            "sensitive_type": "password",
                            "matched_rule": "账号口令",
                            "matched_term": "DBS.com",
                            "risk_score": 10,
                            "severity": "low",
                            "first_seen_at": "2026-06-10T00:00:00+00:00",
                            "last_seen_at": "2026-06-10T00:00:00+00:00",
                            "raw_json": json.dumps(
                                {
                                    "candidate": {
                                        "platform": "github",
                                        "platformLabel": "GitHub",
                                        "fileUrl": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                                        "title": "app.py",
                                        "repositoryOwner": "keithgzx",
                                        "repositoryName": "AutoMoneyCollection",
                                        "repositoryUrl": "https://github.com/keithgzx/AutoMoneyCollection",
                                        "branch": "main",
                                        "filePath": "app.py",
                                        "lineStart": 32,
                                        "lineEnd": 32,
                                    },
                                    "masked_fragment": "featureFlags and layout shell noise",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    snapshot_id = insert_code_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-10T00:00:00+00:00",
                            "search_url": "https://github.com/search?q=DBS.com&type=code",
                            "page_url": "https://github.com/keithgzx/AutoMoneyCollection/blob/main/app.py#L32",
                            "html_path": str(html_path),
                            "screenshot_path": "",
                            "code_fragment": "featureFlags and layout shell noise",
                            "masked_fragment": "featureFlags and layout shell noise",
                            "raw_artifact_path": str(artifact_path),
                            "line_start": 32,
                            "line_end": 32,
                            "language": "Python",
                            "findings_json": json.dumps(
                                [
                                    {
                                        "ruleKey": "password",
                                        "label": "账号口令",
                                        "secretLike": True,
                                        "weight": 20,
                                        "start": 100,
                                        "end": 121,
                                        "value": "PASSWORD = os.getenv(",
                                        "excerpt": "PASSWORD = os.getenv(",
                                    }
                                ],
                                ensure_ascii=False,
                            ),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    update_code_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()

                detail = build_code_hit_detail(int(hit_id))

                self.assertIn("ibanking.alert@dbs.com", detail["codePreview"])
                self.assertNotIn("featureFlags", detail["codePreview"])
                self.assertLessEqual(len(detail["codePreview"].splitlines()), 3)
                self.assertTrue(detail["matchedTermContexts"])
                self.assertIn("ibanking.alert@dbs.com", detail["matchedTermContexts"][0]["text"])
                self.assertEqual(31, detail["matchedTermContexts"][0]["lineStart"])
                self.assertEqual(33, detail["matchedTermContexts"][0]["lineEnd"])


if __name__ == "__main__":
    unittest.main()
