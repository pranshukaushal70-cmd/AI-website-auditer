#!/usr/bin/env python3
"""Tests for the evaluation harness: metric arithmetic, dataset integrity, fidelity, reproducibility."""

import http.client
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import run_evaluation  # noqa: E402


class TestMetrics(unittest.TestCase):
    def test_known_counts(self):
        m = harness.metrics(tp=3, fp=1, fn=2, tn=4)
        self.assertEqual(m["precision"], 0.75)
        self.assertEqual(m["recall"], 0.6)
        self.assertAlmostEqual(m["f1"], 2 * 0.75 * 0.6 / 1.35, places=4)
        self.assertEqual(m["false_positive_rate"], 0.2)
        self.assertEqual(m["accuracy"], 0.7)

    def test_undefined_ratios_are_none_not_zero_or_one(self):
        m = harness.metrics(tp=0, fp=0, fn=0, tn=5)
        self.assertIsNone(m["precision"])
        self.assertIsNone(m["recall"])
        self.assertIsNone(m["f1"])
        self.assertEqual(m["false_positive_rate"], 0.0)

    def test_zero_f1_when_nothing_is_right(self):
        self.assertEqual(harness.metrics(tp=0, fp=2, fn=2, tn=0)["f1"], 0.0)

    def test_outcome_mapping_and_abstention(self):
        self.assertEqual(harness._outcome(1, 1), "tp")
        self.assertEqual(harness._outcome(0, 1), "fp")
        self.assertEqual(harness._outcome(1, 0), "fn")
        self.assertEqual(harness._outcome(0, 0), "tn")
        self.assertEqual(harness._outcome(1, None), "abstain")
        self.assertIsNone(harness._status_prediction({"status": "unavailable"}))
        self.assertEqual(harness._status_prediction({"status": "warning"}), 1)


class TestDatasetIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.cases = harness.load_dataset("v1")

    def test_every_detector_has_both_classes(self):
        for detector in harness.DETECTORS:
            labels = [c.labels[detector] for c in self.cases if detector in c.labels]
            self.assertIn(True, labels, f"{detector} has no positive case")
            self.assertIn(False, labels, f"{detector} has no negative case")

    def test_every_page_is_used_and_every_label_has_a_rationale(self):
        pages_dir = harness.DATASET_DIR / "v1" / "pages"
        used = {c["page"] for c in self.manifest["cases"]}
        self.assertEqual(used, {p.name for p in pages_dir.glob("*.html")})
        for c in self.cases:
            self.assertEqual(set(c.labels), set(c.rationale), c.id)

    def test_reference_year_is_pinned(self):
        self.assertIsInstance(self.manifest["current_year"], int)


class TestFidelity(unittest.TestCase):
    def test_fixture_headers_use_the_same_type_as_the_real_fetcher(self):
        """fetch_url returns response.info(), an HTTPMessage; a dict would exercise non-production code (D14)."""
        _, cases = harness.load_dataset("v1")
        status, _, headers = harness._fixture_fetch(cases[0])(cases[0].url)
        self.assertEqual(status, 200)
        self.assertIsInstance(headers, http.client.HTTPMessage)
        self.assertNotIsInstance(headers, dict)
        self.assertEqual(headers["_final_url"], cases[0].url)


class TestReproducibility(unittest.TestCase):
    def test_two_runs_are_identical_and_match_committed_results(self):
        first, second = harness.evaluate("v1"), harness.evaluate("v1")
        self.assertEqual(harness.deterministic_view(first), harness.deterministic_view(second))
        committed = json.loads((run_evaluation.RESULTS_DIR / "v1" / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(harness.deterministic_view(committed), harness.deterministic_view(first),
                         "committed results are stale; re-run evaluation/run_evaluation.py and review the diff")

    def test_every_number_in_the_markdown_comes_from_the_json(self):
        committed = json.loads((run_evaluation.RESULTS_DIR / "v1" / "results.json").read_text(encoding="utf-8"))
        md = (run_evaluation.RESULTS_DIR / "v1" / "results.md").read_text(encoding="utf-8")
        self.assertEqual(md, run_evaluation.render_markdown(committed))


if __name__ == "__main__":
    unittest.main()
