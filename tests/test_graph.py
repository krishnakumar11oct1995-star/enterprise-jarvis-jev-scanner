"""Tests for Graph Store, Traversal, and Dependency Graph Engine."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config import NodeTypes, EdgeTypes, Systems
from jarvis.graph.models import Node, Edge, Conflict, ScanRun
from jarvis.graph.db import JarvisGraphDB
from jarvis.graph.engine import DependencyGraphEngine
from jarvis.graph.traversal import GraphTraversal


class TestGraphEngine(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_graph.sqlite")
        self.db = JarvisGraphDB(self.db_path)
        self.engine = DependencyGraphEngine(self.db)

    def tearDown(self):
        self.db.close()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_node_and_edge_crud(self):
        # Insert node
        n1 = self.engine.add_node(
            node_id="salesforce.object.Account",
            system=Systems.SALESFORCE,
            node_type=NodeTypes.SF_OBJECT,
            name="Account",
            metadata={"custom": False},
        )
        self.assertEqual(n1.name, "Account")

        # Query node
        fetched = self.engine.get_node("salesforce.object.Account")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.system, Systems.SALESFORCE)

        # Insert second node and edge
        n2 = self.engine.add_node(
            node_id="apex.trigger.AccountTrigger",
            system=Systems.SALESFORCE,
            node_type=NodeTypes.APEX_TRIGGER,
            name="AccountTrigger",
        )
        edge = self.engine.add_edge(
            source_id=n2.id,
            target_id=n1.id,
            relationship=EdgeTypes.TRIGGERS_ON,
            properties={"events": ["before_insert", "after_update"]},
        )
        self.assertEqual(edge.relationship, EdgeTypes.TRIGGERS_ON)

        # Query edges
        edges = self.engine.get_edges(source_id=n2.id)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].target_id, n1.id)

    def test_cycle_detection(self):
        # Create a directed cycle: A -> B -> C -> A
        self.engine.add_node("A", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "A")
        self.engine.add_node("B", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "B")
        self.engine.add_node("C", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "C")

        self.engine.add_edge("A", "B", EdgeTypes.INVOKES)
        self.engine.add_edge("B", "C", EdgeTypes.INVOKES)
        self.engine.add_edge("C", "A", EdgeTypes.INVOKES)

        cycles = self.engine.detect_cycles()
        self.assertTrue(len(cycles) >= 1)
        # Verify cycle nodes
        cycle = cycles[0]
        self.assertEqual(cycle[0], cycle[-1])  # Closed loop
        self.assertTrue(set(cycle).issuperset({"A", "B", "C"}))

    def test_tarjan_scc(self):
        self.engine.add_node("X", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "X")
        self.engine.add_node("Y", Systems.SALESFORCE, NodeTypes.APEX_CLASS, "Y")
        self.engine.add_edge("X", "Y", EdgeTypes.INVOKES)
        self.engine.add_edge("Y", "X", EdgeTypes.INVOKES)

        sccs = self.engine.detect_sccs()
        self.assertEqual(len(sccs), 1)
        self.assertCountEqual(sccs[0], ["X", "Y"])

    def test_blast_radius_traversal(self):
        # A -> B -> C -> D
        for name in ["A", "B", "C", "D"]:
            self.engine.add_node(name, Systems.SALESFORCE, NodeTypes.APEX_CLASS, name)
        self.engine.add_edge("A", "B", EdgeTypes.CALLS)
        self.engine.add_edge("B", "C", EdgeTypes.CALLS)
        self.engine.add_edge("C", "D", EdgeTypes.CALLS)

        res = self.engine.blast_radius("A", depth=3)
        self.assertEqual(len(res.nodes), 4)
        self.assertEqual(res.depth_map["D"], 3)
        self.assertEqual(res.depth_map["A"], 0)

    def test_scalability_benchmark(self):
        # Performance requirement: 10,000 nodes, 25,000 edges traversal in < 2.0s
        nodes = []
        for i in range(10000):
            nodes.append(Node(
                id=f"node_{i}",
                system=Systems.SALESFORCE if i % 2 == 0 else Systems.MULESOFT,
                type=NodeTypes.APEX_CLASS,
                name=f"Class_{i}",
            ))
        self.db.upsert_nodes(nodes)

        edges = []
        for i in range(25000):
            src = f"node_{i % 10000}"
            tgt = f"node_{(i * 7 + 13) % 10000}"
            edges.append(Edge(
                source_id=src,
                target_id=tgt,
                relationship=EdgeTypes.CALLS,
            ))
        self.db.upsert_edges(edges)

        start = time.time()
        res = self.engine.blast_radius("node_0", depth=5)
        elapsed = time.time() - start

        self.assertLess(elapsed, 2.0, f"Traversal took {elapsed:.3f}s which is > 2.0s")
        self.assertTrue(len(res.nodes) > 1)


if __name__ == "__main__":
    unittest.main()
