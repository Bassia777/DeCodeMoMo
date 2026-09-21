#!/usr/bin/env python3
"""Generate ranked password candidates from an author profile JSON.

设计约束全部来自用户确认的规则：

* 不反转任何字符串；
* 不拆分已经给出的密码或关键字；
* 大小写只允许出现在词首或整体大写，不制造词内大写字母；
* 候选只由完整的“原子”拼接而成，不做任意字符洗牌；
* 长度优先：15 位以内优先，超过 15 位的候选统一降权；
* 励志短句等“尾部分类”不参与跨类组合，且永远排在提示词之后。

模块读取本地画像 JSON，输出纯 TXT（每行一个候选值，不含中文与评分），
方便直接喂给离线验证流程。
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE = MODULE_DIR / "author_profile.local.json"
DEFAULT_OUTPUT = MODULE_DIR / "toy_candidates_v7.txt"
DEFAULT_LIMIT = 50_000
DEFAULT_MAX_LENGTH = 20

# 用户提示：密码长度大概率不超过 15 位。16 位以上统一大幅降权，使同等可信度下
# 15 位以内的候选全部靠前，但极强线索（如曾用密码）仍能压过弱短候选。
SHORT_MAX_LENGTH = 15
LONG_LENGTH_PENALTY = 20

# 每多拼接一个原子就额外扣分，保证“拼接结果”不会反超它最强组成部分的可信度，
# 例如“姓名缩写+号码片段”不会排到已验证的曾用密码之前。
COMBINATION_PENALTY = 6

# 三原子组合只取权重最高的若干分类，避免候选爆炸。
TRIO_DIMENSION_COUNT = 5
TRIO_ATOM_LIMIT = 14

# 描述“关系”的行不是候选原子。
NON_ATOM_KINDS = frozenset({"name_pair", "relationship"})
RELATIONSHIP_MARKERS = ("<->", "->", "=>")

# 作者本人旧密码暴露出来的书写习惯，第六期才被纳入模型：
# `wyy25805.0` 说明他会用符号分隔和类似版本号的尾部，`168168` 说明他会重复片段。
DEFAULT_SEPARATORS = ("", ".", "_")
DEFAULT_SEPARATOR_MIN_WEIGHT = 84
DEFAULT_SEPARATOR_PENALTY = 1
DEFAULT_DOUBLING_MAX_LENGTH = 6
DEFAULT_DOUBLING_PENALTY = 4
DEFAULT_VERSION_MIN_MINOR = 1
DEFAULT_VERSION_MAX_MINOR = 9
DEFAULT_VERSION_PENALTY = 4
VERSION_SUFFIX_PATTERN = re.compile(r"^(?P<head>.*?)(?P<major>\d+)\.(?P<minor>\d+)$")

# 手抖/打错一个字符：多打一位（相邻键连击）、漏打一位、结尾多敲一个数字。
DEFAULT_TYPO_ENABLED = True
DEFAULT_TYPO_MIN_WEIGHT = 84
DEFAULT_TYPO_MAX_ATOM_LENGTH = 12
DEFAULT_TYPO_PENALTY = 12
DEFAULT_TYPO_APPEND_DIGITS = "0123456789"
DEFAULT_TYPO_PARTNER_MIN_WEIGHT = 84
DEFAULT_TYPO_PARTNER_MAX_LENGTH = 8

# 默认失败基线：v1/v2 只排除已验证过的前缀，v3/v4 全部排除。
DEFAULT_HEAD_BASELINES = ("toy_candidates_v1.txt", "toy_candidates_v2.txt")
DEFAULT_FULL_BASELINES = (
    "toy_candidates_v3.txt",
    "toy_candidates_v4.txt",
    "toy_candidates_v5.txt",
    "toy_candidates_v6.txt",
)
DEFAULT_EXCLUDE_PREFIX_LENGTH = 10_101


@dataclass(frozen=True)
class _Atom:
    value: str
    dimension: str
    weight: int
    order: int


def case_variants(value: str) -> Iterator[str]:
    """Yield the allowed case styles without creating inner capitals.

    Allowed: as-given, first-letter-capitalised, all-upper. A value that is
    already all upper only yields itself, because both styles coincide.
    """
    if not value:
        return
    yield value
    if value.isupper():
        return
    capitalised = value[:1].upper() + value[1:]
    if capitalised != value:
        yield capitalised
    upper = value.upper()
    if upper != value:
        yield upper


def load_profile(path: Path | str) -> dict:
    """Load and minimally validate a profile JSON document."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "dimensions" not in data or not isinstance(data["dimensions"], dict):
        raise ValueError("profile JSON must contain a 'dimensions' object")
    return data


def _is_atom_value(value: str) -> bool:
    """Return True when a profile row can be used as a password atom."""
    if not value or not value.isascii():
        return False
    return not any(marker in value for marker in RELATIONSHIP_MARKERS)


