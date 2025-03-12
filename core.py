# core.py
import sys
import os
import json
import math
import smtplib
import logging
import logging.handlers
import pyodbc
import sqlparse
import re
import csv
import time
from datetime import datetime, date, time, timedelta
from collections import deque
from email.mime.text import MIMEText

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (
    QApplication, QDialog, QMessageBox, QLineEdit, QComboBox,
    QPushButton, QLabel, QVBoxLayout, QHBoxLayout
)

# -----------------------------------------------------------------------------
# Advanced Logging Configuration (with RotatingFileHandler)
# -----------------------------------------------------------------------------
LOG_FILENAME = 'brm_tool_enhanced.log'
logger = logging.getLogger('BRMTool')
logger.setLevel(logging.DEBUG)
handler = logging.handlers.RotatingFileHandler(
    LOG_FILENAME, maxBytes=5 * 1024 * 1024, backupCount=5
)
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# -----------------------------------------------------------------------------
# Email Configuration & Sender
# -----------------------------------------------------------------------------
EMAIL_CONFIG = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "your_smtp_user",
    "smtp_password": "your_smtp_pass",
    "sender_email": "noreply@example.com"
}

def send_email_notification(subject: str, body: str, recipients: list):
    try:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = ", ".join(recipients)
        smtp = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        smtp.starttls()
        smtp.login(EMAIL_CONFIG['smtp_username'], EMAIL_CONFIG['smtp_password'])
        smtp.sendmail(EMAIL_CONFIG['sender_email'], recipients, msg.as_string())
        smtp.quit()
        logger.info(f"Email sent to {recipients}")
    except Exception as ex:
        logger.error(f"Error sending email: {ex}")

# -----------------------------------------------------------------------------
# Database Connection Dialog
# -----------------------------------------------------------------------------
class DatabaseConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super(DatabaseConnectionDialog, self).__init__(parent)
        self.connection = None
        self.setWindowTitle("Database Connection")
        self.resize(400, 200)
        main_layout = QVBoxLayout(self)
        
        label = QLabel("Select ODBC DSN or provide a custom connection string:")
        main_layout.addWidget(label)
        
        self.dsn_combo = QComboBox()
        try:
            data_sources = pyodbc.dataSources()
            for dsn, driver in data_sources.items():
                if "SQL SERVER" in driver.upper():
                    self.dsn_combo.addItem(f"ODBC DSN: {dsn}", dsn)
        except Exception as e:
            logger.error(f"Error retrieving DSNs: {e}")
        main_layout.addWidget(self.dsn_combo)
        
        self.conn_str_edit = QLineEdit()
        self.conn_str_edit.setPlaceholderText("Or enter custom connection string")
        main_layout.addWidget(self.conn_str_edit)
        
        btn_layout = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(connect_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)
    
    def get_connection(self):
        override = self.conn_str_edit.text().strip()
        if override:
            conn_str = override
        else:
            dsn = self.dsn_combo.currentData()
            if not dsn:
                QMessageBox.critical(self, "Error", "No DSN selected.")
                return None
            conn_str = f"DSN={dsn};Trusted_Connection=yes;"
        try:
            conn = pyodbc.connect(conn_str)
            logger.info("Database connection established.")
            return conn
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            logger.error(f"Database connection error: {e}")
            return None

# -----------------------------------------------------------------------------
# Database Helper Functions
# -----------------------------------------------------------------------------
def fetch_all_dict(cursor):
    rows = cursor.fetchall()
    if cursor.description:
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    return rows

def fetch_one_dict(cursor):
    row = cursor.fetchone()
    if row and cursor.description:
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    return None

