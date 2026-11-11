"""End-to-end tests for Project Jarvis CLI."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config import EXIT_SUCCESS, EXIT_CRITICAL


class TestJarvisCLIEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "cli_test_graph.sqlite")
        self.jarvis_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jarvis.py")

    def tearDown(self):
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [sys.executable, self.jarvis_py] + args
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_cli_help(self):
        proc = self.run_cli(["--help"])
        self.assertEqual(proc.returncode, EXIT_SUCCESS)
        self.assertIn("Project Jarvis", proc.stdout)
        self.assertIn("harvest", proc.stdout)
        self.assertIn("scan", proc.stdout)

    def test_cli_harvest_and_clean_scan(self):
        # Create a clean Apex class
        clean_file = os.path.join(self.tmp_dir.name, "CleanService.cls")
        with open(clean_file, "w", encoding="utf-8") as f:
            f.write("""
            public class CleanService {
                public static void logMessage(String msg) {
                    System.debug(msg);
                }
            }
            """)

        # Harvest
        h_proc = self.run_cli(["harvest", "--source", clean_file, "--db", self.db_path])
        self.assertEqual(h_proc.returncode, EXIT_SUCCESS)
        self.assertIn("Harvest complete", h_proc.stdout)

        # Scan should return 0 (Clean / INFO only)
        s_proc = self.run_cli(["scan", "--db", self.db_path, "--format", "json"])
        self.assertEqual(s_proc.returncode, EXIT_SUCCESS)
        parsed = json.loads(s_proc.stdout)
        self.assertEqual(parsed["scan_run"]["critical_count"], 0)

    def test_cli_scan_critical_exit_code_1(self):
        # Create a bad file with SOQL in loop
        bad_file = os.path.join(self.tmp_dir.name, "BadBatch.cls")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("""
            public class BadBatch {
                public void run(List<Account> accs) {
                    for (Account a : accs) {
                        List<Contact> c = [SELECT Id FROM Contact WHERE AccountId = :a.Id];
                        update c;
                    }
                }
            }
            """)

        # Scan with path directly
        s_proc = self.run_cli(["scan", "--path", bad_file, "--db", self.db_path])
        self.assertEqual(s_proc.returncode, EXIT_CRITICAL)
        self.assertIn("CRITICAL", s_proc.stdout)
        self.assertIn("RULE-GOV-003", s_proc.stdout)

    def test_cli_impact_traversal(self):
        # Create small test nodes via harvest or scan
        file1 = os.path.join(self.tmp_dir.name, "A.cls")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("public class A { void f() { B.run(); } }")

        self.run_cli(["harvest", "--source", file1, "--db", self.db_path])
        i_proc = self.run_cli(["impact", "--component", "apex.class.A", "--db", self.db_path])
        self.assertEqual(i_proc.returncode, EXIT_SUCCESS)
        self.assertIn("Blast Radius", i_proc.stdout)

    def test_cli_memory_search_and_rca(self):
        # Test search
        proc = self.run_cli(["memory", "search", "YesterdayDenialSyncBatch"])
        self.assertEqual(proc.returncode, EXIT_SUCCESS)
        self.assertIn("YesterdayDenialSyncBatch", proc.stdout)

        # Test rca
        rca_proc = self.run_cli(["memory", "rca", "--component", "YesterdayDenialSyncBatch"])
        self.assertEqual(rca_proc.returncode, EXIT_SUCCESS)
        self.assertIn("Historical RCAs for 'YesterdayDenialSyncBatch'", rca_proc.stdout)

    def test_cli_report_generation(self):
        report_file = os.path.join(self.tmp_dir.name, "audit.md")
        proc = self.run_cli(["report", "--output", report_file, "--db", self.db_path])
        self.assertEqual(proc.returncode, EXIT_SUCCESS)
        self.assertTrue(os.path.exists(report_file))
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Project Jarvis: Architecture & Conflict Radar Audit Report", content)


if __name__ == "__main__":
    unittest.main()
