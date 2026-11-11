"""MuleSoft Metadata Harvester for Project Jarvis.

Parses MuleSoft XML flows and RAML/OAS API definitions.
Extracts HTTP endpoints, Salesforce connectors, Snowflake loaders, and DataWeave transformations.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET

from jarvis.config import NodeTypes, EdgeTypes, Systems
from jarvis.graph.models import Node, Edge
from jarvis.harvester.base import BaseHarvester


class MuleHarvester(BaseHarvester):
    """Parses MuleSoft XML configuration files and API specifications."""

    def harvest(self, source: Union[str, Path]) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        if isinstance(source, (str, Path)) and os.path.exists(str(source)):
            path = Path(source)
            if path.is_file():
                return self._parse_file(path)
            elif path.is_dir():
                for root, _, files in os.walk(path):
                    for file in files:
                        lower = file.lower()
                        if lower.endswith((".xml", ".raml", ".yaml", ".json")) and not lower.endswith("-meta.xml"):
                            f_nodes, f_edges = self._parse_file(Path(root) / file)
                            nodes.extend(f_nodes)
                            edges.extend(f_edges)
                return nodes, edges
        else:
            return self._parse_xml_content(str(source))

    def _parse_file(self, file_path: Path) -> Tuple[List[Node], List[Edge]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if file_path.suffix.lower() == ".xml":
                return self._parse_xml_content(content, file_path=str(file_path))
            elif file_path.suffix.lower() in (".raml", ".yaml", ".json"):
                return self._parse_api_spec(content, file_path=str(file_path))
        except Exception:
            pass
        return [], []

    def _parse_xml_content(self, xml_text: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        # Sanitize XML prefixes: replace <prefix:tag with <prefix__tag and strip xmlns to handle unbound namespaces
        sanitized = re.sub(r'<(/)?([A-Za-z0-9_]+):([A-Za-z0-9_\-]+)', r'<\1\2__\3', xml_text)
        sanitized = re.sub(r'xmlns(:\w+)?="[^"]*"', '', sanitized)

        try:
            root = ET.fromstring(sanitized)
        except Exception:
            try:
                root = ET.fromstring(xml_text)
            except Exception:
                return [], []

        # Check if this is a Mule config file
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # Extract flows
        flows = root.findall(".//flow") or root.findall(".//sub-flow")
        if not flows and "mule" in root.tag.lower():
            flows = [root]

        base_file_name = Path(file_path).stem if file_path else "mule_flow"

        for flow_elem in flows:
            flow_name = flow_elem.get("name") or base_file_name
            flow_id = f"mulesoft.flow.{flow_name}"

            flow_node = Node(
                id=flow_id,
                system=Systems.MULESOFT,
                type=NodeTypes.MULE_FLOW,
                name=flow_name,
                file_path=file_path,
                metadata={"file_path": file_path},
            )
            nodes.append(flow_node)

            # Check HTTP listener
            for listener in flow_elem.iter():
                if "listener" in listener.tag.lower():
                    path_attr = listener.get("path")
                    if path_attr:
                        endpoint_id = f"mulesoft.endpoint.{path_attr}"
                        nodes.append(Node(
                            id=endpoint_id,
                            system=Systems.MULESOFT,
                            type=NodeTypes.MULE_ENDPOINT,
                            name=path_attr,
                            parent_id=flow_id,
                            file_path=file_path,
                            metadata={"path": path_attr},
                        ))
                        edges.append(Edge(
                            source_id=flow_id,
                            target_id=endpoint_id,
                            relationship=EdgeTypes.CALLS,
                        ))

            # Check Salesforce operations
            # <salesforce:create type="Order"> or <salesforce:query>
            for elem in flow_elem.iter():
                tag = elem.tag.lower()
                sf_type = elem.get("type") or elem.get("objectType")
                if "salesforce" in tag or sf_type:
                    if sf_type:
                        edges.append(Edge(
                            source_id=flow_id,
                            target_id=f"salesforce.object.{sf_type}",
                            relationship=EdgeTypes.INTEGRATES_WITH,
                            properties={"operation": tag},
                        ))

                    # Inspect query or child text for fields
                    text = elem.text or ""
                    query_match = re.search(r'SELECT\s+(.*?)\s+FROM\s+([A-Za-z0-9_]+)', text, re.IGNORECASE)
                    if query_match:
                        fields_str, obj = query_match.group(1), query_match.group(2)
                        for f in fields_str.split(","):
                            f_clean = f.strip()
                            if f_clean and " " not in f_clean:
                                edges.append(Edge(
                                    source_id=flow_id,
                                    target_id=f"salesforce.field.{obj}.{f_clean}",
                                    relationship=EdgeTypes.READS_FIELD,
                                    properties={"operation": "SF_QUERY"},
                                ))

            # Check Snowflake operations
            for elem in flow_elem.iter():
                tag = elem.tag.lower()
                table = elem.get("table") or elem.get("tableName")
                if "snowflake" in tag or "snow" in tag or table:
                    if table:
                        table_id = f"snow.table.{table.upper()}"
                        edges.append(Edge(
                            source_id=flow_id,
                            target_id=table_id,
                            relationship=EdgeTypes.LOADS_TO,
                            properties={"operation": tag},
                        ))

            # Inspect DataWeave / regex for Salesforce field mappings
            # Look for expressions like payload.Tax_Amount__c or Order.Tax_Amount__c
            raw_flow_str = ET.tostring(flow_elem, encoding="unicode")
            sf_field_refs = re.findall(r'\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]+__c)\b', raw_flow_str)
            for obj_or_var, field_name in sf_field_refs:
                # If obj_or_var looks like an SObject name
                if obj_or_var.endswith("__c") or obj_or_var in ("Order", "Account", "Contact", "Opportunity", "Lead"):
                    edges.append(Edge(
                        source_id=flow_id,
                        target_id=f"salesforce.field.{obj_or_var}.{field_name}",
                        relationship=EdgeTypes.READS_FIELD,
                        properties={"source": "DataWeave_Mapping"},
                    ))
                else:
                    # Generic reference: record as field
                    edges.append(Edge(
                        source_id=flow_id,
                        target_id=f"salesforce.field.{field_name}",
                        relationship=EdgeTypes.READS_FIELD,
                        properties={"source": "DataWeave_Mapping"},
                    ))

        return nodes, edges

    def _parse_api_spec(self, content: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        api_name = Path(file_path).stem if file_path else "MuleAPI"
        api_id = f"mulesoft.api.{api_name}"

        node = Node(
            id=api_id,
            system=Systems.MULESOFT,
            type=NodeTypes.MULE_FLOW,
            name=api_name,
            file_path=file_path,
        )
        nodes.append(node)

        # Detect paths e.g. /orders: or /customers:
        paths = re.findall(r'(\/[a-zA-Z0-9_\-\/]+):', content)
        for p in set(paths):
            endpoint_id = f"mulesoft.endpoint.{p}"
            nodes.append(Node(
                id=endpoint_id,
                system=Systems.MULESOFT,
                type=NodeTypes.MULE_ENDPOINT,
                name=p,
                parent_id=api_id,
                file_path=file_path,
            ))
            edges.append(Edge(
                source_id=api_id,
                target_id=endpoint_id,
                relationship=EdgeTypes.CALLS,
            ))

        return nodes, edges
