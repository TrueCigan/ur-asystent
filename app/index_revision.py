"""File-index revisions. The server still reads data/index.npz and does not build it.

A revision is a directory under <root>/revisions/<id>. Publishing the same
documents again returns the existing id. CURRENT is replaced atomically.
Rollback only moves that pointer. Postgres is not involved.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


class RevisionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def document_digest(docs: list[dict]) -> str:
    rows = sorted(docs, key=lambda row: (row.get("url") or "", row.get("text") or ""))
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def current_id(root: Path) -> str | None:
    path = root / "CURRENT"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def publish(root: Path, docs: list[dict], build) -> str:
    """Import docs. Identical content does not create a second revision."""
    root = Path(root)
    digest = document_digest(docs)
    rev = digest[:20]
    dest = root / "revisions" / rev
    manifest = dest / "manifest.json"
    if manifest.is_file():
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        if recorded.get("sha256") != digest:
            raise RevisionError("hash_mismatch")
        _atomic_write(root / "CURRENT", rev + "\n")
        return rev
    staging = root / ".staging" / rev
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        build(staging, docs)
        _atomic_write(
            staging / "manifest.json",
            json.dumps({"id": rev, "sha256": digest, "documents": len(docs)}, sort_keys=True) + "\n",
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, dest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _atomic_write(root / "CURRENT", rev + "\n")
    return rev


def rollback(root: Path, rev: str) -> str | None:
    root = Path(root)
    manifest = root / "revisions" / rev / "manifest.json"
    if not manifest.is_file():
        raise RevisionError("missing_revision")
    previous = current_id(root)
    _atomic_write(root / "CURRENT", rev + "\n")
    return previous


def activate(root: Path, runtime_dir: Path, rev: str | None = None) -> None:
    """Copy one published revision onto the filenames the server already reads.

    Does nothing to git. Caller chooses a runtime directory. Missing index
    files are an error rather than a silent keep of a stale snapshot.
    """
    root = Path(root)
    rev = rev or current_id(root)
    if not rev:
        raise RevisionError("missing_revision")
    source = root / "revisions" / rev
    if not (source / "manifest.json").is_file():
        raise RevisionError("missing_revision")
    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.npz", "meta.json.gz"):
        src = source / name
        if not src.is_file():
            raise RevisionError("missing_artifact")
        tmp = runtime_dir / (name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, runtime_dir / name)
