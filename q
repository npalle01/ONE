#!/usr/bin/env python
"""
Complete BRM Tool Code (SQL Server Only), PyQt5-based.

Features:
- Login via DB
- Business Rule Management (CRUD, BFS adjacency, table dependencies)
- Multi-step approvals w/ Approve + Reject
- Rule Simulation w/ friendly error if missing table
- Version History & Rollback
- Impact Analysis
- Scheduling & Management
- Metrics Dashboard
- Group Management (Admin)
- Global/Critical Admin (Admin)
- Hierarchy View
- User Management (Admin)
- Audit Log viewer
- Searching rules
- Control Tables viewer
- Advanced table parsing (db, schema, table) with sqlparse

Requires:
- PyQt5, pyodbc, sqlparse, pyqtgraph
- T-SQL schema that matches references:
  (BRM_RULES, BRM_RULE_APPROVALS, BRM_RULE_TABLE_DEPENDENCIES, BUSINESS_GROUPS,
   USERS, etc.)

Author: <You>
"""

import sys
import math
import json
import csv
import re
import smtplib
import logging
import pyodbc
import sqlparse
from email.mime.text import MIMEText
from datetime import datetime
from collections import deque

from sqlparse.sql import IdentifierList, Identifier
from sqlparse.tokens import Keyword, DML

# PyQt imports
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QDateTime, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit, QTableWidget, QTableWidgetItem, QMessageBox,
    QComboBox, QInputDialog, QDateTimeEdit, QTabWidget, QGroupBox, QAbstractItemView,
    QPlainTextEdit, QSplitter, QCheckBox, QTreeWidget, QTreeWidgetItem, QListWidget, 
    QListWidgetItem, QMenu, QFileDialog
)
import pyqtgraph as pg


