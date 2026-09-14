#!/usr/bin/env python3
"""Offline toy candidate-generation demo.

The generator reads only explicitly supplied hints and exclusion TXT files.
It does not inspect Notes, Keychain, databases, network resources, or online
accounts. Candidates stay local and are never submitted automatically.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator


# Fictional teaching data only. Do not replace these with real credentials.
EXAMPLE_HINTS = ("wyy", "wangyaoyi", "010228", "15361652627", "17680162930")
EXAMPLE_TARGET = ""
SEPARATORS = ("", "-", "_", " ", ".")
COMMON_NUMBERS = (
    "0000",
    "1111",
    "2222",
    "3333",
    "4444",
    "5555",
    "6666",
    "7777",
    "8888",
    "9999",
    "012345",
    "123456",
    "234567",
    "345678",
    "456789",
    "654321",
    "543210",
    "112233",
    "223344",
    "123123",
    "520",
    "1314",
    "666",
    "888",
)
# Short-phrase wording was reviewed from these public search pages; the
# generator remains offline and never fetches them at runtime.
# https://hanyu.baidu.com/sentence/search?query=励志短句%20未来可期%20勇往直前
# https://www.baidu.com/s?wd=雄心壮志%20励志短句
INSPIRATIONAL_PHRASES = (
    ("雄心壮志", ("xiong", "xin", "zhuang", "zhi")),
    ("未来可期", ("wei", "lai", "ke", "qi")),
    ("勇往直前", ("yong", "wang", "zhi", "qian")),
    ("不畏艰辛", ("bu", "wei", "jian", "xin")),
    ("不畏困难", ("bu", "wei", "kun", "nan")),
    ("奋发向前", ("fen", "fa", "xiang", "qian")),
    ("超越自己", ("chao", "yue", "zi", "ji")),
    ("坚持梦想", ("jian", "chi", "meng", "xiang")),
    ("披荆斩棘", ("pi", "jing", "zhan", "ji")),
    ("不断超越", ("bu", "duan", "chao", "yue")),
    ("追求卓越", ("zhui", "qiu", "zhuo", "yue")),
    ("保持初心", ("bao", "chi", "chu", "xin")),
    ("以梦为马", ("yi", "meng", "wei", "ma")),
    ("不负韶华", ("bu", "fu", "shao", "hua")),
    ("砥砺前行", ("di", "li", "qian", "xing")),
    ("前途无量", ("qian", "tu", "wu", "liang")),
    ("前程似锦", ("qian", "cheng", "si", "jin")),
    ("无所畏惧", ("wu", "suo", "wei", "ju")),
    ("梦想成真", ("meng", "xiang", "cheng", "zhen")),
    ("不忘初心", ("bu", "wang", "chu", "xin")),
    ("方得始终", ("fang", "de", "shi", "zhong")),
    ("不负时光", ("bu", "fu", "shi", "guang")),
    ("书写辉煌", ("shu", "xie", "hui", "huang")),
    ("敢于追梦", ("gan", "yu", "zhui", "meng")),
    ("铸就辉煌", ("zhu", "jiu", "hui", "huang")),
    ("不负自己", ("bu", "fu", "zi", "ji")),
    ("脚踏实地", ("jiao", "ta", "shi", "di")),
    ("勇攀高峰", ("yong", "pan", "gao", "feng")),
    ("壮志凌云", ("zhuang", "zhi", "ling", "yun")),
    ("乘风破浪", ("cheng", "feng", "po", "lang")),
    ("心中有火", ("xin", "zhong", "you", "huo")),
    ("眼里有光", ("yan", "li", "you", "guang")),
    ("脚下有路", ("jiao", "xia", "you", "lu")),
    ("铸就美好未来", ("zhu", "jiu", "mei", "hao", "wei", "lai")),
    ("大志大勇", ("da", "zhi", "da", "yong")),
    ("立志高远", ("li", "zhi", "gao", "yuan")),
    ("成就非凡", ("cheng", "jiu", "fei", "fan")),
    ("目标明确", ("mu", "biao", "ming", "que")),
    ("成功在望", ("cheng", "gong", "zai", "wang")),
    ("永不止步", ("yong", "bu", "zhi", "bu")),
    ("无畏前行", ("wu", "wei", "qian", "xing")),
    ("一往无前", ("yi", "wang", "wu", "qian")),
    ("信心满怀", ("xin", "xin", "man", "huai")),
    ("相信自己", ("xiang", "xin", "zi", "ji")),
    ("努力向前", ("nu", "li", "xiang", "qian")),
    ("每一步都算数", ("mei", "yi", "bu", "dou", "suan", "shu")),
    ("未来无限美好", ("wei", "lai", "wu", "xian", "mei", "hao")),
    ("心怀梦想", ("xin", "huai", "meng", "xiang")),
    ("梦想启航", ("meng", "xiang", "qi", "hang")),
    ("无畏风浪", ("wu", "wei", "feng", "lang")),
    ("勇敢追梦", ("yong", "gan", "zhui", "meng")),
    ("无畏挑战", ("wu", "wei", "tiao", "zhan")),
    ("乘风起航", ("cheng", "feng", "qi", "hang")),
    ("破浪前行", ("po", "lang", "qian", "xing")),
    ("向远方", ("xiang", "yuan", "fang")),
    ("心可及", ("xin", "ke", "ji")),
    ("迎曙光", ("ying", "shu", "guang")),
    ("踏碎荆棘", ("ta", "sui", "jing", "ji")),
    ("笑傲苍穹", ("xiao", "ao", "cang", "qiong")),
    ("心中有梦", ("xin", "zhong", "you", "meng")),
    ("脚下有力量", ("jiao", "xia", "you", "li", "liang")),
    ("勇者无畏", ("yong", "zhe", "wu", "wei")),
    ("不断突破", ("bu", "duan", "tu", "po")),
    ("迎接挑战", ("ying", "jie", "tiao", "zhan")),
    ("立大志", ("li", "da", "zhi")),
    ("做大事", ("zuo", "da", "shi")),
    ("奋力前行", ("fen", "li", "qian", "xing")),
    ("实现梦想", ("shi", "xian", "meng", "xiang")),
    ("追梦路上", ("zhui", "meng", "lu", "shang")),
    ("勤奋努力", ("qin", "fen", "nu", "li")),
    ("永不言败", ("yong", "bu", "yan", "bai")),
    ("逐梦未来", ("zhu", "meng", "wei", "lai")),
    ("信念坚定", ("xin", "nian", "jian", "ding")),
)
NATURAL_COMMON_SCORE = 50.0
NATURAL_SEQUENCE_SCORE = 48.0
NATURAL_REPEAT_SCORE = 44.0
NATURAL_BLOCK_SCORE = 45.0
NATURAL_PAIRED_SCORE = 46.0
INSPIRATIONAL_PINYIN_SCORE = 68.0
DEFAULT_SHORT_MAX_LENGTH = 15
DEFAULT_MAX_LENGTH = 20
DEFAULT_LIMIT = 50_000
DEFAULT_OUTPUT = Path(__file__).with_name("toy_candidates_v2.txt")
DEFAULT_V3_OUTPUT = Path(__file__).with_name("toy_candidates_v3.txt")
DEFAULT_BASELINE = Path(__file__).with_name("toy_candidates_v1.txt")
DEFAULT_V3_EXCLUSION_PREFIX = 10_101
DEFAULT_HINTS_FILE = Path(__file__).with_name("personal_hints.local.txt")


@dataclass(frozen=True)
class _Candidate:
    value: str
    score: float
    rule: str
    order: int


def _validate_lengths(short_max_length: int, max_length: int) -> None:
    if short_max_length <= 0:
        raise ValueError("short_max_length must be a positive integer")
    if max_length <= 0:
        raise ValueError("max_length must be a positive integer")
    if max_length < short_max_length:
        raise ValueError("max_length must be at least short_max_length")


def _clean_hints(hints: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(hint).strip() for hint in hints if str(hint).strip()))


def _load_nonempty_lines(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(
        dict.fromkeys(
            line.strip()
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        )
    )


def load_hints(path: Path | str) -> tuple[str, ...]:
    """Load local, line-delimited hint atoms without exposing them in code."""
    return _load_nonempty_lines(Path(path))


def load_exclusions(paths: Iterable[Path | str]) -> frozenset[str]:
    """Load exact candidate values that a later phase must never emit."""
    excluded: set[str] = set()
    for path in paths:
        excluded.update(_load_nonempty_lines(Path(path)))
    return frozenset(excluded)


def load_exclusion_prefixes(
    paths: Iterable[Path | str],
    prefix_length: int,
) -> frozenset[str]:
    """Load only the first ``prefix_length`` candidates from each TXT file."""
    if prefix_length <= 0:
        raise ValueError("prefix_length must be a positive integer")

    excluded: set[str] = set()
    for path in paths:
        excluded.update(_load_nonempty_lines(Path(path))[:prefix_length])
    return frozenset(excluded)


def _default_v3_exclusion_files() -> tuple[Path, ...]:
    """Return existing v1/v2 baselines for direct v3 API callers."""
    return tuple(
        path
        for path in (DEFAULT_BASELINE, DEFAULT_OUTPUT)
        if path.exists()
    )


def _is_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", value))


def _text_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Yield bounded, explainable variants for a text atom."""
    yield value, 100.0, "literal-text"

    variants = (
        (value.lower(), 96.0, "text-lower"),
        (value.upper(), 95.0, "text-upper"),
        (value.title(), 94.0, "text-title"),
        (value[::-1], 82.0, "text-reverse"),
    )
    for variant in variants:
        yield variant

    if len(value) >= 2:
        yield value[0], 72.0, "text-first-character"
        yield value[-1], 71.0, "text-last-character"

    leet_map = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5"})
    leet = value.lower().translate(leet_map)
    if leet != value.lower():
        yield leet, 68.0, "text-simple-leet"


