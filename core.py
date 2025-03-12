#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
core.py – Core Foundation Utilities for the BRM Tool

Features:
  • Robust logging configuration and email notification setup.
  • Production‑ready DatabaseConnectionDialog (using PyQt5) for establishing DB connections.
  • Comprehensive DB helper functions (fetch_all_dict, fetch_one_dict, audit logging).
  • Advanced locking functions to prevent concurrent edits.
  • Advanced SQL parsing functions using sqlparse to extract table dependencies,
    handle CTEs, subqueries, and aliases.
  
All functions include robust error handling and proper logging.
"""

import sys
import os
import json
import math
import smtplib
import logging
import pyodbc
import sqlparse
import re
import csv
import time

from datetime import datetime, date, time, timedelta
from collections import deque
from email.mime.text import MIMEText

# ----------------------------
# Logging Configuration
# ----------------------------
LOG_FILE = 'brm_tool_enhanced.log'
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

# ----------------------------
# Email Configuration & Sender
# ----------------------------
EMAIL_CONFIG = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "your_smtp_user",
    "smtp_password": "your_smtp_pass",
    "sender_email": "noreply@example.com"
}

def send_email_notification(subject: str, body: str, recipients: list):
    """
    Send an email using SMTP with TLS.
    Raises an exception if sending fails.
    """
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
        logger.error(f"Error sending email to {recipients}: {ex}")
        raise

# ----------------------------
# Database Connection Dialog
# ----------------------------
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit, QHBoxLayout, QPushButton, QMessageBox

class DatabaseConnectionDialog(QDialog):
    """
    Provides a dialog for the user to select an ODBC DSN or enter a custom connection string.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.connection = None
        self.setWindowTitle("DB Connection – BRM Tool")
        self.resize(400, 200)
        main_layout = QVBoxLayout(self)
        
        lbl = QLabel("Select an ODBC DSN or provide a custom connection string:")
        main_layout.addWidget(lbl)
        
        self.conn_type_combo = QComboBox()
        try:
            dsn_dict = pyodbc.dataSources()
            for dsn_name, driver in dsn_dict.items():
                if "SQL SERVER" in driver.upper():
                    self.conn_type_combo.addItem(f"ODBC DSN: {dsn_name}", dsn_name)
        except Exception as e:
            logger.error(f"Error listing DSNs: {e}")
        main_layout.addWidget(self.conn_type_combo)
        
        self.conn_str_edit = QLineEdit()
        self.conn_str_edit.setPlaceholderText("Or enter custom ODBC connection string")
        main_layout.addWidget(self.conn_str_edit)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Connect")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)

    def get_connection(self):
        override = self.conn_str_edit.text().strip()
        if override:
            conn_str = override
        else:
            choice = self.conn_type_combo.currentData()
            if not choice:
                QMessageBox.critical(self, "Error", "No DSN or connection string selected.")
                return None
            conn_str = f"DSN={choice};Trusted_Connection=yes;"
        try:
            connection = pyodbc.connect(conn_str)
            logger.info("Database connection established.")
            return connection
        except Exception as ex:
            QMessageBox.critical(self, "Connection Error", str(ex))
            logger.error(f"Database connection failed: {ex}")
            return None

# ----------------------------
# DB Helper Functions
# ----------------------------
def fetch_all_dict(cursor):
    """
    Returns all fetched rows as a list of dictionaries.
    """
    rows = cursor.fetchall()
    if cursor.description:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    return rows

def fetch_one_dict(cursor):
    """
    Returns a single row as a dictionary.
    """
    row = cursor.fetchone()
    if row and cursor.description:
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    return None

