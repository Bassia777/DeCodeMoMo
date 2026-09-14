import tempfile
import unittest
from pathlib import Path

from toy_candidate_lab import (
    DEFAULT_LIMIT,
    DEFAULT_OUTPUT,
    INSPIRATIONAL_PHRASES,
    candidates,
    export_candidates,
    load_exclusions,
    load_hints,
    run,
)


class CandidateGenerationTests(unittest.TestCase):
    def test_natural_number_patterns_are_independent_of_hints(self):
        values = set(candidates(("wyy",), max_length=20))

        self.assertTrue(
            {"012345", "123456", "654321", "000000", "112233"} <= values
        )

    def test_numeric_fragments_and_reversed_fragments_are_generated(self):
        values = set(candidates(("010228",), max_length=20))

        self.assertTrue({"010228", "10228", "228", "822010"} <= values)

    def test_text_and_numeric_rules_can_be_mixed(self):
        values = set(candidates(("wyy", "010228"), max_length=20))

        self.assertIn("wyy010228", values)
        self.assertIn("010228wyy", values)

    def test_inspirational_pinyin_is_expanded_and_has_no_spaces_or_chinese(self):
        values = set(candidates(("wyy",), max_length=20))

        expected = {
            "xiongxinzhuangzhi",
            "fenfaxiangqian",
            "lizhigaoyuan",
            "yongpangaofeng",
            "zhuangzhilingyun",
            "zhujiumeihaoweilai",
            "dazhidayong",
        }
        self.assertTrue(expected <= values)
        self.assertTrue(all(" " not in value for value in expected))
        self.assertTrue(all(value.isascii() for value in values))

    def test_inspirational_pinyin_ranks_below_prompt_and_above_common_numbers(self):
        values = list(candidates(("wyy",), max_length=20))

        self.assertLess(values.index("wyy"), values.index("xiongxinzhuangzhi"))
        self.assertLess(values.index("weilaikeqi"), values.index("123456"))

    def test_default_candidate_limit_is_fifty_thousand(self):
        self.assertEqual(DEFAULT_LIMIT, 50_000)
        self.assertGreaterEqual(len(INSPIRATIONAL_PHRASES), 60)
        self.assertEqual(DEFAULT_OUTPUT.name, "toy_candidates_v2.txt")

    def test_exclusion_set_is_a_hard_filter(self):
        excluded = {"wyy", "123456"}
        values = list(candidates(("wyy",), max_length=20, exclude=excluded))

        self.assertNotIn("wyy", values)
        self.assertNotIn("123456", values)
        self.assertIn("weilaikeqi", values)

    def test_exclusion_files_are_loaded_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.txt"
            second = Path(directory) / "second.txt"
            first.write_text("alpha\n\nalpha\n", encoding="utf-8")
            second.write_text("beta\n", encoding="utf-8")

            self.assertEqual(load_exclusions((first, second)), {"alpha", "beta"})

    def test_hints_file_is_loaded_without_comments_or_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            hints_path = Path(directory) / "hints.local.txt"
            hints_path.write_text("alpha\n\n beta \n", encoding="utf-8")

            self.assertEqual(load_hints(hints_path), ("alpha", "beta"))

    def test_mixed_personal_hint_can_keep_literal_and_split_forms(self):
        values = set(candidates(("alpha25805.0",), max_length=20))

        self.assertTrue({"alpha25805.0", "alpha258050", "25805", "0"} <= values)

    def test_export_applies_exclusion_file(self):
        with tempfile.TemporaryDirectory() as directory:
            excluded_path = Path(directory) / "v1.txt"
            output_path = Path(directory) / "v2.txt"
            excluded_path.write_text("wyy\n", encoding="utf-8")

            written = export_candidates(
                25,
                output_path,
                hints=("wyy",),
                max_length=20,
                exclude_files=(excluded_path,),
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(written, 25)
            self.assertNotIn("wyy", lines)

    def test_short_candidates_are_emitted_before_long_candidates(self):
        values = list(candidates(("wangyaoyi", "15361652627"), max_length=20))

        first_long = next(index for index, value in enumerate(values) if len(value) > 15)
        self.assertTrue(all(len(value) <= 15 for value in values[:first_long]))
        self.assertTrue(any(len(value) > 15 for value in values[first_long:]))
        self.assertTrue(all(len(value) <= 20 for value in values))

    def test_candidate_generation_is_deterministic_and_deduplicated(self):
        values_a = list(candidates(("wyy", "010228"), max_length=20))
        values_b = list(candidates(("wyy", "010228"), max_length=20))

        self.assertEqual(values_a, values_b)
        self.assertEqual(len(values_a), len(set(values_a)))

    def test_run_honors_limit_and_can_use_a_test_target(self):
        first = next(candidates(("wyy",), max_length=20))

        self.assertEqual(
            run(1, hints=("wyy",), target=first, max_length=20),
            (first, 1, False),
        )
        self.assertEqual(
            run(1, hints=("wyy",), target="not-generated", max_length=20),
            (None, 1, True),
        )

    def test_export_writes_one_candidate_per_line(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "candidates.txt"

            written = export_candidates(
                25,
                output_path,
                hints=("wyy", "010228"),
                max_length=20,
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(written, 25)
            self.assertEqual(len(lines), 25)
            self.assertEqual(len(lines), len(set(lines)))

    def test_length_configuration_is_validated(self):
        for kwargs in (
            {"short_max_length": 0, "max_length": 20},
            {"short_max_length": 15, "max_length": 14},
            {"short_max_length": 15, "max_length": 0},
        ):
            with self.assertRaises(ValueError):
                list(candidates(("wyy",), **kwargs))


if __name__ == "__main__":
    unittest.main()