def _numeric_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Yield complete values, slices, reversals, and date-like arrangements."""
    yield value, 100.0, "literal-number"

    stripped = value.lstrip("0") or "0"
    if stripped != value:
        yield stripped, 92.0, "number-strip-leading-zero"
    yield value[::-1], 88.0, "number-reverse"

    max_slice = min(6, len(value))
    for size in range(1, max_slice + 1):
        slice_score = 84.0 - (max_slice - size) * 1.5
        for start in range(0, len(value) - size + 1):
            part = value[start : start + size]
            yield part, slice_score, f"number-slice-{size}"
            if part != part.lstrip("0"):
                yield part.lstrip("0") or "0", slice_score - 2.0, f"number-slice-{size}-strip-zero"

    if len(value) == 6:
        groups = (value[:2], value[2:4], value[4:])
        for ordering in itertools.permutations(groups):
            yield "".join(ordering), 86.0, "date-6-digit-order"
    elif len(value) == 8:
        groups = (value[:4], value[4:6], value[6:])
        for ordering in itertools.permutations(groups):
            yield "".join(ordering), 86.0, "date-8-digit-order"


def _mixed_hint_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Split an alphanumeric hint while retaining its literal form."""
    parts = re.findall(r"[A-Za-z]+|[0-9]+", value)
    if len(parts) < 2:
        return

    compact = "".join(parts)
    yield compact, 97.0, "personal-mixed-compact"
    for part in parts:
        yield part, 94.0, "personal-mixed-part"

    for separator in SEPARATORS:
        yield separator.join(parts), 93.0, "personal-mixed-separator"
    yield value[::-1], 78.0, "personal-mixed-reverse"


