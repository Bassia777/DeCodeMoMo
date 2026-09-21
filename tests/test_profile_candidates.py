import json
import tempfile
import unittest
from pathlib import Path

from profile_candidates import (
    candidates_from_profile,
    case_variants,
    export_candidates,
    load_profile,
    typo_variants,
)


def _profile(items_by_dimension, trailing=()):
    dimensions = {}
    for name, (weight, values) in items_by_dimension.items():
        dimensions[name] = {
            "weight": weight,
            "items": [{"value": value, "kind": "test"} for value in values],
        }
    return {"dimensions": dimensions, "trailing_dimensions": list(trailing)}


class CaseVariantTests(unittest.TestCase):
    def test_case_variants_rarely_create_inner_capitals(self):
        self.assertEqual(
            list(case_variants("examplename")),
            ["examplename", "Examplename", "EXAMPLENAME"],
        )

    def test_case_variants_deduplicate_already_upper_values(self):
        self.assertEqual(list(case_variants("WSQ")), ["WSQ"])

    def test_case_variants_keep_existing_inner_capitals(self):
        self.assertEqual(list(case_variants("Example")), ["Example", "EXAMPLE"])


class TypoVariantTests(unittest.TestCase):
    def test_stutter_appends_and_drops_are_enumerated(self):
        values = set(typo_variants("abc", append_digits="9"))

        self.assertTrue({"aabc", "abbc", "abcc", "abc9"} <= values)

    def test_short_values_are_not_dropped_below_meaningfulness(self):
        values = set(typo_variants("abc", append_digits=""))

        self.assertNotIn("ab", values)
        self.assertNotIn("bc", values)

    def test_typo_variants_never_reorder_characters(self):
        values = set(typo_variants("abcd", append_digits="1"))

        self.assertNotIn("dcba", values)


