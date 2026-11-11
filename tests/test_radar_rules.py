"""Tests for Conflict Radar Rules and Evaluator Engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    NodeTypes,
    EdgeTypes,
    Systems,
)
from jarvis.graph.models import Node, Edge
from jarvis.graph.db import JarvisGraphDB
from jarvis.graph.engine import DependencyGraphEngine
from jarvis.radar.evaluator import ConflictRadarEvaluator
from jarvis.radar.rules import (
    RecursionRuleEvaluator,
    RaceConditionRuleEvaluator,
    GovernorLimitLoopRuleEvaluator,
    CalloutAfterDMLRuleEvaluator,
    CrossCloudContractRuleEvaluator,
    MultipleTriggersRuleEvaluator,
    SemanticDuplicateFieldRuleEvaluator,
    OrphanedMetadataRuleEvaluator,
)


class TestRadarRules(unittest.TestCase):

    def setUp(self):
        # In-memory SQLite for super fast, clean test isolation
        self.db = JarvisGraphDB(":memory:")
        self.engine = DependencyGraphEngine(self.db)
        self.evaluator = ConflictRadarEvaluator(self.engine)

    def tearDown(self):
        self.db.close()

    def test_rule_rec_001_infinite_recursion_detected(self):
        # Scenario 1 from SPECIFICATION:
        # AccountTrigger (after update) -> AccountService -> Contact -> ContactTrigger -> Account -> AccountTrigger
        self.engine.add_node("apex.trigger.AccountTrigger", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "AccountTrigger")
        self.engine.add_node("apex.class.AccountService", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "AccountService")
        self.engine.add_node("salesforce.object.Contact", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Contact")
        self.engine.add_node("apex.trigger.ContactTrigger", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "ContactTrigger")
        self.engine.add_node("salesforce.object.Account", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Account")

        # Directed cycle forming recursion
        self.engine.add_edge("apex.trigger.AccountTrigger", "apex.class.AccountService", EdgeTypes.INVOKES)
        self.engine.add_edge("apex.class.AccountService", "salesforce.object.Contact", EdgeTypes.WRITES)
        self.engine.add_edge("apex.trigger.ContactTrigger", "salesforce.object.Account", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.Contact", "apex.trigger.ContactTrigger", EdgeTypes.TRIGGERS_ON)
        self.engine.add_edge("salesforce.object.Account", "apex.trigger.AccountTrigger", EdgeTypes.TRIGGERS_ON)

        evaluator = RecursionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertTrue(len(conflicts) >= 1)
        c = conflicts[0]
        self.assertEqual(c.rule_id, "RULE-REC-001")
        self.assertEqual(c.severity, SEVERITY_CRITICAL)
        self.assertIsNotNone(c.cycle_path)

    def test_rule_rec_001_suppressed_by_recursion_guard(self):
        # With static recursion guard on AccountTrigger
        self.engine.add_node(
            "apex.trigger.AccountTrigger",
            Systems.SALESFORCE,
            NodeTypes.APEX_TRIGGER,
            "AccountTrigger",
            metadata={"has_recursion_guard": True},
        )
        self.engine.add_node("salesforce.object.Account", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Account")
        self.engine.add_edge("apex.trigger.AccountTrigger", "salesforce.object.Account", EdgeTypes.WRITES)
        self.engine.add_edge("salesforce.object.Account", "apex.trigger.AccountTrigger", EdgeTypes.TRIGGERS_ON)

        evaluator = RecursionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)
        self.assertEqual(len(conflicts), 0)

    def test_rule_race_002_competing_flow_and_trigger(self):
        # Scenario 2 from SPECIFICATION:
        # Trigger on Opportunity and Flow on Opportunity both mutating Discount_Rate__c on before update
        self.engine.add_node(
            "apex.trigger.OpportunityTrigger",
            Systems.SALESFORCE,
            NodeTypes.APEX_TRIGGER,
            "OpportunityTrigger",
            metadata={"target_object": "Opportunity", "events": ["before_update"]},
        )
        self.engine.add_node(
            "salesforce.flow.Opportunity_Discount_Flow",
            Systems.SALESFORCE,
            NodeTypes.SF_FLOW,
            "Opportunity_Discount_Flow",
            metadata={"target_object": "Opportunity", "events": ["before_update"]},
        )
        self.engine.add_node(
            "salesforce.field.Opportunity.Discount_Rate__c",
            Systems.SALESFORCE,
            NodeTypes.SF_FIELD,
            "Opportunity.Discount_Rate__c",
        )

        # Both update the same field
        self.engine.add_edge("apex.trigger.OpportunityTrigger", "salesforce.field.Opportunity.Discount_Rate__c", EdgeTypes.UPDATES_FIELD)
        self.engine.add_edge("salesforce.flow.Opportunity_Discount_Flow", "salesforce.field.Opportunity.Discount_Rate__c", EdgeTypes.UPDATES_FIELD)

        evaluator = RaceConditionRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertTrue(len(conflicts) >= 1)
        c = conflicts[0]
        self.assertEqual(c.rule_id, "RULE-RACE-002")
        self.assertEqual(c.severity, SEVERITY_CRITICAL)
        self.assertIn("Discount_Rate__c", c.message)

    def test_rule_gov_003_soql_dml_in_loops(self):
        self.engine.add_node(
            "apex.class.EncounterBatch",
            Systems.SALESFORCE,
            NodeTypes.APEX_CLASS,
            "EncounterBatch",
            metadata={"soql_in_loop": True, "dml_in_loop": True, "loop_details": [{"line": 42, "header": "for (...)"}]},
        )

        evaluator = GovernorLimitLoopRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-003")
        self.assertEqual(conflicts[0].severity, SEVERITY_CRITICAL)

    def test_rule_gov_004_callout_after_dml(self):
        self.engine.add_node(
            "apex.class.BillingSyncService",
            Systems.SALESFORCE,
            NodeTypes.APEX_CLASS,
            "BillingSyncService",
            metadata={"callout_after_dml": True, "callout_details": [{"dml_line": 15, "callout_line": 20}]},
        )

        evaluator = CalloutAfterDMLRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-GOV-004")
        self.assertEqual(conflicts[0].severity, SEVERITY_CRITICAL)

    def test_rule_contr_005_cross_cloud_contract_break(self):
        # Scenario 3 from SPECIFICATION:
        # Salesforce schema has Order.Tax_Value__c (Tax_Amount__c was renamed)
        # MuleSoft flow still references Order.Tax_Amount__c
        self.engine.add_node("salesforce.object.Order", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Order")
        self.engine.add_node("salesforce.field.Order.Tax_Value__c", Systems.SALESFORCE, NodeTypes.SF_FIELD, "Order.Tax_Value__c")

        self.engine.add_node("mulesoft.flow.OrderSyncFlow", Systems.MULESOFT, NodeTypes.MULE_FLOW, "OrderSyncFlow")
        self.engine.add_edge("mulesoft.flow.OrderSyncFlow", "salesforce.field.Order.Tax_Amount__c", EdgeTypes.READS_FIELD)

        evaluator = CrossCloudContractRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c.rule_id, "RULE-CONTR-005")
        self.assertEqual(c.severity, SEVERITY_CRITICAL)
        self.assertIn("Tax_Amount__c", c.message)

    def test_rule_order_006_multiple_triggers(self):
        self.engine.add_node("salesforce.object.Account", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Account")
        self.engine.add_node("apex.trigger.AccountTrigger1", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "AccountTrigger1", metadata={"target_object": "Account"})
        self.engine.add_node("apex.trigger.AccountTrigger2", Systems.SALESFORCE, NodeTypes.APEX_TRIGGER, "AccountTrigger2", metadata={"target_object": "Account"})

        evaluator = MultipleTriggersRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-ORDER-006")
        self.assertEqual(conflicts[0].severity, SEVERITY_WARNING)

    def test_rule_schema_007_semantic_duplicate_fields(self):
        self.engine.add_node("salesforce.object.Account", Systems.SALESFORCE, NodeTypes.SF_OBJECT, "Account")
        self.engine.add_node(
            "salesforce.field.Account.Customer_Phone__c",
            Systems.SALESFORCE,
            NodeTypes.SF_FIELD,
            "Account.Customer_Phone__c",
            parent_id="salesforce.object.Account",
            metadata={"field_name": "Customer_Phone__c"},
        )
        self.engine.add_node(
            "salesforce.field.Account.Client_Phone__c",
            Systems.SALESFORCE,
            NodeTypes.SF_FIELD,
            "Account.Client_Phone__c",
            parent_id="salesforce.object.Account",
            metadata={"field_name": "Client_Phone__c"},
        )

        evaluator = SemanticDuplicateFieldRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-SCHEMA-007")
        self.assertEqual(conflicts[0].severity, SEVERITY_WARNING)

    def test_rule_dead_009_orphaned_metadata(self):
        self.engine.add_node(
            "apex.class.OrphanHelper",
            Systems.SALESFORCE,
            NodeTypes.APEX_CLASS,
            "OrphanHelper",
            metadata={"is_entry_point": False},
        )

        evaluator = OrphanedMetadataRuleEvaluator()
        conflicts = evaluator.evaluate(self.engine)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].rule_id, "RULE-DEAD-009")
        self.assertEqual(conflicts[0].severity, SEVERITY_INFO)


if __name__ == "__main__":
    unittest.main()
