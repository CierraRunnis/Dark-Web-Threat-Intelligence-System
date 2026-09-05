"""Install only the listed AI aggregation plugins. Configuration is never copied."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

BUNDLE = Path(__file__).resolve().parents[1]


def install(bundle: Path, flocks_home: Path, *, dry_run: bool = False, overwrite: bool = False) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    planned, unchanged, conflicts = [], [], []
    target_root = flocks_home.expanduser().resolve()
    for record in manifest["plugin_files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "plugins":
            raise ValueError("Invalid plugin path")
        source = bundle / relative
        destination = target_root / relative
        if not source.resolve().is_relative_to((bundle / "plugins").resolve()) or not destination.resolve().is_relative_to(target_root):
            raise ValueError("Plugin path leaves the selected directory")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Plugin checksum mismatch: {relative}")
        if destination.exists():
            if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
                unchanged.append(relative.as_posix())
                continue
            if not overwrite or not destination.is_file():
                conflicts.append(relative.as_posix())
                continue
        planned.append((source, destination))
    # Check every conflict before the first write, so a conflict cannot leave a partial install.
    if conflicts:
        raise FileExistsError("Existing plugins differ; review before using --overwrite: " + ", ".join(conflicts))
    if not dry_run:
        for source, destination in planned:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return {"target": str(target_root / "plugins"), "dry_run": dry_run, "copied_or_planned": len(planned), "unchanged": len(unchanged)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flocks-home", type=Path, default=Path.home() / ".flocks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(BUNDLE, args.flocks_home, dry_run=args.dry_run, overwrite=args.overwrite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