def _natural_number_patterns() -> Iterator[tuple[str, float, str]]:
    """Generate bounded natural-number patterns independent of input hints."""
    for value in COMMON_NUMBERS:
        yield value, NATURAL_COMMON_SCORE, "common-number"

    # Ascending and descending runs, including leading-zero runs such as 012345.
    for size in range(2, 7):
        for start in range(10):
            for step in (1, -1):
                digits = [start + step * offset for offset in range(size)]
                if all(0 <= digit <= 9 for digit in digits):
                    yield "".join(str(digit) for digit in digits), NATURAL_SEQUENCE_SCORE, "numeric-sequence"

    # Repeated digits, repeated two-digit blocks, and paired increasing digits.
    for size in range(2, 7):
        for digit in range(10):
            yield str(digit) * size, NATURAL_REPEAT_SCORE, "repeated-digit"
    for first in range(10):
        for second in range(10):
            block = f"{first}{second}"
            for repeats in (2, 3):
                value = block * repeats
                yield value, NATURAL_BLOCK_SCORE, "repeated-two-digit-block"
    for start in range(8):
        yield "".join(str(digit) * 2 for digit in range(start, start + 3)), NATURAL_PAIRED_SCORE, "paired-digit-run"


def _inspirational_pinyin_variants() -> Iterator[tuple[str, float, str]]:
    """Yield unspaced pinyin and compact variants for sourced short phrases."""
    for phrase, syllables in INSPIRATIONAL_PHRASES:
        full = "".join(syllables)
        initials = "".join(syllable[0] for syllable in syllables)
        yield full, INSPIRATIONAL_PINYIN_SCORE, f"inspirational-pinyin:{phrase}"
        yield full.capitalize(), INSPIRATIONAL_PINYIN_SCORE - 6.0, f"inspirational-title:{phrase}"
        yield full.upper(), INSPIRATIONAL_PINYIN_SCORE - 8.0, f"inspirational-upper:{phrase}"
        yield initials, INSPIRATIONAL_PINYIN_SCORE - 12.0, f"inspirational-initials:{phrase}"