###############################################################################
# Logging & Email Setup
###############################################################################
logging.basicConfig(
    filename='brmtool_pyqtgraph.log',
    level=logging.DEBUG,
    format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

EMAIL_CONFIG = {
    "smtp_server": "smtp.example.com",   # Replace with your SMTP server
    "smtp_port": 587,
    "smtp_username": "your_username",
    "smtp_password": "your_password",
    "sender_email": "noreply@example.com"
}


###############################################################################
# Utility: SQL Parse for (db, schema, table)
###############################################################################
def parse_identifier(identifier):
    raw = str(identifier).strip("[] ")
    parts = raw.split(".")
    if len(parts) == 3:
        db = parts[0].strip("[] ")
        schema = parts[1].strip("[] ")
        table = parts[2].strip("[] ")
        return (db, schema, table)
    elif len(parts) == 2:
        schema = parts[0].strip("[] ")
        table = parts[1].strip("[] ")
        return ("", schema, table)
    else:
        return ("", "", raw.strip("[] "))

def advanced_extract_tables(sql_text: str):
    parsed = sqlparse.parse(sql_text)
    found = []

    for statement in parsed:
        from_seen = False
        for token in statement.tokens:
            if token.ttype is Keyword and token.value.upper() == "FROM":
                from_seen = True
                continue
            if from_seen:
                if token.ttype is Keyword:
                    break
                if isinstance(token, IdentifierList):
                    for ident in token.get_identifiers():
                        db, sch, tbl = parse_identifier(ident)
                        if tbl:
                            found.append((db, sch, tbl))
                elif isinstance(token, Identifier):
                    db, sch, tbl = parse_identifier(token)
                    if tbl:
                        found.append((db, sch, tbl))

    unique_list = []
    for item in found:
        if item not in unique_list:
            unique_list.append(item)
    return unique_list


###############################################################################
# DB Utilities
###############################################################################
def get_cursor_rows(cursor):
    try:
        rows = cursor.fetchall()
    except:
        rows = []
    if cursor.description:
        colnames = [desc[0] for desc in cursor.description]
        return [dict(zip(colnames, row)) for row in rows]
    return rows

def get_cursor_one(cursor):
    row = cursor.fetchone()
    if row and cursor.description:
        colnames = [desc[0] for desc in cursor.description]
        return dict(zip(colnames, row))
    return row

def send_email_notification(subject, body, recipients):
    try:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = ", ".join(recipients)

        s = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        s.starttls()
        s.login(EMAIL_CONFIG['smtp_username'], EMAIL_CONFIG['smtp_password'])
        s.sendmail(EMAIL_CONFIG['sender_email'], recipients, msg.as_string())
        s.quit()

        logger.info("Email sent to: " + ", ".join(recipients))
    except Exception as ex:
        logger.error("Error sending email: " + str(ex))


###############################################################################
# Insert-if-not-exists for Approvals
###############################################################################
def insert_if_not_exists_approvals(conn, rule_id, group_name, username, stage):
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) as cnt
        FROM BRM_RULE_APPROVALS
        WHERE RULE_ID=? AND GROUP_NAME=? AND USERNAME=? AND APPROVAL_STAGE=?
    """, (rule_id, group_name, username, stage))
    row = c.fetchone()
    if row and row[0] == 0:
        c.execute("""
            INSERT INTO BRM_RULE_APPROVALS(RULE_ID, GROUP_NAME, USERNAME, APPROVED_FLAG, APPROVAL_STAGE, APPROVED_TIMESTAMP)
            VALUES(?,?,?,?,?,NULL)
        """, (rule_id, group_name, username, 0, stage))


###############################################################################
# DB Connection Dialog
###############################################################################
class DatabaseConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database Connection")
        layout = QVBoxLayout(self)

        lbl = QLabel("Select a SQL Server ODBC DSN or enter a custom connection string:")
        layout.addWidget(lbl)

        self.conn_type_combo = QComboBox()
        try:
            dsn_dict = pyodbc.dataSources()
            for dsn_name, driver in dsn_dict.items():
                if "SQL SERVER" in driver.upper():
                    self.conn_type_combo.addItem(f"ODBC DSN: {dsn_name}", dsn_name)
        except Exception as e:
            logger.error("Error listing DSNs: %s", e)
        layout.addWidget(self.conn_type_combo)

        self.conn_str_edit = QLineEdit()
        self.conn_str_edit.setPlaceholderText("Or custom connection string...")
        layout.addWidget(self.conn_str_edit)

        btn_h = QHBoxLayout()
        ok_btn = QPushButton("Connect")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_h.addWidget(ok_btn)
        btn_h.addWidget(cancel_btn)
        layout.addLayout(btn_h)

    def get_connection(self):
        override = self.conn_str_edit.text().strip()
        if override:
            conn_str = override
        else:
            choice = self.conn_type_combo.currentData()
            if not choice:
                QMessageBox.critical(self, "Error", "No DSN or custom string provided.")
                return None
            conn_str = f"DSN={choice};Trusted_Connection=yes;"
        try:
            return pyodbc.connect(conn_str)
        except Exception as ex:
            QMessageBox.critical(self, "Connection Error", str(ex))
            return None


###############################################################################
# Audit Log
###############################################################################
def add_audit_log(conn, action, table_name, record_id, action_by, old_data, new_data):
    c = conn.cursor()
    c.execute("""
    INSERT INTO BRM_AUDIT_LOG(ACTION, TABLE_NAME, RECORD_ID, ACTION_BY, OLD_DATA, NEW_DATA, ACTION_TIMESTAMP)
    VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
    """, (
        action, table_name, str(record_id), action_by,
        json.dumps(old_data) if old_data else None,
        json.dumps(new_data) if new_data else None
    ))
    conn.commit()


###############################################################################
# Rule Utilities
###############################################################################
def get_op_type_from_sql(sql_text: str):
    txt = sql_text.strip().upper()
    if txt.startswith("INSERT"):
        return "INSERT"
    elif txt.startswith("DELETE"):
        return "DELETE"
    elif txt.startswith("UPDATE"):
        return "UPDATE"
    elif txt.startswith("SELECT"):
        return "SELECT"
    return "OTHER"

def run_rule_sql(conn, rule_sql):
    """
    Execute T-SQL. Return (True, msg) if pass, else (False, error).
    If table is missing, show friendlier msg.
    """
    try:
        c = conn.cursor()
        c.execute(rule_sql)
        row = get_cursor_one(c)
        if not row:
            return True, "No rows returned (assumed PASS)"
        val = list(row.values())[0]
        return (val == 1), f"Returned: {val}"
    except Exception as ex:
        msg = str(ex)
        if "Invalid object name" in msg or "does not exist" in msg:
            return False, f"Table missing or invalid object name: {msg}"
        logger.error("Rule execution error: " + msg)
        return False, msg

def build_rule_adjacency(conn):
    c = conn.cursor()
    c.execute("SELECT RULE_ID, PARENT_RULE_ID FROM BRM_RULES")
    rows = get_cursor_rows(c)
    children_map = {}
    all_ids = set()
    parent_ids = set()
    for r in rows:
        rid = r["RULE_ID"]
        pid = r["PARENT_RULE_ID"]
        all_ids.add(rid)
        if pid:
            parent_ids.add(pid)
            children_map.setdefault(pid, []).append(rid)
    roots = [rid for rid in all_ids if rid not in parent_ids]
    return children_map, roots

def load_global_critical_links(conn):
    c = conn.cursor()
    c.execute("SELECT GCR_RULE_ID, TARGET_RULE_ID FROM BRM_GLOBAL_CRITICAL_LINKS")
    rows = get_cursor_rows(c)
    link_map = {}
    for r in rows:
        link_map.setdefault(r["GCR_RULE_ID"], set()).add(r["TARGET_RULE_ID"])
    return link_map

def get_all_rules_as_dict(conn):
    c = conn.cursor()
    c.execute("SELECT * FROM BRM_RULES")
    rows = get_cursor_rows(c)
    return {x["RULE_ID"]: x for x in rows}

def skip_descendants(child_id, children_map, skipped):
    stack = [child_id]
    while stack:
        curr = stack.pop()
        if curr in skipped:
            continue
        skipped.add(curr)
        if curr in children_map:
            stack.extend(children_map[curr])

def execute_rules_in_order(conn):
    children_map, roots = build_rule_adjacency(conn)
    gcr_links = load_global_critical_links(conn)
    rule_lookup = get_all_rules_as_dict(conn)
    executed = []
    skipped = set()
    queue = list(roots)

    while queue:
        rid = queue.pop(0)
        if rid in skipped:
            continue
        if rid not in rule_lookup:
            logger.warning(f"Rule not found: {rid}")
            continue

        rinfo = rule_lookup[rid]
        passed, msg = run_rule_sql(conn, rinfo["RULE_SQL"])
        if passed:
            executed.append(rid)
            if rid in children_map:
                for ch in children_map[rid]:
                    if ch not in skipped:
                        queue.append(ch)
        else:
            is_crit = (rinfo["CRITICAL_RULE"] == 1 or rinfo["IS_GLOBAL"] == 1)
            crit_scope = (rinfo["CRITICAL_SCOPE"] or "NONE").upper()
            if is_crit and crit_scope != "NONE":
                if rid in children_map:
                    for subc in children_map[rid]:
                        skip_descendants(subc, children_map, skipped)
                if rid in gcr_links:
                    for child_rid in gcr_links[rid]:
                        skip_descendants(child_rid, children_map, skipped)

    return executed, skipped

def find_impacted_business_groups(conn, rule_id):
    impacted = set()
    c = conn.cursor()
    c.execute("SELECT OWNER_GROUP FROM BRM_RULES WHERE RULE_ID=?", (rule_id,))
    row = get_cursor_one(c)
    if row:
        impacted.add(row["OWNER_GROUP"])
    queue = [rule_id]
    visited = set()
    while queue:
        curr = queue.pop()
        if curr in visited:
            continue
        visited.add(curr)
        c.execute("SELECT RULE_ID FROM BRM_COLUMN_MAPPING WHERE SOURCE_RULE_ID=?", (curr,))
        for ch in get_cursor_rows(c):
            cid = ch["RULE_ID"]
            c.execute("SELECT OWNER_GROUP FROM BRM_RULES WHERE RULE_ID=?", (cid,))
            row2 = get_cursor_one(c)
            if row2:
                impacted.add(row2["OWNER_GROUP"])
            queue.append(cid)
    return impacted

def create_multistep_approvals(conn, rule_id, impacted_bg_list):
    c = conn.cursor()
    stage_counter = 1
    order = ["BG1", "BG2", "BG3", "FINAL"]
    stage_list = []
    for step in order:
        if step == "FINAL":
            stage_list.append((step, stage_counter))
            stage_counter += 1
        else:
            if step in impacted_bg_list:
                stage_list.append((step, stage_counter))
                stage_counter += 1
    for bg, st in stage_list:
        if bg == "FINAL":
            user_ap = "final_approver"
            insert_if_not_exists_approvals(conn, rule_id, bg, user_ap, st)
        else:
            c.execute("SELECT USERNAME FROM BUSINESS_GROUP_APPROVERS WHERE GROUP_NAME=?", (bg,))
            for rap in get_cursor_rows(c):
                insert_if_not_exists_approvals(conn, rule_id, bg, rap["USERNAME"], st)
    conn.commit()

def get_current_approval_stage(conn, rule_id):
    c = conn.cursor()
    c.execute("""
    SELECT MIN(APPROVAL_STAGE) as stage
    FROM BRM_RULE_APPROVALS
    WHERE RULE_ID=? AND APPROVED_FLAG=0
    """, (rule_id,))
    row = get_cursor_one(c)
    if row and row["stage"]:
        return row["stage"]
    return None

def add_rule(conn, rule_data, created_by, user_group):
    c = conn.cursor()

    # check dup
    c.execute("SELECT RULE_ID FROM BRM_RULES WHERE OWNER_GROUP=? AND RULE_NAME=?",
              (rule_data["OWNER_GROUP"], rule_data["RULE_NAME"].strip()))
    if get_cursor_one(c):
        raise ValueError("Rule already exists in that group")

    is_global = rule_data.get("IS_GLOBAL", 0)
    if is_global == 1 and user_group != "Admin":
        raise ValueError("Only Admin can create global rule.")

    c.execute("""
    INSERT INTO BRM_RULES(
        GROUP_ID, PARENT_RULE_ID, RULE_TYPE_ID, RULE_NAME, RULE_SQL,
        EFFECTIVE_START_DATE, EFFECTIVE_END_DATE, STATUS, VERSION, CREATED_BY,
        DESCRIPTION, OPERATION_TYPE, BUSINESS_JUSTIFICATION, OWNER_GROUP,
        APPROVAL_STATUS, IS_GLOBAL, CRITICAL_RULE, CRITICAL_SCOPE, CDC_TYPE,
        CREATED_TIMESTAMP, UPDATED_BY, CLUSTER_NAME
    )
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,NULL,?)
    """, (
        rule_data.get("GROUP_ID"),
        rule_data.get("PARENT_RULE_ID"),
        rule_data["RULE_TYPE_ID"],
        rule_data["RULE_NAME"].strip(),
        rule_data["RULE_SQL"],
        rule_data["EFFECTIVE_START_DATE"],
        rule_data.get("EFFECTIVE_END_DATE"),
        "INACTIVE",
        1,
        created_by,
        rule_data.get("DESCRIPTION"),
        rule_data.get("OPERATION_TYPE"),
        rule_data.get("BUSINESS_JUSTIFICATION", ""),
        rule_data["OWNER_GROUP"],
        "APPROVAL_IN_PROGRESS",
        is_global,
        rule_data.get("CRITICAL_RULE", 0),
        rule_data.get("CRITICAL_SCOPE", "NONE"),
        rule_data.get("CDC_TYPE", "NONE"),
        rule_data.get("CLUSTER_NAME", "")
    ))
    new_id = c.execute("SELECT SCOPE_IDENTITY()").fetchone()[0]

    # dependencies
    deps = advanced_extract_tables(rule_data["RULE_SQL"])
    for (db, sch, tbl) in deps:
        c.execute("""
            INSERT INTO BRM_RULE_TABLE_DEPENDENCIES(RULE_ID, DATABASE_NAME, SCHEMA_NAME, TABLE_NAME, COLUMN_NAME)
            VALUES(?,?,?,?,?)
        """, (new_id, db, sch, tbl, "DerivedCol"))

    add_audit_log(conn, "INSERT", "BRM_RULES", new_id, created_by, None, rule_data)
    conn.commit()

    if is_global == 0:
        impacted = find_impacted_business_groups(conn, new_id)
        create_multistep_approvals(conn, new_id, impacted)

    try:
        subject = f"New Rule Added: {rule_data['RULE_NAME']}"
        body = f"User {created_by} added Rule ID {new_id}\n\nDetails:\n{json.dumps(rule_data, indent=2)}"
        impacted_grps = find_impacted_business_groups(conn, new_id)
        recips = []
        for g in impacted_grps:
            c.execute("SELECT EMAIL FROM BUSINESS_GROUPS WHERE GROUP_NAME=?", (g,))
            ro = get_cursor_one(c)
            if ro and ro["EMAIL"]:
                recips.append(ro["EMAIL"])
        if recips:
            send_email_notification(subject, body, recips)
    except Exception as ex:
        logger.error(f"Email error on new rule: {ex}")

    return new_id

def update_rule(conn, rule_data, updated_by, user_group):
    c = conn.cursor()
    c.execute("SELECT * FROM BRM_RULES WHERE RULE_ID=?", (rule_data["RULE_ID"],))
    old = get_cursor_one(c)
    if not old:
        raise ValueError("Rule not found.")
    old_data = dict(old)

    new_owner = rule_data.get("OWNER_GROUP", old["OWNER_GROUP"])
    new_name = rule_data.get("RULE_NAME", old["RULE_NAME"]).strip()

    if new_owner != old["OWNER_GROUP"] or new_name != old["RULE_NAME"]:
        c.execute("SELECT RULE_ID FROM BRM_RULES WHERE OWNER_GROUP=? AND RULE_NAME=?", (new_owner, new_name))
        if get_cursor_one(c):
            raise ValueError(f"Duplicate rule name '{new_name}' in group '{new_owner}'")

    if old["IS_GLOBAL"] == 1 and user_group != "Admin":
        raise ValueError("Only Admin can update global rule.")
    if rule_data.get("IS_GLOBAL", old["IS_GLOBAL"]) == 1 and user_group != "Admin":
        raise ValueError("Only Admin can set a rule global.")

    c.execute("""
    UPDATE BRM_RULES
    SET GROUP_ID=?,
        PARENT_RULE_ID=?,
        RULE_TYPE_ID=?,
        RULE_NAME=?,
        RULE_SQL=?,
        EFFECTIVE_START_DATE=?,
        EFFECTIVE_END_DATE=?,
        STATUS='INACTIVE',
        VERSION=VERSION+1,
        UPDATED_BY=?,
        DESCRIPTION=?,
        OPERATION_TYPE=?,
        BUSINESS_JUSTIFICATION=?,
        OWNER_GROUP=?,
        APPROVAL_STATUS='APPROVAL_IN_PROGRESS',
        IS_GLOBAL=?,
        CRITICAL_RULE=?,
        CRITICAL_SCOPE=?,
        CDC_TYPE=?,
        CLUSTER_NAME=?
    WHERE RULE_ID=?
    """, (
        rule_data.get("GROUP_ID", old["GROUP_ID"]),
        rule_data.get("PARENT_RULE_ID", old["PARENT_RULE_ID"]),
        rule_data["RULE_TYPE_ID"],
        new_name,
        rule_data["RULE_SQL"],
        rule_data["EFFECTIVE_START_DATE"],
        rule_data.get("EFFECTIVE_END_DATE"),
        updated_by,
        rule_data.get("DESCRIPTION"),
        rule_data.get("OPERATION_TYPE"),
        rule_data.get("BUSINESS_JUSTIFICATION", ""),
        new_owner,
        rule_data.get("IS_GLOBAL", old["IS_GLOBAL"]),
        rule_data.get("CRITICAL_RULE", old["CRITICAL_RULE"]),
        rule_data.get("CRITICAL_SCOPE", old["CRITICAL_SCOPE"]),
        rule_data.get("CDC_TYPE", old["CDC_TYPE"]),
        rule_data.get("CLUSTER_NAME", old.get("CLUSTER_NAME","")),
        rule_data["RULE_ID"]
    ))

    c.execute("DELETE FROM BRM_RULE_TABLE_DEPENDENCIES WHERE RULE_ID=?", (rule_data["RULE_ID"],))
    deps = advanced_extract_tables(rule_data["RULE_SQL"])
    for (db, sch, tbl) in deps:
        c.execute("""
            INSERT INTO BRM_RULE_TABLE_DEPENDENCIES(RULE_ID, DATABASE_NAME, SCHEMA_NAME, TABLE_NAME, COLUMN_NAME)
            VALUES(?,?,?,?,?)
        """, (rule_data["RULE_ID"], db, sch, tbl, "DerivedCol"))

    new_data = dict(old_data)
    for k, v in rule_data.items():
        new_data[k] = v
    new_data["VERSION"] = old["VERSION"] + 1

    add_audit_log(conn, "UPDATE", "BRM_RULES", rule_data["RULE_ID"], updated_by, old_data, new_data)
    conn.commit()

    # Approvals if not global
    if old["IS_GLOBAL"] == 1 or rule_data.get("IS_GLOBAL", 0) == 1:
        logger.info("Skipping multi-step for global rule update.")
    else:
        c.execute("DELETE FROM BRM_RULE_APPROVALS WHERE RULE_ID=?", (rule_data["RULE_ID"],))
        impacted = find_impacted_business_groups(conn, rule_data["RULE_ID"])
        create_multistep_approvals(conn, rule_data["RULE_ID"], impacted)

    # email
    try:
        subject = f"Rule Updated: {new_name}"
        body = (f"User {updated_by} updated rule ID {rule_data['RULE_ID']}.\n\n"
                f"Old:\n{json.dumps(old_data, indent=2)}\n\n"
                f"New:\n{json.dumps(rule_data, indent=2)}")
        impacted_grps = find_impacted_business_groups(conn, rule_data["RULE_ID"])
        recips = []
        for g_ in impacted_grps:
            c.execute("SELECT EMAIL FROM BUSINESS_GROUPS WHERE GROUP_NAME=?", (g_,))
            ro = get_cursor_one(c)
            if ro and ro["EMAIL"]:
                recips.append(ro["EMAIL"])
        if recips:
            send_email_notification(subject, body, recips)
    except Exception as ex:
        logger.error("Email error on rule update: " + str(ex))

def deactivate_rule(conn, rule_id, updated_by, user_group):
    c = conn.cursor()
    c.execute("SELECT * FROM BRM_RULES WHERE RULE_ID=?", (rule_id,))
    old = get_cursor_one(c)
    if not old:
        raise ValueError("Rule not found.")
    if old["APPROVAL_STATUS"] != "APPROVED":
        raise ValueError("Cannot deactivate unless fully APPROVED.")
    if old["IS_GLOBAL"] == 1 and user_group != "Admin":
        raise ValueError("Only Admin can deactivate global rule.")
    c.execute("SELECT * FROM BRM_RULES WHERE PARENT_RULE_ID=? AND STATUS='ACTIVE'", (rule_id,))
    kids = get_cursor_rows(c)
    if kids:
        raise ValueError("Deactivate child rules first.")

    old_data = dict(old)
    c.execute("""
    UPDATE BRM_RULES
    SET STATUS='INACTIVE', UPDATED_BY=?, VERSION=VERSION+1
    WHERE RULE_ID=?
    """, (updated_by, rule_id))

    new_data = dict(old_data)
    new_data["STATUS"] = "INACTIVE"
    new_data["VERSION"] = old["VERSION"]+1
    add_audit_log(conn, "DEACTIVATE", "BRM_RULES", rule_id, updated_by, old_data, new_data)
    conn.commit()

def delete_rule(conn, rule_id, action_by, user_group):
    c = conn.cursor()
    c.execute("SELECT * FROM BRM_RULES WHERE RULE_ID=?", (rule_id,))
    old = get_cursor_one(c)
    if not old:
        raise ValueError("Rule not found.")
    if old["IS_GLOBAL"] == 1 and user_group != "Admin":
        raise ValueError("Only Admin can delete global rule.")
    if old["APPROVAL_STATUS"] != "APPROVED":
        raise ValueError("Cannot delete unless fully APPROVED.")
    if old["STATUS"] != "INACTIVE":
        raise ValueError("Must be INACTIVE first.")
    c.execute("SELECT * FROM BRM_RULES WHERE PARENT_RULE_ID=?", (rule_id,))
    kids = get_cursor_rows(c)
    if kids:
        raise ValueError("Child rules exist.")
    c.execute("SELECT * FROM BRM_COLUMN_MAPPING WHERE SOURCE_RULE_ID=? OR RULE_ID=?", (rule_id, rule_id))
    leftover = get_cursor_rows(c)
    if leftover:
        raise ValueError("Remove or remap column references first.")

    old_data = dict(old)
    c.execute("DELETE FROM BRM_RULES WHERE RULE_ID=?", (rule_id,))
    add_audit_log(conn, "DELETE", "BRM_RULES", rule_id, action_by, old_data, None)
    conn.commit()


###############################################################################
# Rule Simulation Dialog
###############################################################################
class RuleSimulationDialog(QDialog):
    def __init__(self, connection, rule_sql, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.rule_sql = rule_sql
        self.setWindowTitle("Rule Simulation (Dry-run)")
        self.resize(600,400)

        lay = QVBoxLayout(self)
        self.sim_result = QPlainTextEdit()
        self.sim_result.setReadOnly(True)
        lay.addWidget(self.sim_result)

        bh = QHBoxLayout()
        self.sim_btn = QPushButton("Simulate Rule")
        self.sim_btn.clicked.connect(self.simulate)
        bh.addWidget(self.sim_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        bh.addWidget(close_btn)
        lay.addLayout(bh)

    def simulate(self):
        self.sim_btn.setEnabled(False)
        ok, msg = run_rule_sql(self.connection, self.rule_sql)
        out = f"Result: {'PASS' if ok else 'FAIL'}\nDetail: {msg}"
        self.sim_result.setPlainText(out)
        self.sim_btn.setEnabled(True)


###############################################################################
# Version History and Rollback
###############################################################################
class VersionHistoryDialog(QDialog):
    def __init__(self, connection, rule_id, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.rule_id = rule_id
        self.setWindowTitle(f"Version History for Rule {rule_id}")
        self.resize(800,400)

        lay = QVBoxLayout(self)
        self.history_table = QTableWidget(0,5)
        self.history_table.setHorizontalHeaderLabels(["Audit ID","Action","Timestamp","Old Data","New Data"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.history_table)

        bh = QHBoxLayout()
        self.rollback_btn = QPushButton("Rollback to Selected Version")
        self.rollback_btn.clicked.connect(self.rollback)
        bh.addWidget(self.rollback_btn)
        cls = QPushButton("Close")
        cls.clicked.connect(self.close)
        bh.addWidget(cls)
        lay.addLayout(bh)

        self.setLayout(lay)
        self.load_history()

    def load_history(self):
        c = self.connection.cursor()
        c.execute("""
        SELECT AUDIT_ID, ACTION, OLD_DATA, NEW_DATA, ACTION_TIMESTAMP
        FROM BRM_AUDIT_LOG
        WHERE TABLE_NAME='BRM_RULES'
          AND RECORD_ID=? AND ACTION IN ('INSERT','UPDATE')
        ORDER BY ACTION_TIMESTAMP DESC
        """, (self.rule_id,))
        rows = get_cursor_rows(c)
        self.history_table.setRowCount(0)
        for row in rows:
            r = self.history_table.rowCount()
            self.history_table.insertRow(r)
            self.history_table.setItem(r,0,QTableWidgetItem(str(row["AUDIT_ID"])))
            self.history_table.setItem(r,1,QTableWidgetItem(row["ACTION"]))
            self.history_table.setItem(r,2,QTableWidgetItem(str(row["ACTION_TIMESTAMP"])))
            self.history_table.setItem(r,3,QTableWidgetItem(row["OLD_DATA"] or ""))
            self.history_table.setItem(r,4,QTableWidgetItem(row["NEW_DATA"] or ""))

    def rollback(self):
        sel = self.history_table.selectedItems()
        if not sel:
            QMessageBox.warning(self,"No selection","Select a version to roll back to.")
            return
        row_idx = sel[0].row()
        old_data = self.history_table.item(row_idx, 3)
        if not old_data or not old_data.text():
            QMessageBox.warning(self,"No data","No rollback data for that version.")
            return
        conf = QMessageBox.question(self,"Confirm","Rollback to selected version?")
        if conf != QMessageBox.Yes:
            return
        try:
            old_dict = json.loads(old_data.text())
            update_rule(self.connection, old_dict, "Admin", "Admin")
            QMessageBox.information(self,"Rolled Back","Successfully rolled back.")
            self.load_history()
        except Exception as ex:
            QMessageBox.critical(self,"Error",str(ex))


###############################################################################
# Impact Analysis
###############################################################################
class ImpactAnalysisDialog(QDialog):
    def __init__(self, connection, rule_id, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.rule_id = rule_id
        self.setWindowTitle(f"Impact Analysis for Rule {rule_id}")
        self.resize(600,400)

        lay = QVBoxLayout(self)
        self.impact_text = QTextEdit()
        self.impact_text.setReadOnly(True)
        lay.addWidget(self.impact_text)

        cls = QPushButton("Close")
        cls.clicked.connect(self.close)
        lay.addWidget(cls)

        self.setLayout(lay)
        self.analyze()

    def analyze(self):
        children_map, _ = build_rule_adjacency(self.connection)
        visited = set()
        impacted = set()
        stack = [self.rule_id]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            if curr in children_map:
                for ch in children_map[curr]:
                    impacted.add(ch)
                    stack.append(ch)
        self.impact_text.setPlainText(f"Impacted descendant rule IDs: {sorted(impacted)}")


###############################################################################
# Scheduling
###############################################################################
class RuleSchedulerDialog(QDialog):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.setWindowTitle("Schedule Rule Execution")
        self.resize(400,200)

        lay = QVBoxLayout(self)
        frm = QFormLayout()

        self.rule_combo = QComboBox()
        c = self.connection.cursor()
        c.execute("SELECT RULE_ID, RULE_NAME FROM BRM_RULES ORDER BY RULE_ID")
        for row in get_cursor_rows(c):
            self.rule_combo.addItem(f"{row['RULE_ID']} - {row['RULE_NAME']}", row["RULE_ID"])
        frm.addRow("Select Rule:", self.rule_combo)

        self.dt_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        frm.addRow("Schedule Time:", self.dt_edit)

        lay.addLayout(frm)

        bh = QHBoxLayout()
        sb = QPushButton("Schedule")
        sb.clicked.connect(self.schedule_rule)
        bh.addWidget(sb)
        cb = QPushButton("Close")
        cb.clicked.connect(self.close)
        bh.addWidget(cb)
        lay.addLayout(bh)
        self.setLayout(lay)

    def schedule_rule(self):
        rid = self.rule_combo.currentData()
        dt = self.dt_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        c = self.connection.cursor()
        c.execute("""
        INSERT INTO RULE_SCHEDULES(RULE_ID, SCHEDULE_TIME, STATUS, CREATED_TIMESTAMP)
        VALUES(?,?,'Scheduled',CURRENT_TIMESTAMP)
        """,(rid, dt))
        self.connection.commit()
        QMessageBox.information(self,"Scheduled",f"Rule {rid} scheduled for {dt}.")


class ScheduleManagementTab(QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection

        lay = QVBoxLayout(self)
        self.tbl = QTableWidget(0,4)
        self.tbl.setHorizontalHeaderLabels(["Schedule ID","Rule ID","Schedule Time","Status"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.tbl)

        bh = QHBoxLayout()
        rb = QPushButton("Refresh Schedules")
        rb.clicked.connect(self.load_schedules)
        bh.addWidget(rb)
        lay.addLayout(bh)

        self.setLayout(lay)
        self.load_schedules()

    def load_schedules(self):
        c = self.connection.cursor()
        c.execute("""
        SELECT SCHEDULE_ID, RULE_ID, SCHEDULE_TIME, STATUS
        FROM RULE_SCHEDULES
        ORDER BY SCHEDULE_TIME DESC
        OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY
        """)
        rows = get_cursor_rows(c)
        self.tbl.setRowCount(0)
        for row in rows:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r,0,QTableWidgetItem(str(row["SCHEDULE_ID"])))
            self.tbl.setItem(r,1,QTableWidgetItem(str(row["RULE_ID"])))
            self.tbl.setItem(r,2,QTableWidgetItem(str(row["SCHEDULE_TIME"])))
            self.tbl.setItem(r,3,QTableWidgetItem(row["STATUS"]))


###############################################################################
# Metrics Dashboard
###############################################################################
class MetricsDashboardTab(QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection

        lay = QVBoxLayout(self)
        self.chart = pg.PlotWidget(title="Rule Counts by Status")
        self.chart.setBackground('w')
        lay.addWidget(self.chart)

        rb = QPushButton("Refresh Metrics")
        rb.clicked.connect(self.load_metrics)
        lay.addWidget(rb)
        self.setLayout(lay)
        self.load_metrics()

    def load_metrics(self):
        c = self.connection.cursor()
        c.execute("SELECT STATUS, COUNT(*) as count FROM BRM_RULES GROUP BY STATUS")
        rows = get_cursor_rows(c)
        statuses = [r["STATUS"] for r in rows]
        counts = [r["count"] for r in rows]

        self.chart.clear()
        if statuses:
            x = list(range(len(statuses)))
            bar_item = pg.BarGraphItem(x=x, height=counts, width=0.6, brush="skyblue")
            self.chart.addItem(bar_item)
            self.chart.getAxis("bottom").setTicks([list(zip(x, statuses))])
            self.chart.setLabel("left","Count")
            self.chart.setLabel("bottom","Status")
            self.chart.showGrid(x=True,y=True)


###############################################################################
# Metadata Sync Stub
###############################################################################
def sync_metadata(connection):
    logger.info("Syncing metadata stub...")
    QMessageBox.information(None,"Sync Metadata","Metadata sync completed.")


###############################################################################
# Login Dialog
###############################################################################
class LoginDialog(QDialog):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.user_id = None
        self.user_group = None

        self.setWindowTitle("Login")
        self.setFixedSize(300,200)
        lay = QVBoxLayout(self)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Username")
        lay.addWidget(QLabel("Username:"))
        lay.addWidget(self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setPlaceholderText("Password")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        lay.addWidget(QLabel("Password:"))
        lay.addWidget(self.pass_edit)

        btn = QPushButton("Login")
        btn.clicked.connect(self.do_login)
        lay.addWidget(btn)

        self.setLayout(lay)

    def do_login(self):
        usern = self.user_edit.text().strip()
        passw = self.pass_edit.text().strip()
        if not usern or not passw:
            QMessageBox.warning(self,"Error","Enter username/password.")
            return
        c = self.connection.cursor()
        c.execute("SELECT USER_ID, USER_GROUP FROM USERS WHERE USERNAME=? AND PASSWORD=?", (usern, passw))
        row = get_cursor_one(c)
        if row:
            self.user_id = row["USER_ID"]
            self.user_group = row["USER_GROUP"]
            self.accept()
        else:
            QMessageBox.warning(self,"Login Failed","Invalid username or password.")


###############################################################################
# Rule Editor
###############################################################################
class RuleEditorDialog(QDialog):
    def __init__(self, connection, rule_types, logged_in_user, rule_data=None, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.rule_types = rule_types
        self.logged_in_user = logged_in_user
        self.rule_data = rule_data

        title = "Edit Rule" if rule_data else "Add New Rule"
        self.setWindowTitle(title)
        self.resize(900,500)

        mh = QHBoxLayout(self)

        left_box = QGroupBox("Basic Info")
        left_lay = QFormLayout(left_box)

        self.group_combo = QComboBox()
        c = self.connection.cursor()
        c.execute("SELECT GROUP_ID, GROUP_NAME FROM BRM_RULE_GROUPS ORDER BY GROUP_NAME")
        for r in get_cursor_rows(c):
            self.group_combo.addItem(r["GROUP_NAME"], r["GROUP_ID"])
        left_lay.addRow("Rule Group:", self.group_combo)

        self.parent_rule_combo = QComboBox()
        self.parent_rule_combo.addItem("None", None)
        c.execute("SELECT RULE_ID, RULE_NAME FROM BRM_RULES WHERE STATUS='ACTIVE'")
        for rr in get_cursor_rows(c):
            self.parent_rule_combo.addItem(f"{rr['RULE_NAME']} (ID:{rr['RULE_ID']})", rr["RULE_ID"])
        left_lay.addRow("Parent Rule:", self.parent_rule_combo)

        self.name_edit = QLineEdit()
        left_lay.addRow("Rule Name:", self.name_edit)

        self.type_combo = QComboBox()
        for nm in self.rule_types:
            self.type_combo.addItem(nm)
        left_lay.addRow("Rule Type:", self.type_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["ACTIVE","INACTIVE"])
        left_lay.addRow("Status (info):", self.status_combo)

        self.start_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_dt.setCalendarPopup(True)
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        left_lay.addRow("Start Date:", self.start_dt)

        self.end_dt = QDateTimeEdit(QDateTime.currentDateTime().addDays(30))
        self.end_dt.setCalendarPopup(True)
        self.end_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        left_lay.addRow("End Date:", self.end_dt)

        self.owner_grp_combo = QComboBox()
        c.execute("SELECT DISTINCT GROUP_NAME FROM BUSINESS_GROUPS ORDER BY GROUP_NAME")
        for g in get_cursor_rows(c):
            self.owner_grp_combo.addItem(g["GROUP_NAME"], g["GROUP_NAME"])
        left_lay.addRow("Owner Group:", self.owner_grp_combo)

        self.global_checkbox = None
        if self.logged_in_user=="Admin":
            self.global_checkbox = QCheckBox("Global (admin-only)")
            left_lay.addRow("Global:", self.global_checkbox)

        self.critical_checkbox = QCheckBox()
        left_lay.addRow("Critical Rule?", self.critical_checkbox)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["NONE","GROUP","CLUSTER","GLOBAL"])
        left_lay.addRow("Critical Scope:", self.scope_combo)

        self.cdc_combo = QComboBox()
        self.cdc_combo.addItems(["NONE","FULL_LOAD","INCREMENTAL","INSERT_ONLY","UPSERT"])
        left_lay.addRow("CDC Type:", self.cdc_combo)

        mh.addWidget(left_box)

        right_box = QGroupBox("Details & Logic")
        right_lay = QFormLayout(right_box)

        self.sql_editor = QPlainTextEdit()
        font = QtGui.QFont("Courier",10)
        self.sql_editor.setFont(font)
        right_lay.addRow(QLabel("Rule SQL:"), self.sql_editor)

        self.desc_edit = QTextEdit()
        right_lay.addRow(QLabel("Description:"), self.desc_edit)

        self.just_edit = QTextEdit()
        right_lay.addRow(QLabel("Justification:"), self.just_edit)

        b_h = QHBoxLayout()
        self.save_btn = QPushButton("Save" if rule_data else "Add")
        self.save_btn.clicked.connect(self.on_save)
        b_h.addWidget(self.save_btn)
        c_btn = QPushButton("Cancel")
        c_btn.clicked.connect(self.reject)
        b_h.addWidget(c_btn)
        right_lay.addRow(b_h)

        mh.addWidget(right_box)
        self.setLayout(mh)

        if self.rule_data:
            self.load_rule_data()

    def load_rule_data(self):
        rd = self.rule_data
        if rd["GROUP_ID"]:
            idx = self.group_combo.findData(rd["GROUP_ID"])
            if idx>=0:
                self.group_combo.setCurrentIndex(idx)
        if rd["PARENT_RULE_ID"]:
            idx2 = self.parent_rule_combo.findData(rd["PARENT_RULE_ID"])
            if idx2>=0:
                self.parent_rule_combo.setCurrentIndex(idx2)

        self.name_edit.setText(rd["RULE_NAME"])
        for nm,tid in self.rule_types.items():
            if tid==rd["RULE_TYPE_ID"]:
                i = self.type_combo.findText(nm)
                if i>=0:
                    self.type_combo.setCurrentIndex(i)
                break

        i_st = self.status_combo.findText(rd["STATUS"])
        if i_st>=0:
            self.status_combo.setCurrentIndex(i_st)

        try:
            sdt = datetime.strptime(rd["EFFECTIVE_START_DATE"],"%Y-%m-%d %H:%M:%S")
            self.start_dt.setDateTime(QtCore.QDateTime(sdt))
        except:
            pass
        if rd["EFFECTIVE_END_DATE"]:
            try:
                edt = datetime.strptime(rd["EFFECTIVE_END_DATE"],"%Y-%m-%d %H:%M:%S")
                self.end_dt.setDateTime(QtCore.QDateTime(edt))
            except:
                pass

        iog = self.owner_grp_combo.findText(rd["OWNER_GROUP"])
        if iog>=0:
            self.owner_grp_combo.setCurrentIndex(iog)

        self.sql_editor.setPlainText(rd.get("RULE_SQL",""))
        if rd.get("DESCRIPTION"):
            self.desc_edit.setText(rd["DESCRIPTION"])
        if rd.get("BUSINESS_JUSTIFICATION"):
            self.just_edit.setText(rd["BUSINESS_JUSTIFICATION"])
        if self.global_checkbox and rd.get("IS_GLOBAL",0)==1:
            self.global_checkbox.setChecked(True)
        if rd.get("CRITICAL_RULE",0)==1:
            self.critical_checkbox.setChecked(True)
        cscope = rd.get("CRITICAL_SCOPE","NONE").upper()
        idx3 = self.scope_combo.findText(cscope)
        if idx3>=0:
            self.scope_combo.setCurrentIndex(idx3)
        cdcv = rd.get("CDC_TYPE","NONE").upper()
        idx4 = self.cdc_combo.findText(cdcv)
        if idx4>=0:
            self.cdc_combo.setCurrentIndex(idx4)

    def on_save(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self,"Error","Rule name is empty.")
            return
        sql_txt = self.sql_editor.toPlainText().strip()
        if not sql_txt:
            QMessageBox.warning(self,"Error","SQL is empty.")
            return
        op_type = get_op_type_from_sql(sql_txt)
        data = {
            "GROUP_ID": self.group_combo.currentData(),
            "PARENT_RULE_ID": self.parent_rule_combo.currentData(),
            "RULE_TYPE_ID": self.rule_types.get(self.type_combo.currentText()),
            "RULE_NAME": self.name_edit.text().strip(),
            "RULE_SQL": sql_txt,
            "EFFECTIVE_START_DATE": self.start_dt.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            "EFFECTIVE_END_DATE": self.end_dt.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            "STATUS": self.status_combo.currentText(),
            "DESCRIPTION": self.desc_edit.toPlainText().strip(),
            "OPERATION_TYPE": op_type,
            "BUSINESS_JUSTIFICATION": self.just_edit.toPlainText().strip(),
            "OWNER_GROUP": self.owner_grp_combo.currentText().strip(),
            "IS_GLOBAL": 1 if (self.global_checkbox and self.global_checkbox.isChecked()) else 0,
            "CRITICAL_RULE": 1 if self.critical_checkbox.isChecked() else 0,
            "CRITICAL_SCOPE": self.scope_combo.currentText().upper(),
            "CDC_TYPE": self.cdc_combo.currentText().upper()
        }
        created_by = self.logged_in_user
        if self.rule_data:
            data["RULE_ID"] = self.rule_data["RULE_ID"]
            if QMessageBox.question(self,"Confirm","Update rule?")!=QMessageBox.Yes:
                return
            try:
                update_rule(self.connection, data, created_by, self.logged_in_user)
                QMessageBox.information(self,"Success","Rule updated (re-approval triggered).")
                self.accept()
            except Exception as ex:
                QMessageBox.critical(self,"DB Error",str(ex))
        else:
            if QMessageBox.question(self,"Confirm","Add new rule?")!=QMessageBox.Yes:
                return
            try:
                new_id = add_rule(self.connection, data, created_by, self.logged_in_user)
                QMessageBox.information(self,"Success",f"Rule created (ID={new_id}). Approval in progress.")
                self.accept()
            except Exception as ex:
                QMessageBox.critical(self,"DB Error",str(ex))


###############################################################################
# Rule Analytics
###############################################################################
class RuleAnalyticsDialog(QDialog):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.setWindowTitle("Rule Analytics")
        self.resize(800,600)

        lay = QVBoxLayout(self)
        chart_hbox = QHBoxLayout()

        self.bar_chart = pg.PlotWidget(title="Number of Rules by Creator")
        self.bar_chart.setBackground('w')
        chart_hbox.addWidget(self.bar_chart)

        self.pie_chart = pg.PlotWidget(title="Rule Status Distribution")
        self.pie_chart.setBackground('w')
        chart_hbox.addWidget(self.pie_chart)

        lay.addLayout(chart_hbox)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)
        self.setLayout(lay)
        self.load_charts()

    def load_charts(self):
        c = self.connection.cursor()
        query_bar = "SELECT CREATED_BY, COUNT(*) as cnt FROM BRM_RULES GROUP BY CREATED_BY"
        c.execute(query_bar)
        rows = get_cursor_rows(c)
        creators = {r["CREATED_BY"]: r["cnt"] for r in rows if r["CREATED_BY"]}

        status_counts = {"ACTIVE":0, "INACTIVE":0, "DELETED":0}
        c.execute("SELECT STATUS, COUNT(*) as sc FROM BRM_RULES GROUP BY STATUS")
        for s_ in get_cursor_rows(c):
            key = s_["STATUS"].upper()
            if key in status_counts:
                status_counts[key] = s_["sc"]
        c.execute("SELECT COUNT(*) as delcnt FROM BRM_AUDIT_LOG WHERE ACTION='DELETE'")
        drow = get_cursor_one(c)
        if drow:
            status_counts["DELETED"] = drow["delcnt"]

        # bar
        self.bar_chart.clear()
        if creators:
            sorted_creators = sorted(creators.items(), key=lambda x:x[1], reverse=True)
            names = [x[0] for x in sorted_creators]
            vals = [x[1] for x in sorted_creators]
            bar_item = pg.BarGraphItem(x=range(len(names)), height=vals, width=0.6, brush="skyblue")
            self.bar_chart.addItem(bar_item)
            ax = self.bar_chart.getAxis("bottom")
            ax.setTicks([list(zip(range(len(names)), names))])
            self.bar_chart.setLabel("left","Number of Rules")
            self.bar_chart.setLabel("bottom","Created By")
            self.bar_chart.showGrid(x=True,y=True)

        # pie chart placeholder
        self.pie_chart.clear()
        # For a real pie chart in pyqtgraph, you'd do custom arcs or a separate library.


###############################################################################
# Audit Log Viewer
###############################################################################
class AuditLogViewer(QDialog):
    def __init__(self, connection, user_group, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.user_group = user_group
        self.setWindowTitle("Audit Logs")
        self.resize(800,600)

        lay = QVBoxLayout(self)
        top_h = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search action/table/actor ...")
        self.search_edit.textChanged.connect(self.perform_search)
        top_h.addWidget(QLabel("Search:"))
        top_h.addWidget(self.search_edit)
        lay.addLayout(top_h)

        self.audit_table = QTableWidget(0,8)
        self.audit_table.setHorizontalHeaderLabels(
            ["Audit ID","Action","Table","Record ID","Action By","Old Data","New Data","Timestamp"]
        )
        self.audit_table.horizontalHeader().setStretchLastSection(True)
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.audit_table)

        bh = QHBoxLayout()
        refb = QPushButton("Refresh Logs")
        refb.clicked.connect(self.load_logs)
        bh.addWidget(refb)
        expb = QPushButton("Export to CSV")
        expb.clicked.connect(self.export_csv)
        bh.addWidget(expb)
        lay.addLayout(bh)

        self.setLayout(lay)
        self.load_logs()

    def load_logs(self):
        c = self.connection.cursor()
        c.execute("""
        SELECT AUDIT_ID, ACTION, TABLE_NAME, RECORD_ID, ACTION_BY, OLD_DATA, NEW_DATA, ACTION_TIMESTAMP
        FROM BRM_AUDIT_LOG
        ORDER BY ACTION_TIMESTAMP DESC
        OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY
        """)
        rows = get_cursor_rows(c)
        self.audit_table.setRowCount(0)
        for row in rows:
            r = self.audit_table.rowCount()
            self.audit_table.insertRow(r)
            self.audit_table.setItem(r,0,QTableWidgetItem(str(row["AUDIT_ID"])))
            self.audit_table.setItem(r,1,QTableWidgetItem(row["ACTION"]))
            self.audit_table.setItem(r,2,QTableWidgetItem(row["TABLE_NAME"]))
            self.audit_table.setItem(r,3,QTableWidgetItem(row["RECORD_ID"]))
            self.audit_table.setItem(r,4,QTableWidgetItem(row["ACTION_BY"]))

            oldtxt = ""
            if row["OLD_DATA"]:
                try:
                    p = json.loads(row["OLD_DATA"])
                    oldtxt = json.dumps(p, indent=2)
                except:
                    oldtxt = row["OLD_DATA"]
            self.audit_table.setItem(r,5,QTableWidgetItem(oldtxt))

            newtxt = ""
            if row["NEW_DATA"]:
                try:
                    p2 = json.loads(row["NEW_DATA"])
                    newtxt = json.dumps(p2, indent=2)
                except:
                    newtxt = row["NEW_DATA"]
            self.audit_table.setItem(r,6,QTableWidgetItem(newtxt))

            self.audit_table.setItem(r,7,QTableWidgetItem(str(row["ACTION_TIMESTAMP"])))

    def perform_search(self, txt):
        txt_l = txt.lower()
        for row in range(self.audit_table.rowCount()):
            show = False
            # search action (col=1), table=2, actor=4
            for col in (1,2,4):
                it = self.audit_table.item(row,col)
                if it and txt_l in it.text().lower():
                    show = True
                    break
            self.audit_table.setRowHidden(row, not show)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self,"Save CSV","","CSV Files (*.csv)")
        if not path:
            return
        with open(path,"w",newline="") as f:
            writer = csv.writer(f)
            headers = [self.audit_table.horizontalHeaderItem(i).text()
                       for i in range(self.audit_table.columnCount())]
            writer.writerow(headers)
            for row in range(self.audit_table.rowCount()):
                if self.audit_table.isRowHidden(row):
                    continue
                rowdata=[]
                for col in range(self.audit_table.columnCount()):
                    it = self.audit_table.item(row,col)
                    rowdata.append(it.text() if it else "")
                writer.writerow(rowdata)
        QMessageBox.information(self,"Exported","Audit logs exported.")


###############################################################################
# Search Rule Dialog
###############################################################################
class SearchRuleDialog(QDialog):
    def __init__(self, connection, user_group, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.user_group = user_group
        self.setWindowTitle("Search Rules")
        self.resize(800,600)

        lay = QVBoxLayout(self)
        top_h = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Enter name or snippet...")
        self.search_edit.textChanged.connect(self.load_results)

        top_h.addWidget(QLabel("Search:"))
        top_h.addWidget(self.search_edit)
        lay.addLayout(top_h)

        self.res_table = QTableWidget(0,6)
        self.res_table.setHorizontalHeaderLabels(["Rule ID","Name","SQL","Status","Version","Created By"])
        self.res_table.horizontalHeader().setStretchLastSection(True)
        self.res_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.res_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.res_table)

        rb = QPushButton("Refresh")
        rb.clicked.connect(self.load_results)
        lay.addWidget(rb)
        self.setLayout(lay)
        self.load_results()

    def load_results(self):
        c = self.connection.cursor()
        txt = self.search_edit.text().strip()
        if txt:
            c.execute("""
            SELECT RULE_ID, RULE_NAME, RULE_SQL, STATUS, VERSION, CREATED_BY
            FROM BRM_RULES
            WHERE RULE_NAME LIKE ? OR RULE_SQL LIKE ?
            ORDER BY RULE_ID DESC
            OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY
            """,(f"%{txt}%", f"%{txt}%"))
        else:
            c.execute("""
            SELECT RULE_ID, RULE_NAME, RULE_SQL, STATUS, VERSION, CREATED_BY
            FROM BRM_RULES
            ORDER BY RULE_ID DESC
            OFFSET 0 ROWS FETCH NEXT 1000 ROWS ONLY
            """)
        rows = get_cursor_rows(c)
        self.res_table.setRowCount(0)
        for row in rows:
            r = self.res_table.rowCount()
            self.res_table.insertRow(r)
            self.res_table.setItem(r,0,QTableWidgetItem(str(row["RULE_ID"])))
            self.res_table.setItem(r,1,QTableWidgetItem(row["RULE_NAME"]))
            self.res_table.setItem(r,2,QTableWidgetItem(row["RULE_SQL"]))
            self.res_table.setItem(r,3,QTableWidgetItem(row["STATUS"]))
            self.res_table.setItem(r,4,QTableWidgetItem(str(row["VERSION"])))
            self.res_table.setItem(r,5,QTableWidgetItem(row["CREATED_BY"]))


###############################################################################
# Rule Dashboard
###############################################################################
class RuleDashboard(QGroupBox):
    def __init__(self, connection, user_id, user_group, parent=None):
        super().__init__("Rule Dashboard", parent)
        self.connection = connection
        self.user_id = user_id
        self.user_group = user_group
        self.selected_rule_id = None
        self.current_page = 1
        self.records_per_page = 50
        self.total_pages = 1

        main_layout = QVBoxLayout(self)

        top_h = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name or SQL...")
        top_h.addWidget(QLabel("Search:"))
        top_h.addWidget(self.search_edit)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All Statuses", None)
        self.status_filter.addItem("ACTIVE","ACTIVE")
        self.status_filter.addItem("INACTIVE","INACTIVE")
        self.status_filter.addItem("DELETED","DELETED")
        top_h.addWidget(QLabel("Status:"))
        top_h.addWidget(self.status_filter)

        main_layout.addLayout(top_h)

        self.rule_table = QTableWidget(0,8)
        self.rule_table.setHorizontalHeaderLabels([
            "Rule ID","Name","SQL","Status","Version","Owner Group",
            "Created Timestamp","Approval Status"
        ])
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rule_table.itemSelectionChanged.connect(self.update_selected_rule_id)
        main_layout.addWidget(self.rule_table)

        nav_h = QHBoxLayout()
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        self.page_label = QLabel("Page 1/1")
        nav_h.addWidget(self.prev_btn)
        nav_h.addWidget(self.page_label)
        nav_h.addWidget(self.next_btn)
        main_layout.addLayout(nav_h)

        btn_h = QHBoxLayout()
        ref_btn = QPushButton("Refresh")
        ref_btn.clicked.connect(self.load_rules)
        btn_h.addWidget(ref_btn)

        run_etl_btn = QPushButton("Run ETL (Execute Rules)")
        run_etl_btn.clicked.connect(self.run_etl)
        btn_h.addWidget(run_etl_btn)

        analytics_btn = QPushButton("Rule Analytics")
        analytics_btn.clicked.connect(self.show_analytics)
        btn_h.addWidget(analytics_btn)

        simulate_btn = QPushButton("Simulate Rule")
        simulate_btn.clicked.connect(self.simulate_rule)
        btn_h.addWidget(simulate_btn)

        impact_btn = QPushButton("Impact Analysis")
        impact_btn.clicked.connect(self.analyze_impact)
        btn_h.addWidget(impact_btn)

        history_btn = QPushButton("Version History")
        history_btn.clicked.connect(self.show_history)
        btn_h.addWidget(history_btn)

        btn_h.addStretch()
        main_layout.addLayout(btn_h)

        self.setLayout(main_layout)

        self.search_edit.textChanged.connect(self.load_rules)
        self.status_filter.currentIndexChanged.connect(self.load_rules)
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)
        self.load_rules()

    def run_etl(self):
        exe, skip = execute_rules_in_order(self.connection)
        msg = f"ETL done.\nExecuted: {exe}\nSkipped: {list(skip)}"
        QMessageBox.information(self,"ETL",msg)
        self.load_rules()

    def show_analytics(self):
        dlg = RuleAnalyticsDialog(self.connection,self)
        dlg.exec_()

    def build_filter_query(self):
        fs = []
        ps = []
        txt = self.search_edit.text().strip()
        if txt:
            fs.append("(RULE_NAME LIKE ? OR RULE_SQL LIKE ?)")
            ps.extend([f"%{txt}%", f"%{txt}%"])
        st = self.status_filter.currentData()
        if st:
            if st.upper()=="DELETED":
                fs.append("""RULE_ID IN (
                    SELECT CAST(RECORD_ID as int)
                    FROM BRM_AUDIT_LOG
                    WHERE ACTION='DELETE'
                      AND ISNUMERIC(RECORD_ID)=1
                )""")
            else:
                fs.append("STATUS=?")
                ps.append(st)
        clause = " AND ".join(fs) if fs else "1=1"
        return clause, ps

    def load_rules(self):
        c = self.connection.cursor()
        clause,params = self.build_filter_query()

        count_q = f"SELECT COUNT(*) as ccount FROM BRM_RULES WHERE {clause}"
        c.execute(count_q, params)
        rowc = get_cursor_one(c)
        total = rowc["ccount"] if rowc else 0
        self.total_pages = max(1, math.ceil(total/self.records_per_page))
        if self.current_page>self.total_pages:
            self.current_page=self.total_pages
        elif self.current_page<1:
            self.current_page=1
        self.page_label.setText(f"Page {self.current_page}/{self.total_pages}")
        offset = (self.current_page-1)*self.records_per_page

        data_q = f"""
        SELECT RULE_ID, RULE_NAME, RULE_SQL, STATUS, VERSION, OWNER_GROUP,
               CREATED_TIMESTAMP, APPROVAL_STATUS
        FROM BRM_RULES
        WHERE {clause}
        ORDER BY RULE_ID DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        c.execute(data_q, (*params, offset, self.records_per_page))
        rows = get_cursor_rows(c)
        self.rule_table.setRowCount(0)
        for rd in rows:
            r = self.rule_table.rowCount()
            self.rule_table.insertRow(r)
            self.rule_table.setItem(r,0,QTableWidgetItem(str(rd["RULE_ID"])))
            self.rule_table.setItem(r,1,QTableWidgetItem(rd["RULE_NAME"]))
            self.rule_table.setItem(r,2,QTableWidgetItem(rd["RULE_SQL"]))

            st_item = QTableWidgetItem(rd["STATUS"])
            if rd["STATUS"].lower()=="active":
                st_item.setBackground(QColor(144,238,144))
            else:
                st_item.setBackground(QColor(255,182,193))
            self.rule_table.setItem(r,3,st_item)

            self.rule_table.setItem(r,4,QTableWidgetItem(str(rd["VERSION"])))
            self.rule_table.setItem(r,5,QTableWidgetItem(rd["OWNER_GROUP"]))
            self.rule_table.setItem(r,6,QTableWidgetItem(str(rd["CREATED_TIMESTAMP"])))
            self.rule_table.setItem(r,7,QTableWidgetItem(rd["APPROVAL_STATUS"]))

    def update_selected_rule_id(self):
        sel = self.rule_table.selectedItems()
        if not sel:
            self.selected_rule_id=None
            return
        row = sel[0].row()
        it = self.rule_table.item(row,0)
        if it:
            self.selected_rule_id = int(it.text())

    def get_selected_rule_ids(self):
        idxs = self.rule_table.selectionModel().selectedRows()
        rids=[]
        for i in idxs:
            row=i.row()
            it=self.rule_table.item(row,0)
            if it:
                rids.append(int(it.text()))
        return rids

    def prev_page(self):
        if self.current_page>1:
            self.current_page-=1
            self.load_rules()

    def next_page(self):
        if self.current_page<self.total_pages:
            self.current_page+=1
            self.load_rules()

    def simulate_rule(self):
        if not self.selected_rule_id:
            QMessageBox.warning(self,"No Selection","Select a rule first.")
            return
        c = self.connection.cursor()
        c.execute("SELECT RULE_SQL FROM BRM_RULES WHERE RULE_ID=?", (self.selected_rule_id,))
        row = get_cursor_one(c)
        if not row:
            QMessageBox.warning(self,"Not Found","No rule with that ID.")
            return
        dlg = RuleSimulationDialog(self.connection, row["RULE_SQL"], self)
        dlg.exec_()

    def analyze_impact(self):
        if not self.selected_rule_id:
            QMessageBox.warning(self,"No Selection","Select a rule first.")
            return
        dlg = ImpactAnalysisDialog(self.connection, self.selected_rule_id, self)
        dlg.exec_()

    def show_history(self):
        if not self.selected_rule_id:
            QMessageBox.warning(self,"No Selection","Select a rule.")
            return
        dlg = VersionHistoryDialog(self.connection, self.selected_rule_id, self)
        dlg.exec_()


