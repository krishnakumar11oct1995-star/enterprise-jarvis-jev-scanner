"""Tests for Metadata Harvesters."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config import NodeTypes, EdgeTypes, Systems, DEFAULT_INDEX_DIR
from jarvis.harvester.salesforce import ApexHarvester, FlowHarvester, SchemaHarvester
from jarvis.harvester.mulesoft import MuleHarvester
from jarvis.harvester.snowflake import SnowflakeHarvester
from jarvis.harvester.transcript_harvester import TranscriptHarvester


class TestHarvesters(unittest.TestCase):

    def test_apex_trigger_parsing(self):
        code = """
        trigger AccountTrigger on Account (before insert, after update) {
            if (RecursionGuard.hasRun(Trigger.new[0].Id)) return;
            AccountService.process(Trigger.new);
        }
        """
        harvester = ApexHarvester()
        nodes, edges = harvester.harvest(code)

        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node.type, NodeTypes.APEX_TRIGGER)
        self.assertEqual(node.name, "AccountTrigger")
        self.assertTrue(node.metadata.get("has_recursion_guard"))
        self.assertIn("before insert", node.metadata.get("events"))

        # Verify TRIGGERS_ON edge
        trig_edges = [e for e in edges if e.relationship == EdgeTypes.TRIGGERS_ON]
        self.assertEqual(len(trig_edges), 1)
        self.assertEqual(trig_edges[0].target_id, "salesforce.object.Account")

        # Verify INVOKES edge
        call_edges = [e for e in edges if e.relationship == EdgeTypes.INVOKES]
        self.assertTrue(any(e.target_id == "apex.class.AccountService" for e in call_edges))

    def test_apex_soql_and_dml_in_loops(self):
        code = """
        public class BadBatch {
            public void execute(List<Account> accounts) {
                for (Account a : accounts) {
                    List<Contact> c = [SELECT Id FROM Contact WHERE AccountId = :a.Id];
                    update c;
                }
            }
        }
        """
        harvester = ApexHarvester()
        nodes, edges = harvester.harvest(code)

        node = nodes[0]
        self.assertTrue(node.metadata.get("soql_in_loop"))
        self.assertTrue(node.metadata.get("dml_in_loop"))
        self.assertTrue(len(node.metadata.get("loop_details")) >= 1)

    def test_apex_callout_after_dml(self):
        code = """
        public class PaymentService {
            public void syncPayment(Payment__c p) {
                insert p;
                Http http = new Http();
                HttpRequest req = new HttpRequest();
                HttpResponse res = http.send(req);
            }
        }
        """
        harvester = ApexHarvester()
        nodes, edges = harvester.harvest(code)

        node = nodes[0]
        self.assertTrue(node.metadata.get("callout_after_dml"))
        self.assertTrue(len(node.metadata.get("callout_details")) >= 1)

    def test_flow_parsing(self):
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
        harvester = FlowHarvester()
        nodes, edges = harvester.harvest(flow_xml)

        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node.type, NodeTypes.SF_FLOW)
        self.assertEqual(node.metadata.get("target_object"), "Opportunity")

        # Verify field update edge
        update_edges = [e for e in edges if e.relationship == EdgeTypes.UPDATES_FIELD]
        self.assertTrue(any("Discount_Rate__c" in e.target_id for e in update_edges))

    def test_mulesoft_parsing(self):
        mule_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <mule xmlns="http://www.mulesoft.org/schema/mule/core">
            <flow name="OrderSyncFlow">
                <http:listener path="/api/v1/orders" config-ref="HTTP_Listener_config"/>
                <salesforce:query config-ref="SF_Config">SELECT Tax_Amount__c, Status FROM Order</salesforce:query>
                <snowflake:bulk-insert config-ref="Snowflake_Config" table="ORDER_ANALYTICS"/>
            </flow>
        </mule>
        """
        harvester = MuleHarvester()
        nodes, edges = harvester.harvest(mule_xml)

        flow_nodes = [n for n in nodes if n.type == NodeTypes.MULE_FLOW]
        self.assertEqual(len(flow_nodes), 1)
        self.assertEqual(flow_nodes[0].name, "OrderSyncFlow")

        # Verify Snowflake loads_to edge
        loads_edges = [e for e in edges if e.relationship == EdgeTypes.LOADS_TO]
        self.assertTrue(any(e.target_id == "snow.table.ORDER_ANALYTICS" for e in loads_edges))

        # Verify SF field reads edge
        reads_edges = [e for e in edges if e.relationship == EdgeTypes.READS_FIELD]
        self.assertTrue(any("Tax_Amount__c" in e.target_id for e in reads_edges))

    def test_snowflake_ddl_parsing(self):
        ddl = """
        CREATE OR REPLACE TABLE RAW_ENCOUNTERS (
            ENCOUNTER_ID VARCHAR(50),
            TAX_AMOUNT__C NUMBER(18,2),
            STATUS VARCHAR(20)
        );
        CREATE OR REPLACE PIPE PIPE_ENCOUNTERS COPY INTO RAW_ENCOUNTERS FROM @STAGE_ENCOUNTERS;
        """
        harvester = SnowflakeHarvester()
        nodes, edges = harvester.harvest(ddl)

        table_nodes = [n for n in nodes if n.type == NodeTypes.SNOW_TABLE]
        self.assertEqual(len(table_nodes), 1)
        self.assertEqual(table_nodes[0].name, "RAW_ENCOUNTERS")

        pipe_nodes = [n for n in nodes if n.type == NodeTypes.SNOW_PIPE]
        self.assertEqual(len(pipe_nodes), 1)
        self.assertEqual(pipe_nodes[0].name, "PIPE_ENCOUNTERS")

    def test_transcript_harvester_antigravity_index(self):
        if not os.path.exists(os.path.join(DEFAULT_INDEX_DIR, "index.sqlite")):
            self.skipTest("Antigravity Index not present on machine")

        harvester = TranscriptHarvester(DEFAULT_INDEX_DIR)
        nodes, edges = harvester.harvest()

        node_ids = {n.id for n in nodes}
        # Check that core components are present
        self.assertIn("salesforce.object.Encounter__c", node_ids)
        self.assertIn("salesforce.object.Patient_Insurance__c", node_ids)
        self.assertIn("apex.class.YesterdayDenialSyncBatch", node_ids)
        self.assertIn("apex.class.UpdateEncounterOwnerAndRoutingBatch", node_ids)
        self.assertTrue(len(edges) > 0)


if __name__ == "__main__":
    unittest.main()