def _source_group(rule: str) -> int:
    """Return the source tier used after the length phase.

    Lower groups are more trusted. This keeps every original hint ahead of
    sourced inspirational phrases, and keeps both ahead of generic number
    patterns and multi-atom concatenations.
    """
    if rule.startswith("inspirational-"):
        return 1
    if rule.startswith(
        (
            "common-number",
            "numeric-sequence",
            "repeated-digit",
            "repeated-two-digit-block",
            "paired-digit-run",
        )
    ):
        return 2
    if rule.startswith("concat"):
        return 3
    return 0


@lru_cache(maxsize=64)
def _ordered_candidates(
    hints: tuple[str, ...],
    short_max_length: int,
    max_length: int,
    exclude: frozenset[str] = frozenset(),
) -> list[_Candidate]:
    _validate_lengths(short_max_length, max_length)

    values: dict[str, _Candidate] = {}
    next_order = 0

    def add(value: str, score: float, rule: str) -> None:
        nonlocal next_order
        # TXT output is intentionally ASCII-only: Chinese source phrases are
        # metadata, never candidate values.
        if (
            not value
            or value in exclude
            or not value.isascii()
            or len(value) > max_length
        ):
            return
        existing = values.get(value)
        candidate = _Candidate(value, score, rule, next_order)
        next_order += 1
        if existing is None or (candidate.score, -candidate.order) > (
            existing.score,
            -existing.order,
        ):
            values[value] = candidate

    text_atoms: list[tuple[str, float, str]] = []
    numeric_atoms: list[tuple[str, float, str]] = []
    inspirational_atoms: list[tuple[str, float, str]] = []

    for hint in hints:
        if _is_numeric(hint):
            for value, score, rule in _numeric_variants(hint):
                add(value, score, rule)
                numeric_atoms.append((value, score, rule))
        else:
            for value, score, rule in _text_variants(hint):
                add(value, score, rule)
                text_atoms.append((value, score, rule))
            if re.search(r"[0-9]", hint):
                for value, score, rule in _mixed_hint_variants(hint):
                    add(value, score, rule)
                    if _is_numeric(value):
                        numeric_atoms.append((value, score, rule))
                    else:
                        text_atoms.append((value, score, rule))

    natural_atoms = list(_natural_number_patterns())
    for value, score, rule in natural_atoms:
        add(value, score, rule)

    for value, score, rule in _inspirational_pinyin_variants():
        add(value, score, rule)
        inspirational_atoms.append((value, score, rule))

    def add_pair_compositions(
        composition_atoms: list[tuple[str, float, str]],
    ) -> None:
        for left, right in itertools.product(composition_atoms, repeat=2):
            left_value, left_score, left_rule = left
            right_value, right_score, right_rule = right
            for separator in SEPARATORS:
                base = f"{left_value}{separator}{right_value}"
                inspirational_penalty = (
                    10.0
                    if left_rule.startswith("inspirational-")
                    or right_rule.startswith("inspirational-")
                    else 0.0
                )
                score = (left_score + right_score) / 2.0 - 8.0 - inspirational_penalty
                add(base, score, f"concat:{left_rule}+{right_rule}")
                add(base[::-1], score - 5.0, "concat-reverse")

    # Natural patterns are kept as standalone candidates. The broad pool is
    # reserved for input-derived text and numeric atoms to keep expansion
    # finite; a small pool below adds representative pinyin mixtures.
    add_pair_compositions(text_atoms + numeric_atoms + natural_atoms[: len(COMMON_NUMBERS)])
    pinyin_atoms = [
        atom for atom in inspirational_atoms if atom[2].startswith("inspirational-pinyin:")
    ][:24]
    add_pair_compositions(pinyin_atoms + text_atoms[:12] + numeric_atoms[:48])

    # A small three-part grammar covers common text + date + suffix forms
    # without turning the generator into unrestricted Cartesian-product search.
    short_atoms = (text_atoms + numeric_atoms)[:24]
    for first, second, third in itertools.product(short_atoms, repeat=3):
        base = first[0] + second[0] + third[0]
        score = (first[1] + second[1] + third[1]) / 3.0 - 16.0
        add(base, score, "concat-three-atoms")

    heap: list[tuple[int, int, float, int, int, str, _Candidate]] = []
    for candidate in values.values():
        phase = 0 if len(candidate.value) <= short_max_length else 1
        heapq.heappush(
            heap,
            (
                phase,
                _source_group(candidate.rule),
                -candidate.score,
                len(candidate.value),
                candidate.order,
                candidate.value,
                candidate,
            ),
        )

    ordered: list[_Candidate] = []
    while heap:
        _phase, _group, _negative_score, _length, _order, _value, candidate = heapq.heappop(heap)
        ordered.append(candidate)
    return ordered