###############################################################################
# Business Rule Management Tab
###############################################################################
class BusinessRuleManagementTab(QWidget):
    def __init__(self, main_app, connection, user_id, user_group, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.connection = connection
        self.user_id = user_id
        self.user_group = user_group

        layout = QVBoxLayout(self)
        bh = QHBoxLayout()

        add_btn = QPushButton("Add Rule")
        add_btn.clicked.connect(self.on_add_rule)
        bh.addWidget(add_btn)

        upd_btn = QPushButton("Update Rule")
        upd_btn.clicked.connect(self.on_update_rule)
        bh.addWidget(upd_btn)

        dact_btn = QPushButton("Deactivate Selected")
        dact_btn.clicked.connect(self.on_deactivate_rules)
        bh.addWidget(dact_btn)

        del_btn = QPushButton("Delete Rule")
        del_btn.clicked.connect(self.on_delete_rule)
        bh.addWidget(del_btn)

        aud_btn = QPushButton("View Audit Logs")
        aud_btn.clicked.connect(self.main_app.launch_audit_log_viewer)
        bh.addWidget(aud_btn)

        sr_btn = QPushButton("Search Rules")
        sr_btn.clicked.connect(self.main_app.launch_search_rule_dialog)
        bh.addWidget(sr_btn)

        bh.addStretch()
        layout.addLayout(bh)

        self.rule_dash = RuleDashboard(self.connection, self.user_id, self.user_group)
        layout.addWidget(self.rule_dash)
        layout.addStretch()
        self.setLayout(layout)

    def on_add_rule(self):
        rtypes = self.main_app.get_rule_types()
        dlg = RuleEditorDialog(self.connection, rtypes, self.user_group, parent=self)
        if dlg.exec_()==QDialog.Accepted:
            self.rule_dash.load_rules()

    def on_update_rule(self):
        rid = self.rule_dash.selected_rule_id
        if not rid:
            QMessageBox.warning(self,"No Selection","Select a rule.")
            return
        c = self.connection.cursor()
        c.execute("SELECT * FROM BRM_RULES WHERE RULE_ID=?", (rid,))
        row = get_cursor_one(c)
        if not row:
            QMessageBox.warning(self,"Not Found","No rule with that ID.")
            return
        data = dict(row)
        rtypes = self.main_app.get_rule_types()
        dlg = RuleEditorDialog(self.connection, rtypes, self.user_group, data, self)
        if dlg.exec_()==QDialog.Accepted:
            self.rule_dash.load_rules()

    def on_deactivate_rules(self):
        rids = self.rule_dash.get_selected_rule_ids()
        if not rids:
            QMessageBox.warning(self,"None","No rules selected.")
            return
        suc=0
        fails=[]
        for rr in rids:
            try:
                deactivate_rule(self.connection, rr, self.user_group, self.user_group)
                suc+=1
            except Exception as ex:
                fails.append(f"Rule {rr}: {str(ex)}")
        msg = f"Deactivation done. Success={suc}"
        if fails:
            msg+= "\nFails:\n"+"\n".join(fails)
        QMessageBox.information(self,"Deactivate",msg)
        self.rule_dash.load_rules()

    def on_delete_rule(self):
        rids = self.rule_dash.get_selected_rule_ids()
        if not rids:
            QMessageBox.warning(self,"None","No rule(s) selected.")
            return
        if QMessageBox.question(self,"Confirm",f"Delete {len(rids)} rule(s)?")!=QMessageBox.Yes:
            return
        suc=0
        fails=[]
        for rid in rids:
            try:
                delete_rule(self.connection, rid, self.user_group, self.user_group)
                suc+=1
            except Exception as ex:
                fails.append(f"Rule {rid}: {ex}")
        msg = f"Deletion done. Success={suc}"
        if fails:
            msg+= "\nFails:\n"+"\n".join(fails)
        QMessageBox.information(self,"Delete",msg)
        self.rule_dash.load_rules()


###############################################################################
# Group Management Tab
###############################################################################
class GroupManagementTab(QWidget):
    def __init__(self, main_app, connection, user_id, user_group, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.connection = connection
        self.user_id = user_id
        self.user_group = user_group

        if user_group!="Admin":
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("Access Denied: Admin Only."))
            self.setLayout(lay)
            return

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # groups & membership
        gm_tab = QWidget()
        gm_layout = QVBoxLayout(gm_tab)

        grp_box = QGroupBox("Group Details")
        grp_lay = QVBoxLayout(grp_box)
        self.groups_table = QTableWidget(0,3)
        self.groups_table.setHorizontalHeaderLabels(["Group Name","Description","Email"])
        self.groups_table.horizontalHeader().setStretchLastSection(True)
        grp_lay.addWidget(self.groups_table)

        btn_h = QHBoxLayout()
        add_grp_btn = QPushButton("Add Group")
        add_grp_btn.clicked.connect(self.on_add_group)
        btn_h.addWidget(add_grp_btn)

        ren_grp_btn = QPushButton("Rename Group")
        ren_grp_btn.clicked.connect(self.on_rename_group)
        btn_h.addWidget(ren_grp_btn)

        del_grp_btn = QPushButton("Delete Group")
        del_grp_btn.clicked.connect(self.on_delete_group)
        btn_h.addWidget(del_grp_btn)

        btn_h.addStretch()
        grp_lay.addLayout(btn_h)
        gm_layout.addWidget(grp_box)

        membership_box = QGroupBox("Membership Management")
        membership_lay = QVBoxLayout(membership_box)
        self.users_table = QTableWidget(0,3)
        self.users_table.setHorizontalHeaderLabels(["User ID","Username","Group"])
        self.users_table.horizontalHeader().setStretchLastSection(True)
        membership_lay.addWidget(self.users_table)

        memb_bh = QHBoxLayout()
        add_usr_btn = QPushButton("Add User to Group")
        add_usr_btn.clicked.connect(self.on_add_user_to_group)
        memb_bh.addWidget(add_usr_btn)

        rem_usr_btn = QPushButton("Remove User from Group")
        rem_usr_btn.clicked.connect(self.on_remove_user_from_group)
        memb_bh.addWidget(rem_usr_btn)

        memb_bh.addStretch()
        membership_lay.addLayout(memb_bh)
        gm_layout.addWidget(membership_box)

        self.tabs.addTab(gm_tab,"Groups & Membership")

        # minimal user permissions or approvers could go here if desired

        ref_b = QPushButton("Refresh")
        ref_b.clicked.connect(self.load_data)
        layout.addWidget(ref_b)

        self.setLayout(layout)
        self.load_data()

    def load_data(self):
        self.load_groups()
        self.load_users()

    def load_groups(self):
        c = self.connection.cursor()
        c.execute("SELECT GROUP_NAME, DESCRIPTION, EMAIL FROM BUSINESS_GROUPS ORDER BY GROUP_NAME")
        rows = c.fetchall()
        self.groups_table.setRowCount(0)
        for row in rows:
            r = self.groups_table.rowCount()
            self.groups_table.insertRow(r)
            self.groups_table.setItem(r,0,QTableWidgetItem(row[0]))
            self.groups_table.setItem(r,1,QTableWidgetItem(row[1] or ""))
            self.groups_table.setItem(r,2,QTableWidgetItem(row[2] or ""))

    def load_users(self):
        c = self.connection.cursor()
        c.execute("SELECT USER_ID, USERNAME, USER_GROUP FROM USERS ORDER BY USER_ID")
        rows = c.fetchall()
        self.users_table.setRowCount(0)
        for row in rows:
            r = self.users_table.rowCount()
            self.users_table.insertRow(r)
            self.users_table.setItem(r,0,QTableWidgetItem(str(row[0])))
            self.users_table.setItem(r,1,QTableWidgetItem(row[1]))
            self.users_table.setItem(r,2,QTableWidgetItem(row[2]))

    def get_selected_group(self):
        i = self.groups_table.currentRow()
        if i<0:
            return None
        it = self.groups_table.item(i,0)
        return it.text().strip() if it else None

    def on_add_group(self):
        name, ok = QInputDialog.getText(self,"Add Group","Group Name:")
        if not ok or not name.strip():
            return
        desc, ok2 = QInputDialog.getText(self,"Add Group","Description:")
        if not ok2:
            desc=""
        email, ok3 = QInputDialog.getText(self,"Add Group","Email:")
        if not ok3:
            email=""
        c = self.connection.cursor()
        c.execute("SELECT * FROM BUSINESS_GROUPS WHERE GROUP_NAME=?",(name.strip(),))
        if c.fetchone():
            QMessageBox.warning(self,"Error","Group already exists.")
            return
        c.execute("INSERT INTO BUSINESS_GROUPS(GROUP_NAME,DESCRIPTION,EMAIL) VALUES(?,?,?)",
                  (name.strip(),desc.strip(),email.strip()))
        self.connection.commit()
        QMessageBox.information(self,"Success","Group added.")
        self.load_data()

    def on_rename_group(self):
        grp = self.get_selected_group()
        if not grp:
            QMessageBox.warning(self,"No selection","No group selected.")
            return
        new_name, ok = QInputDialog.getText(self,"Rename Group","New group name:")
        if not ok or not new_name.strip():
            return
        c = self.connection.cursor()
        c.execute("SELECT * FROM BUSINESS_GROUPS WHERE GROUP_NAME=?",(new_name.strip(),))
        if c.fetchone():
            QMessageBox.warning(self,"Error","New group name already exists.")
            return
        try:
            c.execute("BEGIN TRANSACTION")
            c.execute("UPDATE BUSINESS_GROUPS SET GROUP_NAME=? WHERE GROUP_NAME=?", (new_name.strip(), grp))
            c.execute("UPDATE BRM_RULES SET OWNER_GROUP=? WHERE OWNER_GROUP=?", (new_name.strip(), grp))
            c.execute("UPDATE BRM_RULE_GROUPS SET GROUP_NAME=? WHERE GROUP_NAME=?", (new_name.strip(), grp))
            c.execute("COMMIT")
            add_audit_log(self.connection, "RENAME_GROUP", "BUSINESS_GROUPS",
                          grp, "Admin",
                          {"old_group_name": grp},
                          {"new_group_name": new_name.strip()})
            QMessageBox.information(self,"Renamed",f"Renamed {grp} to {new_name}.")
            self.load_data()
        except Exception as ex:
            c.execute("ROLLBACK")
            QMessageBox.critical(self,"Error",str(ex))

    def on_delete_group(self):
        grp = self.get_selected_group()
        if not grp:
            QMessageBox.warning(self,"No selection","No group selected.")
            return
        if QMessageBox.question(self,"Confirm",f"Delete group {grp}?")!=QMessageBox.Yes:
            return
        c = self.connection.cursor()
        try:
            c.execute("DELETE FROM BUSINESS_GROUPS WHERE GROUP_NAME=?",(grp,))
            self.connection.commit()
            QMessageBox.information(self,"Deleted","Group deleted.")
            self.load_data()
        except Exception as ex:
            QMessageBox.critical(self,"Error",str(ex))

    def get_selected_user(self):
        i = self.users_table.currentRow()
        if i<0:
            return None
        it = self.users_table.item(i,0)
        return int(it.text()) if it else None

    def on_add_user_to_group(self):
        uid = self.get_selected_user()
        if not uid:
            QMessageBox.warning(self,"None","No user selected.")
            return
        grp, ok = QInputDialog.getText(self,"Add to Group","Group name:")
        if not ok or not grp.strip():
            return
        c = self.connection.cursor()
        c.execute("SELECT * FROM BUSINESS_GROUPS WHERE GROUP_NAME=?",(grp.strip(),))
        if not c.fetchone():
            QMessageBox.warning(self,"Error","Group not found.")
            return
        c.execute("SELECT USERNAME, USER_GROUP FROM USERS WHERE USER_ID=?",(uid,))
        row = c.fetchone()
        if not row:
            QMessageBox.warning(self,"Error","User not found.")
            return
        if row[1]==grp.strip():
            QMessageBox.warning(self,"Error","User already in that group.")
            return
        c.execute("UPDATE USERS SET USER_GROUP=? WHERE USER_ID=?", (grp.strip(), uid))
        self.connection.commit()
        QMessageBox.information(self,"Success","User added to group.")
        self.load_data()

    def on_remove_user_from_group(self):
        uid = self.get_selected_user()
        if not uid:
            QMessageBox.warning(self,"None","No user.")
            return
        if QMessageBox.question(self,"Confirm","Remove user from group? (Will move to BG1)")!=QMessageBox.Yes:
            return
        c = self.connection.cursor()
        c.execute("UPDATE USERS SET USER_GROUP='BG1' WHERE USER_ID=?", (uid,))
        self.connection.commit()
        QMessageBox.information(self,"Success","User moved to BG1.")
        self.load_data()


###############################################################################
# Enhanced Lineage Graph + BFS
###############################################################################
class EnhancedLineageGraphWidget(QtWidgets.QGraphicsView):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)

        self.node_map = {}
        self.children_map = {}
        self.parents_map = {}

        self.populate_graph()

    def populate_graph(self):
        self.scene.clear()
        self.node_map.clear()
        self.children_map.clear()
        self.parents_map.clear()

        c = self.connection.cursor()
        c.execute("""
        SELECT RULE_ID, RULE_NAME, PARENT_RULE_ID, STATUS, RULE_TYPE_ID,
               CLUSTER_NAME, IS_GLOBAL, CRITICAL_RULE
        FROM BRM_RULES
        ORDER BY RULE_ID
        """)
        rules = get_cursor_rows(c)
        if not rules:
            self.scene.addItem(QtWidgets.QGraphicsTextItem("No rules found."))
            return

        for r in rules:
            rid = r["RULE_ID"]
            pid = r["PARENT_RULE_ID"]
            if pid:
                self.children_map.setdefault(pid,[]).append(rid)
                self.parents_map[rid] = pid

        rule_lookup = {x["RULE_ID"]: x for x in rules}
        all_ids = set(x["RULE_ID"] for x in rules)
        child_ids = set(self.parents_map.keys())
        roots = list(all_ids - child_ids)

        from collections import deque
        queue = deque()
        level_map = {}
        visited = set()

        for rt in roots:
            queue.append((rt,0))

        while queue:
            (rid,depth) = queue.popleft()
            if rid in visited:
                continue
            visited.add(rid)
            rinfo = rule_lookup[rid]
            at_level = level_map.get(depth,0)
            level_map[depth]=at_level+1

            x = depth*220
            y = at_level*120
            node = self.create_node(rinfo)
            node.setPos(x,y)
            self.scene.addItem(node)
            self.node_map[rid]=node

            if rid in self.children_map:
                for ch in self.children_map[rid]:
                    queue.append((ch,depth+1))

        for r in rules:
            rid = r["RULE_ID"]
            pid = r["PARENT_RULE_ID"]
            if pid and pid in self.node_map and rid in self.node_map:
                self.draw_edge(self.node_map[pid], self.node_map[rid])

        # table dependencies
        c.execute("SELECT RULE_ID, DATABASE_NAME, SCHEMA_NAME, TABLE_NAME FROM BRM_RULE_TABLE_DEPENDENCIES")
        deps = get_cursor_rows(c)
        table_node_map={}
        table_idx=0
        for dep in deps:
            key = f"{dep['DATABASE_NAME']}.{dep['SCHEMA_NAME']}.{dep['TABLE_NAME']}".strip(".")
            if key not in table_node_map:
                t_item = QtWidgets.QGraphicsEllipseItem(0,0,100,40)
                t_item.setBrush(QtGui.QBrush(QtGui.QColor("lightblue")))
                t_item.setToolTip(f"Table: {key}")
                t_item.setPos(800, table_idx*60)
                self.scene.addItem(t_item)
                table_node_map[key]=t_item
                table_idx+=1
            rrid = dep["RULE_ID"]
            if rrid in self.node_map:
                self.draw_edge(self.node_map[rrid], table_node_map[key], color=QtGui.QColor("darkmagenta"))

        self.scene.setSceneRect(self.scene.itemsBoundingRect())
        self.resetView()

    def create_node(self, rinfo):
        rtype = rinfo["RULE_TYPE_ID"]
        status = rinfo["STATUS"]
        cluster = rinfo.get("CLUSTER_NAME","") or ""
        g = rinfo["IS_GLOBAL"]
        c = rinfo["CRITICAL_RULE"]

        if rtype==1:
            node = QtWidgets.QGraphicsRectItem(0,0,120,50)
        else:
            node = QtWidgets.QGraphicsEllipseItem(0,0,120,50)

        if status.lower()=="active":
            basecol=QtGui.QColor("lightgreen")
        else:
            basecol=QtGui.QColor("tomato")

        if cluster:
            hv=abs(hash(cluster))%360
            basecol=QtGui.QColor.fromHsv(hv,128,255)

        node.setBrush(QtGui.QBrush(basecol))
        pen = QtGui.QPen(QtCore.Qt.black,2)
        if c==1:
            pen=QtGui.QPen(QtGui.QColor("red"),3)
        node.setPen(pen)

        display_name = rinfo["RULE_NAME"]
        if g==1:
            display_name=f"(G) {display_name}"
        node.setToolTip(f"Rule {rinfo['RULE_ID']}: {display_name}")
        return node

    def draw_edge(self, item1, item2, color=QtGui.QColor("darkblue")):
        r1 = item1.sceneBoundingRect()
        r2 = item2.sceneBoundingRect()
        p1 = r1.center()
        p2 = r2.center()
        line = QtWidgets.QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
        line.setPen(QtGui.QPen(color,2))
        self.scene.addItem(line)

    def resetView(self):
        if self.scene and self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button()==Qt.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item,(QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem)):
                QMessageBox.information(self,"Rule Details", item.toolTip())
        super().mousePressEvent(event)

    def clear_highlights(self):
        for nd in self.node_map.values():
            nd.setPen(QtGui.QPen(QtCore.Qt.black,2))

    def search_nodes(self, query):
        self.clear_highlights()
        ql = query.lower()
        c = self.connection.cursor()
        found = set()

        c.execute("""
        SELECT RULE_ID
        FROM BRM_RULES
        WHERE LOWER(RULE_NAME) LIKE ?
           OR LOWER(RULE_SQL) LIKE ?
           OR LOWER(DESCRIPTION) LIKE ?
           OR LOWER(BUSINESS_JUSTIFICATION) LIKE ?
           OR CAST(RULE_ID as varchar(50)) LIKE ?
        """,(f"%{ql}%",f"%{ql}%",f"%{ql}%",f"%{ql}%",f"%{ql}%"))
        for r in get_cursor_rows(c):
            found.add(r["RULE_ID"])

        c.execute("""
        SELECT RULE_ID
        FROM BRM_COLUMN_MAPPING
        WHERE LOWER(SOURCE_COLUMN_NAME) LIKE ?
           OR LOWER(TARGET_COLUMN_NAME) LIKE ?
        """,(f"%{ql}%",f"%{ql}%"))
        for r in get_cursor_rows(c):
            found.add(r["RULE_ID"])

        c.execute("""
        SELECT RULE_ID
        FROM BRM_RULE_TABLE_DEPENDENCIES
        WHERE LOWER(DATABASE_NAME) LIKE ?
           OR LOWER(SCHEMA_NAME) LIKE ?
           OR LOWER(TABLE_NAME) LIKE ?
        """,(f"%{ql}%", f"%{ql}%", f"%{ql}%"))
        for r in get_cursor_rows(c):
            found.add(r["RULE_ID"])

        if not found:
            QMessageBox.information(self,"No Match",f"No match for '{query}'")
            return
        # highlight
        for rid in found:
            if rid in self.node_map:
                self.node_map[rid].setPen(QtGui.QPen(QtGui.QColor("yellow"),4))
                self.highlight_ancestors(rid)
                self.highlight_descendants(rid)

    def highlight_ancestors(self, rid):
        cur = rid
        while cur in self.parents_map:
            node = self.node_map.get(cur)
            if node:
                node.setPen(QtGui.QPen(QtGui.QColor("yellow"),4))
            p = self.parents_map[cur]
            if p in self.node_map:
                self.node_map[p].setPen(QtGui.QPen(QtGui.QColor("yellow"),4))
            cur=p

    def highlight_descendants(self, rid):
        st=[rid]
        visited=set()
        while st:
            c = st.pop()
            if c in visited:
                continue
            visited.add(c)
            if c in self.node_map:
                self.node_map[c].setPen(QtGui.QPen(QtGui.QColor("yellow"),4))
            if c in self.children_map:
                st.extend(self.children_map[c])


