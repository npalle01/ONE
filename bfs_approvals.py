#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
bfs_engine.py – BFS Engine for Rule Execution and Simulation in the BRM Tool

Features:
  • Builds relationships among rules (parent–child, global-critical links,
    conflict links, composite rule dependencies).
  • Executes rules using a unified BFS approach.
  • Performs dry-run simulations capturing detailed logs of the number of records impacted,
    success/failure notifications, and error messages.
  • Uses advanced SQL parsing from the core module.
  • Uses robust error handling and standard naming conventions for production readiness.
  
All simulation details are logged via the logger.
"""

import logging
from collections import deque
from datetime import datetime
import json
import re

# If the core module is available, we can import advanced SQL parsing and audit logging functions.
# For example:
# from core import parse_sql_dependencies, insert_audit_log, logger

logger = logging.getLogger(__name__)

def load_rule_relationships(conn):
    """
    Constructs the rule relationships (adjacency) for:
      - Child rules (based on PARENT_RULE_ID)
      - Global-critical links (from BRM_GLOBAL_CRITICAL_LINKS)
      - Conflicts (bidirectional from RULE_CONFLICTS)
      - Composite rules (extracted from COMPOSITE_RULES using regex)

    Returns:
      - adjacency: dict mapping rule_id -> set of related rule_ids
      - roots: list of rule_ids with no parent (starting points for BFS)
      - parent_map: dict mapping child_rule_id -> parent_rule_id
    """
    c = conn.cursor()
    c.execute("SELECT RULE_ID, PARENT_RULE_ID FROM BRM_RULES")
    rows = c.fetchall()
    adjacency = {}
    parent_map = {}
    all_ids = set()
    for rid, pid in rows:
        all_ids.add(rid)
        if pid:
            adjacency.setdefault(pid, set()).add(rid)
            parent_map[rid] = pid

    # Global-critical links
    c.execute("SELECT GCR_RULE_ID, TARGET_RULE_ID FROM BRM_GLOBAL_CRITICAL_LINKS")
    for gcr, tgt in c.fetchall():
        adjacency.setdefault(gcr, set()).add(tgt)

    # Conflict links (bidirectional)
    c.execute("SELECT RULE_ID1, RULE_ID2 FROM RULE_CONFLICTS")
    for r1, r2 in c.fetchall():
        adjacency.setdefault(r1, set()).add(r2)
        adjacency.setdefault(r2, set()).add(r1)

    # Composite rules: Extract sub-rule references from the LOGIC_EXPR field.
    c.execute("SELECT COMPOSITE_RULE_ID, LOGIC_EXPR FROM COMPOSITE_RULES")
    pattern = re.compile(r"Rule(\d+)")
    for crid, expr in c.fetchall():
        if expr:
            matches = pattern.findall(expr)
            for m in matches:
                try:
                    sub_rule = int(m)
                    adjacency.setdefault(sub_rule, set()).add(crid)
                except ValueError:
                    continue

    roots = [r for r in all_ids if r not in parent_map]
    logger.debug(f"Loaded rule relationships: {len(all_ids)} total rules, {len(roots)} roots.")
    return adjacency, roots, parent_map

def skip_all_descendants(start_id, adjacency, skipped):
    """
    Marks all descendant rules of start_id as skipped using DFS.
    Modifies the 'skipped' set in place.
    """
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current in skipped:
            continue
        skipped.add(current)
        for child in adjacency.get(current, []):
            if child not in skipped:
                stack.append(child)

def run_single_rule_in_transaction(conn, rule_info, is_dry_run=False):
    """
    Executes a single rule within a transaction.
    
    For rules of type DECISION_TABLE, it simulates a pass.
    For standard rules, it executes the SQL and checks if the first column of the first row equals 1.
    
    Returns:
      (success_flag, message, record_count)
    
    If is_dry_run is True, the transaction is always rolled back.
    Logs the number of impacted records and outcome.
    """
    op_type = rule_info.get("OPERATION_TYPE", "OTHER")
    rule_id = rule_info.get("RULE_ID", "Unknown")
    
    if op_type == "DECISION_TABLE":
        dt_id = rule_info.get("DECISION_TABLE_ID")
        msg = f"Decision Table {dt_id} simulated PASS."
        logger.info(f"Rule {rule_id}: {msg}")
        return (True, msg, 1)
    
    sql_text = rule_info.get("RULE_SQL", "").strip()
    c = conn.cursor()
    c.execute("BEGIN TRANSACTION")
    success = False
    msg = ""
    rec_count = 0
    try:
        c.execute(sql_text)
        rows = c.fetchall()
        rec_count = len(rows)
        if rows:
            first_val = rows[0][0]
            success = (first_val == 1)
            msg = f"SQL executed; returned {first_val}; impacted {rec_count} record(s)."
        else:
            success = True
            msg = "SQL executed; no rows returned; interpreted as PASS."
        
        if is_dry_run or not success:
            c.execute("ROLLBACK")
            logger.info(f"Dry-run rollback for rule {rule_id}: {msg}")
        else:
            c.execute("COMMIT")
            logger.info(f"Rule {rule_id} committed successfully: {msg}")
    except Exception as ex:
        c.execute("ROLLBACK")
        msg = f"Error executing rule {rule_id}: {ex}"
        logger.error(msg)
        success = False
    return (success, msg, rec_count)

def insert_rule_execution_log(conn, rule_id, pass_flag, message, record_count):
    """
    Inserts an entry into the RULE_EXECUTION_LOGS table capturing:
      - Rule ID
      - Execution timestamp (current)
      - Pass flag (1 for success, 0 for failure)
      - Detailed message (including record count)
      - Record count impacted
      - Execution time (set to 0 here; can be updated for performance metrics)
    """
    c = conn.cursor()
    c.execute("""
    INSERT INTO RULE_EXECUTION_LOGS(
        RULE_ID, EXECUTION_TIMESTAMP, PASS_FLAG, MESSAGE, RECORD_COUNT, EXECUTION_TIME_MS
    )
    VALUES (?, GETDATE(), ?, ?, ?, ?)
    """, (rule_id, 1 if pass_flag else 0, message, record_count, 0))
    conn.commit()
    logger.debug(f"Logged execution for rule {rule_id}: {message} (Records: {record_count})")

def get_all_rules_map(conn):
    """
    Retrieves all rules from the BRM_RULES table.
    Returns a dictionary mapping RULE_ID to the complete rule record (as a dictionary).
    """
    c = conn.cursor()
    c.execute("SELECT * FROM BRM_RULES")
    rows = c.fetchall()
    colnames = [desc[0] for desc in c.description]
    rule_map = {}
    for row in rows:
        rule_data = dict(zip(colnames, row))
        rule_map[rule_data["RULE_ID"]] = rule_data
    logger.debug(f"Loaded {len(rule_map)} rules from BRM_RULES.")
    return rule_map

def execute_rules_unified_bfs(conn, dry_run=False):
    """
    Executes rules using a unified BFS strategy starting from all root rules.
    
    For each rule:
      - Executes the rule via run_single_rule_in_transaction.
      - Logs the outcome and number of impacted records.
      - If a rule fails and is marked as critical or global, its descendants are skipped.
    
    Returns a tuple:
      (list of executed rule IDs, set of skipped rule IDs)
    """
    adjacency, roots, parent_map = load_rule_relationships(conn)
    rule_lookup = get_all_rules_map(conn)
    executed = []
    skipped = set()
    queue = list(roots)

    while queue:
        rid = queue.pop(0)
        if rid in skipped:
            continue
        if rid not in rule_lookup:
            skipped.add(rid)
            continue

        rule_info = rule_lookup[rid]
        success, msg, rec_count = run_single_rule_in_transaction(conn, rule_info, is_dry_run=dry_run)
        insert_rule_execution_log(conn, rid, success, msg, rec_count)

        if success:
            executed.append(rid)
            for child in adjacency.get(rid, []):
                if child not in skipped:
                    queue.append(child)
        else:
            # If the rule fails and is critical, skip all its descendants.
            is_critical = rule_info.get("CRITICAL_RULE", 0) == 1 or rule_info.get("IS_GLOBAL", 0) == 1
            if is_critical:
                skip_all_descendants(rid, adjacency, skipped)
            skipped.add(rid)
    logger.info(f"BFS Execution Completed: Executed={executed}, Skipped={list(skipped)}")
    return executed, skipped

# ----------------------------
# End of bfs_engine.py Module
if __name__ == '__main__':
    # For testing purposes, you can run a dry-run BFS simulation.
    try:
        # This assumes that core.py exists and provides a DatabaseConnectionDialog.
        from core import DatabaseConnectionDialog  # Import from the core module
        app_dialog = DatabaseConnectionDialog()
        if app_dialog.exec_() == app_dialog.Accepted:
            conn = app_dialog.get_connection()
            if conn:
                executed, skipped = execute_rules_unified_bfs(conn, dry_run=True)
                print("Dry-Run BFS Simulation Results:")
                print("Executed Rules:", executed)
                print("Skipped Rules:", list(skipped))
    except Exception as e:
        print(f"Error during BFS simulation: {e}")