def candidates(
    hints: tuple[str, ...],
    *,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
) -> Iterator[str]:
    """Yield ranked candidates, with <=15-character values before 16..20-character values."""
    clean = _clean_hints(hints)
    excluded = frozenset(_clean_hints(exclude))
    for candidate in _ordered_candidates(clean, short_max_length, max_length, excluded):
        yield candidate.value


def _v3_text_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Yield source-backed text variants without reversing or leet expansion."""
    yield value, 100.0, "v3-literal-text"
    yield value.lower(), 96.0, "v3-text-lower"
    yield value.upper(), 95.0, "v3-text-upper"
    yield value.title(), 94.0, "v3-text-title"


def _valid_yyyymmdd(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():
        return False
    year = int(value[:4])
    month = int(value[4:6])
    day = int(value[6:])
    if year < 1900 or year > 2099 or month == 0 or month > 12:
        return False
    february = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    days_in_month = (31, february, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= day <= days_in_month[month - 1]


def _valid_yymmdd(value: str) -> bool:
    if len(value) != 6 or not value.isdigit():
        return False
    month = int(value[2:4])
    day = int(value[4:])
    if month == 0 or month > 12:
        return False
    year = 2000 + int(value[:2])
    return _valid_yyyymmdd(f"{year:04d}{month:02d}{day:02d}")


def _v3_numeric_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Yield only complete numeric hints and recognisable date/year values."""
    yield value, 100.0, "v3-literal-number"
    if len(value) == 4 and value[:2] in {"19", "20"}:
        yield value, 96.0, "v3-year"
    elif _valid_yymmdd(value):
        yield value, 94.0, "v3-date-yymmdd"
    elif _valid_yyyymmdd(value):
        yield value, 94.0, "v3-date-yyyymmdd"