###############################################################################
# Multi-step Approval (with Reject)
###############################################################################
class ApprovalPipelineWidget(QWidget):
    def __init__(self, stage_map, parent=None):
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(0,0,0,0)
        self.layout().setSpacing(5)
        stages=["BG1","BG2","BG3","FINAL"]
        for st in stages:
            circ = QLabel()
            circ.setFixedSize(20,20)
            circ.setStyleSheet("border-radius:10px;border:1px solid black;")
            status = stage_map.get(st,"NotStarted")
            if status=="Approved":
                circ.setStyleSheet("background-color:green;border-radius:10px;border:1px solid black;")
            elif status=="Pending":
                circ.setStyleSheet("background-color:yellow;border-radius:10px;border:1px solid black;")
            elif status=="Rejected":
                circ.setStyleSheet("background-color:red;border-radius:10px;border:1px solid black;")
            else:
                circ.setStyleSheet("background-color:lightgray;border-radius:10px;border:1px solid black;")
            circ.setToolTip(f"{st}: {status}")
            self.layout().addWidget(circ)

def mark_rule_rejected(conn, rule_id, username):
    c = conn.cursor()
    # set APPROVED_FLAG=2 => Rejected
    c.execute("""
    UPDATE BRM_RULE_APPROVALS
    SET APPROVED_FLAG=2, APPROVED_TIMESTAMP=CURRENT_TIMESTAMP
    WHERE RULE_ID=? AND USERNAME=? AND APPROVED_FLAG=0
    """,(rule_id, username))
    # mark rule
    c.execute("""
    UPDATE BRM_RULES
    SET APPROVAL_STATUS='REJECTED', STATUS='INACTIVE'
    WHERE RULE_ID=?
    """,(rule_id,))
    conn.commit()

