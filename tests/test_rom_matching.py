"""Optimized matching preserves SequenceMatcher scoring and first-match ties."""
from difflib import SequenceMatcher
import random

import pytest

from spindoctor import romutils


def reference_match(query, candidates, threshold):
    best = None
    for name in candidates:
        score = SequenceMatcher(None, romutils.normalize(query), romutils.normalize(name)).ratio()
        if best is None or score > best[1]:
            best = (name, score)
    return best if best is not None and best[1] >= threshold else None


@pytest.mark.parametrize("threshold", [-1.0, 0.0, 0.5, 0.8, 1.0, 1.1])
def test_matching_agrees_with_reference(threshold):
    rng = random.Random(42)
    names = ["", "Mario (USA)", "Mario", "tide", "diet", "a" * 210 + "b"]
    names += ["".join(rng.choices("abcde _-123", k=rng.randrange(1, 35))) for _ in range(80)]
    for query in ["", "mario", "diet", "tide", "a" * 210 + "c", *names[10:30]]:
        assert romutils.find_best_match(query, names, threshold) == reference_match(query, names, threshold)
    assert romutils.find_best_match("game", [], threshold) is None


def test_matching_skips_candidates_that_cannot_beat_best(monkeypatch):
    scored = []
    class CountingMatcher(SequenceMatcher):
        def ratio(self):
            scored.append(self.b)
            return super().ratio()
    monkeypatch.setattr(romutils, "SequenceMatcher", CountingMatcher)
    assert romutils.find_best_match("mario", ["maria", "zzzzz", "x"]) == ("maria", 0.8)
    assert scored == ["maria"]
