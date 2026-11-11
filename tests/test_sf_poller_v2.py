"""Comprehensive Test Suite for Salesforce Telemetry & Poller Engine (Milestone 2 Upgrade).

Tests:
1. Strongly typed models in app/models.py:
   - BatchApexErrorEventRecord, CronTriggerInfo, BulkApiJobInfo, CertExpiryInfo,
     SetupAuditTrailRecord, CodeCoverageInfo, AuthSessionUser, SnowflakeReconInfo, DataQualityProbe.
2. In-Memory LRU ChildParentLookupCache (Platform Engineering Correction 4):
   - Hit/miss tracking, LRU eviction, resolve_parents batching, thread-safety.
3. High-Frequency Delta Sentry (Tier 1):
   - AsyncApexJob delta velocity (items/min) over time.
   - AuthSession active users parsing (correcting LoginHistory table scans).
   - CronTrigger sentinel for late, missed, or blocked scheduled jobs.
   - DeployRequest Tooling API query for in-flight deployments.
4. Real-Time Event & Failure Listener (Tier 2):
   - BatchApexErrorEvent ingestion with JobScope record IDs, stack trace, and toast dispatch.
   - FlowExecutionErrorEvent and FlowInterview stuck flow detection.
5. Low-Frequency Governance Sentry (Tier 3):
   - SetupAuditTrail direct-prod config change detection outside CI/CD.
   - Bulk API 2.0 Ingest & Query job monitoring via REST API.
   - Certificate expiration and OAuth token validity across 3 orgs.
   - ApexOrgWideCoverage and ApexCodeCoverageAggregate tooling queries.
   - Storage & Records (/limits/recordCount and DataStorageMB / FileStorageMB).
   - Data Quality Probes (statistical null rate sampling).
   - Daily SF <-> Snowflake Reconciliation (MAX SystemModstamp and record count).
6. CREATE_NO_WINDOW stealth execution flag compliance.
7. End-to-end atomic state persistence to app/state.json and backwards compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.event_bus import EventBus
from app.models import (
    AuthSessionUser,
    BatchApexErrorEventRecord,
    BulkApiJobInfo,
    CertExpiryInfo,
    CodeCoverageInfo,
    CronTriggerInfo,
    DataQualityProbe,
    EventTopic,
    OrgStatus,
    PollerState,
    SetupAuditTrailRecord,
    Severity,
    SnowflakeReconInfo,
)
from app.sf_poller import (
    CREATE_NO_WINDOW,
    ChildParentLookupCache,
    SalesforceCLI,
    SalesforcePoller,
    extract_json_from_cli_output,
    format_currency_usd,
    format_iso_timestamp,
)


class TestStronglyTypedModels(unittest.TestCase):
    """Verifies all 9 strongly typed models in app/models.py."""

    def test_batch_apex_error_event_record(self) -> None:
        rec = BatchApexErrorEventRecord(
            async_apex_job_id="707UP0000000001",
            job_scope_record_ids=("a2lUP000001ABC1", "a2lUP000001ABC2"),
            exception_type="System.LimitException",
            message="Apex CPU time limit exceeded",
            stack_trace="Class.YesterdayDenialSyncBatch.execute: line 42",
            phase="EXECUTE",
        )
        d = rec.to_dict()
        self.assertEqual(d["async_apex_job_id"], "707UP0000000001")
        self.assertEqual(len(d["job_scope_record_ids"]), 2)
        self.assertEqual(d["exception_type"], "System.LimitException")
        self.assertEqual(d["phase"], "EXECUTE")
        self.assertIn("timestamp", d)

    def test_cron_trigger_info(self) -> None:
        cron = CronTriggerInfo(
            job_id="08eUP0000000001",
            cron_job_detail_name="YesterdayDenialSyncBatch_Nightly",
            state="WAITING",
            next_fire_time="2026-10-03T02:00:00.000Z",
            previous_fire_time="2026-10-02T02:00:00.000Z",
            times_triggered=420,
            time_zone="America/New_York",
            is_missed_or_late=False,
        )
        d = cron.to_dict()
        self.assertEqual(d["job_id"], "08eUP0000000001")
        self.assertEqual(d["cron_job_detail_name"], "YesterdayDenialSyncBatch_Nightly")
        self.assertFalse(d["is_missed_or_late"])
        self.assertEqual(d["times_triggered"], 420)

    def test_bulk_api_job_info(self) -> None:
        job = BulkApiJobInfo(
            job_id="750UP0000000001",
            operation="insert",
            object_name="Denial_Lines__c",
            state="JobComplete",
            records_processed=12500,
            records_failed=0,
            total_processing_time_ms=45000,
            created_date="2026-10-02T12:00:00.000Z",
            job_type="V2Ingest",
        )
        d = job.to_dict()
        self.assertEqual(d["job_id"], "750UP0000000001")
        self.assertEqual(d["records_processed"], 12500)
        self.assertEqual(d["records_failed"], 0)
        self.assertEqual(d["job_type"], "V2Ingest")

    def test_cert_expiry_info(self) -> None:
        cert = CertExpiryInfo(
            cert_name="SelfSignedCert_Alliance_2026",
            developer_name="SelfSignedCert_Alliance_2026",
            expiration_date="2027-11-27T12:00:00.000Z",
            days_until_expiry=421,
            is_expired=False,
            org_name="Alliance Prod",
            key_size=4096,
        )
        d = cert.to_dict()
        self.assertEqual(d["cert_name"], "SelfSignedCert_Alliance_2026")
        self.assertEqual(d["days_until_expiry"], 421)
        self.assertFalse(d["is_expired"])
        self.assertEqual(d["key_size"], 4096)

    def test_setup_audit_trail_record(self) -> None:
        audit = SetupAuditTrailRecord(
            id="0YmUP0000000001",
            action="changedValidationRule",
            section="Validation Rules",
            created_date="2026-10-02T14:30:00.000Z",
            created_by_name="Admin User",
            display="Deactivated Validation Rule VR_Encounter_Lock",
            delegate_user=None,
        )
        d = audit.to_dict()
        self.assertEqual(d["action"], "changedValidationRule")
        self.assertEqual(d["section"], "Validation Rules")
        self.assertEqual(d["created_by_name"], "Admin User")

    def test_code_coverage_info(self) -> None:
        cov = CodeCoverageInfo(
            org_wide_coverage_pct=82.5,
            classes_evaluated=120,
            num_below_75_pct=4,
            uncovered_lines_total=1450,
            top_uncovered_classes=({"name": "LegacyController", "uncovered": 420},),
        )
        d = cov.to_dict()
        self.assertEqual(d["org_wide_coverage_pct"], 82.5)
        self.assertEqual(d["num_below_75_pct"], 4)
        self.assertEqual(len(d["top_uncovered_classes"]), 1)

    def test_auth_session_user(self) -> None:
        user = AuthSessionUser(
            session_id="0AkUP0000000001",
            user_id="005UP0000000001",
            username="analyst@alliancehealth.org",
            user_type="Standard",
            source_ip="192.168.1.100",
            login_type="Application",
            session_type="UI",
            created_date="2026-10-02T08:00:00.000Z",
            last_modified_date="2026-10-02T15:00:00.000Z",
            name="Data Analyst",
        )
        d = user.to_dict()
        self.assertEqual(d["username"], "analyst@alliancehealth.org")
        self.assertEqual(d["session_type"], "UI")
        self.assertEqual(d["name"], "Data Analyst")

    def test_snowflake_recon_info(self) -> None:
        recon = SnowflakeReconInfo(
            object_name="Encounter__c",
            sf_record_count=1091457,
            sf_max_modstamp="2026-10-02T15:45:00.000Z",
            snowflake_record_count=1091457,
            snowflake_max_modstamp="2026-10-02T15:45:00.000Z",
            variance_count=0,
            is_reconciled=True,
        )
        d = recon.to_dict()
        self.assertEqual(d["sf_record_count"], 1091457)
        self.assertEqual(d["variance_count"], 0)
        self.assertTrue(d["is_reconciled"])

    def test_data_quality_probe(self) -> None:
        probe = DataQualityProbe(
            probe_name="Encounter_Missing_Insurance_Member_ID",
            target_object="Encounter__c",
            field_name="Insurance_Member_ID__c",
            total_records=10000,
            null_or_invalid_count=950,
            null_rate_pct=9.5,
            status=Severity.INFO,
            message="9.5% missing member ID",
        )
        d = probe.to_dict()
        self.assertEqual(d["field_name"], "Insurance_Member_ID__c")
        self.assertEqual(d["null_rate_pct"], 9.5)
        self.assertEqual(d["status"], "INFO")


class TestChildParentLookupCache(unittest.TestCase):
    """Verifies ChildParentLookupCache LRU operations, thread-safety, and resolution."""

    def setUp(self) -> None:
        self.cache = ChildParentLookupCache(maxsize=3)

    def test_basic_get_put(self) -> None:
        self.assertIsNone(self.cache.get("child-1"))
        self.cache.put("child-1", {"patient_id": "P-1", "account_id": "A-1"})
        data = self.cache.get("child-1")
        self.assertIsNotNone(data)
        self.assertEqual(data["patient_id"], "P-1")

    def test_lru_eviction(self) -> None:
        self.cache.put("child-1", {"val": 1})
        self.cache.put("child-2", {"val": 2})
        self.cache.put("child-3", {"val": 3})
        # Access child-1 so child-2 becomes the least recently used
        self.cache.get("child-1")
        # Add child-4: child-2 should be evicted
        self.cache.put("child-4", {"val": 4})

        self.assertIsNotNone(self.cache.get("child-1"))
        self.assertIsNone(self.cache.get("child-2"))
        self.assertIsNotNone(self.cache.get("child-3"))
        self.assertIsNotNone(self.cache.get("child-4"))

    def test_cache_stats(self) -> None:
        self.cache.put("c-1", {"val": 1})
        self.cache.get("c-1")  # hit
        self.cache.get("c-2")  # miss
        stats = self.cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_ratio_pct"], 50.0)

    def test_resolve_parents_offline_fallback(self) -> None:
        results = self.cache.resolve_parents(["enc-123456", "enc-789012"])
        self.assertEqual(len(results), 2)
        self.assertIn("enc-123456", results)
        self.assertIn("enc-789012", results)
        # Verify subsequent call hits cache
        stats_before = self.cache.stats()
        results2 = self.cache.resolve_parents(["enc-123456"])
        stats_after = self.cache.stats()
        self.assertGreater(stats_after["hits"], stats_before["hits"])

    def test_thread_safety_concurrent_access(self) -> None:
        cache = ChildParentLookupCache(maxsize=100)
        num_threads = 5
        ops_per_thread = 50

        def worker(t_id: int):
            for i in range(ops_per_thread):
                key = f"key-{t_id}-{i % 10}"
                cache.put(key, {"t": t_id, "i": i})
                cache.get(key)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = cache.stats()
        self.assertGreaterEqual(stats["hits"], 1)


class TestSalesforcePollerV2(unittest.TestCase):
    """Unit tests for the 3-tiered poller architecture and governance sentinel."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "state.json"
        self.cache_file = Path(self.temp_dir.name) / "telemetry_cache.json"
        self.event_bus = EventBus()
        self.poller = SalesforcePoller(
            interval_seconds=30,
            low_freq_interval_seconds=900,
            state_file=self.state_file,
            cache_file=self.cache_file,
            mock_mode=True,
            event_bus=self.event_bus,
        )

    def tearDown(self) -> None:
        self.poller.stop()
        self.temp_dir.cleanup()

    def test_delta_velocity_calculation(self) -> None:
        """Verify delta velocity calculation between successive AsyncApexJob poll cycles."""
        target_org = "Alliance Prod"

        # Mock first response: 500 items processed
        mock_cli_1 = {
            "result": {
                "records": [
                    {
                        "ApexClass": {"Name": "YesterdayDenialSyncBatch"},
                        "Status": "Processing",
                        "JobItemsProcessed": 500,
                        "TotalJobItems": 2000,
                        "NumberOfErrors": 0,
                        "Id": "707TEST001",
                        "CompletedDate": None,
                    }
                ]
            }
        }

        # Mock second response 10 seconds later: 800 items processed
        mock_cli_2 = {
            "result": {
                "records": [
                    {
                        "ApexClass": {"Name": "YesterdayDenialSyncBatch"},
                        "Status": "Processing",
                        "JobItemsProcessed": 800,
                        "TotalJobItems": 2000,
                        "NumberOfErrors": 0,
                        "Id": "707TEST001",
                        "CompletedDate": None,
                    }
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            # Poll 1
            mock_run.return_value = (True, mock_cli_1, "")
            batches_1, _ = self.poller._poll_async_apex_jobs_with_velocity(target_org)
            self.assertEqual(batches_1["YesterdayDenialSyncBatch"]["velocity_items_per_min"], 0.0)

            # Advance tracker timestamp slightly for Poll 2
            self.poller._batch_velocity_tracker["YesterdayDenialSyncBatch"] = (time.time() - 10.0, 500)

            # Poll 2
            mock_run.return_value = (True, mock_cli_2, "")
            batches_2, _ = self.poller._poll_async_apex_jobs_with_velocity(target_org)
            velocity = batches_2["YesterdayDenialSyncBatch"]["velocity_items_per_min"]
            # 300 items in 10s = 30 items/sec = 1800 items/min
            self.assertGreater(velocity, 0.0)
            self.assertEqual(batches_2["YesterdayDenialSyncBatch"]["progress_pct"], 40.0)

    def test_auth_session_active_users_polling(self) -> None:
        """Verify active users parsing from AuthSession (correcting LoginHistory)."""
        mock_data = {
            "result": {
                "records": [
                    {
                        "Id": "0Ak001",
                        "UsersId": "005001",
                        "Users": {"Username": "alice@alliance.org", "Name": "Alice"},
                        "UserType": "Standard",
                        "SourceIp": "10.0.0.1",
                        "LoginType": "Application",
                        "SessionType": "UI",
                        "CreatedDate": "2026-10-02T10:00:00Z",
                        "LastModifiedDate": "2026-10-02T15:00:00Z",
                    },
                    {
                        "Id": "0Ak002",
                        "UsersId": "005001",  # Same user, different session
                        "Users": {"Username": "alice@alliance.org", "Name": "Alice"},
                        "UserType": "Standard",
                        "SourceIp": "10.0.0.1",
                        "LoginType": "Application",
                        "SessionType": "Aura",
                        "CreatedDate": "2026-10-02T10:05:00Z",
                        "LastModifiedDate": "2026-10-02T15:00:00Z",
                    },
                    {
                        "Id": "0Ak003",
                        "UsersId": "005002",
                        "Users": {"Username": "bob@alliance.org", "Name": "Bob"},
                        "UserType": "Standard",
                        "SourceIp": "10.0.0.2",
                        "LoginType": "Application",
                        "SessionType": "UI",
                        "CreatedDate": "2026-10-02T11:00:00Z",
                        "LastModifiedDate": "2026-10-02T15:00:00Z",
                    },
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            mock_run.return_value = (True, mock_data, "")
            unique_count, sessions = self.poller._poll_auth_sessions("Alliance Prod")
            self.assertEqual(unique_count, 2)  # Alice and Bob
            self.assertEqual(len(sessions), 3)
            self.assertEqual(sessions[0]["username"], "alice@alliance.org")

    def test_cron_trigger_sentinel(self) -> None:
        """Verify CronTrigger detection of blocked and late scheduled jobs."""
        mock_data = {
            "result": {
                "records": [
                    {
                        "Id": "08e001",
                        "CronJobDetail": {"Name": "NightlySync"},
                        "State": "BLOCKED",
                        "NextFireTime": "2026-10-03T02:00:00Z",
                        "PreviousFireTime": "2026-10-02T02:00:00Z",
                        "TimesTriggered": 100,
                        "TimeZoneSidKey": "America/New_York",
                    },
                    {
                        "Id": "08e002",
                        "CronJobDetail": {"Name": "HourlySync"},
                        "State": "WAITING",
                        "NextFireTime": "2026-10-01T12:00:00Z",  # NextFireTime in the past!
                        "PreviousFireTime": "2026-10-01T11:00:00Z",
                        "TimesTriggered": 50,
                        "TimeZoneSidKey": "America/New_York",
                    },
                    {
                        "Id": "08e003",
                        "CronJobDetail": {"Name": "FutureSync"},
                        "State": "WAITING",
                        "NextFireTime": "2026-10-10T12:00:00Z",
                        "PreviousFireTime": "2026-10-02T12:00:00Z",
                        "TimesTriggered": 20,
                        "TimeZoneSidKey": "America/New_York",
                    },
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            mock_run.return_value = (True, mock_data, "")
            late_or_blocked, crons = self.poller._poll_cron_triggers("Alliance Prod")
            self.assertEqual(late_or_blocked, 2)  # 08e001 (BLOCKED) + 08e002 (Late/Past)
            self.assertEqual(len(crons), 3)

    def test_batch_apex_error_event_ingestion_and_toast(self) -> None:
        """Verify real-time ingestion of BatchApexErrorEvent and desktop toast dispatch."""
        tier1_events = []
        self.event_bus.subscribe(EventTopic.TIER1_ALERT, lambda p: tier1_events.append(p))

        event_payload = {
            "AsyncApexJobId": "707TEST00000000FAIL",
            "JobScope": "a2lUP000001ABC1,a2lUP000001ABC2",
            "ExceptionType": "System.LimitException",
            "Message": "Apex CPU time limit exceeded",
            "StackTrace": "Class.YesterdayDenialSyncBatch.execute: line 42",
            "Phase": "EXECUTE",
        }

        with patch("app.sf_poller.notify_batch_failure") as mock_notify:
            mock_notify.return_value = True
            rec = self.poller.ingest_batch_apex_error_event(event_payload)

            self.assertEqual(rec.async_apex_job_id, "707TEST00000000FAIL")
            self.assertEqual(len(rec.job_scope_record_ids), 2)
            self.assertEqual(rec.exception_type, "System.LimitException")

            mock_notify.assert_called_once()
            self.assertGreaterEqual(len(tier1_events), 1)
            self.assertEqual(tier1_events[0]["async_apex_job_id"], "707TEST00000000FAIL")

    def test_setup_audit_trail_direct_prod_change_detection(self) -> None:
        """Verify SetupAuditTrail flags direct Prod changes made outside CI/CD."""
        mock_data = {
            "result": {
                "records": [
                    {
                        "Id": "0Ym001",
                        "Action": "changedValidationRule",
                        "Section": "Validation Rules",
                        "CreatedDate": "2026-10-02T14:00:00Z",
                        "CreatedBy": {"Name": "Jessica Landstrom"},  # Direct human user
                        "Display": "Deactivated validation rule VR_Encounter_Routing",
                        "DelegateUser": None,
                    },
                    {
                        "Id": "0Ym002",
                        "Action": "changedApexClass",
                        "Section": "Apex",
                        "CreatedDate": "2026-10-02T13:00:00Z",
                        "CreatedBy": {"Name": "Copado Deployment User"},  # CI/CD user
                        "Display": "Deployed ApexClass from pipeline",
                        "DelegateUser": None,
                    },
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            mock_run.return_value = (True, mock_data, "")
            direct_change, records = self.poller._poll_setup_audit_trail("Alliance Prod")
            self.assertTrue(direct_change)
            self.assertEqual(len(records), 2)

    def test_certificate_expiration_evaluation(self) -> None:
        """Verify Certificate evaluation flags expired and warning certs."""
        mock_data = {
            "result": {
                "records": [
                    {
                        "Id": "0P1001",
                        "MasterLabel": "Expired_Cert",
                        "DeveloperName": "Expired_Cert",
                        "ExpirationDate": "2024-05-17T12:00:00.000Z",
                        "KeySize": 2048,
                    },
                    {
                        "Id": "0P1002",
                        "MasterLabel": "Valid_Cert",
                        "DeveloperName": "Valid_Cert",
                        "ExpirationDate": "2027-11-27T12:00:00.000Z",
                        "KeySize": 4096,
                    },
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_tooling_query") as mock_tooling:
            mock_tooling.return_value = (True, mock_data, "")
            certs, expired_cnt, warn_cnt = self.poller._poll_certificates("Alliance Prod")
            self.assertEqual(expired_cnt, 1)
            self.assertEqual(warn_cnt, 0)
            self.assertEqual(len(certs), 2)
            self.assertTrue(certs[0]["is_expired"])
            self.assertFalse(certs[1]["is_expired"])

    def test_code_coverage_evaluation(self) -> None:
        """Verify ApexOrgWideCoverage and classes below 75% coverage."""
        mock_org_cov = {"result": {"records": [{"PercentCovered": 68}]}}
        mock_agg_cov = {
            "result": {
                "records": [
                    {
                        "ApexClassOrTrigger": {"Name": "LowCoverageHelper"},
                        "NumLinesCovered": 10,
                        "NumLinesUncovered": 90,  # 10%
                    },
                    {
                        "ApexClassOrTrigger": {"Name": "HighCoverageHelper"},
                        "NumLinesCovered": 95,
                        "NumLinesUncovered": 5,   # 95%
                    },
                ]
            }
        }

        with patch("app.sf_poller.SalesforceCLI.run_tooling_query") as mock_tooling:
            mock_tooling.side_effect = [
                (True, mock_org_cov, ""),
                (True, mock_agg_cov, ""),
            ]
            cov = self.poller._poll_code_coverage("Alliance Prod")
            self.assertEqual(cov["org_wide_coverage_pct"], 68.0)
            self.assertEqual(cov["num_below_75_pct"], 1)

    def test_data_quality_probes(self) -> None:
        """Verify statistical null-rate probes calculation on Encounter__c."""
        mock_total = {"result": {"totalSize": 100000}}
        mock_null_members = {"result": {"totalSize": 9500}}
        mock_stranded = {"result": {"totalSize": 5}}

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            mock_run.side_effect = [
                (True, mock_total, ""),
                (True, mock_null_members, ""),
                (True, mock_stranded, ""),
            ]
            probes, null_rate = self.poller._poll_data_quality_probes("Alliance Prod")
            self.assertEqual(len(probes), 2)
            self.assertEqual(null_rate, 9.5)
            self.assertEqual(probes[0]["field_name"], "Insurance_Member_ID__c")
            self.assertEqual(probes[1]["field_name"], "Needs_Routing__c")

    def test_snowflake_reconciliation(self) -> None:
        """Verify Daily SF <-> Snowflake Reconciliation comparing count and SystemModstamp."""
        mock_recon = {"result": {"records": [{"cnt": 1091457, "max_mod": "2026-10-02T15:45:00.000Z"}]}}

        with patch("app.sf_poller.SalesforceCLI.run_command") as mock_run:
            mock_run.return_value = (True, mock_recon, "")
            recon = self.poller._poll_snowflake_reconciliation("Alliance Prod")
            self.assertEqual(recon["object_name"], "Encounter__c")
            self.assertEqual(recon["sf_record_count"], 1091457)
            self.assertTrue(recon["is_reconciled"])
            self.assertEqual(recon["variance_count"], 0)

    def test_full_fallback_snapshot_schema_and_persistence(self) -> None:
        """Verify mock fallback contains all 4 tiers and is atomically written to state.json."""
        snapshot = self.poller.poll_now(force_refresh=True, full_governance=True)

        # Tier 1 checks
        self.assertIn("auth_sessions", snapshot)
        self.assertIn("cron_triggers", snapshot)
        self.assertIn("deployments", snapshot)
        self.assertIn("batches", snapshot)

        # Tier 2 checks
        self.assertIn("batch_error_events", snapshot)
        self.assertIn("flow_health", snapshot)

        # Tier 3 checks
        self.assertIn("setup_audit_trail", snapshot)
        self.assertIn("bulk_api", snapshot)
        self.assertIn("certificates", snapshot)
        self.assertIn("code_coverage", snapshot)

        # Tier 4 checks
        self.assertIn("storage_records", snapshot)
        self.assertIn("data_quality_probes", snapshot)
        self.assertIn("snowflake_recon", snapshot)
        self.assertIn("child_parent_cache_stats", snapshot)

        # Backwards compatibility checks
        self.assertIn("org_name", snapshot)
        self.assertIn("username", snapshot)
        self.assertIn("connected", snapshot)
        self.assertIn("revenue", snapshot)
        self.assertIn("metrics", snapshot)
        self.assertIn("governor_limits", snapshot)
        self.assertIn("system_state", snapshot)

        # Verify disk persistence
        self.assertTrue(self.state_file.exists())
        with open(self.state_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(disk_data["org_name"], snapshot["org_name"])
        self.assertEqual(disk_data["metrics"]["active_users_count"], snapshot["metrics"]["active_users_count"])

    def test_stealth_create_no_window_flag(self) -> None:
        """Verify Windows CREATE_NO_WINDOW constant is set to 0x08000000."""
        if sys.platform == "win32":
            self.assertEqual(CREATE_NO_WINDOW, 0x08000000)


if __name__ == "__main__":
    unittest.main()
