"""Salesforce Metadata Harvester for Project Jarvis.

Parses Apex classes, Apex triggers, Flows (.flow-meta.xml), and SObject schemas (.object-meta.xml).
Detects trigger events, recursion guards, SOQL/DML in loops, callouts after DML, and field mutations.
"""

from __future__ import annotations
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET

from jarvis.config import NodeTypes, EdgeTypes, Systems
from jarvis.graph.models import Node, Edge
from jarvis.harvester.base import BaseHarvester


class ApexHarvester(BaseHarvester):
    """Parses Apex classes and triggers using regex AST tokenization."""

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
                        if file.endswith((".cls", ".trigger", ".apex")):
                            f_nodes, f_edges = self._parse_file(Path(root) / file)
                            nodes.extend(f_nodes)
                            edges.extend(f_edges)
                return nodes, edges
        else:
            # Source is raw code string
            return self._parse_content(str(source), file_path=None)

    def _parse_file(self, file_path: Path) -> Tuple[List[Node], List[Edge]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._parse_content(content, file_path=str(file_path))
        except Exception as e:
            return [], []

    def _parse_content(self, content: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        # Strip comments for cleaner analysis
        clean_code = re.sub(r'//.*', '', content)
        clean_code = re.sub(r'/\*.*?\*/', '', clean_code, flags=re.DOTALL)

        # 1. Check for Trigger
        trigger_match = re.search(
            r'\btrigger\s+([A-Za-z0-9_]+)\s+on\s+([A-Za-z0-9_]+)\s*\(([^)]+)\)',
            clean_code,
            re.IGNORECASE,
        )

        # 2. Check for Class
        class_match = re.search(
            r'\b(?:public|private|global)\s+(?:with\s+sharing\s+|without\s+sharing\s+|inherited\s+sharing\s+)?(?:virtual\s+|abstract\s+)?class\s+([A-Za-z0-9_]+)(?:\s+extends\s+([A-Za-z0-9_]+))?(?:\s+implements\s+([^\{]+))?',
            clean_code,
            re.IGNORECASE,
        )

        is_trigger = bool(trigger_match)
        component_name = ""
        component_id = ""
        system = Systems.SALESFORCE

        # Check recursion guard
        has_recursion_guard = bool(re.search(
            r'(?:static\s+(?:Set<Id>|Boolean|Map<[A-Za-z0-9_, ]+>)\s+(?:processedIds|hasRun|isExecuting|alreadyExecuted|isRecursive))|'
            r'(?:RecursionGuard|TriggerHandler\.bypass|CheckRecursive)',
            clean_code,
            re.IGNORECASE,
        ))

        # Check loop governor limits (SOQL / DML in loops)
        loop_violations = self._detect_loops(clean_code)

        # Check callout after DML
        callout_violations = self._detect_callout_after_dml(clean_code)

        # Extract field writes / DML targets
        dml_targets = self._detect_dml_targets(clean_code)

        # Extract SOQL reads
        soql_reads = self._detect_soql_reads(clean_code)

        # Extract class invocations / calls
        invocations = self._detect_invocations(clean_code)

        if is_trigger and trigger_match:
            component_name = trigger_match.group(1)
            target_sobject = trigger_match.group(2)
            events_raw = trigger_match.group(3)
            events = [e.strip().lower() for e in events_raw.split(",")]

            component_id = f"apex.trigger.{component_name}"
            node_type = NodeTypes.APEX_TRIGGER

            metadata = {
                "events": events,
                "target_object": target_sobject,
                "has_recursion_guard": has_recursion_guard,
                "soql_in_loop": loop_violations["soql_in_loop"],
                "dml_in_loop": loop_violations["dml_in_loop"],
                "loop_details": loop_violations["details"],
                "callout_after_dml": len(callout_violations) > 0,
                "callout_details": callout_violations,
                "file_path": file_path,
            }
            node = Node(
                id=component_id,
                system=system,
                type=node_type,
                name=component_name,
                file_path=file_path,
                metadata=metadata,
            )
            nodes.append(node)

            # Edge: TRIGGERS_ON SObject
            sobject_id = f"salesforce.object.{target_sobject}"
            edges.append(Edge(
                source_id=component_id,
                target_id=sobject_id,
                relationship=EdgeTypes.TRIGGERS_ON,
                properties={"events": events},
            ))

        elif class_match:
            component_name = class_match.group(1)
            implements_str = class_match.group(3) or ""
            is_batch = "database.batchable" in implements_str.lower()
            is_queueable = "queueable" in implements_str.lower()
            is_schedulable = "schedulable" in implements_str.lower()
            is_test = bool(re.search(r'@isTest|testMethod', clean_code, re.IGNORECASE))

            component_id = f"apex.class.{component_name}"
            node_type = NodeTypes.APEX_CLASS

            metadata = {
                "is_batch": is_batch,
                "is_queueable": is_queueable,
                "is_schedulable": is_schedulable,
                "is_test": is_test,
                "has_recursion_guard": has_recursion_guard,
                "soql_in_loop": loop_violations["soql_in_loop"],
                "dml_in_loop": loop_violations["dml_in_loop"],
                "loop_details": loop_violations["details"],
                "callout_after_dml": len(callout_violations) > 0,
                "callout_details": callout_violations,
                "file_path": file_path,
            }
            node = Node(
                id=component_id,
                system=system,
                type=node_type,
                name=component_name,
                file_path=file_path,
                metadata=metadata,
            )
            nodes.append(node)

        if not component_id and file_path:
            # Fallback if neither class nor trigger matched cleanly
            base_name = Path(file_path).stem
            component_id = f"apex.class.{base_name}"
            node = Node(
                id=component_id,
                system=system,
                type=NodeTypes.APEX_CLASS,
                name=base_name,
                file_path=file_path,
                metadata={
                    "has_recursion_guard": has_recursion_guard,
                    "soql_in_loop": loop_violations["soql_in_loop"],
                    "dml_in_loop": loop_violations["dml_in_loop"],
                    "loop_details": loop_violations["details"],
                    "callout_after_dml": len(callout_violations) > 0,
                    "callout_details": callout_violations,
                },
            )
            nodes.append(node)

        # Generate edges for DML target SObjects and Fields
        for target_obj in dml_targets["objects"]:
            edges.append(Edge(
                source_id=component_id,
                target_id=f"salesforce.object.{target_obj}",
                relationship=EdgeTypes.WRITES,
                properties={"operation": "DML"},
            ))

        for target_field in dml_targets["fields"]:
            # target_field format: Object.Field or Field
            if "." in target_field:
                field_id = f"salesforce.field.{target_field}"
            elif is_trigger and trigger_match:
                field_id = f"salesforce.field.{trigger_match.group(2)}.{target_field}"
            else:
                field_id = f"salesforce.field.{target_field}"
            edges.append(Edge(
                source_id=component_id,
                target_id=field_id,
                relationship=EdgeTypes.UPDATES_FIELD,
                properties={"operation": "DML_UPDATE"},
            ))

        # Generate edges for SOQL reads
        for read_obj in soql_reads["objects"]:
            edges.append(Edge(
                source_id=component_id,
                target_id=f"salesforce.object.{read_obj}",
                relationship=EdgeTypes.READS,
                properties={"operation": "SOQL"},
            ))
        for read_field in soql_reads["fields"]:
            edges.append(Edge(
                source_id=component_id,
                target_id=f"salesforce.field.{read_field}",
                relationship=EdgeTypes.READS_FIELD,
                properties={"operation": "SOQL_SELECT"},
            ))

        # Generate edges for Invocations (calls to other classes or batches)
        for called_cls in invocations:
            if called_cls != component_name:
                edges.append(Edge(
                    source_id=component_id,
                    target_id=f"apex.class.{called_cls}",
                    relationship=EdgeTypes.INVOKES,
                    properties={"call_type": "METHOD_CALL"},
                ))

        return nodes, edges

    def _detect_loops(self, content: str) -> Dict[str, Any]:
        """Detects loop constructs and checks for SOQL or DML inside loop bodies."""
        details = []
        soql_in_loop = False
        dml_in_loop = False

        # Find loop heads with balanced parenthesis tracking
        loop_kw_regex = re.compile(r'\b(for|while)\s*\(|\bdo\s*\{', re.IGNORECASE)
        for m in loop_kw_regex.finditer(content):
            matched_str = m.group(0).lower()
            if "do" in matched_str:
                start_idx = m.end() - 1
                header = m.group(0).strip()
            else:
                paren_start = m.end() - 1
                p_depth = 1
                paren_end = -1
                for j in range(paren_start + 1, len(content)):
                    if content[j] == '(':
                        p_depth += 1
                    elif content[j] == ')':
                        p_depth -= 1
                        if p_depth == 0:
                            paren_end = j
                            break
                if paren_end == -1:
                    continue
                rest = content[paren_end + 1:]
                brace_match = re.match(r'^\s*\{', rest)
                if not brace_match:
                    continue
                start_idx = paren_end + 1 + brace_match.end() - 1
                header = content[m.start():start_idx + 1].strip()

            depth = 0
            end_idx = -1
            for i in range(start_idx, len(content)):
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            if end_idx != -1:
                loop_body = content[start_idx + 1:end_idx]
                line_no = content[:m.start()].count('\n') + 1

                # Check SOQL inside loop body
                soql_found = bool(re.search(r'\[\s*SELECT\b|Database\.query\b', loop_body, re.IGNORECASE))
                # Check DML inside loop body
                dml_found = bool(re.search(
                    r'\b(insert|update|delete|upsert|Database\.insert|Database\.update|Database\.delete|Database\.upsert)\b\s+[A-Za-z0-9_]+',
                    loop_body,
                    re.IGNORECASE,
                ))

                if soql_found or dml_found:
                    if soql_found:
                        soql_in_loop = True
                    if dml_found:
                        dml_in_loop = True
                    details.append({
                        "line": line_no,
                        "header": header,
                        "has_soql": soql_found,
                        "has_dml": dml_found,
                    })

        return {
            "soql_in_loop": soql_in_loop,
            "dml_in_loop": dml_in_loop,
            "details": details,
        }

    def _detect_callout_after_dml(self, content: str) -> List[Dict[str, Any]]:
        """Detects synchronous callouts occurring after DML in the same class/method."""
        has_future = bool(re.search(r'@future\s*\(\s*callout\s*=\s*true\s*\)', content, re.IGNORECASE))
        allows_callouts = bool(re.search(r'Database\.AllowsCallouts', content, re.IGNORECASE))
        if has_future or allows_callouts:
            return []

        dml_regex = re.compile(
            r'\b(insert|update|delete|upsert|Database\.insert|Database\.update|Database\.delete|Database\.upsert)\b\s+[A-Za-z0-9_]+',
            re.IGNORECASE,
        )
        callout_regex = re.compile(r'\b(Http\b.*?\bsend\b|\bWebServiceCallout\b)', re.IGNORECASE)

        dml_matches = list(dml_regex.finditer(content))
        callout_matches = list(callout_regex.finditer(content))

        violations = []
        if dml_matches and callout_matches:
            for dml in dml_matches:
                for callout in callout_matches:
                    if dml.start() < callout.start():
                        violations.append({
                            "dml_line": content[:dml.start()].count('\n') + 1,
                            "dml_statement": dml.group(0),
                            "callout_line": content[:callout.start()].count('\n') + 1,
                            "callout_statement": callout.group(0),
                        })
        return violations

    def _detect_dml_targets(self, content: str) -> Dict[str, Set[str]]:
        """Extracts SObjects and fields being modified via DML or assignments."""
        objects = set()
        fields = set()

        # Variable declarations e.g. Contact c = ... or List<Account> accs = ...
        var_types: Dict[str, str] = {}
        decl_regex = re.compile(r'\b(?:List<)?([A-Za-z0-9_]+)(?:>)?\s+([A-Za-z0-9_]+)\s*=', re.IGNORECASE)
        for m in decl_regex.finditer(content):
            t, v = m.group(1), m.group(2)
            if t not in ("String", "Integer", "Boolean", "Decimal", "Double", "Id", "Date", "Datetime", "Object", "Map", "Set", "List"):
                var_types[v] = t

        # DML statements: update c; insert accs;
        dml_regex = re.compile(
            r'\b(?:insert|update|delete|upsert|Database\.insert|Database\.update|Database\.delete|Database\.upsert)\s+([A-Za-z0-9_]+)',
            re.IGNORECASE,
        )
        for m in dml_regex.finditer(content):
            target_var = m.group(1)
            if target_var in var_types:
                objects.add(var_types[target_var])
            elif target_var.endswith("__c") or target_var in ("Account", "Contact", "Opportunity", "Lead", "Case", "Task", "Event"):
                objects.add(target_var)

        # Field mutations: record.Discount_Rate__c = ... or opp.Discount_Rate__c = ...
        field_assign_regex = re.compile(r'\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]+__c)\s*=', re.IGNORECASE)
        for m in field_assign_regex.finditer(content):
            var_name, field_name = m.group(1), m.group(2)
            if var_name in var_types:
                fields.add(f"{var_types[var_name]}.{field_name}")
            else:
                fields.add(field_name)

        return {"objects": objects, "fields": fields}

    def _detect_soql_reads(self, content: str) -> Dict[str, Set[str]]:
        """Extracts SObjects and fields queried in SOQL."""
        objects = set()
        fields = set()

        soql_regex = re.compile(r'\[\s*SELECT\s+(.*?)\s+FROM\s+([A-Za-z0-9_]+)', re.IGNORECASE | re.DOTALL)
        for m in soql_regex.finditer(content):
            select_clause = m.group(1)
            from_obj = m.group(2)
            objects.add(from_obj)

            # Extract fields
            for f in select_clause.split(","):
                f = f.strip()
                if f and not f.startswith("(") and " " not in f:
                    fields.add(f"{from_obj}.{f}")

        return {"objects": objects, "fields": fields}

    def _detect_invocations(self, content: str) -> Set[str]:
        """Extracts calls to helper classes or batch executions."""
        invocations = set()

        # Class.method(...)
        call_regex = re.compile(r'\b([A-Z][A-Za-z0-9_]+)\.[A-Za-z0-9_]+\s*\(', re.IGNORECASE)
        for m in call_regex.finditer(content):
            cls_name = m.group(1)
            if cls_name not in ("System", "Database", "String", "Math", "Test", "Assert", "JSON", "Http", "HttpRequest", "HttpResponse"):
                invocations.add(cls_name)

        # new ClassName(...)
        new_regex = re.compile(r'\bnew\s+([A-Z][A-Za-z0-9_]+)\s*\(', re.IGNORECASE)
        for m in new_regex.finditer(content):
            cls_name = m.group(1)
            if cls_name not in ("Http", "HttpRequest", "HttpResponse", "List", "Set", "Map", "Exception"):
                invocations.add(cls_name)

        # Database.executeBatch(new MyBatch())
        batch_regex = re.compile(r'Database\.executeBatch\s*\(\s*new\s+([A-Za-z0-9_]+)\s*\(', re.IGNORECASE)
        for m in batch_regex.finditer(content):
            invocations.add(m.group(1))

        return invocations


class FlowHarvester(BaseHarvester):
    """Parses Salesforce Flows from .flow-meta.xml files or XML content."""

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
                        if file.endswith((".flow-meta.xml", ".flow")):
                            f_nodes, f_edges = self._parse_file(Path(root) / file)
                            nodes.extend(f_nodes)
                            edges.extend(f_edges)
                return nodes, edges
        else:
            return self._parse_xml_content(str(source), file_path=None)

    def _parse_file(self, file_path: Path) -> Tuple[List[Node], List[Edge]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._parse_xml_content(content, file_path=str(file_path))
        except Exception:
            return [], []

    def _parse_xml_content(self, xml_text: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return [], []

        # Strip XML namespaces for easy element lookup
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        flow_name = Path(file_path).stem.replace(".flow-meta", "") if file_path else "FlowDefinition"
        label_elem = root.find("label")
        if label_elem is not None and label_elem.text:
            flow_name = label_elem.text.replace(" ", "_")

        process_type = (root.findtext("processType") or "AutoLaunched").strip()
        trigger_type = (root.findtext("triggerType") or "").strip()

        # Target SObject (from recordTriggerType or start element)
        target_sobject = ""
        start_elem = root.find("start")
        if start_elem is not None:
            obj_elem = start_elem.find("object")
            if obj_elem is not None and obj_elem.text:
                target_sobject = obj_elem.text.strip()
            trig_elem = start_elem.find("triggerType")
            if trig_elem is not None and trig_elem.text:
                trigger_type = trig_elem.text.strip()

        if not target_sobject:
            # Fallback search in XML
            obj_elem = root.find(".//object") or root.find(".//objectType")
            if obj_elem is not None and obj_elem.text:
                target_sobject = obj_elem.text.strip()

        # Map triggerType to standard events
        events: List[str] = []
        if trigger_type == "RecordBeforeSave":
            events = ["before_insert", "before_update"]
        elif trigger_type == "RecordAfterSave":
            events = ["after_insert", "after_update"]
        elif "before" in trigger_type.lower():
            events = ["before_update"]
        elif "after" in trigger_type.lower():
            events = ["after_update"]

        flow_id = f"salesforce.flow.{flow_name}"
        node = Node(
            id=flow_id,
            system=Systems.SALESFORCE,
            type=NodeTypes.SF_FLOW,
            name=flow_name,
            file_path=file_path,
            metadata={
                "process_type": process_type,
                "trigger_type": trigger_type,
                "target_object": target_sobject,
                "events": events,
            },
        )
        nodes.append(node)

        # Edge: TRIGGERS_ON
        if target_sobject:
            sobject_id = f"salesforce.object.{target_sobject}"
            edges.append(Edge(
                source_id=flow_id,
                target_id=sobject_id,
                relationship=EdgeTypes.TRIGGERS_ON,
                properties={"events": events, "trigger_type": trigger_type},
            ))

        # Check field updates / recordUpdates / assignments
        updated_fields = set()
        for update_elem in root.findall(".//recordUpdates") + root.findall(".//assignments"):
            for assign in update_elem.findall(".//assignmentItems") + update_elem.findall(".//inputAssignments"):
                field_name = assign.findtext("field") or assign.findtext("assignToReference")
                if field_name:
                    field_name = field_name.strip()
                    # Strip $Record. if present
                    if field_name.startswith("$Record."):
                        field_name = field_name.replace("$Record.", "")
                    if target_sobject and "." not in field_name:
                        field_id = f"salesforce.field.{target_sobject}.{field_name}"
                    elif "." in field_name:
                        field_id = f"salesforce.field.{field_name}"
                    else:
                        field_id = f"salesforce.field.{field_name}"
                    updated_fields.add(field_id)

        for field_id in updated_fields:
            edges.append(Edge(
                source_id=flow_id,
                target_id=field_id,
                relationship=EdgeTypes.UPDATES_FIELD,
                properties={"operation": "FLOW_UPDATE"},
            ))

        # Check subflows
        for subflow in root.findall(".//subflows"):
            subflow_name = subflow.findtext("flowName")
            if subflow_name:
                edges.append(Edge(
                    source_id=flow_id,
                    target_id=f"salesforce.flow.{subflow_name.strip()}",
                    relationship=EdgeTypes.INVOKES,
                    properties={"type": "SUBFLOW"},
                ))

        return nodes, edges


class SchemaHarvester(BaseHarvester):
    """Parses SObject schemas (.object-meta.xml, .field-meta.xml)."""

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
                        if file.endswith((".object-meta.xml", ".field-meta.xml")):
                            f_nodes, f_edges = self._parse_file(Path(root) / file)
                            nodes.extend(f_nodes)
                            edges.extend(f_edges)
                return nodes, edges
        else:
            return self._parse_schema_content(str(source))

    def _parse_file(self, file_path: Path) -> Tuple[List[Node], List[Edge]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._parse_schema_content(content, file_path=str(file_path))
        except Exception:
            return [], []

    def _parse_schema_content(self, xml_text: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return [], []

        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # 1. CustomObject
        if root.tag == "CustomObject":
            label = root.findtext("label") or ""
            if file_path:
                obj_name = Path(file_path).name.replace(".object-meta.xml", "")
            elif label:
                obj_name = label.replace(" ", "_")
            else:
                obj_name = "CustomObject"
            label = label or obj_name
            obj_id = f"salesforce.object.{obj_name}"
            node = Node(
                id=obj_id,
                system=Systems.SALESFORCE,
                type=NodeTypes.SF_OBJECT,
                name=obj_name,
                file_path=file_path,
                metadata={"label": label},
            )
            nodes.append(node)

            # Check embedded fields inside object XML
            for field_elem in root.findall("fields"):
                field_name = field_elem.findtext("fullName")
                field_type = field_elem.findtext("type") or "Text"
                field_label = field_elem.findtext("label") or field_name
                if field_name:
                    f_id = f"salesforce.field.{obj_name}.{field_name}"
                    f_node = Node(
                        id=f_id,
                        system=Systems.SALESFORCE,
                        type=NodeTypes.SF_FIELD,
                        name=f"{obj_name}.{field_name}",
                        parent_id=obj_id,
                        file_path=file_path,
                        metadata={"field_name": field_name, "data_type": field_type, "label": field_label},
                    )
                    nodes.append(f_node)
                    edges.append(Edge(
                        source_id=f_id,
                        target_id=obj_id,
                        relationship=EdgeTypes.DEPENDS_ON,
                    ))

        # 2. CustomField
        elif root.tag == "CustomField":
            field_name = root.findtext("fullName")
            field_type = root.findtext("type") or "Text"
            field_label = root.findtext("label") or field_name
            # In SFDX, fields are in objects/<Object>/fields/<Field>.field-meta.xml
            parent_obj = "UnknownObject"
            if file_path:
                parts = Path(file_path).parts
                if "objects" in parts:
                    idx = parts.index("objects")
                    if idx + 1 < len(parts):
                        parent_obj = parts[idx + 1]
                if not field_name:
                    field_name = Path(file_path).name.replace(".field-meta.xml", "")

            if field_name:
                field_id = f"salesforce.field.{parent_obj}.{field_name}"
                parent_id = f"salesforce.object.{parent_obj}"
                node = Node(
                    id=field_id,
                    system=Systems.SALESFORCE,
                    type=NodeTypes.SF_FIELD,
                    name=f"{parent_obj}.{field_name}",
                    parent_id=parent_id,
                    file_path=file_path,
                    metadata={"field_name": field_name, "data_type": field_type, "label": field_label},
                )
                nodes.append(node)
                edges.append(Edge(
                    source_id=field_id,
                    target_id=parent_id,
                    relationship=EdgeTypes.DEPENDS_ON,
                ))

        return nodes, edges


class SalesforceHarvester(BaseHarvester):
    """Unified harvester for Salesforce metadata: Apex, Triggers, Flows, and Schemas."""

    def __init__(self):
        self.apex_harvester = ApexHarvester()
        self.flow_harvester = FlowHarvester()
        self.schema_harvester = SchemaHarvester()

    def harvest(self, source: Union[str, Path]) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        path = Path(source)
        if not path.exists():
            # If not a file/dir, attempt parsing as raw Apex
            return self.apex_harvester.harvest(source)

        if path.is_file():
            ext = path.suffix.lower()
            name = path.name.lower()
            if ext in (".cls", ".trigger", ".apex"):
                return self.apex_harvester.harvest(path)
            elif ".flow" in name:
                return self.flow_harvester.harvest(path)
            elif ".object-meta" in name or ".field-meta" in name:
                return self.schema_harvester.harvest(path)
            else:
                return self.apex_harvester.harvest(path)

        elif path.is_dir():
            # Traverse and harvest all
            for root, _, files in os.walk(path):
                for file in files:
                    full_p = Path(root) / file
                    lower_f = file.lower()
                    if lower_f.endswith((".cls", ".trigger", ".apex")):
                        n, e = self.apex_harvester.harvest(full_p)
                        nodes.extend(n)
                        edges.extend(e)
                    elif ".flow" in lower_f:
                        n, e = self.flow_harvester.harvest(full_p)
                        nodes.extend(n)
                        edges.extend(e)
                    elif ".object-meta" in lower_f or ".field-meta" in lower_f:
                        n, e = self.schema_harvester.harvest(full_p)
                        nodes.extend(n)
                        edges.extend(e)

        return nodes, edges
