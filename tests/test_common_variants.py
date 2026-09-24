import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from theologia_search.common import grammatical_variants


class GrammaticalVariantsTests(unittest.TestCase):
    def assert_symmetric_family(self, forms: tuple[str, ...], expected: set[str]) -> None:
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(set(grammatical_variants(form)), expected)

    def test_regular_families_are_symmetric(self):
        self.assert_symmetric_family(
            ("clean", "cleans", "cleaned", "cleaning"),
            {"clean", "cleans", "cleaned", "cleaning"},
        )
        self.assert_symmetric_family(
            ("play", "plays", "played", "playing"),
            {"play", "plays", "played", "playing"},
        )
        self.assert_symmetric_family(
            ("study", "studies", "studied", "studying"),
            {"study", "studies", "studied", "studying"},
        )
        self.assert_symmetric_family(
            ("stop", "stops", "stopped", "stopping"),
            {"stop", "stops", "stopped", "stopping"},
        )
        self.assert_symmetric_family(
            ("create", "creates", "created", "creating"),
            {"create", "creates", "created", "creating"},
        )
        self.assert_symmetric_family(
            ("die", "dies", "died", "dying"),
            {"die", "dies", "died", "dying", "dice"},
        )

    def test_irregular_verbs_are_symmetric(self):
        self.assert_symmetric_family(
            ("go", "goes", "going", "went", "gone"),
            {"go", "goes", "going", "went", "gone"},
        )
        self.assert_symmetric_family(
            ("be", "am", "is", "are", "was", "were", "been", "being"),
            {"be", "am", "is", "are", "was", "were", "been", "being"},
        )
        self.assert_symmetric_family(
            ("write", "writes", "writing", "wrote", "written"),
            {"write", "writes", "writing", "wrote", "written"},
        )

    def test_irregular_nouns_and_invariant_nouns_are_symmetric(self):
        self.assert_symmetric_family(("man", "men"), {"man", "men"})
        self.assert_symmetric_family(("child", "children"), {"child", "children"})
        self.assert_symmetric_family(("analysis", "analyses"), {"analysis", "analyses"})
        self.assert_symmetric_family(("criterion", "criteria"), {"criterion", "criteria"})
        self.assert_symmetric_family(("sheep",), {"sheep"})
        self.assert_symmetric_family(("news",), {"news"})

    def test_comparison_families_are_symmetric(self):
        self.assert_symmetric_family(("good", "better", "best"), {"good", "better", "best"})
        self.assert_symmetric_family(("far", "farther", "farthest", "further", "furthest"), {
            "far",
            "farther",
            "farthest",
            "further",
            "furthest",
        })

    def test_noun_mode_keeps_noun_forms_without_verb_forms(self):
        variants = set(
            grammatical_variants(
                "animal",
                include_verb_forms=False,
                include_comparison_forms=False,
            )
        )
        self.assertIn("animal", variants)
        self.assertIn("animals", variants)
        self.assertNotIn("animaled", variants)
        self.assertNotIn("animaling", variants)


if __name__ == "__main__":
    unittest.main()