def _profile_atoms(profile: dict) -> list[_Atom]:
    atoms: list[_Atom] = []
    order = 0
    for name, dimension in profile["dimensions"].items():
        dimension_weight = int(dimension.get("weight", 0))
        for item in dimension.get("items", []):
            value = str(item.get("value", "")).strip()
            if item.get("kind") in NON_ATOM_KINDS or not _is_atom_value(value):
                continue
            # 单条线索可以用 weight 覆盖所属分类的默认权重。
            weight = int(item.get("weight", dimension_weight))
            atoms.append(_Atom(value, name, weight, order))
            order += 1
    return atoms


def _trailing_dimensions(profile: dict) -> frozenset[str]:
    names = profile.get("trailing_dimensions", ())
    if isinstance(names, str):
        names = (names,)
    return frozenset(str(name) for name in names)


def _rule(profile: dict, key: str, default):
    """Read one optional tuning value from the profile's combination_rules."""
    rules = profile.get("combination_rules")
    if not isinstance(rules, dict) or key not in rules:
        return default
    return rules[key]


def version_variants(value: str, *, min_minor: int, max_minor: int) -> Iterator[str]:
    """Yield version-bumped forms of a dotted value such as ``oldpass5.0``.

    作者用过的旧密码带有 “.0” 这样的尾部，说明他可能按版本号递增来改密码，
    因此这里只生成“尾号加一档”和“主号加减一”的形式，不做任意数字替换。
    """
    match = VERSION_SUFFIX_PATTERN.match(value)
    if not match:
        return
    head = match.group("head")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    for candidate_minor in range(min_minor, max_minor + 1):
        if candidate_minor != minor:
            yield f"{head}{major}.{candidate_minor}"
    for candidate_major in (major - 1, major + 1):
        if candidate_major >= 0:
            yield f"{head}{candidate_major}.{minor}"


def typo_variants(
    value: str,
    *,
    append_digits: str = DEFAULT_TYPO_APPEND_DIGITS,
    stutter: bool = True,
    drop: bool = True,
) -> Iterator[str]:
    """Yield likely single-character typos of a value.

    只覆盖三种“手抖”形态，不做任意字符插入：

    * stutter：某一位被连击，多出一个相同字符（如 ``wsq`` → ``wssq``）；
    * drop：某一位漏打（如 ``wangsiqi`` → ``wangsiq``）；
    * append：结尾多敲一个数字（如 ``2580`` → ``25805``）。
    """
    if not value:
        return
    seen: set[str] = set()
    if stutter:
        for index, char in enumerate(value):
            candidate = f"{value[: index + 1]}{char}{value[index + 1 :]}"
            if candidate != value and candidate not in seen:
                seen.add(candidate)
                yield candidate
    if drop and len(value) > 3:
        for index in range(len(value)):
            candidate = f"{value[:index]}{value[index + 1 :]}"
            if candidate and candidate not in seen:
                seen.add(candidate)
                yield candidate
    for digit in append_digits:
        candidate = value + digit
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _trusted_atoms(
    profile: dict, atoms: Sequence[_Atom], trailing: frozenset[str]
) -> list[_Atom]:
    """Pick atoms from the highest weighted dimensions for trio generation."""
    weights: dict[str, int] = {}
    for atom in atoms:
        if atom.dimension in trailing:
            continue
        weights[atom.dimension] = max(weights.get(atom.dimension, 0), atom.weight)
    top_dimensions = {
        name
        for name, _weight in sorted(
            weights.items(), key=lambda item: (-item[1], item[0])
        )[:TRIO_DIMENSION_COUNT]
    }
    selected = [atom for atom in atoms if atom.dimension in top_dimensions]
    selected.sort(key=lambda atom: (-atom.weight, atom.order))
    return selected[:TRIO_ATOM_LIMIT]


