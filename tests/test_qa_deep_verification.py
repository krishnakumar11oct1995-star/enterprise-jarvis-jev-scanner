"""Comprehensive QA Deep Verification Test Suite for Project Jarvis.

Staff QA Engineer Independent Verification covering:
1. Deep nested recursion chains & false-positive prevention with static recursion guards.
2. Governor limit detection for SOQL inside nested for, while, and do-while loops.
3. Flow vs. Apex Trigger race condition on shared field updates (direct and indirect).
4. Cross-system breaking change detection (Salesforce -> MuleSoft -> Snowflake 3-tier pipeline).
5. Memory Bridge queries and enrichment against live Antigravity Index SQLite DB.
6. CLI execution and exit codes (Exit 1 on CRITICAL, Exit 0 on clean/warnings, JSON/MD formatting).
7. Graph Engine scalability and performance benchmarks.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

# Ensure jarvis package is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jarvis.config import (
    DEFAULT_INDEX_DIR,
    EXIT_SUCCESS,
    EXIT_CRITICAL,
    EXIT_ERROR,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    NodeTypes,
    EdgeTypes,
    Systems,
)
from jarvis.graph.models import Node, Edge, Conflict, ScanRun
from jarvis.graph.db import JarvisGraphDB
from jarvis.graph.engine import DependencyGraphEngine
from jarvis.harvester.salesforce import ApexHarvester, FlowHarvester, SchemaHarvester, SalesforceHarvester
from jarvis.harvester.mulesoft import MuleHarvester
from jarvis.harvester.snowflake import SnowflakeHarvester
from jarvis.memory.bridge import MemoryBridge
from jarvis.radar.evaluator import ConflictRadarEvaluator
from jarvis.radar.rules import (
    RecursionRuleEvaluator,
    RaceConditionRuleEvaluator,
    GovernorLimitLoopRuleEvaluator,
    CalloutAfterDMLRuleEvaluator,
    CrossCloudContractRuleEvaluator,
    MultipleTriggersRuleEvaluator,
    SemanticDuplicateFieldRuleEvaluator,
    ParentLockContentionRuleEvaluator,
    OrphanedMetadataRuleEvaluator,
)


class TestQADeepVerification(unittest.TestCase):
    """Staff QA Verification Test Cases."""

    def setUp(self):
        self.db = JarvisGraphDB(":memory:")
        self.engine = DependencyGraphEngine(self.db)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.jarvis_py = str(BASE_DIR / "jarvis.py")

    def tearDown(self):
        self.db.close()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    # =========================================================================
    # 1. DEEP NESTED RECURSION & RECURSION GUARD VERIFICATION
    # =========================================================================

    def test_deep_nested_multi_hop_recursion_detected(self):
        """Verify deep 6-hop recursion loop across multiple objects and services is detected."""
        # Chain:
        # TriggerA (on ObjA) -> Invokes ServiceA -> Writes ObjB ->
        # Triggers TriggerB (on ObjB) -> Invokes ServiceB -> Writes ObjC ->
        # Triggers TriggerC (on ObjC) -> Invokes ServiceC -> Writes ObjA ->
        # Triggers TriggerA (Cycle!)
        self.engine.add_node("apex.trigger.TriggerA", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "TriggerA")
        self.engine.add_node("apex.class.ServiceA", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "ServiceA")
        self.engine.add_node("salesforce.object.ObjB", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "ObjB")
        self.engine.add_node("apex.trigger.TriggerB", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "TriggerB")
        self.engine.add_node("apex.class.ServiceB", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "ServiceB")
        self.engine.add_node("salesforce.object.ObjC", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "ObjC")
        self.engine.add_node("apex.trigger.TriggerC", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "TriggerC")
        self.engine.add_node("apex.class.ServiceC", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "ServiceC")
        self.engine.add_node("salesforce.object.ObjA", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "ObjA")

        self.engine.add_edge("apex.trigger.TriggerA", "apex.class.ServiceA", EdgeTypes.INVOKES)
        self.engine.add_edge("apex.class.ServiceA", "salesforce.object.ObjB", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.ObjB", "apex.trigger.TriggerB", EdgeTypes.TRIGGERS_ON)

        self.engine.add_edge("apex.trigger.TriggerB", "apex.class.ServiceB", EdgeTypes.INVOKES)
        self.engine.add_edge("apex.class.ServiceB", "salesforce.object.ObjC", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.ObjC", "apex.trigger.TriggerC", EdgeTypes.TRIGGERS_ON)

        self.engine.add_edge("apex.trigger.TriggerC", "apex.class.ServiceC", EdgeTypes.INVOKES)
        self.engine.add_edge("apex.class.ServiceC", "salesforce.object.ObjA", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.ObjA", "apex.trigger.TriggerA", EdgeTypes.TRIGGERS_ON)

        evaluator = RecursionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertGreaterEqual(len(conflicts), 1, "Deep multi-hop recursion must be detected")
        c = conflicts[0]
        self.assertEqual(c.rule_id, "RULE-REC-001")
        self.assertEqual(c.severity, SEVERITY_CRITICAL)
        self.assertTrue(len(c.cycle_path) >= 6, "Cycle path must contain all hops in the multi-hop loop")

    def test_deep_nested_recursion_suppressed_by_intermediate_guard(self):
        """Verify static recursion guard on any intermediate trigger suppresses the recursion warning."""
        self.engine.add_node("apex.trigger.TriggerA", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "TriggerA")
        self.engine.add_node("apex.class.ServiceA", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "ServiceA")
        self.engine.add_node("salesforce.object.ObjB", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "ObjB")
        # TriggerB has a static recursion guard
        self.engine.add_node(
            "apex.trigger.TriggerB",
            Systems.SALESFORCE,
            NodeTypes.APEX_TRIGGER,
            "TriggerB",
            metadata={"has_recursion_guard": True},
        )
        self.engine.add_node("salesforce.object.ObjA", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "ObjA")

        self.engine.add_edge("apex.trigger.TriggerA", "apex.class.ServiceA", EdgeTypes.INVOKES)
        self.engine.add_edge("apex.class.ServiceA", "salesforce.object.ObjB", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.ObjB", "apex.trigger.TriggerB", EdgeTypes.TRIGGERS_ON)
        self.engine.add_edge("apex.trigger.TriggerB", "salesforce.object.ObjA", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.ObjA", "apex.trigger.TriggerA", EdgeTypes.TRIGGERS_ON)

        evaluator = RecursionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 0, "Recursion guard on TriggerB must suppress false-positive recursion alert")

    def test_apex_harvester_recursion_guard_syntax_patterns(self):
        """Verify ApexHarvester recognizes various enterprise recursion guard patterns."""
        patterns = [
            ("public static Boolean hasRun = false;", True),
            ("private static Set<Id> processedIds = new Set<Id>();", True),
            ("if (RecursionGuard.hasRun(Trigger.new[0].Id)) return;", True),
            ("if (CheckRecursive.isExecuting) return;", True),
            ("TriggerHandler.bypass('AccountTrigger');", True),
            ("public static Boolean isRecursive = false;", True),
            ("public class NormalClass { void f() { System.debug('no guard'); } }", False),
        ]
        harvester = ApexHarvester()
        for idx, (code_snippet, expected_guard) in enumerate(patterns):
            code = f"""
            public class GuardTest{idx} {{
                {code_snippet}
            }}
            """
            nodes, _ = harvester.harvest(code)
            self.assertEqual(len(nodes), 1)
            actual_guard = bool(nodes[0].metadata.get("has_recursion_guard"))
            self.assertEqual(
                actual_guard,
                expected_guard,
                f"Failed for snippet '{code_snippet}': expected {expected_guard}, got {actual_guard}",
            )

    def test_read_only_dependency_chain_does_not_trigger_recursion(self):
        """Verify non-mutating query (READS edge) does not trigger infinite recursion."""
        self.engine.add_node("apex.trigger.AccountTrigger", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "AccountTrigger")
        self.engine.add_node("salesforce.object.Contact", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Contact")
        self.engine.add_node("salesforce.object.Account", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Account")

        # AccountTrigger reads Contact, but does NOT write
        self.engine.add_edge("apex.trigger.AccountTrigger", "salesforce.object.Contact", EdgeTypes.READS)
        self.engine.add_edge("salesforce.object.Account", "apex.trigger.AccountTrigger", EdgeTypes.TRIGGERS_ON)

        evaluator = RecursionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 0, "Read-only relationship must not trigger recursion conflict")

    # =========================================================================
    # 2. GOVERNOR LIMIT DETECTION FOR SOQL / DML IN LOOPS
    # =========================================================================

    def test_soql_inside_nested_for_loops(self):
        """Verify SOQL nested inside outer and inner for-loops is detected with loop details."""
        apex_code = """
        public class NestedLoopService {
            public void processAccounts(List<Account> accounts) {
                for (Account acc : accounts) {
                    for (Contact con : acc.Contacts) {
                        List<Case> cases = [SELECT Id, Status FROM Case WHERE ContactId = :con.Id];
                        update cases;
                    }
                }
            }
        }
        """
        harvester = ApexHarvester()
        nodes, _ = harvester.harvest(apex_code)
        self.assertEqual(len(nodes), 1)
        node = nodes[0]

        self.assertTrue(node.metadata.get("soql_in_loop"))
        self.assertTrue(node.metadata.get("dml_in_loop"))
        self.assertGreaterEqual(len(node.metadata.get("loop_details", [])), 2)

        self.engine.add_nodes(nodes)
        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-003")
        self.assertEqual(conflicts[0].severity, SEVERITY_CRITICAL)
        self.assertIn("NestedLoopService", conflicts[0].message)

    def test_soql_inside_while_loop_with_nested_method_call(self):
        """Verify SOQL inside while loop with method call condition while (iterator.hasNext()) is detected."""
        apex_code = """
        public class WhileLoopBatch {
            public void run(Iterator<Account> iterator) {
                while (iterator.hasNext()) {
                    Account a = iterator.next();
                    List<Task> tasks = [SELECT Id FROM Task WHERE WhatId = :a.Id];
                    insert tasks;
                }
            }
        }
        """
        harvester = ApexHarvester()
        nodes, _ = harvester.harvest(apex_code)
        self.assertEqual(len(nodes), 1)
        node = nodes[0]

        self.assertTrue(node.metadata.get("soql_in_loop"))
        self.assertTrue(node.metadata.get("dml_in_loop"))

        self.engine.add_nodes(nodes)
        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-003")

    def test_dynamic_soql_database_query_in_loop(self):
        """Verify dynamic SOQL Database.query inside loop is detected."""
        apex_code = """
        public class DynamicQueryBatch {
            public void execute(List<String> emails) {
                for (String email : emails) {
                    List<Lead> leads = Database.query('SELECT Id FROM Lead WHERE Email = \\'' + email + '\\'');
                }
            }
        }
        """
        harvester = ApexHarvester()
        nodes, _ = harvester.harvest(apex_code)
        self.assertTrue(nodes[0].metadata.get("soql_in_loop"))

        self.engine.add_nodes(nodes)
        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-003")

    def test_dml_inside_do_while_loop(self):
        """Verify DML statement inside do-while loop is flagged as a governor hazard."""
        apex_code = """
        public class DoWhileService {
            public void createRecords(List<Contact> contacts) {
                Integer i = 0;
                do {
                    insert contacts;
                    i++;
                } while (i < 5);
            }
        }
        """
        harvester = ApexHarvester()
        nodes, _ = harvester.harvest(apex_code)
        self.assertTrue(nodes[0].metadata.get("dml_in_loop"))

        self.engine.add_nodes(nodes)
        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-003")

    def test_bulkified_clean_pattern_no_false_positive(self):
        """Verify bulkified pattern (SOQL outside loop, loop in memory, DML outside loop) raises NO conflict."""
        apex_code = """
        public class CleanBulkifiedService {
            public void updateContacts(Set<Id> accountIds) {
                // SOQL query bulkified outside loop
                List<Contact> contacts = [SELECT Id, Status__c FROM Contact WHERE AccountId IN :accountIds];
                for (Contact c : contacts) {
                    c.Status__c = 'Active';
                }
                // DML bulkified outside loop
                update contacts;
            }
        }
        """
        harvester = ApexHarvester()
        nodes, _ = harvester.harvest(apex_code)
        self.assertEqual(len(nodes), 1)
        self.assertFalse(nodes[0].metadata.get("soql_in_loop"))
        self.assertFalse(nodes[0].metadata.get("dml_in_loop"))

        self.engine.add_nodes(nodes)
        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 0, "Bulkified pattern must not trigger governor limit conflict")

    # =========================================================================
    # 3. FLOW VS. TRIGGER RACE CONDITION ON SHARED FIELD UPDATES
    # =========================================================================

    def test_flow_vs_trigger_direct_race_condition(self):
        """Verify conflict detected when Trigger and Flow mutate the exact same field."""
        trigger_code = """
        trigger OpportunityDiscountTrigger on Opportunity (before update) {
            for (Opportunity opp : Trigger.new) {
                opp.Discount_Rate__c = 0.15;
            }
        }
        """
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
            <label>Opportunity Discount Rule</label>
            <processType>AutoLaunched</processType>
            <start>
                <object>Opportunity</object>
                <triggerType>RecordBeforeSave</triggerType>
            </start>
            <recordUpdates>
                <inputAssignments>
                    <field>Discount_Rate__c</field>
                </inputAssignments>
            </recordUpdates>
        </Flow>
        """
        apex_h = ApexHarvester()
        flow_h = FlowHarvester()

        t_nodes, t_edges = apex_h.harvest(trigger_code)
        f_nodes, f_edges = flow_h.harvest(flow_xml)

        self.engine.add_nodes(t_nodes + f_nodes)
        self.engine.add_edges(t_edges + f_edges)

        evaluator = RaceConditionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c.rule_id, "RULE-RACE-002")
        self.assertEqual(c.severity, SEVERITY_CRITICAL)
        self.assertIn("Discount_Rate__c", c.message)
        self.assertEqual(c.context_data.get("sobject"), "Opportunity")

    def test_flow_vs_trigger_indirect_race_via_helper_class(self):
        """Verify race condition detected when trigger delegates to a helper class that mutates the field."""
        trigger_code = """
        trigger CaseStatusTrigger on Case (before update) {
            CaseHelper.applyRouting(Trigger.new);
        }
        """
        helper_code = """
        public class CaseHelper {
            public static void applyRouting(List<Case> cases) {
                for (Case c : cases) {
                    c.Routing_Tier__c = 'Tier-1';
                }
            }
        }
        """
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
            <label>Case Flow Routing</label>
            <processType>AutoLaunched</processType>
            <start>
                <object>Case</object>
                <triggerType>RecordBeforeSave</triggerType>
            </start>
            <recordUpdates>
                <inputAssignments>
                    <field>Routing_Tier__c</field>
                </inputAssignments>
            </recordUpdates>
        </Flow>
        """
        apex_h = ApexHarvester()
        flow_h = FlowHarvester()

        t_nodes, t_edges = apex_h.harvest(trigger_code)
        h_nodes, h_edges = apex_h.harvest(helper_code)
        f_nodes, f_edges = flow_h.harvest(flow_xml)

        self.engine.add_nodes(t_nodes + h_nodes + f_nodes)
        self.engine.add_edges(t_edges + h_edges + f_edges)

        evaluator = RaceConditionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-RACE-002")
        self.assertIn("Routing_Tier__c", conflicts[0].message)

    def test_flow_vs_trigger_disjoint_fields_no_race_condition(self):
        """Verify NO race condition conflict when Trigger and Flow update completely disjoint fields."""
        trigger_code = """
        trigger AccountRatingTrigger on Account (before update) {
            for (Account a : Trigger.new) {
                a.Rating = 'Hot';
            }
        }
        """
        flow_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
            <label>Account Revenue Flow</label>
            <processType>AutoLaunched</processType>
            <start>
                <object>Account</object>
                <triggerType>RecordBeforeSave</triggerType>
            </start>
            <recordUpdates>
                <inputAssignments>
                    <field>AnnualRevenue</field>
                </inputAssignments>
            </recordUpdates>
        </Flow>
        """
        apex_h = ApexHarvester()
        flow_h = FlowHarvester()

        t_nodes, t_edges = apex_h.harvest(trigger_code)
        f_nodes, f_edges = flow_h.harvest(flow_xml)

        self.engine.add_nodes(t_nodes + f_nodes)
        self.engine.add_edges(t_edges + f_edges)

        evaluator = RaceConditionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        # Should not flag shared field conflict
        shared_conflicts = [c for c in conflicts if "Race condition detected" in c.message]
        self.assertEqual(len(shared_conflicts), 0)

    # =========================================================================
    # 4. CROSS-SYSTEM BREAKING CHANGE DETECTION (SALESFORCE -> MULESOFT -> SNOWFLAKE)
    # =========================================================================

    def test_cross_cloud_contract_break_3_tier(self):
        """Verify 3-tier pipeline breakage: SF schema missing field breaks both MuleSoft and Snowflake."""
        sf_schema = """<?xml version="1.0" encoding="UTF-8"?>
        <CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
            <label>Order</label>
            <fields>
                <fullName>Tax_Value__c</fullName>
                <type>Number</type>
                <label>Tax Value</label>
            </fields>
        </CustomObject>
        """
        mule_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <mule xmlns="http://www.mulesoft.org/schema/mule/core">
            <flow name="OrderSyncFlow">
                <http:listener path="/api/v1/orders" config-ref="HTTP_Listener"/>
                <salesforce:query config-ref="SF_Config">SELECT Tax_Amount__c FROM Order</salesforce:query>
                <snowflake:bulk-insert config-ref="Snowflake_Config" table="ORDER_ANALYTICS"/>
            </flow>
        </mule>
        """
        snow_ddl = """
        CREATE OR REPLACE TABLE ORDER_ANALYTICS (
            ORDER_ID VARCHAR(50),
            TAX_AMOUNT__C NUMBER(18,2)
        );
        """
        # Harvest SF schema
        sf_nodes, sf_edges = SchemaHarvester().harvest(sf_schema)
        # Harvest MuleSoft
        m_nodes, m_edges = MuleHarvester().harvest(mule_xml)
        # Harvest Snowflake
        s_nodes, s_edges = SnowflakeHarvester().harvest(snow_ddl)

        self.engine.add_nodes(sf_nodes + m_nodes + s_nodes)
        self.engine.add_edges(sf_edges + m_edges + s_edges)

        evaluator = CrossCloudContractRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertGreaterEqual(len(conflicts), 1, "Cross-cloud contract break must be flagged")
        rule_ids = [c.rule_id for c in conflicts]
        self.assertTrue(all(rid == "RULE-CONTR-005" for rid in rule_ids))
        self.assertTrue(all(c.severity == SEVERITY_CRITICAL for c in conflicts))

        # MuleSoft consumer conflict check
        mule_conflicts = [c for c in conflicts if c.context_data.get("consumer_system") == Systems.MULESOFT]
        self.assertEqual(len(mule_conflicts), 1)
        self.assertIn("Tax_Amount__c", mule_conflicts[0].message)

    def test_cross_cloud_contract_valid_no_conflict(self):
        """Verify valid contract across all 3 tiers produces 0 contract conflicts (no false positives)."""
        sf_schema = """<?xml version="1.0" encoding="UTF-8"?>
        <CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
            <label>Order</label>
            <fields>
                <fullName>Tax_Amount__c</fullName>
                <type>Number</type>
                <label>Tax Amount</label>
            </fields>
        </CustomObject>
        """
        mule_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <mule xmlns="http://www.mulesoft.org/schema/mule/core">
            <flow name="OrderSyncFlow">
                <http:listener path="/api/v1/orders" config-ref="HTTP_Listener"/>
                <salesforce:query config-ref="SF_Config">SELECT Tax_Amount__c FROM Order</salesforce:query>
                <snowflake:bulk-insert config-ref="Snowflake_Config" table="ORDER_ANALYTICS"/>
            </flow>
        </mule>
        """
        snow_ddl = """
        CREATE OR REPLACE TABLE ORDER_ANALYTICS (
            ORDER_ID VARCHAR(50),
            TAX_AMOUNT__C NUMBER(18,2)
        );
        """
        sf_nodes, sf_edges = SchemaHarvester().harvest(sf_schema)
        m_nodes, m_edges = MuleHarvester().harvest(mule_xml)
        s_nodes, s_edges = SnowflakeHarvester().harvest(snow_ddl)

        self.engine.add_nodes(sf_nodes + m_nodes + s_nodes)
        self.engine.add_edges(sf_edges + m_edges + s_edges)

        evaluator = CrossCloudContractRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 0, "Valid cross-cloud contract must produce 0 conflicts")

    # =========================================================================
    # 5. MEMORY BRIDGE LIVE DATABASE & HISTORICAL RCA VERIFICATION
    # =========================================================================

    def test_memory_bridge_live_db_queries_and_enrichment(self):
        """Verify Memory Bridge queries against live Antigravity Index SQLite DB."""
        bridge = MemoryBridge(DEFAULT_INDEX_DIR)
        if not bridge.is_available():
            self.skipTest("Antigravity Index live DB not present on machine")

        # 1. Search for known components
        components_to_test = [
            "YesterdayDenialSyncBatch",
            "UpdateEncounterOwnerAndRoutingBatch",
            "Encounter",
            "MuleSoft",
        ]
        for comp in components_to_test:
            results = bridge.search(comp, limit=3)
            self.assertGreaterEqual(len(results), 1, f"Search for '{comp}' should return at least 1 turn")
            r = results[0]
            self.assertTrue(bool(r.conv_id), "Historical turn must have conv_id")
            self.assertTrue(bool(r.solution_summary), "Historical turn must have solution_summary")

        # 2. Test RCA retrieval with rule id
        rcas = bridge.get_rca_context("YesterdayDenialSyncBatch", rule_id="RULE-REC-001", limit=2)
        self.assertGreaterEqual(len(rcas), 1)

        # 3. Test conflict enrichment
        mock_conflict = Conflict(
            rule_id="RULE-REC-001",
            severity=SEVERITY_CRITICAL,
            primary_node_id="apex.class.YesterdayDenialSyncBatch",
            message="Recursion detected",
        )
        enriched = bridge.enrich_conflicts([mock_conflict])
        self.assertIsNotNone(enriched[0].historical_conv_id)
        self.assertIsNotNone(enriched[0].historical_rca_summary)
        self.assertIn("Historical RCA Match", enriched[0].historical_rca_summary)

        # 4. Test reading transcript file
        results = bridge.search("YesterdayDenialSyncBatch", limit=1)
        md_file = results[0].md_file
        if md_file:
            content = bridge.read_transcript(md_file)
            self.assertIsNotNone(content)
            self.assertGreater(len(content), 50)

    def test_memory_bridge_nonexistent_path_graceful_handling(self):
        """Verify MemoryBridge handles missing/invalid directory gracefully without crashing."""
        fake_bridge = MemoryBridge(r"C:\NonExistent\DummyDir")
        self.assertFalse(fake_bridge.is_available())
        self.assertEqual(fake_bridge.search("Anything"), [])
        self.assertEqual(fake_bridge.get_rca_context("Component"), [])
        self.assertIsNone(fake_bridge.read_transcript("missing.md"))

        conflict = Conflict(rule_id="R1", severity="INFO", primary_node_id="test", message="msg")
        enriched = fake_bridge.enrich_conflicts([conflict])
        self.assertEqual(len(enriched), 1)
        self.assertIsNone(enriched[0].historical_conv_id)

    # =========================================================================
    # 6. CLI EXECUTION & EXIT CODE VERIFICATION
    # =========================================================================

    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [sys.executable, self.jarvis_py] + args
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_cli_exit_code_0_on_clean_metadata(self):
        """Verify CLI scan returns exit code 0 on clean code without conflicts."""
        clean_file = os.path.join(self.tmp_dir.name, "CleanPaymentService.cls")
        with open(clean_file, "w", encoding="utf-8") as f:
            f.write("""
            public class CleanPaymentService {
                public static void log(String s) {
                    System.debug('Safe: ' + s);
                }
            }
            """)
        db_file = os.path.join(self.tmp_dir.name, "clean.sqlite")
        proc = self._run_cli(["scan", "--path", clean_file, "--db", db_file])
        self.assertEqual(proc.returncode, EXIT_SUCCESS, f"Expected exit code 0, got {proc.returncode}: {proc.stderr}")

    def test_cli_exit_code_0_on_warnings_only(self):
        """Verify CLI scan returns exit code 0 when ONLY warnings (non-critical) are detected."""
        # Create two triggers on same object (triggers RULE-ORDER-006 WARNING)
        t1 = os.path.join(self.tmp_dir.name, "AccountTriggerA.trigger")
        t2 = os.path.join(self.tmp_dir.name, "AccountTriggerB.trigger")
        with open(t1, "w", encoding="utf-8") as f:
            f.write("trigger AccountTriggerA on Account (before insert) {}")
        with open(t2, "w", encoding="utf-8") as f:
            f.write("trigger AccountTriggerB on Account (after insert) {}")

        db_file = os.path.join(self.tmp_dir.name, "warn.sqlite")
        h_proc = self._run_cli(["harvest", "--source", self.tmp_dir.name, "--db", db_file])
        self.assertEqual(h_proc.returncode, EXIT_SUCCESS)

        s_proc = self._run_cli(["scan", "--db", db_file, "--format", "json"])
        self.assertEqual(s_proc.returncode, EXIT_SUCCESS, "Quality gate must PASS (Exit 0) on warnings only")
        parsed = json.loads(s_proc.stdout)
        self.assertEqual(parsed["scan_run"]["critical_count"], 0)
        self.assertGreaterEqual(parsed["scan_run"]["warning_count"], 1)

    def test_cli_exit_code_1_on_critical_conflicts(self):
        """Verify CLI scan returns exit code 1 when CRITICAL conflicts are detected."""
        bad_file = os.path.join(self.tmp_dir.name, "InfiniteLoop.cls")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("""
            public class InfiniteLoop {
                public void run(List<Account> accs) {
                    for (Account a : accs) {
                        List<Contact> c = [SELECT Id FROM Contact WHERE AccountId = :a.Id];
                    }
                }
            }
            """)
        db_file = os.path.join(self.tmp_dir.name, "crit.sqlite")
        proc = self._run_cli(["scan", "--path", bad_file, "--db", db_file])
        self.assertEqual(proc.returncode, EXIT_CRITICAL, "Quality gate must FAIL (Exit 1) on CRITICAL conflicts")

    def test_cli_formatting_json_and_markdown(self):
        """Verify CLI scan supports JSON and Markdown output formats."""
        bad_file = os.path.join(self.tmp_dir.name, "BadFormat.cls")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("public class BadFormat { void f(List<Lead> l) { for (Lead x : l) { insert x; } } }")
        db_file = os.path.join(self.tmp_dir.name, "fmt.sqlite")

        # JSON format
        j_proc = self._run_cli(["scan", "--path", bad_file, "--db", db_file, "--format", "json"])
        data = json.loads(j_proc.stdout)
        self.assertIn("scan_run", data)
        self.assertIn("conflicts", data)

        # Markdown format
        m_proc = self._run_cli(["scan", "--path", bad_file, "--db", db_file, "--format", "markdown"])
        self.assertIn("# Project Jarvis: Architecture & Conflict Radar Audit Report", m_proc.stdout)

    def test_cli_impact_traversal_directions(self):
        """Verify CLI impact command supports downstream, upstream, and both directions."""
        db_file = os.path.join(self.tmp_dir.name, "impact.sqlite")
        db = JarvisGraphDB(db_file)
        engine = DependencyGraphEngine(db)
        engine.add_node("A", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "A")
        engine.add_node("B", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "B")
        engine.add_edge("A", "B", EdgeTypes.CALLS)
        db.close()

        for d in ["downstream", "upstream", "both"]:
            proc = self._run_cli(["impact", "--component", "A", "--direction", d, "--db", db_file])
            self.assertEqual(proc.returncode, EXIT_SUCCESS, f"Impact traversal failed for direction {d}")

    # =========================================================================
    # 7. PERFORMANCE & SCALABILITY BENCHMARKS
    # =========================================================================

    def test_large_graph_traversal_performance_benchmark(self):
        """Performance: 10,000 nodes, 30,000 edges traversed in < 1.5 seconds."""
        nodes = [
            Node(id=f"node_{i}", system=Systems.SALESFORCE, type=NodeTypes.APEX_CLASS, name=f"Class_{i}")
            for i in range(10000)
        ]
        self.db.upsert_nodes(nodes)

        edges = [
            Edge(source_id=f"node_{i % 10000}", target_id=f"node_{(i * 11 + 7) % 10000}", relationship=EdgeTypes.CALLS)
            for i in range(30000)
        ]
        self.db.upsert_edges(edges)

        start = time.perf_counter()
        res = self.engine.blast_radius("node_0", depth=6)
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.5, f"10k nodes blast radius took {elapsed:.3f}s, exceeding 1.5s threshold")
        self.assertGreater(len(res.nodes), 1)

    def test_tarjan_scc_performance_benchmark(self):
        """Performance: Tarjan SCC on 1,000 nodes with multiple cycles completes in < 0.5 seconds."""
        nodes = [
            Node(id=f"scc_node_{i}", system=Systems.SALESFORCE, type=NodeTypes.APEX_CLASS, name=f"Node_{i}")
            for i in range(1000)
        ]
        self.db.upsert_nodes(nodes)

        # Create cycle clusters
        edges = []
        for c in range(0, 1000, 5):
            edges.append(Edge(source_id=f"scc_node_{c}", target_id=f"scc_node_{c+1}", relationship=EdgeTypes.INVOKES))
            edges.append(Edge(source_id=f"scc_node_{c+1}", target_id=f"scc_node_{c+2}", relationship=EdgeTypes.INVOKES))
            edges.append(Edge(source_id=f"scc_node_{c+2}", target_id=f"scc_node_{c}", relationship=EdgeTypes.INVOKES))
        self.db.upsert_edges(edges)

        start = time.perf_counter()
        sccs = self.engine.detect_sccs()
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.5, f"Tarjan SCC took {elapsed:.3f}s, exceeding 0.5s threshold")
        self.assertGreaterEqual(len(sccs), 100, "Should detect all cyclic clusters")


if __name__ == "__main__":
    unittest.main()
