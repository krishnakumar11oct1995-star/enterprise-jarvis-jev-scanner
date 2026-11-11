"""Snowflake DDL & Pipeline Harvester for Project Jarvis.

Parses Snowflake SQL DDL files, Snowpipe definitions, and Scheduled Tasks.
Extracts tables, columns, copy stages, and upstream Salesforce/MuleSoft data lineage.
"""

from __future__ import annotations
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from jarvis.config import NodeTypes, EdgeTypes, Systems
from jarvis.graph.models import Node, Edge
from jarvis.harvester.base import BaseHarvester


class SnowflakeHarvester(BaseHarvester):
    """Parses Snowflake SQL files for tables, columns, pipes, and tasks."""

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
                        if file.lower().endswith(".sql"):
                            f_nodes, f_edges = self._parse_file(Path(root) / file)
                            nodes.extend(f_nodes)
                            edges.extend(f_edges)
                return nodes, edges
        else:
            return self._parse_sql_content(str(source))

    def _parse_file(self, file_path: Path) -> Tuple[List[Node], List[Edge]]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._parse_sql_content(content, file_path=str(file_path))
        except Exception:
            return [], []

    def _parse_sql_content(self, sql_text: str, file_path: Optional[str] = None) -> Tuple[List[Node], List[Edge]]:
        nodes: List[Node] = []
        edges: List[Edge] = []

        # Clean single-line comments for statement parsing, but save comments for field mapping lineage
        comments = re.findall(r'--.*', sql_text)

        # 1. Parse CREATE TABLE statements
        table_regex = re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\.]+)\s*\((.*?)\);',
            re.IGNORECASE | re.DOTALL,
        )

        for match in table_regex.finditer(sql_text):
            full_table_name = match.group(1).upper()
            body = match.group(2)
            # Table name could be DB.SCHEMA.TABLE or just TABLE
            table_name = full_table_name.split(".")[-1]
            table_id = f"snow.table.{table_name}"

            table_node = Node(
                id=table_id,
                system=Systems.SNOWFLAKE,
                type=NodeTypes.SNOW_TABLE,
                name=table_name,
                file_path=file_path,
                metadata={"full_name": full_table_name},
            )
            nodes.append(table_node)

            # Parse columns inside table
            for col_line in body.split(","):
                col_line = col_line.strip()
                if not col_line or col_line.upper().startswith(("PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE")):
                    continue
                parts = col_line.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip('"`[]').upper()
                    col_type = parts[1].strip('"`[],()')
                    col_id = f"snow.column.{table_name}.{col_name}"

                    nodes.append(Node(
                        id=col_id,
                        system=Systems.SNOWFLAKE,
                        type=NodeTypes.SNOW_COLUMN,
                        name=f"{table_name}.{col_name}",
                        parent_id=table_id,
                        file_path=file_path,
                        metadata={"data_type": col_type},
                    ))
                    edges.append(Edge(
                        source_id=col_id,
                        target_id=table_id,
                        relationship=EdgeTypes.DEPENDS_ON,
                    ))

                    # Check if column matches or maps to a Salesforce field
                    # e.g. TAX_AMOUNT__C or TAX_AMOUNT
                    if col_name.endswith("__C"):
                        edges.append(Edge(
                            source_id=col_id,
                            target_id=f"salesforce.field.{col_name}",
                            relationship=EdgeTypes.SYNCED_FROM,
                            properties={"lineage": "direct_column_match"},
                        ))

        # 2. Parse CREATE PIPE statements
        pipe_regex = re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?PIPE\s+([A-Za-z0-9_\.]+)\s+.*?COPY\s+INTO\s+([A-Za-z0-9_\.]+)',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pipe_regex.finditer(sql_text):
            pipe_name = match.group(1).split(".")[-1].upper()
            target_table = match.group(2).split(".")[-1].upper()
            pipe_id = f"snow.pipe.{pipe_name}"

            nodes.append(Node(
                id=pipe_id,
                system=Systems.SNOWFLAKE,
                type=NodeTypes.SNOW_PIPE,
                name=pipe_name,
                file_path=file_path,
                metadata={"target_table": target_table},
            ))
            edges.append(Edge(
                source_id=pipe_id,
                target_id=f"snow.table.{target_table}",
                relationship=EdgeTypes.LOADS_TO,
            ))

        # 3. Parse CREATE TASK statements
        task_regex = re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?TASK\s+([A-Za-z0-9_\.]+)',
            re.IGNORECASE,
        )
        for match in task_regex.finditer(sql_text):
            task_name = match.group(1).split(".")[-1].upper()
            task_id = f"snow.task.{task_name}"
            nodes.append(Node(
                id=task_id,
                system=Systems.SNOWFLAKE,
                type=NodeTypes.SNOW_TASK,
                name=task_name,
                file_path=file_path,
            ))

        # 4. Check comments or text for cross-cloud Salesforce field references
        # e.g., -- mapped from Order.Tax_Amount__c or referencing Order.Tax_Amount__c in SQL
        sf_field_refs = re.findall(r'\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]+__c)\b', sql_text, re.IGNORECASE)
        for obj_name, field_name in sf_field_refs:
            if nodes:
                # Link the primary table in this file to the SF field
                primary_table_id = nodes[0].id if nodes[0].type == NodeTypes.SNOW_TABLE else f"snow.table.{obj_name.upper()}"
                edges.append(Edge(
                    source_id=primary_table_id,
                    target_id=f"salesforce.field.{obj_name}.{field_name}",
                    relationship=EdgeTypes.SYNCED_FROM,
                    properties={"mapped_via": "SQL_LINEAGE"},
                ))

        return nodes, edges
