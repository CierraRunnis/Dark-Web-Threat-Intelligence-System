#!/usr/bin/env python3
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def load_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Generate a parser/import scaffold for a new site.")
    parser.add_argument("--site", required=True, help="Human-friendly site name or slug")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    site_name = slugify(args.site)
    if not site_name:
        raise SystemExit("site name resolved to an empty slug")

    parser_template = load_template("site_parser.py.tpl").replace("{{SITE_NAME}}", site_name)
    import_template = load_template("import_script.py.tpl").replace("{{SITE_NAME}}", site_name)

    parser_path = ROOT / "src" / "darkweb_collector" / "sites" / f"{site_name}.py"
    import_path = ROOT / "scripts" / f"import_{site_name}_sample.py"
    sample_dir = ROOT / "samples" / site_name
    readme_path = sample_dir / "README.md"

    created_parser = write_if_missing(parser_path, parser_template)
    created_import = write_if_missing(import_path, import_template)
    sample_dir.mkdir(parents=True, exist_ok=True)
    if not readme_path.exists():
        readme_path.write_text(
            "\n".join(
                [
                    f"# {site_name} samples",
                    "",
                    "Put authorized HTML samples here, for example:",
                    "",
                    "- homepage.html",
                    "- list_page_1.html",
                    "- detail_example.html",
                    "",
                    "Then update the generated parser under `src/darkweb_collector/sites/`.",
                ]
            ),
            encoding="utf-8",
        )

    print(f"site_name={site_name}")
    print(f"parser_created={created_parser} path={parser_path}")
    print(f"import_script_created={created_import} path={import_path}")
    print(f"samples_dir={sample_dir}")
    print("")
    print("Next steps:")
    print(f"1. Register `{site_name}` in src/darkweb_collector/sites/registry.py")
    print(f"2. Replace the placeholder regex in {parser_path.name}")
    print(f"3. Drop authorized HTML samples into {sample_dir}")
    print(f"4. Run {import_path.name} against a sample HTML file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
