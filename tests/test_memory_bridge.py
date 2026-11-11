"""Tests for Memory Bridge and Antigravity Index integration."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config import DEFAULT_INDEX_DIR
from jarvis.graph.models import Conflict
from jarvis.memory.bridge import MemoryBridge


class TestMemoryBridge(unittest.TestCase):

    def setUp(self):
        self.bridge = MemoryBridge(DEFAULT_INDEX_DIR)
        if not self.bridge.is_available():
            self.skipTest("Antigravity Index not present on machine")

    def test_search_memory_fts_and_like(self):
        # Search for a known term from Krishna's work
        results = self.bridge.search("YesterdayDenialSyncBatch", limit=5)
        self.assertTrue(len(results) >= 1)
        r = results[0]
        self.assertTrue(len(r.conv_id) > 0)
        self.assertIn("YesterdayDenialSyncBatch", r.solution_summary + r.user_prompt)
        self.assertTrue(os.path.exists(r.transcript_path))

    def test_get_rca_context(self):
        rcas = self.bridge.get_rca_context("YesterdayDenialSyncBatch", rule_id="RULE-REC-001", limit=2)
        self.assertTrue(len(rcas) >= 1)
        best = rcas[0]
        self.assertTrue(len(best.solution_summary) > 10)

    def test_enrich_conflicts(self):
        conflict = Conflict(
            rule_id="RULE-REC-001",
            severity="CRITICAL",
            primary_node_id="apex.class.YesterdayDenialSyncBatch",
            message="Recursion loop detected",
        )
        enriched = self.bridge.enrich_conflicts([conflict])
        self.assertEqual(len(enriched), 1)
        c = enriched[0]
        self.assertIsNotNone(c.historical_rca_summary)
        self.assertIsNotNone(c.historical_conv_id)
        self.assertIn("Historical RCA Match", c.historical_rca_summary)

    def test_read_transcript_file(self):
        results = self.bridge.search("YesterdayDenialSyncBatch", limit=1)
        self.assertTrue(len(results) >= 1)
        md_file = results[0].md_file
        content = self.bridge.read_transcript(md_file)
        self.assertIsNotNone(content)
        self.assertTrue(len(content) > 100)


if __name__ == "__main__":
    unittest.main()
