import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import toy_candidate_lab as lab
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

    def test_v3_keeps_meaningful_hints_but_never_reverses_them(self):
        values = set(
            lab.candidates_v3(
                ("ExampleName", "en", "010228", "2020"),
                max_length=20,
            )
        )

        self.assertTrue({"ExampleName", "examplename", "en", "EN", "010228", "2020"} <= values)
        self.assertNotIn("emaNelpmaxE", values)
        self.assertNotIn("ne", values)
        self.assertNotIn("822010", values)

    def test_v3_drops_generic_numbers_and_arbitrary_combinations(self):
        values = set(
            lab.candidates_v3(
                ("ExampleName", "en", "987654321012", "2020"),
                max_length=20,
            )
        )

        self.assertIn("987654321012", values)
        self.assertIn("2020", values)
        self.assertNotIn("123456", values)
        self.assertNotIn("1111", values)
        self.assertNotIn("87654321012", values)
        self.assertNotIn("765", values)
        self.assertNotIn("ExampleName-en", values)
        self.assertNotIn("enExampleName", values)

        mixed_values = set(lab.candidates_v3(("a1-b",), max_length=20))
        self.assertNotIn("a", mixed_values)
        self.assertNotIn("b", mixed_values)

    def test_v3_pinyin_stays_below_personal_hints(self):
        values = list(lab.candidates_v3(("ExampleName", "en"), max_length=20))

        self.assertLess(values.index("ExampleName"), values.index("xiongxinzhuangzhi"))
        self.assertLess(values.index("en"), values.index("xiongxinzhuangzhi"))

    def test_v3_prefix_exclusions_read_only_the_requested_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.txt"
            baseline.write_text("first\nsecond\nthird\n", encoding="utf-8")

            self.assertEqual(
                lab.load_exclusion_prefixes((baseline,), 2),
                {"first", "second"},
            )

    def test_v3_export_applies_prefix_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.txt"
            output = Path(directory) / "v3.txt"
            baseline.write_text("ExampleName\nnot-used\n", encoding="utf-8")

            written = lab.export_candidates_v3(
                25,
                output,
                hints=("ExampleName", "en"),
                max_length=20,
                exclude_files=(baseline,),
                exclude_prefix=1,
            )

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(written, len(lines))
            self.assertNotIn("ExampleName", lines)
            self.assertIn("en", lines)

    def test_v3_default_output_and_prefix_limit(self):
        self.assertEqual(lab.DEFAULT_V3_OUTPUT.name, "toy_candidates_v3.txt")
        self.assertEqual(lab.DEFAULT_V3_EXCLUSION_PREFIX, 10_101)

    def test_run_v3_never_falls_back_to_the_v2_generator(self):
        found, attempts, capped = lab.run_v3(
            50_000,
            hints=("ExampleName", "en"),
            target="123456",
            max_length=20,
        )

        self.assertIsNone(found)
        self.assertLess(attempts, 50_000)
        self.assertFalse(capped)

    def test_v3_api_uses_default_baseline_prefixes_when_not_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline_v1 = Path(directory) / "v1.txt"
            baseline_v2 = Path(directory) / "v2.txt"
            output = Path(directory) / "v3.txt"
            baseline_v1.write_text("ExampleName\n", encoding="utf-8")
            baseline_v2.write_text("en\n", encoding="utf-8")

            with patch.object(lab, "DEFAULT_BASELINE", baseline_v1), patch.object(
                lab, "DEFAULT_OUTPUT", baseline_v2
            ):
                lab.export_candidates_v3(
                    25,
                    output,
                    hints=("ExampleName", "en"),
                    max_length=20,
                )

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("ExampleName", lines)
            self.assertNotIn("en", lines)

    def test_phase3_custom_exclude_is_used_for_export_and_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hints = root / "hints.txt"
            custom_baseline = root / "custom.txt"
            default_v1 = root / "default-v1.txt"
            default_v2 = root / "default-v2.txt"
            output = root / "v3.txt"
            hints.write_text("ExampleName\nen\n", encoding="utf-8")
            custom_baseline.write_text("en\n", encoding="utf-8")
            default_v1.write_text("ExampleName\n", encoding="utf-8")
            default_v2.write_text("unused\n", encoding="utf-8")

            argv = [
                "toy_candidate_lab.py",
                "--phase",
                "3",
                "--hints-file",
                str(hints),
                "--exclude",
                str(custom_baseline),
                "--output",
                str(output),
                "--limit",
                "50000",
            ]
            captured = io.StringIO()
            with patch.object(lab, "DEFAULT_BASELINE", default_v1), patch.object(
                lab, "DEFAULT_OUTPUT", default_v2
            ), patch.object(sys, "argv", argv), contextlib.redirect_stdout(captured):
                exit_code = lab.main()

            messages = captured.getvalue()
            written = int(re.search(r"已写入 (\d+) 条候选", messages).group(1))
            attempted = int(re.search(r"未命中，共尝试 (\d+) 个组合", messages).group(1))
            self.assertEqual(exit_code, 0)
            self.assertEqual(written, attempted)


if __name__ == "__main__":
    unittest.main()
