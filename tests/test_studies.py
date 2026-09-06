import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import studies


class StudyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.case = SimpleNamespace(id="case-01", label="Sample", concepts=[], patch_size=96)
        self.concept = SimpleNamespace(id="concept-0001", patches_revision="rev")
        self.positives = [SimpleNamespace(rank=i + 1, patch_index=i, source_x=i * 2,
                          source_y=i * 3, score=100 - i) for i in range(100)]
        self.zeros = [SimpleNamespace(rank=i, patch_index=1000 + i, source_x=i,
                      source_y=i, score=1) for i in range(20)]
        for name, value in [("STUDIES_DIR", self.root), ("get_case", self.case),
                            ("get_concept", self.concept), ("load_patches", self.positives),
                            ("_zero_candidates", self.zeros)]:
            context = patch.object(studies, name, return_value=value) if callable(value) is False and name.startswith("_") else None
            if name in {"STUDIES_DIR"}:
                context = patch.object(studies, name, value)
            elif name == "_zero_candidates":
                context = patch.object(studies, name, return_value=value)
            else:
                context = patch.object(studies, name, return_value=value)
            context.start(); self.addCleanup(context.stop)

    def test_validation_payload_is_blinded_and_disjoint(self):
        public = studies.create_study(studies.StudyCreate(
            case_id="case-01", concept_id="concept-0001", reviewer="P1",
            assessment="clear", pattern="adipose tissue", confidence="high"))
        self.assertEqual(set(public["evaluation"][0]), {"position", "judgment", "image_url"})
        record = studies._load(public["id"])
        self.assertFalse(set(range(studies.DISCOVERY_COUNT)) & {x["patch_index"] for x in record["evaluation"]})
        self.assertEqual({x["stratum"] for x in record["evaluation"]}, set(studies.STRATA))

    def test_average_precision_rewards_correct_ranking(self):
        score, curve = studies.average_precision([(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)])
        self.assertEqual(score, 1.0)
        self.assertEqual(curve[-1]["recall"], 1.0)

    def test_uncertain_is_excluded_from_binary_metrics(self):
        record = studies._load(studies.create_study(studies.StudyCreate(
            case_id="case-01", concept_id="concept-0001", reviewer="P1",
            assessment="partial", pattern="glands", confidence="medium"))["id"])
        record["evaluation"][0]["judgment"] = "present"
        record["evaluation"][1]["judgment"] = "uncertain"
        result = studies.study_results(record)
        self.assertEqual(result["prevalence"], 1.0)
        self.assertEqual(result["judgment_counts"]["uncertain"], 1)


if __name__ == "__main__":
    unittest.main()