class MultiStepApprovalTab(QWidget):
    def __init__(self, connection, logged_in_username, user_group, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.logged_in_username = logged_in_username
        self.user_group = user_group

        lay = QVBoxLayout(self)
        self.appr_table = QTableWidget(0,8)
        self.appr_table.setHorizontalHeaderLabels([
            "Rule ID","Group Name","Rule Name","Stage",
            "Approved?","Approve","Reject","Pipeline"
        ])
        self.appr_table.horizontalHeader().setStretchLastSection(True)
        self.appr_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.appr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.appr_table)

        ref = QPushButton("Refresh Approvals")
        ref.clicked.connect(self.load_approvals)
        lay.addWidget(ref)

        self.setLayout(lay)
        self.load_approvals()

    def load_approvals(self):
        c = self.connection.cursor()
        c.execute("""
        SELECT A.RULE_ID, A.GROUP_NAME, A.USERNAME, A.APPROVED_FLAG, A.APPROVAL_STAGE,
               R.RULE_NAME, R.APPROVAL_STATUS
        FROM BRM_RULE_APPROVALS A
        JOIN BRM_RULES R ON A.RULE_ID=R.RULE_ID
        WHERE A.USERNAME=? AND A.APPROVED_FLAG=0
        ORDER BY A.RULE_ID
        """,(self.logged_in_username,))
        rows = get_cursor_rows(c)

        # build pipeline
        pipeline={}
        all_app = self.connection.cursor()
        all_app.execute("SELECT * FROM BRM_RULE_APPROVALS")
        for apr in get_cursor_rows(all_app):
            rid = apr["RULE_ID"]
            grp = apr["GROUP_NAME"]
            st = apr["APPROVAL_STAGE"]
            fl = apr["APPROVED_FLAG"]
            pipeline.setdefault(rid, {"BG1":"NotStarted","BG2":"NotStarted","BG3":"NotStarted","FINAL":"NotStarted"})
            if fl==1:
                pipeline[rid][grp]="Approved"
            elif fl==2:
                pipeline[rid][grp]="Rejected"
            else:
                cur_st = get_current_approval_stage(self.connection, rid)
                if cur_st==st:
                    pipeline[rid][grp]="Pending"

        # only show rows that match current stage
        minimal=[]
        for rd in rows:
            rid = rd["RULE_ID"]
            stg = rd["APPROVAL_STAGE"]
            min_st = get_current_approval_stage(self.connection, rid)
            if min_st==stg:
                minimal.append(rd)

        self.appr_table.setRowCount(0)
        for rd in minimal:
            r = self.appr_table.rowCount()
            self.appr_table.insertRow(r)
            self.appr_table.setItem(r,0,QTableWidgetItem(str(rd["RULE_ID"])))
            self.appr_table.setItem(r,1,QTableWidgetItem(rd["GROUP_NAME"]))
            self.appr_table.setItem(r,2,QTableWidgetItem(rd["RULE_NAME"]))
            self.appr_table.setItem(r,3,QTableWidgetItem(str(rd["APPROVAL_STAGE"])))
            self.appr_table.setItem(r,4,QTableWidgetItem(str(rd["APPROVED_FLAG"])))

            approve_btn = QPushButton("Approve")
            approve_btn.clicked.connect(lambda _, row_idx=r: self.do_approve(row_idx))
            self.appr_table.setCellWidget(r,5,approve_btn)

            reject_btn = QPushButton("Reject")
            reject_btn.clicked.connect(lambda _, row_idx=r: self.do_reject(row_idx))
            self.appr_table.setCellWidget(r,6,reject_btn)

            pmap = pipeline.get(rd["RULE_ID"],{"BG1":"NotStarted","BG2":"NotStarted","BG3":"NotStarted","FINAL":"NotStarted"})
            pipe_w = ApprovalPipelineWidget(pmap)
            self.appr_table.setCellWidget(r,7, pipe_w)

    def do_approve(self, row_idx):
        rid_item = self.appr_table.item(row_idx,0)
        grp_item = self.appr_table.item(row_idx,1)
        if not rid_item or not grp_item:
            return
        rid = int(rid_item.text())
        grp = grp_item.text()

        c = self.connection.cursor()
        c.execute("""
        UPDATE BRM_RULE_APPROVALS
        SET APPROVED_FLAG=1, APPROVED_TIMESTAMP=CURRENT_TIMESTAMP
        WHERE RULE_ID=? AND GROUP_NAME=? AND USERNAME=?
        """,(rid, grp, self.logged_in_username))

        nxt = get_current_approval_stage(self.connection, rid)
        if nxt is None:
            c.execute("UPDATE BRM_RULES SET APPROVAL_STATUS='APPROVED', STATUS='ACTIVE' WHERE RULE_ID=?",(rid,))
        else:
            c.execute("UPDATE BRM_RULES SET APPROVAL_STATUS='APPROVAL_IN_PROGRESS', STATUS='INACTIVE' WHERE RULE_ID=?",(rid,))

        add_audit_log(self.connection, "APPROVE", "BRM_RULE_APPROVALS", rid,
                      self.logged_in_username, {"APPROVED_FLAG":0}, {"APPROVED_FLAG":1})
        self.connection.commit()

        QMessageBox.information(self,"Approved",f"Rule {rid} approved.")
        self.load_approvals()

    def do_reject(self, row_idx):
        rid_item = self.appr_table.item(row_idx,0)
        if not rid_item:
            return
        rid = int(rid_item.text())
        conf = QMessageBox.question(self,"Reject Confirmation",f"Reject rule {rid}?")
        if conf!=QMessageBox.Yes:
            return
        mark_rule_rejected(self.connection, rid, self.logged_in_username)
        add_audit_log(self.connection, "REJECT", "BRM_RULE_APPROVALS", rid,
                      self.logged_in_username, {"APPROVED_FLAG":0}, {"APPROVED_FLAG":2})
        QMessageBox.information(self,"Rejected",f"Rule {rid} has been Rejected.")
        self.load_approvals()