def _v3_mixed_hint_variants(value: str) -> Iterator[tuple[str, float, str]]:
    """Keep literal/compact mixed hints and meaningful source components only."""
    parts = re.findall(r"[A-Za-z]+|[0-9]+", value)
    if len(parts) < 2:
        yield value, 100.0, "v3-literal-mixed"
        return

    yield value, 100.0, "v3-literal-mixed"
    compact = "".join(parts)
    if compact != value:
        yield compact, 96.0, "v3-mixed-compact"

    for part in parts:
        if len(part) < 2:
            continue
        if part.isdigit():
            for variant, score, rule in _v3_numeric_variants(part):
                yield variant, score - 4.0, f"v3-mixed-{rule}"
        else:
            for variant, score, rule in _v3_text_variants(part):
                yield variant, score - 4.0, f"v3-mixed-{rule}"


def _v3_source_group(rule: str) -> int:
    """Rank personal source forms before ordered combinations and public pinyin."""
    if rule.startswith("inspirational-"):
        return 2
    if rule.startswith("v3-concat-ordered"):
        return 1
    return 0


@lru_cache(maxsize=64)
def _ordered_candidates_v3(
    hints: tuple[str, ...],
    short_max_length: int,
    max_length: int,
    exclude: frozenset[str] = frozenset(),
) -> list[_Candidate]:
    """Build a conservative v3 pool from meaningful source-backed rules."""
    _validate_lengths(short_max_length, max_length)

    values: dict[str, _Candidate] = {}
    next_order = 0

    def add(value: str, score: float, rule: str) -> None:
        nonlocal next_order
        if (
            not value
            or value in exclude
            or not value.isascii()
            or len(value) > max_length
        ):
            return
        existing = values.get(value)
        candidate = _Candidate(value, score, rule, next_order)
        next_order += 1
        if existing is None or (candidate.score, -candidate.order) > (
            existing.score,
            -existing.order,
        ):
            values[value] = candidate

    ordered_atoms: list[list[tuple[str, float, str]]] = []
    for hint in hints:
        if _is_numeric(hint):
            atoms = list(_v3_numeric_variants(hint))
        elif re.search(r"[0-9]", hint):
            atoms = list(_v3_mixed_hint_variants(hint))
        else:
            atoms = list(_v3_text_variants(hint))
        ordered_atoms.append(atoms)
        for value, score, rule in atoms:
            add(value, score, rule)

    # Combine only contiguous hints in their supplied order. No permutations,
    # synthetic separators, or reversed strings are introduced.
    for start in range(len(ordered_atoms)):
        for end in range(start + 2, min(len(ordered_atoms), start + 3) + 1):
            groups = ordered_atoms[start:end]
            for combination in itertools.product(*groups):
                value = "".join(atom[0] for atom in combination)
                score = sum(atom[1] for atom in combination) / len(combination) - 10.0
                rules = "+".join(atom[2] for atom in combination)
                add(value, score, f"v3-concat-ordered:{rules}")

    for value, score, rule in _inspirational_pinyin_variants():
        add(value, score - 8.0, rule)

    heap: list[tuple[int, int, float, int, int, str, _Candidate]] = []
    for candidate in values.values():
        phase = 0 if len(candidate.value) <= short_max_length else 1
        heapq.heappush(
            heap,
            (
                phase,
                _v3_source_group(candidate.rule),
                -candidate.score,
                len(candidate.value),
                candidate.order,
                candidate.value,
                candidate,
            ),
        )

    ordered: list[_Candidate] = []
    while heap:
        _phase, _group, _negative_score, _length, _order, _value, candidate = heapq.heappop(heap)
        ordered.append(candidate)
    return ordered


