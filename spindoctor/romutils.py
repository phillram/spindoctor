"""ROM filename normalization, variant parsing, and fuzzy matching."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional


# Ordered strip passes — most specific first so "(USA, Rev A)" is handled cleanly
_REGION = re.compile(
    r'\s*\(\s*(?:USA|Japan|Europe|World|Germany|France|Spain|Italy|Australia|Brazil|'
    r'China|Korea|Taiwan|Asia|Scandinavia|Netherlands|Sweden|Norway|Denmark|Finland|'
    r'Poland|Russia|En|Ja|De|Fr|Es|It|Nl|Pt|Sv|No|Da|Fi|Pl|Ru|Zh|Ko|'
    r'JU|UE|JE|JUE|U|J|E)(?:[,\s][^)]*?)?\s*\)',
    re.IGNORECASE,
)
_VERSION = re.compile(r'\s*\(\s*v\s*[\d.]+[^)]*\)', re.IGNORECASE)
_REVISION = re.compile(r'\s*\(\s*Rev\s*[^)]*\)', re.IGNORECASE)
_DISC = re.compile(r'\s*\(\s*Disc\s*\d+[^)]*\)', re.IGNORECASE)
_ANY_PARENS = re.compile(r'\s*\([^)]*\)')
_ANY_BRACKETS = re.compile(r'\s*\[[^\]]*\]')
_PUNCT = re.compile(r"[''`\-\.\,\:\;\!\?]+")
_SPACE = re.compile(r'[\s_]+')

# Tags that signal a patched/modified ROM — used for labelling, not stripping
_PATCH_TAGS = re.compile(
    r'\b(patch(?:ed)?|hack|translation|translated|fixed|trainer|bootleg|pirate|'
    r'unlicensed|proto(?:type)?|demo|sample|promo|beta|alpha)\b',
    re.IGNORECASE,
)


def normalize(name: str) -> str:
    """Return a stripped, lower-cased name suitable for fuzzy comparison.

    Strips region codes, version numbers, revision labels, bracket tags, and
    punctuation so that '1942 (Japan, Rev B)' and '1942' compare as equal.
    """
    s = _REGION.sub('', name)
    s = _VERSION.sub('', s)
    s = _REVISION.sub('', s)
    s = _DISC.sub('', s)
    s = _ANY_PARENS.sub('', s)
    s = _ANY_BRACKETS.sub('', s)
    s = _PUNCT.sub(' ', s)
    s = _SPACE.sub(' ', s)
    return s.strip().lower()


def parse_variant(name: str) -> dict:
    """Extract structured metadata from a ROM filename stem.

    Returns a dict with keys:
      base       — original name
      clean      — normalized name
      regions    — list of region strings found
      version    — version string or None
      revision   — revision label or None
      disc       — disc number or None
      tags       — list of bracket tags (e.g. ['!', 'b2'])
      is_patched — True if patch/hack/translation tag detected
    """
    info: dict = {
        "base": name,
        "clean": normalize(name),
        "regions": [],
        "version": None,
        "revision": None,
        "disc": None,
        "tags": [],
        "is_patched": bool(_PATCH_TAGS.search(name)),
    }

    for m in _REGION.finditer(name):
        raw = m.group(0).strip(" ()")
        info["regions"].extend(r.strip() for r in raw.split(",") if r.strip())

    v = _VERSION.search(name)
    if v:
        vm = re.search(r'v\s*([\d.]+)', v.group(0), re.IGNORECASE)
        info["version"] = vm.group(1) if vm else v.group(0).strip(" ()")

    r = _REVISION.search(name)
    if r:
        rm = re.search(r'Rev\s*([^)]+)', r.group(0), re.IGNORECASE)
        info["revision"] = rm.group(1).strip() if rm else None

    d = _DISC.search(name)
    if d:
        dm = re.search(r'Disc\s*(\d+)', d.group(0), re.IGNORECASE)
        info["disc"] = int(dm.group(1)) if dm else None

    info["tags"] = re.findall(r'\[([^\]]+)\]', name)
    return info


def similarity(a: str, b: str) -> float:
    """Fuzzy similarity ratio (0.0–1.0) between two ROM or game names."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def find_best_match(
    rom_name: str,
    candidates: list[str],
    threshold: float = 0.80,
) -> Optional[tuple[str, float]]:
    """Return (best_candidate, score) or None if nothing clears the threshold."""
    best: Optional[tuple[str, float]] = None
    norm_rom = normalize(rom_name)
    for candidate in candidates:
        score = SequenceMatcher(None, norm_rom, normalize(candidate)).ratio()
        if best is None or score > best[1]:
            best = (candidate, score)
    if best and best[1] >= threshold:
        return best
    return None


def find_all_matches(
    rom_name: str,
    candidates: list[str],
    threshold: float = 0.60,
    max_results: int = 8,
) -> list[tuple[str, float]]:
    """Return all (candidate, score) pairs above threshold, best first."""
    norm_rom = normalize(rom_name)
    results = [
        (c, SequenceMatcher(None, norm_rom, normalize(c)).ratio())
        for c in candidates
    ]
    return sorted(
        [(c, s) for c, s in results if s >= threshold],
        key=lambda x: x[1],
        reverse=True,
    )[:max_results]


_VARIANT_SEGMENT = re.compile(r'(\([^)]*\)|\[[^\]]*\])')
_ROMAN = ("II", "III", "IV", "VI", "VII", "VIII", "IX", "XI")


def _title_case_base(text: str) -> str:
    words = re.split(r'[\s_]+', text.strip())
    titled = []
    for w in words:
        if not w:
            continue
        if len(w) <= 3 and w.upper() in _ROMAN:
            titled.append(w.upper())
        else:
            titled.append(w.capitalize())
    return " ".join(titled)


def clean_display_name(rom_name: str, strip_variants: bool = False) -> str:
    """Return a human-readable display name from a ROM filename.

    When ``strip_variants`` is False (default), region/revision/version tags
    inside ``(...)`` or ``[...]`` are preserved verbatim so e.g.
    ``1942 (Japan)`` and ``1942 (USA)`` stay distinguishable.

    When ``strip_variants`` is True, all variant tags are removed and the
    name is collapsed to its base form (``1942 (Japan)`` → ``1942``).
    """
    if strip_variants:
        return _title_case_base(parse_variant(rom_name)["clean"])

    parts = _VARIANT_SEGMENT.split(rom_name)
    rebuilt = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Parenthetical/bracket segment — keep verbatim
            rebuilt.append(part)
        else:
            titled = _title_case_base(part)
            if titled:
                rebuilt.append(titled)
    out = " ".join(s for s in rebuilt if s)
    return _SPACE.sub(' ', out).strip()
