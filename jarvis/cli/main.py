"""Command Line Interface for Project Jarvis."""

from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
from typing import List, Optional

# Safe stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from jarvis.config import (
    DEFAULT_DB_PATH,
    DEFAULT_INDEX_DIR,
    DEFAULT_INDEX_DB,
    EXIT_SUCCESS,
    EXIT_CRITICAL,
    EXIT_ERROR,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)
from jarvis.graph.db import JarvisGraphDB
from jarvis.graph.engine import DependencyGraphEngine
from jarvis.harvester.salesforce import SalesforceHarvester, ApexHarvester, FlowHarvester, SchemaHarvester
from jarvis.harvester.mulesoft import MuleHarvester
from jarvis.harvester.snowflake import SnowflakeHarvester
from jarvis.harvester.transcript_harvester import TranscriptHarvester
from jarvis.radar.evaluator import ConflictRadarEvaluator
from jarvis.memory.bridge import MemoryBridge
from jarvis.router.jev_router import JevRouter
from jarvis.reporter.console import print_scan_report, print_blast_radius
from jarvis.reporter.markdown import generate_scan_markdown, generate_blast_radius_markdown
from jarvis.reporter.json_exporter import export_scan_json, export_blast_radius_json



def run_harvest(args: argparse.Namespace) -> int:
    """Executes metadata harvesting into the Jarvis graph database."""
    try:
        db_path = args.db or DEFAULT_DB_PATH
        engine = DependencyGraphEngine(db_path=db_path)
        source = args.source

        total_nodes = 0
        total_edges = 0

        # Optional bootstrap from Antigravity Index transcripts
        if getattr(args, "from_index", False):
            print(f"[*] Bootstrapping graph from Antigravity Index ({DEFAULT_INDEX_DIR})...")
            hist_harv = TranscriptHarvester(args.index_dir or DEFAULT_INDEX_DIR)
            n, e = hist_harv.harvest()
            engine.add_nodes(n)
            engine.add_edges(e)
            total_nodes += len(n)
            total_edges += len(e)
            print(f"    Indexed {len(n)} nodes, {len(e)} relationships from historical transcripts.")

        if source:
            source_path = Path(source)
            if not source_path.exists():
                print(f"[!] Warning: Source path '{source}' not found on filesystem. Attempting string parsing.", file=sys.stderr)

            # Harvest Salesforce
            sf_harv = SalesforceHarvester()
            n, e = sf_harv.harvest(source)
            engine.add_nodes(n)
            engine.add_edges(e)
            total_nodes += len(n)
            total_edges += len(e)

            # Harvest MuleSoft
            mule_harv = MuleHarvester()
            n, e = mule_harv.harvest(source)
            engine.add_nodes(n)
            engine.add_edges(e)
            total_nodes += len(n)
            total_edges += len(e)

            # Harvest Snowflake
            snow_harv = SnowflakeHarvester()
            n, e = snow_harv.harvest(source)
            engine.add_nodes(n)
            engine.add_edges(e)
            total_nodes += len(n)
            total_edges += len(e)

        counts = engine.counts()
        print(f"[+] Harvest complete.")
        print(f"    Total in Graph: {counts.get('nodes', 0)} nodes, {counts.get('edges', 0)} edges.")
        print(f"    Database: {db_path}")
        return EXIT_SUCCESS

    except Exception as e:
        print(f"[!] Error during harvest: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_scan(args: argparse.Namespace) -> int:
    """Runs Conflict Radar evaluation against harvested metadata."""
    try:
        db_path = args.db or DEFAULT_DB_PATH
        engine = DependencyGraphEngine(db_path=db_path)

        # If --path or --source is provided, harvest first into the DB
        scan_target = getattr(args, "path", None) or getattr(args, "source", None)
        if scan_target:
            target_path = Path(scan_target)
            if target_path.exists():
                # Harvest target path
                sf_harv = SalesforceHarvester()
                n, e = sf_harv.harvest(scan_target)
                engine.add_nodes(n)
                engine.add_edges(e)

                mule_harv = MuleHarvester()
                n, e = mule_harv.harvest(scan_target)
                engine.add_nodes(n)
                engine.add_edges(e)

                snow_harv = SnowflakeHarvester()
                n, e = snow_harv.harvest(scan_target)
                engine.add_nodes(n)
                engine.add_edges(e)
            else:
                # Direct code snippet
                sf_harv = SalesforceHarvester()
                n, e = sf_harv.harvest(scan_target)
                engine.add_nodes(n)
                engine.add_edges(e)

        # Setup Memory Bridge
        index_dir = getattr(args, "index_dir", None) or DEFAULT_INDEX_DIR
        memory_bridge = MemoryBridge(index_dir)

        # Run evaluator
        evaluator = ConflictRadarEvaluator(engine, memory_bridge=memory_bridge)
        scan_run, conflicts = evaluator.evaluate(
            target_path=str(scan_target) if scan_target else "local_graph",
            severity_filter=args.severity,
        )

        fmt = getattr(args, "format", "table") or "table"
        if fmt == "json":
            print(export_scan_json(scan_run, conflicts))
        elif fmt == "markdown":
            print(generate_scan_markdown(scan_run, conflicts))
        else:
            print_scan_report(scan_run, conflicts)

        # Check CI/CD quality gate: Exit 1 on CRITICAL
        if scan_run.critical_count > 0:
            return EXIT_CRITICAL
        return EXIT_SUCCESS

    except Exception as e:
        print(f"[!] Error during scan: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_impact(args: argparse.Namespace) -> int:
    """Runs blast radius traversal for a component."""
    try:
        db_path = args.db or DEFAULT_DB_PATH
        engine = DependencyGraphEngine(db_path=db_path)
        component_id = args.component
        depth = getattr(args, "depth", 5) or 5
        direction = getattr(args, "direction", "downstream") or "downstream"

        result = engine.blast_radius(component_id, depth=depth, direction=direction)
        print_blast_radius(result)
        return EXIT_SUCCESS

    except Exception as e:
        print(f"[!] Error during impact analysis: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_memory(args: argparse.Namespace) -> int:
    """Interacts with Antigravity Index historical memory."""
    try:
        index_dir = getattr(args, "index_dir", None) or DEFAULT_INDEX_DIR
        bridge = MemoryBridge(index_dir)
        if not bridge.is_available():
            print(f"[!] Antigravity Index not found at {bridge.db_path}", file=sys.stderr)
            return EXIT_ERROR

        subcommand = getattr(args, "memory_cmd", "search")

        if subcommand == "search":
            query = args.query
            limit = getattr(args, "limit", 5) or 5
            turns = bridge.search(query, limit=limit)
            if not turns:
                print(f"No historical solutions found matching: '{query}'")
            else:
                print(f"\n=== Found {len(turns)} Relevant Past Conversations for '{query}' ===\n")
                for i, t in enumerate(turns, 1):
                    ts = t.timestamp[:16] if t.timestamp else "N/A"
                    print(f"[{i}] Date: {ts} | Detail: {t.transcript_path}")
                    print(f"    User Asked: {t.user_prompt[:120]}...")
                    if t.files_touched:
                        print(f"    Files: {t.files_touched}")
                    print(f"    Solution Snippet: {t.solution_summary[:180].replace(chr(10), ' ')}...")
                    print("-" * 75)

        elif subcommand == "rca":
            component = args.component
            turns = bridge.get_rca_context(component, limit=getattr(args, "limit", 3) or 3)
            if not turns:
                print(f"No historical RCAs found for component: '{component}'")
            else:
                print(f"\n=== Historical RCAs for '{component}' ===\n")
                for i, t in enumerate(turns, 1):
                    ts = t.timestamp[:16] if t.timestamp else "N/A"
                    print(f"[{i}] Date: {ts} | Conv ID: {t.conv_id}")
                    print(f"    Transcript: {t.transcript_path}")
                    print(f"    Root Cause / Fix Summary: {t.solution_summary[:220].replace(chr(10), ' ')}...")
                    print("-" * 75)

        return EXIT_SUCCESS

    except Exception as e:
        print(f"[!] Error during memory operation: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_report(args: argparse.Namespace) -> int:
    """Generates an audit report from past or current scan."""
    try:
        db_path = args.db or DEFAULT_DB_PATH
        engine = DependencyGraphEngine(db_path=db_path)
        evaluator = ConflictRadarEvaluator(engine, memory_bridge=MemoryBridge(DEFAULT_INDEX_DIR))

        scan_run, conflicts = evaluator.evaluate()
        fmt = getattr(args, "format", "markdown") or "markdown"

        if fmt == "json":
            content = export_scan_json(scan_run, conflicts)
        else:
            content = generate_scan_markdown(scan_run, conflicts)

        output_path = getattr(args, "output", None)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[+] Audit report saved to: {output_path}")
        else:
            print(content)

        if scan_run.critical_count > 0:
            return EXIT_CRITICAL
        return EXIT_SUCCESS

    except Exception as e:
        print(f"[!] Error generating report: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_triage(args: argparse.Namespace) -> int:
    """Runs fast System 1 triage via Jev (TypeSafe AI) decision engine."""
    try:
        router = JevRouter(api_key=getattr(args, "api_key", None))
        text = args.text or ""
        is_code = getattr(args, "code", False)

        if getattr(args, "file", None):
            file_path = Path(args.file)
            if file_path.exists():
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                is_code = True
            else:
                print(f"[!] File not found: {args.file}", file=sys.stderr)
                return EXIT_ERROR

        if not text:
            print("[!] Please provide --text, --code, or --file for triage.", file=sys.stderr)
            return EXIT_ERROR

        decision = router.triage(text, is_code=is_code)

        print("\n" + "="*65)
        print(" ⚡ JEV SYSTEM 1 TRIAGE (TypeSafe Decision Engine)")
        print("="*65)
        print(f"  • Engine Provider         : {decision.provider}")
        print(f"  • Decision Latency        : {decision.latency_ms} ms")
        print(f"  • Domain Classification   : {decision.domain} (Confidence: {decision.domain_confidence*100:.1f}%)")
        print(f"  • Risk Score              : {decision.risk_score} (Level: {decision.risk_score_numeric}/10)")
        print(f"  • Needs Conflict Scan     : {'🚨 YES' if decision.needs_conflict_scan else '✅ NO'}")
        print(f"  • Needs Historical Recall : {'📚 YES' if decision.needs_historical_recall else '❌ NO'}")
        if decision.suggested_memory_queries:
            print(f"  • Suggested Memory Focus  : {', '.join(decision.suggested_memory_queries)}")
        print("="*65 + "\n")

        # Auto-trigger scan if requested or if risk is critical
        if getattr(args, "auto_execute", False):
            if decision.needs_historical_recall and decision.suggested_memory_queries:
                print(f"[*] Jev Auto-Recall: Querying memory for '{decision.suggested_memory_queries[0]}'...")
                bridge = MemoryBridge(args.index_dir or DEFAULT_INDEX_DIR)
                matches = bridge.search(decision.suggested_memory_queries[0], limit=2)
                for m in matches:
                    print(f"    - Historical Match: {m.user_prompt[:80]}... ({m.md_file})")


            if decision.needs_conflict_scan:
                print("[*] Jev Auto-Radar: High risk detected, triggering Conflict Radar scan...")
                args.path = getattr(args, "file", None)
                args.source = args.path
                args.severity = None
                args.format = "table"
                return run_scan(args)

        return EXIT_SUCCESS
    except Exception as e:
        print(f"[!] Error during Jev triage: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_hud(args: argparse.Namespace) -> int:
    """Launches the Desktop HUD Cockpit UI."""
    try:
        from app.ui.hud import launch_hud
        launch_hud(
            port=getattr(args, "port", 8765),
            browser=getattr(args, "browser", False),
            no_window=getattr(args, "no_window", False),
        )
        return EXIT_SUCCESS
    except Exception as e:
        print(f"[!] Error launching HUD: {e}", file=sys.stderr)
        return EXIT_ERROR


def build_parser() -> argparse.ArgumentParser:
    """Builds the main argument parser for Project Jarvis CLI."""
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Project Jarvis: Enterprise Architecture & Conflict Radar Engine",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. Harvest
    harvest_parser = subparsers.add_parser("harvest", help="Harvest metadata into local graph")
    harvest_parser.add_argument("--source", required=False, default=None, help="Path to repo or metadata files")
    harvest_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite graph database")
    harvest_parser.add_argument("--from-index", action="store_true", help="Bootstrap graph from Antigravity Index transcripts")
    harvest_parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Path to Antigravity Index directory")

    # 2. Scan
    scan_parser = subparsers.add_parser("scan", help="Run Conflict Radar scan")
    scan_parser.add_argument("--path", required=False, default=None, help="Target file or directory to scan")
    scan_parser.add_argument("--source", required=False, default=None, help="Alias for --path")
    scan_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite graph database")
    scan_parser.add_argument("--severity", choices=[SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO], default=None, help="Filter by severity")
    scan_parser.add_argument("--format", choices=["table", "json", "markdown"], default="table", help="Output format")
    scan_parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Path to Antigravity Index directory")

    # 3. Impact
    impact_parser = subparsers.add_parser("impact", help="Analyze Blast Radius / Impact of a component")
    impact_parser.add_argument("--component", required=True, help="Component Node ID or name")
    impact_parser.add_argument("--depth", type=int, default=5, help="Traversal depth (default: 5)")
    impact_parser.add_argument("--direction", choices=["downstream", "upstream", "both"], default="downstream", help="Traversal direction")
    impact_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite graph database")

    # 4. Memory
    memory_parser = subparsers.add_parser("memory", help="Query Antigravity Index historical memory")
    mem_subs = memory_parser.add_subparsers(dest="memory_cmd", help="Memory subcommands")

    mem_search = mem_subs.add_parser("search", help="Search conversation turns")
    mem_search.add_argument("query", help="Search term or phrase")
    mem_search.add_argument("--limit", type=int, default=5, help="Max results to return")
    mem_search.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Path to Antigravity Index directory")

    mem_rca = mem_subs.add_parser("rca", help="Retrieve root cause analysis for component")
    mem_rca.add_argument("--component", required=True, help="Component name or ID")
    mem_rca.add_argument("--limit", type=int, default=3, help="Max results to return")
    mem_rca.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Path to Antigravity Index directory")

    # 5. Report
    report_parser = subparsers.add_parser("report", help="Generate comprehensive architectural audit report")
    report_parser.add_argument("--output", default=None, help="Output file path (e.g. audit_report.md)")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Report format")
    report_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite graph database")

    # 6. Triage (Jev System 1)
    triage_parser = subparsers.add_parser("triage", help="Run fast Jev System 1 triage on code or prompt")
    triage_parser.add_argument("--text", default=None, help="Prompt or text to triage")
    triage_parser.add_argument("--file", default=None, help="Code file to triage")
    triage_parser.add_argument("--code", action="store_true", help="Treat input as code snippet")
    triage_parser.add_argument("--auto-execute", action="store_true", help="Automatically trigger radar scan and memory search if needed")
    triage_parser.add_argument("--api-key", default=None, help="TypeSafe AI API key")
    triage_parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR, help="Path to Antigravity Index directory")
    triage_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite graph database")

    # 7. HUD (Desktop Cockpit)
    hud_parser = subparsers.add_parser("hud", help="Launch Desktop HUD Cockpit UI (Alt + J hotkey)")
    hud_parser.add_argument("--port", type=int, default=8765, help="Port for HUD server (default: 8765)")
    hud_parser.add_argument("--browser", action="store_true", help="Launch in native browser app mode")
    hud_parser.add_argument("--no-window", action="store_true", help="Start background server only without desktop window")

    return parser


def main() -> int:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        return EXIT_SUCCESS

    args = parser.parse_args()
    if args.subcommand == "harvest":
        return run_harvest(args)
    elif args.subcommand == "scan":
        return run_scan(args)
    elif args.subcommand == "impact":
        return run_impact(args)
    elif args.subcommand == "memory":
        return run_memory(args)
    elif args.subcommand == "report":
        return run_report(args)
    elif args.subcommand == "triage":
        return run_triage(args)
    elif args.subcommand == "hud":
        return run_hud(args)
    else:
        parser.print_help(sys.stderr)
        return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())