def insert_audit_log(conn, action, table_name, record_id, actor, old_data, new_data):
    """
    Inserts a record into the audit log table.
    """
    c = conn.cursor()
    c.execute("""
    INSERT INTO BRM_AUDIT_LOG(
        ACTION, TABLE_NAME, RECORD_ID, ACTION_BY, OLD_DATA, NEW_DATA, ACTION_TIMESTAMP
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
    logger.debug(f"Audit log inserted for action '{action}' on {table_name} (Record: {record_id}).")

# ----------------------------
# Locking Functions
# ----------------------------
def lock_rule(conn, rule_id, locked_by, force=False):
    """
    Acquires a lock on a rule to prevent concurrent edits.
    Automatically cleans up locks older than 30 minutes.
    """
    c = conn.cursor()
    # Clean up stale locks
    c.execute("DELETE FROM RULE_LOCKS WHERE DATEDIFF(MINUTE, LOCK_TIMESTAMP, GETDATE()) > 30")
    conn.commit()
    
    c.execute("SELECT LOCKED_BY FROM RULE_LOCKS WHERE RULE_ID = ?", (rule_id,))
    row = c.fetchone()
    if row:
        current_lock = row[0]
        if current_lock != locked_by and not force:
            error_msg = f"Rule {rule_id} is already locked by {current_lock}."
            logger.warning(error_msg)
            raise ValueError(error_msg)
        else:
            c.execute("DELETE FROM RULE_LOCKS WHERE RULE_ID = ?", (rule_id,))
    c.execute("INSERT INTO RULE_LOCKS (RULE_ID, LOCKED_BY, LOCK_TIMESTAMP) VALUES (?, ?, GETDATE())", (rule_id, locked_by))
    conn.commit()
    logger.debug(f"Rule {rule_id} locked by {locked_by}.")

def unlock_rule(conn, rule_id, locked_by, force=False):
    """
    Releases a lock on a rule.
    """
    c = conn.cursor()
    c.execute("SELECT LOCKED_BY FROM RULE_LOCKS WHERE RULE_ID = ?", (rule_id,))
    row = c.fetchone()
    if row:
        current_lock = row[0]
        if current_lock != locked_by and not force:
            error_msg = f"Cannot unlock rule {rule_id} locked by {current_lock}."
            logger.warning(error_msg)
            raise ValueError(error_msg)
    c.execute("DELETE FROM RULE_LOCKS WHERE RULE_ID = ?", (rule_id,))
    conn.commit()
    logger.debug(f"Rule {rule_id} unlocked by {locked_by}.")

# ----------------------------
# Advanced SQL Parsing Functions
# ----------------------------
def parse_sql_dependencies(sql_text: str):
    """
    Parses the given SQL text and extracts dependencies:
      - Tables referenced (including in CTEs and subqueries)
      - CTE names and their definitions
      - Alias mappings and selected columns
    Returns a dictionary with keys: 'tables', 'cte_tables', 'alias_map', 'columns'
    """
    statements = sqlparse.parse(sql_text)
    all_tables = []
    cte_info = {}
    alias_map = {}
    columns = []
    
    for stmt in statements:
        # Process WITH clauses for CTEs
        cte_map = _extract_with_clauses(stmt)
        cte_info.update(cte_map)
        # Process main query to get tables and aliases, excluding CTE names
        main_tables, main_aliases = _extract_main_from(stmt.tokens, set(cte_map.keys()))
        all_tables.extend(main_tables)
        alias_map.update(main_aliases)
        # Process column selections
        cols = _extract_columns(stmt)
        columns.extend(cols)
        
    return {
        "tables": list(set(all_tables)),
        "cte_tables": cte_info,
        "alias_map": alias_map,
        "columns": columns
    }

def _extract_with_clauses(statement):
    """
    Extracts CTE definitions from a SQL statement.
    Returns a dictionary mapping CTE name to a list of table dependencies extracted from its subquery.
    """
    cte_map = {}
    tokens = list(statement.tokens)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.Keyword and token.value.upper() == "WITH":
            i += 1
            i = _parse_cte_block(tokens, i, cte_map)
        else:
            i += 1
    return cte_map

def _parse_cte_block(tokens, i, cte_map):
    """
    Parses the tokens for a CTE block.
    """
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.Keyword and token.value.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            return i
        if isinstance(token, sqlparse.sql.Identifier):
            cte_name = token.get_real_name()
            i += 1
            i = _parse_cte_as_clause(tokens, i, cte_name, cte_map)
        else:
            i += 1
    return i

def _parse_cte_as_clause(tokens, i, cte_name, cte_map):
    """
    Parses the AS clause for a given CTE.
    """
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.Keyword and token.value.upper() == "AS":
            i += 1
            if i < len(tokens):
                subquery = tokens[i]
                if isinstance(subquery, sqlparse.sql.Parenthesis):
                    sub_refs = _extract_subselect_tokens(subquery.tokens)
                    cte_map[cte_name] = sub_refs
                    i += 1
                    return i
        else:
            i += 1
    return i

def _extract_subselect_tokens(tokens):
    """
    Recursively extracts table references from a subquery.
    Returns a list of tuples: (schema_name, table_name, alias, is_subquery)
    """
    results = []
    i = 0
    from_seen = False
    while i < len(tokens):
        token = tokens[i]
        if token.is_group and _is_subselect(token):
            results.extend(_extract_subselect_tokens(token.tokens))
        if token.ttype is sqlparse.tokens.Keyword:
            if token.value.upper() in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN"):
                from_seen = True
            else:
                from_seen = False
        if from_seen:
            if isinstance(token, sqlparse.sql.IdentifierList):
                for identifier in token.get_identifiers():
                    res = _parse_identifier(identifier, set())
                    results.append((*res, True))
            elif isinstance(token, sqlparse.sql.Identifier):
                res = _parse_identifier(token, set())
                results.append((*res, True))
        i += 1
    return results

def _is_subselect(token):
    if not token.is_group:
        return False
    for t in token.tokens:
        if t.ttype is sqlparse.tokens.DML and t.value.upper() == "SELECT":
            return True
    return False

def _extract_main_from(token_list, known_cte_names):
    """
    Extracts main FROM clause references and builds an alias mapping.
    Returns a tuple (list of table references, alias_map) where each table reference is a tuple
    (schema_name, table_name, alias, is_subquery).
    """
    results = []
    alias_map = {}
    tokens = list(token_list)
    from_seen = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.is_group and _is_subselect(token):
            results.extend(_extract_subselect_tokens(token.tokens))
        if token.ttype is sqlparse.tokens.Keyword:
            if token.value.upper() in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN"):
                from_seen = True
            else:
                from_seen = False
        if from_seen:
            if isinstance(token, sqlparse.sql.IdentifierList):
                for identifier in token.get_identifiers():
                    res = _parse_identifier(identifier, known_cte_names)
                    results.append(res)
                    if res[2]:
                        alias_map[res[2]] = (res[0], res[1])
            elif isinstance(token, sqlparse.sql.Identifier):
                res = _parse_identifier(token, known_cte_names)
                results.append(res)
                if res[2]:
                    alias_map[res[2]] = (res[0], res[1])
        i += 1
    return results, alias_map

def _parse_identifier(identifier, known_cte_names):
    """
    Parses an identifier to extract (schema_name, table_name, alias, is_subquery flag).
    """
    alias = identifier.get_alias()
    real_name = identifier.get_real_name()
    schema = identifier.get_parent_name()
    if real_name and real_name.upper() in (name.upper() for name in known_cte_names):
        return (None, f"(CTE) {real_name}", alias, False)
    return (schema, real_name, alias, False)

def _extract_columns(statement):
    """
    Extracts column names from a SELECT or DML statement.
    Returns a list of tuples: (column_name, is_dml, is_select)
    """
    results = []
    tokens = list(statement.tokens)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.DML:
            word = token.value.upper()
            if word == "SELECT":
                cols = _parse_select_list(tokens, i + 1)
                results.extend([(col, False, True) for col in cols])
            elif word in ("INSERT", "UPDATE"):
                cols = _parse_dml_columns(tokens, i, word)
                results.extend([(col, True, False) for col in cols])
        i += 1
    return results

def _parse_select_list(tokens, start_idx):
    """
    Parses the select list to extract column names.
    """
    columns = []
    i = start_idx
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.Keyword and token.value.upper() in ("FROM", "JOIN", "WHERE", "GROUP", "ORDER", "UNION", "INTERSECT"):
            break
        if isinstance(token, sqlparse.sql.IdentifierList):
            for identifier in token.get_identifiers():
                name = identifier.get_name()
                if name and name.upper() not in ("DISTINCT", "TOP", "ALL"):
                    columns.append(name)
        elif isinstance(token, sqlparse.sql.Identifier):
            name = token.get_name()
            if name and name.upper() not in ("DISTINCT", "TOP", "ALL"):
                columns.append(name)
        i += 1
    return columns

def _parse_dml_columns(tokens, start_idx, dml_word):
    """
    Parses the columns for INSERT or UPDATE statements.
    """
    columns = []
    if dml_word.upper() == "INSERT":
        i = start_idx
        while i < len(tokens):
            token = tokens[i]
            if token.is_group and token.__class__.__name__ == "Parenthesis":
                for sub in token.tokens:
                    if isinstance(sub, sqlparse.sql.IdentifierList):
                        for identifier in sub.get_identifiers():
                            columns.append(identifier.get_name())
                    elif isinstance(sub, sqlparse.sql.Identifier):
                        columns.append(sub.get_name())
                return columns
            i += 1
    elif dml_word.upper() == "UPDATE":
        found_set = False
        i = start_idx
        while i < len(tokens):
            token = tokens[i]
            if token.ttype is sqlparse.tokens.Keyword and token.value.upper() == "SET":
                found_set = True
                i += 1
                columns.extend(_parse_update_set_list(tokens, i))
                break
            i += 1
    return columns

def _parse_update_set_list(tokens, start_idx):
    """
    Parses the list of columns in the SET clause of an UPDATE.
    """
    columns = []
    i = start_idx
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is sqlparse.tokens.Keyword and token.value.upper() in ("WHERE", "FROM"):
            break
        if isinstance(token, sqlparse.sql.Identifier):
            columns.append(token.get_name())
        i += 1
    return columns

# ----------------------------
# End of core.py
if __name__ == '__main__':
    # For testing purposes: run the SQL parser on sample SQL
    sample_sql = """
    WITH cte AS (
        SELECT id, name FROM dbo.Customers WHERE active=1
    )
    SELECT a.id, a.value, b.description
    FROM dbo.TableA a
    INNER JOIN dbo.TableB b ON a.id = b.aid
    LEFT JOIN cte ON a.cid = cte.id
    """
    parsed = parse_sql_dependencies(sample_sql)
    print("Parsed SQL Dependencies:")
    print(json.dumps(parsed, indent=2))