def candidates_v3(
    hints: tuple[str, ...],
    *,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
) -> Iterator[str]:
    """Yield conservative v3 candidates, with short values emitted first."""
    clean = _clean_hints(hints)
    excluded = frozenset(_clean_hints(exclude))
    for candidate in _ordered_candidates_v3(clean, short_max_length, max_length, excluded):
        yield candidate.value


def run_v3(
    limit: int,
    *,
    hints: tuple[str, ...] = EXAMPLE_HINTS,
    target: str = EXAMPLE_TARGET,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
    exclude_files: Iterable[Path | str] | None = None,
    exclude_prefix: int = DEFAULT_V3_EXCLUSION_PREFIX,
) -> tuple[str | None, int, bool]:
    """Try the toy target using only the conservative v3 generator."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    excluded = set(_clean_hints(exclude))
    baseline_files = (
        _default_v3_exclusion_files()
        if exclude_files is None
        else tuple(exclude_files)
    )
    excluded.update(load_exclusion_prefixes(baseline_files, exclude_prefix))
    attempts = 0
    for attempts, candidate in enumerate(
        candidates_v3(
            hints,
            short_max_length=short_max_length,
            max_length=max_length,
            exclude=excluded,
        ),
        start=1,
    ):
        if attempts > limit:
            return None, limit, True
        if candidate == target:
            return candidate, attempts, False
    return None, attempts, False


def export_candidates_v3(
    limit: int,
    output_path: Path,
    *,
    hints: tuple[str, ...] = EXAMPLE_HINTS,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
    exclude_files: Iterable[Path | str] | None = None,
    exclude_prefix: int = DEFAULT_V3_EXCLUSION_PREFIX,
) -> int:
    """Write v3 candidates while excluding each baseline file's prefix."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    excluded = set(_clean_hints(exclude))
    baseline_files = (
        _default_v3_exclusion_files()
        if exclude_files is None
        else tuple(exclude_files)
    )
    excluded.update(load_exclusion_prefixes(baseline_files, exclude_prefix))
    written = 0
    with output_path.open("w", encoding="utf-8") as output:
        for candidate in candidates_v3(
            hints,
            short_max_length=short_max_length,
            max_length=max_length,
            exclude=excluded,
        ):
            if written >= limit:
                break
            output.write(candidate + "\n")
            written += 1
    return written


