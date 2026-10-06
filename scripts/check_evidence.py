"""Verify immutable publication files and the recovered prediction supplement."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "evidence/import-manifest.json").read_text())
checked = 0
for item in manifest["files"]:
    # Maintained code and README are expected to evolve; publication bytes are not.
    if not item["path"].startswith(("article/", "downloads/")):
        continue
    relative = "article/published-original.md" if item["path"] == "article/original.md" else item["path"]
    path = ROOT / relative
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(f"Historical publication checksum mismatch: {item['path']}")
    checked += 1
for item in json.loads((ROOT / "evidence/recovered-original-results/recovery-manifest.json").read_text())["files"]:
    path = ROOT / "evidence/recovered-original-results" / item["name"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(f"Recovered artifact checksum mismatch: {item['name']}")
    checked += 1
if checked < 3:
    raise SystemExit("Insufficient immutable files found in provenance manifests")
print(f"Verified {checked} immutable historical evidence files")