###############################################################################
# Control Tables Tab
###############################################################################
class CtrlTablesTab(QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection

        layout = QVBoxLayout(self)
        self.table_list = [
            "USERS","BUSINESS_GROUPS","GROUP_PERMISSIONS","BRM_RULE_TYPES","BRM_RULE_GROUPS",
            "BRM_RULES","BRM_RULE_TABLE_DEPENDENCIES","BRM_AUDIT_LOG","BRM_RULE_LINEAGE",
            "BRM_GROUP_BACKUPS","BRM_COLUMN_MAPPING","BRM_CUSTOM_RULE_GROUPS",
            "BRM_CUSTOM_GROUP_MEMBERS","BUSINESS_GROUP_APPROVERS",
            "BRM_RULE_APPROVALS","BRM_CUSTOM_GROUP_BACKUPS","BRM_GLOBAL_CRITICAL_LINKS",
            "RULE_SCHEDULES"
        ]

        self.table_combo = QComboBox()
        for t in self.table_list:
            self.table_combo.addItem(t)
        layout.addWidget(QLabel("Select Table:"))
        layout.addWidget(self.table_combo)

        self.load_btn = QPushButton("Load Data")
        self.load_btn.clicked.connect(self.on_load_data)
        layout.addWidget(self.load_btn)

        self.table_view = QTableWidget(0,0)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table_view)

        self.setLayout(layout)

    def on_load_data(self):
        tbl = self.table_combo.currentText()
        if not tbl:
            return
        c = self.connection.cursor()
        col_query = f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='{tbl}'
        ORDER BY ORDINAL_POSITION
        """
        c.execute(col_query)
        col_info = c.fetchall()
        col_names = [x[0] for x in col_info]

        data_q = f"SELECT * FROM dbo.{tbl}"
        c.execute(data_q)
        rows = c.fetchall()

        self.table_view.setRowCount(0)
        self.table_view.setColumnCount(len(col_names))
        self.table_view.setHorizontalHeaderLabels(col_names)

        for rd in rows:
            r = self.table_view.rowCount()
            self.table_view.insertRow(r)
            for j,coln in enumerate(col_names):
                val = rd[j]
                self.table_view.setItem(r,j,QTableWidgetItem(str(val)))

        self.table_view.resizeColumnsToContents()


###############################################################################
# Global/Critical Admin Tab
###############################################################################
class GlobalCriticalAdminTab(QWidget):
    def __init__(self, main_app, connection, user_group, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.connection = connection
        self.user_group = user_group

        layout = QVBoxLayout(self)
        if self.user_group!="Admin":
            layout.addWidget(QLabel("Access Denied: Admin Only."))
            self.setLayout(layout)
            return

        fl = QHBoxLayout()
        self.show_only_gcr = QCheckBox("Show only Global/Critical")
        self.show_only_gcr.setChecked(True)
        rf = QPushButton("Refresh Rule List")
        rf.clicked.connect(self.load_rule_list)
        fl.addWidget(self.show_only_gcr)
        fl.addWidget(rf)
        fl.addStretch()
        layout.addLayout(fl)

        self.rule_table = QTableWidget(0,8)
        self.rule_table.setHorizontalHeaderLabels([
            "Rule ID","Rule Name","Owner Group","IS_GLOBAL",
            "CRITICAL_RULE","CRITICAL_SCOPE","STATUS","UPDATED_BY"
        ])
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.rule_table)

        gcs = QHBoxLayout()
        self.global_checkbox = QCheckBox("Set Global?")
        gcs.addWidget(self.global_checkbox)
        self.critical_checkbox = QCheckBox("Set Critical?")
        gcs.addWidget(self.critical_checkbox)
        gcs.addWidget(QLabel("Critical Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["NONE","GROUP","CLUSTER","GLOBAL"])
        gcs.addWidget(self.scope_combo)

        apply_btn = QPushButton("Apply Flags/Scope To Selected")
        apply_btn.clicked.connect(self.apply_gcs_to_selected)
        gcs.addWidget(apply_btn)
        gcs.addStretch()
        layout.addLayout(gcs)

        self.setLayout(layout)
        self.load_rule_list()

    def load_rule_list(self):
        c = self.connection.cursor()
        if self.show_only_gcr.isChecked():
            c.execute("""
            SELECT RULE_ID, RULE_NAME, OWNER_GROUP, IS_GLOBAL, CRITICAL_RULE,
                   CRITICAL_SCOPE, STATUS, UPDATED_BY
            FROM BRM_RULES
            WHERE IS_GLOBAL=1 OR CRITICAL_RULE=1
            ORDER BY RULE_ID DESC
            """)
        else:
            c.execute("""
            SELECT RULE_ID, RULE_NAME, OWNER_GROUP, IS_GLOBAL, CRITICAL_RULE,
                   CRITICAL_SCOPE, STATUS, UPDATED_BY
            FROM BRM_RULES
            ORDER BY RULE_ID DESC
            """)
        rows = c.fetchall()
        self.rule_table.setRowCount(0)
        for rd in rows:
            r = self.rule_table.rowCount()
            self.rule_table.insertRow(r)
            for j,val in enumerate(rd):
                self.rule_table.setItem(r,j,QTableWidgetItem(str(val)))

    def get_selected_rule_ids(self):
        idxs = self.rule_table.selectionModel().selectedRows()
        out=[]
        for i in idxs:
            row = i.row()
            it = self.rule_table.item(row,0)
            if it:
                out.append(int(it.text()))
        return out

    def apply_gcs_to_selected(self):
        rids = self.get_selected_rule_ids()
        if not rids:
            QMessageBox.warning(self,"No Selection","Select one or more rules.")
            return
        is_global = 1 if self.global_checkbox.isChecked() else 0
        is_crit = 1 if self.critical_checkbox.isChecked() else 0
        scope_val = self.scope_combo.currentText().upper()

        msg = (f"Update {len(rids)} rule(s):\n"
               f"IS_GLOBAL={is_global}, CRITICAL_RULE={is_crit}, CRITICAL_SCOPE={scope_val}.\nContinue?")
        if QMessageBox.question(self,"Confirm",msg)!=QMessageBox.Yes:
            return

        c = self.connection.cursor()
        for rid in rids:
            c.execute("SELECT * FROM BRM_RULES WHERE RULE_ID=?",(rid,))
            old = get_cursor_one(c)
            if not old:
                continue
            new_data = dict(old)
            new_data["IS_GLOBAL"]=is_global
            new_data["CRITICAL_RULE"]=is_crit
            new_data["CRITICAL_SCOPE"]=scope_val
            try:
                update_rule(self.connection, new_data, "Admin", "Admin")
            except Exception as ex:
                logger.error(f"Error updating rule {rid}: {ex}")
        QMessageBox.information(self,"Done","Global/Critical updated.")
        self.load_rule_list()


###############################################################################
# Hierarchy View Tab (simple example)
###############################################################################
class HierarchyViewTab(QWidget):
    """
    Example of a hierarchy view:
    - Show groups => rules => maybe child rules
    """
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Group / Rule Name"])
        layout.addWidget(self.tree)
        refb = QPushButton("Refresh Hierarchy")
        refb.clicked.connect(self.load_hierarchy)
        layout.addWidget(refb)
        self.setLayout(layout)
        self.load_hierarchy()

    def load_hierarchy(self):
        self.tree.clear()
        c = self.connection.cursor()
        c.execute("SELECT GROUP_ID, GROUP_NAME FROM BRM_RULE_GROUPS ORDER BY GROUP_NAME")
        groups = get_cursor_rows(c)
        grp_map = {}
        for g in groups:
            gitem = QTreeWidgetItem([f"{g['GROUP_NAME']} (ID={g['GROUP_ID']})"])
            self.tree.addTopLevelItem(gitem)
            grp_map[g["GROUP_ID"]]=gitem

        # Now fetch rules in each group
        c.execute("SELECT RULE_ID, RULE_NAME, GROUP_ID FROM BRM_RULES")
        ruleset = get_cursor_rows(c)
        for r in ruleset:
            gid = r["GROUP_ID"]
            if gid in grp_map:
                parent_item = grp_map[gid]
                chitem = QTreeWidgetItem([f"Rule {r['RULE_ID']}: {r['RULE_NAME']}"])
                parent_item.addChild(chitem)


###############################################################################
# Minimal User Management Tab (Admin only)
###############################################################################
class UserManagementTab(QWidget):
    """
    Shows all users, can add new user or reset password.
    """
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(["User ID","Username","Password","User Group"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        bh = QHBoxLayout()
        add_btn = QPushButton("Add User")
        add_btn.clicked.connect(self.on_add_user)
        bh.addWidget(add_btn)
        reset_btn = QPushButton("Reset Password")
        reset_btn.clicked.connect(self.on_reset_password)
        bh.addWidget(reset_btn)
        del_btn = QPushButton("Delete User")
        del_btn.clicked.connect(self.on_delete_user)
        bh.addWidget(del_btn)
        bh.addStretch()
        layout.addLayout(bh)

        ref = QPushButton("Refresh Users")
        ref.clicked.connect(self.load_users)
        layout.addWidget(ref)
        self.setLayout(layout)
        self.load_users()

    def load_users(self):
        c = self.connection.cursor()
        c.execute("SELECT USER_ID, USERNAME, PASSWORD, USER_GROUP FROM USERS ORDER BY USER_ID")
        rows = c.fetchall()
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r,0,QTableWidgetItem(str(row[0])))
            self.table.setItem(r,1,QTableWidgetItem(row[1]))
            self.table.setItem(r,2,QTableWidgetItem(row[2]))
            self.table.setItem(r,3,QTableWidgetItem(row[3]))

    def get_selected_user_id(self):
        i = self.table.currentRow()
        if i<0:
            return None
        it = self.table.item(i,0)
        return int(it.text()) if it else None

    def on_add_user(self):
        un, ok = QInputDialog.getText(self,"Add User","Username:")
        if not ok or not un.strip():
            return
        pw, ok2 = QInputDialog.getText(self,"Add User","Password:")
        if not ok2:
            pw=""
        grp, ok3 = QInputDialog.getText(self,"Add User","User Group:")
        if not ok3:
            grp="BG1"
        c = self.connection.cursor()
        c.execute("SELECT * FROM USERS WHERE USERNAME=?",(un.strip(),))
        if c.fetchone():
            QMessageBox.warning(self,"Error","User already exists.")
            return
        c.execute("INSERT INTO USERS(USERNAME,PASSWORD,USER_GROUP) VALUES(?,?,?)",(un.strip(),pw.strip(),grp.strip()))
        self.connection.commit()
        QMessageBox.information(self,"Success","User added.")
        self.load_users()

    def on_reset_password(self):
        uid = self.get_selected_user_id()
        if not uid:
            QMessageBox.warning(self,"None","No user selected.")
            return
        new_pw, ok = QInputDialog.getText(self,"Reset Password","New password:")
        if not ok:
            return
        c = self.connection.cursor()
        c.execute("UPDATE USERS SET PASSWORD=? WHERE USER_ID=?",(new_pw.strip(),uid))
        self.connection.commit()
        QMessageBox.information(self,"Updated","Password reset.")
        self.load_users()

    def on_delete_user(self):
        uid = self.get_selected_user_id()
        if not uid:
            QMessageBox.warning(self,"None","No user selected.")
            return
        if QMessageBox.question(self,"Confirm","Delete user?")!=QMessageBox.Yes:
            return
        c = self.connection.cursor()
        c.execute("DELETE FROM USERS WHERE USER_ID=?",(uid,))
        self.connection.commit()
        QMessageBox.information(self,"Deleted","User deleted.")
        self.load_users()


###############################################################################
# Main Window
###############################################################################
class BRMTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BRM Tool – Full Integrated Enhanced Version (SQL Server)")
        self.resize(1200, 800)
        self.connection = None

        dlg = DatabaseConnectionDialog()
        if dlg.exec_()==QDialog.Accepted:
            self.connection = dlg.get_connection()
            if not self.connection:
                sys.exit(1)
        else:
            sys.exit(0)

        self.login_dialog = LoginDialog(self.connection)
        if self.login_dialog.exec_()!=QDialog.Accepted:
            sys.exit(0)

        self.user_id = self.login_dialog.user_id

        c = self.connection.cursor()
        c.execute("SELECT USERNAME FROM USERS WHERE USER_ID=?", (self.user_id,))
        rowu = get_cursor_one(c)
        self.logged_in_username = rowu["USERNAME"] if rowu else "Unknown"

        c.execute("SELECT USER_GROUP FROM USERS WHERE USER_ID=?", (self.user_id,))
        rowg = get_cursor_one(c)
        self.user_group = rowg["USER_GROUP"] if rowg else "Unknown"

        self.init_ui()

    def init_ui(self):
        menubar = self.menuBar()
        fileMenu = menubar.addMenu("File")
        syncAction = QtWidgets.QAction("Sync Metadata", self)
        syncAction.triggered.connect(lambda: sync_metadata(self.connection))
        fileMenu.addAction(syncAction)

        metricsAction = QtWidgets.QAction("View Metrics Dashboard", self)
        metricsAction.triggered.connect(self.show_metrics_dashboard)
        fileMenu.addAction(metricsAction)

        schedAction = QtWidgets.QAction("Schedule a Rule", self)
        schedAction.triggered.connect(lambda: RuleSchedulerDialog(self.connection,self).exec_())
        fileMenu.addAction(schedAction)

        cw = QWidget()
        lay = QVBoxLayout(cw)

        if self.user_group=="Admin":
            top_h = QHBoxLayout()
            self.switch_combo = QComboBox()
            self.switch_btn = QPushButton("Switch User")
            self.switch_btn.clicked.connect(self.on_switch_user)
            top_h.addWidget(QLabel("Impersonate:"))
            top_h.addWidget(self.switch_combo)
            top_h.addWidget(self.switch_btn)
            top_h.addStretch()
            lay.addLayout(top_h)
            self.populate_switch_combo()

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # 1) Business Rule Management
        self.brm_tab = BusinessRuleManagementTab(self, self.connection, self.user_id, self.user_group)
        self.tabs.addTab(self.brm_tab, "Business Rule Management")

        # 2) Group Management
        if self.user_group=="Admin":
            self.grp_mgmt_tab = GroupManagementTab(self, self.connection, self.user_id, self.user_group)
            self.tabs.addTab(self.grp_mgmt_tab, "Group Management")

            # 3) User Management
            self.user_mgmt_tab = UserManagementTab(self.connection)
            self.tabs.addTab(self.user_mgmt_tab, "User Management")

        # 4) Enhanced Lineage Graph
        self.lineage_tab = EnhancedLineageGraphWidget(self.connection)
        lw_container = QWidget()
        lw_layout = QVBoxLayout(lw_container)
        lb = QLabel("Lineage Visualization (BFS-based)")
        lb.setStyleSheet("font-weight:bold;")
        lw_layout.addWidget(lb)
        lw_layout.addWidget(self.lineage_tab)
        s_h = QHBoxLayout()
        self.lineage_search = QLineEdit()
        self.lineage_search.setPlaceholderText("Search rule / db / schema / table ...")
        s_btn = QPushButton("Search")
        s_btn.clicked.connect(lambda: self.lineage_tab.search_nodes(self.lineage_search.text()))
        rst_btn = QPushButton("Reset View")
        rst_btn.clicked.connect(self.lineage_tab.resetView)
        ref_btn = QPushButton("Refresh Graph")
        ref_btn.clicked.connect(self.lineage_tab.populate_graph)
        s_h.addWidget(self.lineage_search)
        s_h.addWidget(s_btn)
        s_h.addWidget(rst_btn)
        s_h.addWidget(ref_btn)
        s_h.addStretch()
        lw_layout.addLayout(s_h)
        self.tabs.addTab(lw_container,"Lineage Visualization")

        # 5) Hierarchy View
        self.hierarchy_tab = HierarchyViewTab(self.connection)
        self.tabs.addTab(self.hierarchy_tab,"Hierarchy View")

        # 6) Approvals
        self.approv_tab = MultiStepApprovalTab(self.connection, self.logged_in_username, self.user_group)
        self.tabs.addTab(self.approv_tab, "Approvals")

        # 7) Global/Critical Admin
        if self.user_group=="Admin":
            self.gc_admin_tab = GlobalCriticalAdminTab(self, self.connection, self.user_group)
            self.tabs.addTab(self.gc_admin_tab,"Global/Critical Admin")

        # 8) Control Tables
        self.ctrl_tab = CtrlTablesTab(self.connection)
        self.tabs.addTab(self.ctrl_tab,"Control Tables")

        # 9) Schedules
        self.schedule_tab = ScheduleManagementTab(self.connection)
        self.tabs.addTab(self.schedule_tab,"Schedule Management")

        # 10) Metrics
        self.metrics_tab = MetricsDashboardTab(self.connection)
        self.tabs.addTab(self.metrics_tab,"Metrics Dashboard")

        cw.setLayout(lay)
        self.setCentralWidget(cw)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_approvals)
        self.timer.start(5000)

        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self.check_due_schedules)
        self.schedule_timer.start(60000)

        self.show()

    def populate_switch_combo(self):
        c = self.connection.cursor()
        c.execute("SELECT USER_ID, USERNAME, USER_GROUP FROM USERS ORDER BY USER_ID")
        rows = get_cursor_rows(c)
        for r in rows:
            disp = f"{r['USERNAME']} ({r['USER_GROUP']})"
            self.switch_combo.addItem(disp, (r["USER_ID"], r["USER_GROUP"]))

    def on_switch_user(self):
        data = self.switch_combo.currentData()
        if not data:
            return
        uid, grp = data
        if uid==self.user_id and grp==self.user_group:
            return
        self.user_id = uid
        self.user_group = grp
        self.reinit_tabs()

    def reinit_tabs(self):
        self.tabs.clear()
        self.brm_tab = BusinessRuleManagementTab(self, self.connection, self.user_id, self.user_group)
        self.tabs.addTab(self.brm_tab,"Business Rule Management")

        if self.user_group=="Admin":
            self.grp_mgmt_tab = GroupManagementTab(self, self.connection, self.user_id, self.user_group)
            self.tabs.addTab(self.grp_mgmt_tab,"Group Management")

            self.user_mgmt_tab = UserManagementTab(self.connection)
            self.tabs.addTab(self.user_mgmt_tab,"User Management")

        self.lineage_tab = EnhancedLineageGraphWidget(self.connection)
        lw_container = QWidget()
        lw_layout = QVBoxLayout(lw_container)
        lb = QLabel("Lineage Visualization")
        lb.setStyleSheet("font-weight:bold;")
        lw_layout.addWidget(lb)
        lw_layout.addWidget(self.lineage_tab)
        s_h = QHBoxLayout()
        self.lineage_search = QLineEdit()
        s_btn = QPushButton("Search")
        s_btn.clicked.connect(lambda: self.lineage_tab.search_nodes(self.lineage_search.text()))
        rst_btn = QPushButton("Reset View")
        rst_btn.clicked.connect(self.lineage_tab.resetView)
        ref_btn = QPushButton("Refresh Graph")
        ref_btn.clicked.connect(self.lineage_tab.populate_graph)
        s_h.addWidget(self.lineage_search)
        s_h.addWidget(s_btn)
        s_h.addWidget(rst_btn)
        s_h.addWidget(ref_btn)
        s_h.addStretch()
        lw_layout.addLayout(s_h)
        self.tabs.addTab(lw_container,"Lineage Visualization")

        self.hierarchy_tab = HierarchyViewTab(self.connection)
        self.tabs.addTab(self.hierarchy_tab,"Hierarchy View")

        self.approv_tab = MultiStepApprovalTab(self.connection, self.logged_in_username, self.user_group)
        self.tabs.addTab(self.approv_tab,"Approvals")

        if self.user_group=="Admin":
            self.gc_admin_tab = GlobalCriticalAdminTab(self, self.connection, self.user_group)
            self.tabs.addTab(self.gc_admin_tab,"Global/Critical Admin")

        self.ctrl_tab = CtrlTablesTab(self.connection)
        self.tabs.addTab(self.ctrl_tab,"Control Tables")

        self.schedule_tab = ScheduleManagementTab(self.connection)
        self.tabs.addTab(self.schedule_tab,"Schedule Management")

        self.metrics_tab = MetricsDashboardTab(self.connection)
        self.tabs.addTab(self.metrics_tab,"Metrics Dashboard")

    def refresh_approvals(self):
        self.approv_tab.load_approvals()

    def check_due_schedules(self):
        c = self.connection.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
        SELECT SCHEDULE_ID, RULE_ID, SCHEDULE_TIME
        FROM RULE_SCHEDULES
        WHERE SCHEDULE_TIME<=? AND STATUS='Scheduled'
        """,(now,))
        due = get_cursor_rows(c)
        for sch in due:
            rid = sch["RULE_ID"]
            c.execute("SELECT RULE_SQL FROM BRM_RULES WHERE RULE_ID=?",(rid,))
            row = get_cursor_one(c)
            if row:
                sql_ = row["RULE_SQL"]
                ok,msg = run_rule_sql(self.connection, sql_)
                logger.info(f"Scheduled rule {rid}: {'PASS' if ok else 'FAIL'} => {msg}")
            c.execute("UPDATE RULE_SCHEDULES SET STATUS='Executed' WHERE SCHEDULE_ID=?",(sch["SCHEDULE_ID"],))
        self.connection.commit()
        self.schedule_tab.load_schedules()

    def show_metrics_dashboard(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Operational Metrics Dashboard")
        dlg.resize(800,600)
        layout = QVBoxLayout(dlg)
        met_tab = MetricsDashboardTab(self.connection)
        layout.addWidget(met_tab)
        cb = QPushButton("Close")
        cb.clicked.connect(dlg.close)
        layout.addWidget(cb)
        dlg.exec_()

    def launch_audit_log_viewer(self):
        dlg = AuditLogViewer(self.connection, self.user_group, self)
        dlg.exec_()

    def launch_search_rule_dialog(self):
        dlg = SearchRuleDialog(self.connection, self.user_group, self)
        dlg.exec_()

    def get_rule_types(self):
        # Example or DB-driven
        return {"DQ":1, "DM":2, "Validation":3}

    def closeEvent(self, event):
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
        event.accept()


###############################################################################
# MAIN
###############################################################################
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = BRMTool()
    w.show()
    sys.exit(app.exec_())

if __name__=="__main__":
    main()