def run(
    limit: int,
    *,
    hints: tuple[str, ...] = EXAMPLE_HINTS,
    target: str = EXAMPLE_TARGET,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
    exclude_files: Iterable[Path | str] = (),
) -> tuple[str | None, int, bool]:
    """Try the toy target with a hard candidate-count limit."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    excluded = set(_clean_hints(exclude))
    excluded.update(load_exclusions(exclude_files))
    attempts = 0
    for attempts, candidate in enumerate(
        candidates(
            hints,
            short_max_length=short_max_length,
            max_length=max_length,
            exclude=excluded,
        ),
        start=1,
    ):
        if attempts > limit:
            return None, limit, True
        if candidate == target:
            return candidate, attempts, False
    return None, attempts, False


def export_candidates(
    limit: int,
    output_path: Path,
    *,
    hints: tuple[str, ...] = EXAMPLE_HINTS,
    short_max_length: int = DEFAULT_SHORT_MAX_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
    exclude_files: Iterable[Path | str] = (),
) -> int:
    """Write generated candidates to a local text file, one per line."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    excluded = set(_clean_hints(exclude))
    excluded.update(load_exclusions(exclude_files))
    written = 0
    with output_path.open("w", encoding="utf-8") as output:
        for candidate in candidates(
            hints,
            short_max_length=short_max_length,
            max_length=max_length,
            exclude=excluded,
        ):
            if written >= limit:
                break
            output.write(candidate + "\n")
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline toy candidate lab")
    parser.add_argument(
        "--phase",
        choices=("2", "3"),
        default="2",
        help="candidate strategy to run (default: 2)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--hints-file",
        type=Path,
        help="local line-delimited hints file (kept out of version control)",
    )
    parser.add_argument(
        "--exclude",
        type=Path,
        action="append",
        help="candidate TXT to exclude; may be supplied more than once",
    )
    parser.add_argument(
        "--exclude-prefix",
        type=int,
        default=DEFAULT_V3_EXCLUSION_PREFIX,
        help="for phase 3, exclude this many entries from each baseline TXT (default: 10101)",
    )
    parser.add_argument(
        "--short-max-length",
        type=int,
        default=DEFAULT_SHORT_MAX_LENGTH,
        help="emit candidates up to this length before longer candidates (default: 15)",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=DEFAULT_MAX_LENGTH,
        help="maximum candidate length (default: 20)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output text file (default depends on --phase)",
    )
    args = parser.parse_args()

    print("离线教学实验：候选仅在本地生成，不自动提交到任何服务。")
    print(f"实验阶段: {args.phase}")
    print(f"候选上限: {args.limit}")
    print(f"长度阶段: <= {args.short_max_length}，然后 {args.short_max_length + 1}..{args.max_length}")
    hints = (
        load_hints(args.hints_file)
        if args.hints_file
        else (load_hints(DEFAULT_HINTS_FILE) if DEFAULT_HINTS_FILE.exists() else EXAMPLE_HINTS)
    )
    try:
        if args.phase == "3":
            output_path = args.output or DEFAULT_V3_OUTPUT
            exclude_files = args.exclude or [
                path
                for path in (DEFAULT_BASELINE, DEFAULT_OUTPUT)
                if path.exists()
            ]
            excluded = load_exclusion_prefixes(exclude_files, args.exclude_prefix)
            written = export_candidates_v3(
                args.limit,
                output_path,
                hints=hints,
                short_max_length=args.short_max_length,
                max_length=args.max_length,
                exclude=excluded,
                exclude_files=(),
            )
            found, attempts, capped = run_v3(
                args.limit,
                hints=hints,
                short_max_length=args.short_max_length,
                max_length=args.max_length,
                exclude=excluded,
                exclude_files=(),
            )
        else:
            output_path = args.output or DEFAULT_OUTPUT
            exclude_files = args.exclude or ([DEFAULT_BASELINE] if DEFAULT_BASELINE.exists() else [])
            written = export_candidates(
                args.limit,
                output_path,
                hints=hints,
                short_max_length=args.short_max_length,
                max_length=args.max_length,
                exclude_files=exclude_files,
            )
            found, attempts, capped = run(
                args.limit,
                hints=hints,
                short_max_length=args.short_max_length,
                max_length=args.max_length,
                exclude_files=exclude_files,
            )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    print(f"已写入 {written} 条候选到: {output_path}")

    if found is not None:
        print(f"命中虚构目标: {found!r}")
        print(f"尝试次数: {attempts}")
    elif capped:
        print(f"达到候选上限，已尝试 {attempts} 个组合。")
    else:
        print(f"未命中，共尝试 {attempts} 个组合。")
    print("注意：这不会也不能解锁 Apple 备忘录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