def insert_audit_log(conn, action, table_name, record_id, actor, old_data, new_data):
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO BRM_AUDIT_LOG(
                ACTION, TABLE_NAME, RECORD_ID, ACTION_BY,
                OLD_DATA, NEW_DATA, ACTION_TIMESTAMP
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE())
        """, (
            action,
            table_name,
            str(record_id) if record_id else None,
            actor,
            json.dumps(old_data) if old_data else None,
            json.dumps(new_data) if new_data else None
        ))
        conn.commit()
        logger.info(f"Audit log inserted for action: {action} on record {record_id}.")
    except Exception as e:
        logger.error(f"Error inserting audit log: {e}")

# -----------------------------------------------------------------------------
# Locking Functions
# -----------------------------------------------------------------------------
def lock_rule(conn, rule_id, locked_by, force=False):
    try:
        c = conn.cursor()
        # Auto-release locks older than 30 minutes
        c.execute("DELETE FROM RULE_LOCKS WHERE DATEDIFF(MINUTE, LOCK_TIMESTAMP, GETDATE()) > 30")
        conn.commit()
        c.execute("SELECT LOCKED_BY FROM RULE_LOCKS WHERE RULE_ID=?", (rule_id,))
        row = c.fetchone()
        if row:
            current_lock = row[0]
            if current_lock != locked_by and not force:
                raise ValueError(f"Rule {rule_id} is locked by {current_lock}.")
            else:
                c.execute("DELETE FROM RULE_LOCKS WHERE RULE_ID=?", (rule_id,))
        c.execute("INSERT INTO RULE_LOCKS(RULE_ID, LOCKED_BY, LOCK_TIMESTAMP) VALUES (?, ?, GETDATE())", (rule_id, locked_by))
        conn.commit()
        logger.info(f"Rule {rule_id} locked by {locked_by}.")
    except Exception as e:
        logger.error(f"Error locking rule {rule_id}: {e}")
        raise

def unlock_rule(conn, rule_id, locked_by, force=False):
    try:
        c = conn.cursor()
        c.execute("SELECT LOCKED_BY FROM RULE_LOCKS WHERE RULE_ID=?", (rule_id,))
        row = c.fetchone()
        if row and row[0] != locked_by and not force:
            raise ValueError(f"Cannot unlock rule {rule_id}; it is locked by {row[0]}.")
        c.execute("DELETE FROM RULE_LOCKS WHERE RULE_ID=?", (rule_id,))
        conn.commit()
        logger.info(f"Rule {rule_id} unlocked by {locked_by}.")
    except Exception as e:
        logger.error(f"Error unlocking rule {rule_id}: {e}")
        raise

# -----------------------------------------------------------------------------
# Utility Function: Detect Operation Type
# -----------------------------------------------------------------------------
def detect_operation_type(rule_sql: str, decision_table_id=None) -> str:
    if (not rule_sql.strip()) and decision_table_id:
        return "DECISION_TABLE"
    txt = rule_sql.strip().upper()
    if txt.startswith("INSERT"):
        return "INSERT"
    elif txt.startswith("UPDATE"):
        return "UPDATE"
    elif txt.startswith("DELETE"):
        return "DELETE"
    elif txt.startswith("SELECT"):
        return "SELECT"
    return "OTHER"

# -----------------------------------------------------------------------------
# Advanced SQL Parsing using sqlparse
# -----------------------------------------------------------------------------
def parse_sql_dependencies(sql_text: str):
    try:
        statements = sqlparse.parse(sql_text)
        tables = []
        cte_tables = {}
        alias_map = {}
        columns = []
        for stmt in statements:
            # Extract WITH clauses (CTEs)
            cte_info = _extract_with_clauses(stmt)
            cte_tables.update(cte_info)
            # Extract main tables from FROM clause
            main_tables, main_alias = _extract_main_from(stmt.tokens, set(cte_info.keys()))
            tables.extend(main_tables)
            alias_map.update(main_alias)
            # Extract columns from SELECT clause
            cols = _extract_columns(stmt)
            columns.extend(cols)
        unique_tables = list(set(tables))
        return {
            "tables": unique_tables,
            "cte_tables": cte_tables,
            "alias_map": alias_map,
            "columns": columns
        }
    except Exception as e:
        logger.error(f"Error parsing SQL dependencies: {e}")
        return {"tables": [], "cte_tables": {}, "alias_map": {}, "columns": []}

def _extract_with_clauses(statement):
    cte_map = {}
    tokens = list(statement.tokens)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.ttype == sqlparse.tokens.Keyword and token.value.upper() == "WITH":
            i += 1
            i = _parse_cte_block(tokens, i, cte_map)
            break
        i += 1
    return cte_map

def _parse_cte_block(tokens, i, cte_map):
    while i < len(tokens):
        token = tokens[i]
        if token.ttype == sqlparse.tokens.Keyword and token.value.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            return i
        if isinstance(token, sqlparse.sql.Identifier):
            cte_name = token.get_real_name()
            i += 1
            i = _parse_cte_as_clause(tokens, i, cte_name, cte_map)
        else:
            i += 1
    return i

def _parse_cte_as_clause(tokens, i, cte_name, cte_map):
    while i < len(tokens):
        token = tokens[i]
        if token.value.upper() == "AS":
            i += 1
            if i < len(tokens) and isinstance(tokens[i], sqlparse.sql.Parenthesis):
                subselect = tokens[i]
                sub_deps = _extract_subselect_tokens(subselect.tokens)
                cte_map[cte_name] = sub_deps
                i += 1
                return i
        i += 1
    return i

def _extract_subselect_tokens(tokens):
    results = []
    from_seen = False
    for token in tokens:
        if token.ttype == sqlparse.tokens.Keyword and token.value.upper() in ("FROM", "JOIN"):
            from_seen = True
        if from_seen:
            if isinstance(token, sqlparse.sql.IdentifierList):
                for ident in token.get_identifiers():
                    results.append(_parse_identifier(ident, set()))
            elif isinstance(token, sqlparse.sql.Identifier):
                results.append(_parse_identifier(token, set()))
    return results

def _extract_main_from(tokens, known_cte):
    results = []
    alias_map = {}
    from_seen = False
    for token in tokens:
        if token.ttype == sqlparse.tokens.Keyword:
            if token.value.upper() in ("FROM", "JOIN"):
                from_seen = True
            else:
                from_seen = False
        if from_seen:
            if isinstance(token, sqlparse.sql.IdentifierList):
                for ident in token.get_identifiers():
                    res = _parse_identifier(ident, known_cte)
                    results.append(res)
                    if res[2]:
                        alias_map[res[2]] = (res[0], res[1])
            elif isinstance(token, sqlparse.sql.Identifier):
                res = _parse_identifier(token, known_cte)
                results.append(res)
                if res[2]:
                    alias_map[res[2]] = (res[0], res[1])
    return results, alias_map

def _parse_identifier(ident, known_cte):
    alias = ident.get_alias()
    real_name = ident.get_real_name()
    schema = ident.get_parent_name()
    if real_name and any(real_name.upper() == name.upper() for name in known_cte):
        return (None, f"(CTE) {real_name}", alias)
    return (schema, real_name, alias)

def _extract_columns(statement):
    results = []
    for token in statement.tokens:
        if token.ttype == sqlparse.tokens.DML and token.value.upper() == "SELECT":
            idx = statement.token_index(token) + 1
            results.extend(_parse_select_list(statement.tokens, idx))
    return results

def _parse_select_list(tokens, idx):
    columns = []
    while idx < len(tokens):
        token = tokens[idx]
        if token.ttype == sqlparse.tokens.Keyword and token.value.upper() in ("FROM", "WHERE", "GROUP", "ORDER"):
            break
        if isinstance(token, sqlparse.sql.IdentifierList):
            for ident in token.get_identifiers():
                col = ident.get_name()
                if col:
                    columns.append(col)
        elif isinstance(token, sqlparse.sql.Identifier):
            col = token.get_name()
            if col:
                columns.append(col)
        idx += 1
    return columns

# End of core.py