class ProfileCandidateTests(unittest.TestCase):
    def test_no_value_is_ever_reversed(self):
        profile = _profile({"identity": (100, ["abc"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertNotIn("cba", values)

    def test_given_password_is_kept_whole_and_only_case_styled(self):
        profile = _profile({"history": (96, ["oldpass1.0"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertTrue({"oldpass1.0", "Oldpass1.0", "OLDPASS1.0"} <= values)
        self.assertNotIn("oldpass", values)
        self.assertNotIn("pass1", values)
        self.assertNotIn("oldpass1", values)

    def test_former_password_ranks_near_the_top(self):
        profile = _profile({"identity": (100, ["aaa"]), "history": (96, ["abc123"])})

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertLess(values.index("abc123"), 12)

    def test_whole_atoms_combine_in_both_orders(self):
        profile = _profile({"identity": (100, ["aaa"]), "dates": (86, ["111"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("aaa111", values)
        self.assertIn("111aaa", values)
        self.assertNotIn("aaa-111", values)

    def test_configured_separators_only_apply_to_strong_atoms(self):
        strong = _profile({"identity": (100, ["aaa"]), "dates": (86, ["111"])})
        weak = _profile({"identity": (100, ["aaa"]), "contacts": (66, ["111"])})

        strong_values = set(candidates_from_profile(strong, max_length=20))
        weak_values = set(candidates_from_profile(weak, max_length=20))

        self.assertIn("aaa.111", strong_values)
        self.assertIn("aaa_111", strong_values)
        self.assertNotIn("aaa.111", weak_values)
        self.assertNotIn("aaa_111", weak_values)

    def test_repeated_fragments_are_generated_for_short_atoms(self):
        profile = _profile({"identity": (100, ["aaa"]), "dates": (86, ["1234567"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("aaaaaa", values)
        self.assertNotIn("12345671234567", values)

    def test_version_suffix_is_bumped_without_touching_the_body(self):
        profile = _profile({"history": (96, ["oldpass5.0"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("oldpass5.1", values)
        self.assertIn("oldpass5.9", values)
        self.assertIn("oldpass6.0", values)
        self.assertIn("oldpass4.0", values)
        self.assertNotIn("oldpass5.0.0", values)
        self.assertNotIn("oldpass", values)

    def test_scoring_parameters_can_be_overridden_in_the_profile(self):
        profile = _profile({"identity": (100, ["aaa"]), "dates": (86, ["verylongatom"] )})
        profile["combination_rules"] = {
            "short_max_length": 15,
            "long_length_penalty": 100,
            "combination_penalty": 6,
            "separators": [""],
            "separator_min_weight": 84,
            "doubling_max_length": 0,
            "doubling_penalty": 4,
            "version_min_minor": 1,
            "version_max_minor": 9,
            "version_penalty": 4,
        }

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertLess(values.index("aaa"), values.index("verylongatom"))

    def test_single_character_typos_of_strong_atoms_are_generated(self):
        profile = _profile({"identity": (100, ["abcd"]), "contacts": (66, ["wxyz"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("aabcd", values)
        self.assertIn("abcd0", values)
        self.assertNotIn("wxyz0", values)

    def test_typo_atoms_combine_with_strong_partners_only(self):
        profile = _profile(
            {
                "identity": (100, ["abcd"]),
                "dates": (86, ["1111"]),
                "contacts": (66, ["9999"]),
            }
        )

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("aabcd1111", values)
        self.assertIn("1111aabcd", values)
        self.assertNotIn("aabcd9999", values)

    def test_typo_family_can_be_disabled(self):
        profile = _profile({"identity": (100, ["abcd"])})
        profile["combination_rules"] = {"typo_enabled": False, "separators": [""]}

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("abcd", values)
        self.assertNotIn("aabcd", values)

    def test_trusted_dimensions_rank_before_weaker_ones(self):
        profile = _profile(
            {"identity": (100, ["aaa"]), "contacts": (66, ["999"]), "zodiac": (76, ["zzz"])}
        )

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertLess(values.index("aaa"), values.index("zzz"))
        self.assertLess(values.index("zzz"), values.index("999"))

    def test_candidates_longer_than_fifteen_sink_below_shorter_ones(self):
        long_atom = "b" * 16
        profile = _profile(
            {"games": (80, ["ggg"]), "dates": (86, [long_atom])}
        )

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertLess(values.index("ggg"), values.index(long_atom))

    def test_item_weight_can_override_its_dimension_weight(self):
        profile = {
            "dimensions": {
                "identity": {"weight": 100, "items": [{"value": "aaa", "kind": "test"}]},
                "contacts": {
                    "weight": 66,
                    "items": [{"value": "777", "kind": "test", "weight": 92}],
                },
            }
        }

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertIn("aaa777", values)
        ranked = list(candidates_from_profile(profile, max_length=20))
        # 覆盖后的 777 是 92 分，高于 aaa777（取较弱原子 92 再扣组合惩罚 6），
        # 而 aaa777 仍然高于 66 分的未覆盖线索。
        self.assertLess(ranked.index("777"), ranked.index("aaa777"))

    def test_weak_dimension_items_stay_below_overridden_items(self):
        profile = {
            "dimensions": {
                "identity": {"weight": 100, "items": [{"value": "aaa", "kind": "test"}]},
                "contacts": {
                    "weight": 66,
                    "items": [
                        {"value": "777", "kind": "test", "weight": 92},
                        {"value": "555", "kind": "test"},
                    ],
                },
            }
        }

        ranked = list(candidates_from_profile(profile, max_length=20))

        self.assertLess(ranked.index("777"), ranked.index("aaa777"))
        self.assertLess(ranked.index("aaa777"), ranked.index("555"))

    def test_trailing_dimension_never_combines_and_comes_last(self):
        profile = _profile(
            {"identity": (100, ["aaa"]), "inspiration": (45, ["qqq", "aaa"])},
            trailing=("inspiration",),
        )

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertEqual(values.count("aaa"), 1)
        self.assertLess(values.index("aaa"), values.index("qqq"))
        self.assertNotIn("aaaqqq", values)
        self.assertNotIn("qqqaaa", values)

    def test_name_pair_relationship_rows_are_not_emitted_as_candidates(self):
        profile = _profile({"aliases": (95, ["examplename <-> efn"])})

        values = list(candidates_from_profile(profile, max_length=40))

        self.assertEqual(values, [])

    def test_max_length_is_enforced(self):
        profile = _profile({"identity": (100, ["abcdefghij"])})

        values = list(candidates_from_profile(profile, max_length=6))

        self.assertEqual(values, [])

    def test_exclusions_are_applied(self):
        profile = _profile({"identity": (100, ["aaa"]), "dates": (86, ["111"])})

        values = set(
            candidates_from_profile(profile, max_length=20, exclude={"aaa111", "aaa"})
        )

        self.assertNotIn("aaa111", values)
        self.assertNotIn("aaa", values)
        self.assertIn("111aaa", values)

    def test_non_ascii_values_are_skipped(self):
        profile = _profile({"identity": (100, ["文明雪", "ascii"])})

        values = set(candidates_from_profile(profile, max_length=20))

        self.assertTrue({"ascii", "Ascii", "ASCII"} <= values)
        self.assertFalse(any(not value.isascii() for value in values))

    def test_every_candidate_is_unique(self):
        profile = _profile(
            {"identity": (100, ["aaa", "bbb"]), "dates": (86, ["111"]), "contacts": (66, ["999"])}
        )

        values = list(candidates_from_profile(profile, max_length=20))

        self.assertEqual(len(values), len(set(values)))

    def test_load_profile_rejects_missing_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"other": 1}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(path)

    def test_export_writes_one_candidate_per_line_and_honors_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.json"
            output_path = Path(directory) / "out.txt"
            profile_path.write_text(
                json.dumps(_profile({"identity": (100, ["aaa"]), "dates": (86, ["111"])})),
                encoding="utf-8",
            )

            written = export_candidates(profile_path, output_path, limit=4, max_length=20)

            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(written, 4)
            self.assertEqual(len(lines), 4)
            self.assertEqual(len(lines), len(set(lines)))

    def test_export_applies_full_and_prefix_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.json"
            output_path = Path(directory) / "out.txt"
            full_path = Path(directory) / "full.txt"
            head_path = Path(directory) / "head.txt"
            profile_path.write_text(
                json.dumps(_profile({"identity": (100, ["aaa", "bbb"])})),
                encoding="utf-8",
            )
            full_path.write_text("aaa\n", encoding="utf-8")
            head_path.write_text("bbb\nccc\n", encoding="utf-8")

            written = export_candidates(
                profile_path,
                output_path,
                limit=10,
                max_length=20,
                exclude_files=(full_path,),
                exclude_prefix_files=(head_path,),
                exclude_prefix_length=1,
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("aaa", lines)
            self.assertNotIn("bbb", lines)
            self.assertEqual(written, len(lines))

    def test_export_rejects_invalid_prefix_length(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.json"
            output_path = Path(directory) / "out.txt"
            profile_path.write_text(json.dumps(_profile({})), encoding="utf-8")

            with self.assertRaises(ValueError):
                export_candidates(
                    profile_path, output_path, exclude_prefix_length=0
                )


if __name__ == "__main__":
    unittest.main()