def candidates_from_profile(
    profile: dict,
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude: Iterable[str] = (),
    include_triples: bool = True,
) -> Iterator[str]:
    """Yield ranked candidates built from whole profile atoms."""
    if max_length <= 0:
        raise ValueError("max_length must be a positive integer")

    excluded = {value.strip() for value in exclude if value and value.strip()}
    atoms = _profile_atoms(profile)
    trailing = _trailing_dimensions(profile)
    combinable = [atom for atom in atoms if atom.dimension not in trailing]

    # 评分参数可在画像里调整，方便每轮实验只改数据不改代码。
    short_max_length = int(_rule(profile, "short_max_length", SHORT_MAX_LENGTH))
    long_length_penalty = float(
        _rule(profile, "long_length_penalty", LONG_LENGTH_PENALTY)
    )
    combination_penalty = float(
        _rule(profile, "combination_penalty", COMBINATION_PENALTY)
    )

    def _score(value: str, component_weights: Sequence[float]) -> float:
        """分数以最弱原子为准，再扣掉组合复杂度与超长惩罚。"""
        score = min(component_weights) - combination_penalty * (len(component_weights) - 1)
        if len(value) > short_max_length:
            score -= long_length_penalty
        return score

    hint_rank: dict[str, tuple[float, int, int]] = {}
    tail_rank: dict[str, tuple[float, int, int]] = {}

    def _remember(
        store: dict[str, tuple[float, int, int]],
        value: str,
        component_weights: Sequence[float],
    ) -> None:
        if (
            not value
            or value in excluded
            or not value.isascii()
            or len(value) > max_length
        ):
            return
        score = _score(value, component_weights)
        size = len(component_weights)
        previous = store.get(value)
        if previous is None:
            store[value] = (score, size, len(store))
        elif score > previous[0]:
            store[value] = (score, size, previous[2])

    def add(value: str, component_weights: Sequence[float]) -> None:
        _remember(hint_rank, value, component_weights)

    # 单个原子 + 允许的大小写形态。
    for atom in atoms:
        store = tail_rank if atom.dimension in trailing else hint_rank
        for variant in case_variants(atom.value):
            _remember(store, variant, (atom.weight,))

    # 作者旧密码暴露的书写习惯：符号分隔、片段重复、版本号递增。
    separators = tuple(
        str(item) for item in _rule(profile, "separators", DEFAULT_SEPARATORS)
    ) or ("",)
    separator_min_weight = int(
        _rule(profile, "separator_min_weight", DEFAULT_SEPARATOR_MIN_WEIGHT)
    )
    separator_penalty = float(
        _rule(profile, "separator_penalty", DEFAULT_SEPARATOR_PENALTY)
    )
    doubling_max_length = int(
        _rule(profile, "doubling_max_length", DEFAULT_DOUBLING_MAX_LENGTH)
    )
    doubling_penalty = float(
        _rule(profile, "doubling_penalty", DEFAULT_DOUBLING_PENALTY)
    )
    version_minor = (
        int(_rule(profile, "version_min_minor", DEFAULT_VERSION_MIN_MINOR)),
        int(_rule(profile, "version_max_minor", DEFAULT_VERSION_MAX_MINOR)),
    )
    version_penalty = float(_rule(profile, "version_penalty", DEFAULT_VERSION_PENALTY))

    for atom in combinable:
        if 0 < len(atom.value) <= doubling_max_length:
            for variant in case_variants(atom.value):
                _remember(hint_rank, variant + variant, (atom.weight - doubling_penalty,))
        for bumped in version_variants(
            atom.value, min_minor=version_minor[0], max_minor=version_minor[1]
        ):
            for variant in case_variants(bumped):
                _remember(hint_rank, variant, (atom.weight - version_penalty,))

    # 手抖多打/漏打一个字符：只对高可信短线索生效，并允许它继续和强线索拼接。
    typo_enabled = bool(_rule(profile, "typo_enabled", DEFAULT_TYPO_ENABLED))
    typo_min_weight = float(_rule(profile, "typo_min_weight", DEFAULT_TYPO_MIN_WEIGHT))
    typo_max_atom_length = int(
        _rule(profile, "typo_max_atom_length", DEFAULT_TYPO_MAX_ATOM_LENGTH)
    )
    typo_penalty = float(_rule(profile, "typo_penalty", DEFAULT_TYPO_PENALTY))
    typo_append_digits = str(
        _rule(profile, "typo_append_digits", DEFAULT_TYPO_APPEND_DIGITS)
    )
    partner_min_weight = float(
        _rule(profile, "typo_partner_min_weight", DEFAULT_TYPO_PARTNER_MIN_WEIGHT)
    )
    partner_max_length = int(
        _rule(profile, "typo_partner_max_length", DEFAULT_TYPO_PARTNER_MAX_LENGTH)
    )

    if typo_enabled:
        typo_atoms: list[tuple[str, float, str]] = []
        for atom in combinable:
            if atom.weight < typo_min_weight or len(atom.value) > typo_max_atom_length:
                continue
            for typo in typo_variants(atom.value, append_digits=typo_append_digits):
                typo_weight = atom.weight - typo_penalty
                typo_atoms.append((typo, typo_weight, atom.value))
                for variant in case_variants(typo):
                    _remember(hint_rank, variant, (typo_weight,))

        partners = [
            atom
            for atom in combinable
            if atom.weight >= partner_min_weight and len(atom.value) <= partner_max_length
        ]
        for typo, typo_weight, source in typo_atoms:
            for partner in partners:
                if partner.value == source:
                    continue
                add(typo + partner.value, (typo_weight, float(partner.weight)))
                add(partner.value + typo, (float(partner.weight), typo_weight))

    # 两原子组合：整块拼接、两种顺序；高可信线索之间才插入符号分隔。
    for left, right in itertools.permutations(combinable, 2):
        if left.value == right.value:
            continue
        weights = (float(left.weight), float(right.weight))
        usable_separators = separators if min(weights) >= separator_min_weight else ("",)
        for left_variant in case_variants(left.value):
            for right_variant in case_variants(right.value):
                for index, separator in enumerate(usable_separators):
                    penalised = tuple(weight - separator_penalty * index for weight in weights)
                    add(left_variant + separator + right_variant, penalised)

    # 三原子组合：只取最高权重分类中的少量原子，保持候选集有限。
    if include_triples:
        trusted = _trusted_atoms(profile, combinable, trailing)
        for first, second in itertools.permutations(trusted, 2):
            if first.value == second.value:
                continue
            for third in trusted:
                if third.value in {first.value, second.value}:
                    continue
                weights = (
                    float(first.weight),
                    float(second.weight),
                    float(third.weight),
                )
                add(first.value + second.value + third.value, weights)

    def _ordered(store: dict[str, tuple[float, int, int]]) -> list[str]:
        return [
            value
            for value, _meta in sorted(
                store.items(),
                key=lambda item: (-item[1][0], item[1][1], len(item[0]), item[0]),
            )
        ]

    seen: set[str] = set()
    for value in _ordered(hint_rank):
        seen.add(value)
        yield value
    # 尾部分类（励志短句等）不参与组合，且永远排在提示词之后。
    for value in _ordered(tail_rank):
        if value not in seen:
            yield value


