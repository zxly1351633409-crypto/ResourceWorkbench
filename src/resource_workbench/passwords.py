from __future__ import annotations

import re
from pathlib import Path


def infer_archive_passwords(archive_path: Path) -> list[str]:
    """Infer likely passwords from archive/folder names.

    Current user rule: passwords are often the characters/numbers after `_` in
    the folder that contains the archive. We also include obvious numeric tails
    as fallback candidates.
    """
    candidates: list[str] = [""]
    texts = [
        archive_path.parent.name,
        archive_path.parent.parent.name if archive_path.parent.parent else "",
        archive_path.stem,
    ]

    for text in texts:
        candidates.extend(_underscore_suffixes(text))
        candidates.extend(_numeric_suffixes(text))
        candidates.extend(_compact_alnum_suffixes(text))

    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        item = item.strip()
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result[:12]


def _underscore_suffixes(text: str) -> list[str]:
    if "_" not in text:
        return []
    parts = [part.strip() for part in text.split("_") if part.strip()]
    suffixes = parts[1:] + parts[-1:]
    return [item for item in suffixes if 2 <= len(item) <= 32]


def _numeric_suffixes(text: str) -> list[str]:
    matches = re.findall(r"(?<!\d)(\d{4,16})(?!\d)", text)
    return matches[-3:]


def _compact_alnum_suffixes(text: str) -> list[str]:
    matches = re.findall(r"[_\-\s]([A-Za-z0-9]{4,32})$", text)
    return matches[-2:]
