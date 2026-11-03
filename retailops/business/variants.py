"""Variant text helpers shared by the order-request service and the customer agent tools (W3.2).

Pure functions, no I/O. A variant is described by attributes (size, color); the customer's own words
("màu nâu", "size L", "đen size M") are matched against the real variants of the order's product, so the
server, not the model, decides which variant a phrase refers to.
"""
import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")


def fold_text(text) -> str | None:
    """Lower-case, accent-free, single-spaced form; None for empty input. "Đen" -> "den"."""
    if text is None:
        return None
    folded = "".join(
        c for c in unicodedata.normalize("NFD", str(text).lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )
    folded = " ".join(folded.split())
    return folded or None


def fold_attribute(text) -> str | None:
    """Like fold_text, and a leading "size " is not part of a size attribute ("Size M" -> "m")."""
    folded = fold_text(text)
    if folded and folded.startswith("size "):
        folded = folded[5:]
    return folded or None


def _words(text) -> list[str]:
    return _WORD.findall(fold_text(text) or "")


def match_variants(variants, wanted_text) -> list[dict]:
    """Variants of one product that a customer's free-text description points at.

    Each variant dict needs `label`, `size`, `color` and `is_current`. An attribute the customer names
    (a color or a size that some variant of this product really has) must match; an attribute they do
    not name is taken from the variant the order holds, so "màu nâu" on a black size-41 shoe means the
    brown size-41 one. The variant the order already holds is never a match. Returns [] when the text
    names no known attribute.
    """
    words = _words(wanted_text)
    if not words or not variants:
        return []
    for variant in variants:  # a full label quoted back ("Đen · Size L") is the strongest signal
        label = fold_text(variant.get("label"))
        if label and label in fold_text(wanted_text) and not variant.get("is_current"):
            return [variant]
    colors = {fold_attribute(v.get("color")) for v in variants} - {None}
    sizes = {fold_attribute(v.get("size")) for v in variants} - {None}
    word_set = set(words)
    named_color = max((c for c in colors if all(w in word_set for w in c.split())), key=len, default=None)
    named_size = next((s for s in sorted(sizes, key=len, reverse=True)
                       if all(w in word_set for w in s.split())), None)
    if named_color is None and named_size is None:
        return []
    current = next((v for v in variants if v.get("is_current")), None)
    want_color = named_color or (fold_attribute(current.get("color")) if current else None)
    want_size = named_size or (fold_attribute(current.get("size")) if current else None)
    matches = []
    for variant in variants:
        if variant.get("is_current"):
            continue
        if want_color is not None and fold_attribute(variant.get("color")) != want_color:
            continue
        if want_size is not None and fold_attribute(variant.get("size")) != want_size:
            continue
        matches.append(variant)
    return matches