def _read_lines(path: Path | str) -> list[str]:
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def default_head_baselines() -> tuple[Path, ...]:
    return tuple(
        MODULE_DIR / name
        for name in DEFAULT_HEAD_BASELINES
        if (MODULE_DIR / name).is_file()
    )


def default_full_baselines() -> tuple[Path, ...]:
    return tuple(
        MODULE_DIR / name
        for name in DEFAULT_FULL_BASELINES
        if (MODULE_DIR / name).is_file()
    )


def export_candidates(
    profile_path: Path | str,
    output_path: Path,
    *,
    limit: int = DEFAULT_LIMIT,
    max_length: int = DEFAULT_MAX_LENGTH,
    exclude_files: Iterable[Path | str] = (),
    exclude_prefix_files: Iterable[Path | str] = (),
    exclude_prefix_length: int = DEFAULT_EXCLUDE_PREFIX_LENGTH,
    exclude: Iterable[str] = (),
    include_triples: bool = True,
) -> int:
    """Write ranked candidates to a TXT file, one value per line."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    if exclude_prefix_length <= 0:
        raise ValueError("exclude_prefix_length must be a positive integer")

    profile = load_profile(profile_path)
    excluded = {value for value in exclude if value}
    for path in exclude_files:
        file_path = Path(path)
        if file_path.is_file():
            excluded.update(_read_lines(file_path))
    for path in exclude_prefix_files:
        file_path = Path(path)
        if file_path.is_file():
            excluded.update(_read_lines(file_path)[:exclude_prefix_length])

    written = 0
    with Path(output_path).open("w", encoding="utf-8") as output:
        for candidate in candidates_from_profile(
            profile,
            max_length=max_length,
            exclude=excluded,
            include_triples=include_triples,
        ):
            if written >= limit:
                break
            output.write(candidate + "\n")
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile-driven candidate ranking")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument(
        "--exclude",
        type=Path,
        action="append",
        help="候选 TXT，整份排除；可重复传入",
    )
    parser.add_argument(
        "--exclude-head",
        type=Path,
        action="append",
        help="候选 TXT，只排除前 N 行（默认 10101）；可重复传入",
    )
    parser.add_argument("--exclude-head-lines", type=int, default=DEFAULT_EXCLUDE_PREFIX_LENGTH)
    parser.add_argument("--no-triples", action="store_true", help="不生成三原子组合")
    args = parser.parse_args()

    explicit = bool(args.exclude or args.exclude_head)
    full_files = tuple(args.exclude) if explicit else default_full_baselines()
    head_files = tuple(args.exclude_head) if explicit else default_head_baselines()

    try:
        written = export_candidates(
            args.profile,
            args.output,
            limit=args.limit,
            max_length=args.max_length,
            exclude_files=full_files,
            exclude_prefix_files=head_files,
            exclude_prefix_length=args.exclude_head_lines,
            include_triples=not args.no_triples,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    print(f"完整排除文件: {', '.join(Path(p).name for p in full_files) or '无'}")
    print(
        f"前缀排除文件: {', '.join(Path(p).name for p in head_files) or '无'}"
        f"（每个前 {args.exclude_head_lines} 行）"
    )
    print(f"已写入 {written} 条候选到: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
