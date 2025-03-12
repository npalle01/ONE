
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
advanced_sql_parser.py – Advanced SQL Parsing Module for the BRM Tool

Features:
  • detect_operation_type: Determines the type of SQL operation (INSERT/UPDATE/DELETE/SELECT/DECISION_TABLE/OTHER).
  • parse_sql_dependencies: Parses SQL statements using sqlparse to extract:
      - Tables (including those in subselects and CTEs)
      - CTE definitions
      - Alias mapping
      - Columns referenced in SELECT and DML clauses.
  • Fully implemented helper functions:
      - _extract_with_clauses, _parse_cte_block, _parse_cte_as_clause
      - _extract_subselect_tokens, _is_subselect, _extract_main_from, _parse_identifier
      - _extract_columns, _parse_select_list, _parse_dml_columns, _parse_update_set_list
  • Comprehensive logging and error handling for production readiness.

Dependencies:
  • sqlparse, logging, json

Usage:
  Import and call the functions to determine the operation type or parse SQL dependencies.
  
Example:
    from advanced_sql_parser import detect_operation_type, parse_sql_dependencies
    op_type = detect_operation_type("SELECT * FROM Customers")
    dependencies = parse_sql_dependencies("WITH cte AS (SELECT id FROM Orders) SELECT * FROM cte JOIN Customers ON cte.id=Customers.id")
"""

import logging
import json
import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis
from sqlparse.tokens import Keyword, DML

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# --- Public Functions ---

def detect_operation_type(rule_sql: str, decision_table_id=None) -> str:
    """
    Determine the SQL operation type based on the rule SQL.
    If rule_sql is empty but decision_table_id is provided, returns 'DECISION_TABLE'.
    Otherwise, returns one of: INSERT, UPDATE, DELETE, SELECT, or OTHER.
    """
    try:
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
        else:
            return "OTHER"
    except Exception as ex:
        logger.error(f"Error in detect_operation_type: {ex}")
        return "OTHER"


def parse_sql_dependencies(sql_text: str) -> dict:
    """
    Parse the provided SQL text to extract:
      - A unique list of table references.
      - Information about CTEs (Common Table Expressions).
      - Alias mapping (alias to actual table reference).
      - Column references from SELECT or DML statements.
      
    Returns a dictionary with keys:
      'tables': list of tuples (schema, table, alias, is_subselect)
      'cte_tables': list of tuples (cte_name, list of its table references)
      'alias_map': dict mapping alias -> (schema, table)
      'columns': list of tuples (column_name, is_write, is_read)
    """
    dependencies = {
        "tables": [],
        "cte_tables": [],
        "alias_map": {},
        "columns": []
    }
    try:
        statements = sqlparse.parse(sql_text)
        for stmt in statements:
            ctes = _extract_with_clauses(stmt)
            for cte_name, cte_refs in ctes.items():
                dependencies["cte_tables"].append((cte_name, cte_refs))
            main_tables, alias_map = _extract_main_from(stmt.tokens, set(ctes.keys()))
            dependencies["tables"].extend(main_tables)
            dependencies["alias_map"].update(alias_map)
            cols = _extract_columns(stmt)
            dependencies["columns"].extend(cols)
        # Ensure uniqueness of table references
        dependencies["tables"] = list({tbl: tbl for tbl in dependencies["tables"]}.values())
        return dependencies
    except Exception as ex:
        logger.error(f"Error in parse_sql_dependencies: {ex}")
        return dependencies

# --- Helper Functions for SQL Parsing ---

def _extract_with_clauses(statement) -> dict:
    """
    Extracts CTE definitions from a SQL statement.
    Returns a dictionary mapping CTE names to their extracted table references.
    """
    cte_map = {}
    tokens = list(statement.tokens)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is Keyword and token.value.upper() == "WITH":
            i += 1
            i = _parse_cte_block(tokens, i, cte_map)
        else:
            i += 1
    return cte_map

def _parse_cte_block(tokens, i: int, cte_map: dict) -> int:
    """
    Parses the tokens following a WITH keyword to extract CTE definitions.
    """
    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, Identifier):
            cte_name = token.get_real_name()
            i += 1
            i = _parse_cte_as_clause(tokens, i, cte_name, cte_map)
        elif token.ttype is Keyword and token.value.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            return i
        else:
            i += 1
    return i

def _parse_cte_as_clause(tokens, i: int, cte_name: str, cte_map: dict) -> int:
    """
    Parses the AS clause for a given CTE and stores its subselect table references.
    """
    while i < len(tokens):
        token = tokens[i]
        if token.value.upper() == "AS":
            i += 1
            if i < len(tokens):
                sub_token = tokens[i]
                if isinstance(sub_token, Parenthesis):
                    sub_refs = _extract_subselect_tokens(sub_token.tokens)
                    cte_map[cte_name] = sub_refs
                    i += 1
                    return i
        else:
            i += 1
    return i

def _extract_subselect_tokens(tokens) -> list:
    """
    Extract table references from a list of tokens inside a subselect.
    Returns a list of tuples: (schema, table, alias, is_subselect=True).
    """
    results = []
    from_seen = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.is_group and _is_subselect(token):
            results.extend(_extract_subselect_tokens(token.tokens))
        if token.ttype is Keyword:
            value = token.value.upper()
            if value in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN"):
                from_seen = True
            else:
                from_seen = False
        if from_seen:
            if isinstance(token, IdentifierList):
                for ident in token.get_identifiers():
                    ref = _parse_identifier(ident, set())
                    # Mark as coming from subselect
                    results.append((ref[0], ref[1], ref[2], True))
            elif isinstance(token, Identifier):
                ref = _parse_identifier(token, set())
                results.append((ref[0], ref[1], ref[2], True))
        i += 1
    return results

def _is_subselect(token) -> bool:
    """
    Determines if a token contains a subselect.
    """
    if not token.is_group:
        return False
    for subtoken in token.tokens:
        if subtoken.ttype is DML and subtoken.value.upper() == "SELECT":
            return True
    return False

def _extract_main_from(token_list, known_cte_names: set) -> tuple:
    """
    Extracts table references and alias mappings from the main part of a SQL statement,
    excluding any CTEs that are defined in known_cte_names.
    
    Returns a tuple (results, alias_map), where results is a list of table reference tuples,
    and alias_map is a dict mapping alias names to (schema, table) tuples.
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
        if token.ttype is Keyword:
            val = token.value.upper()
            if val in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN"):
                from_seen = True
            else:
                from_seen = False
        if from_seen:
            if isinstance(token, IdentifierList):
                for ident in token.get_identifiers():
                    ref = _parse_identifier(ident, known_cte_names)
                    results.append(ref)
                    if ref[2]:
                        alias_map[ref[2]] = (ref[0], ref[1])
            elif isinstance(token, Identifier):
                ref = _parse_identifier(token, known_cte_names)
                results.append(ref)
                if ref[2]:
                    alias_map[ref[2]] = (ref[0], ref[1])
        i += 1
    return (results, alias_map)

def _parse_identifier(ident, known_cte_names: set) -> tuple:
    """
    Parse an Identifier token to extract schema name, real table name, and alias.
    If the real table name is in known_cte_names, it returns a special tuple indicating a CTE.
    """
    alias = ident.get_alias()
    real_name = ident.get_real_name()
    schema_name = ident.get_parent_name()
    if real_name and real_name.upper() in {n.upper() for n in known_cte_names}:
        return (None, f"(CTE) {real_name}", alias, False)
    return (schema_name, real_name, alias, False)

def _extract_columns(statement) -> list:
    """
    Extracts column names from the given SQL statement.
    Returns a list of tuples: (column_name, is_write, is_read)
    """
    results = []
    tokens = list(statement.tokens)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is DML:
            word = token.value.upper()
            if word == "SELECT":
                select_cols = _parse_select_list(tokens, i + 1)
                for col in select_cols:
                    results.append((col, False, True))
            elif word in ("INSERT", "UPDATE"):
                dml_cols = _parse_dml_columns(tokens, i, word)
                for col in dml_cols:
                    results.append((col, True, False))
        i += 1
    return results

def _parse_select_list(tokens, start_idx: int) -> list:
    """
    Parse the tokens following a SELECT to extract column names.
    """
    columns = []
    i = start_idx
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is Keyword:
            if token.value.upper() in ("FROM", "JOIN", "WHERE", "GROUP", "ORDER", "UNION", "INTERSECT"):
                break
        if isinstance(token, IdentifierList):
            for ident in token.get_identifiers():
                name = ident.get_name()
                if name and name.upper() not in ("DISTINCT", "TOP", "ALL"):
                    columns.append(name)
        elif isinstance(token, Identifier):
            name = token.get_name()
            if name and name.upper() not in ("DISTINCT", "TOP", "ALL"):
                columns.append(name)
        i += 1
    return columns

def _parse_dml_columns(tokens, start_idx: int, dml_word: str) -> list:
    """
    Parse the tokens for INSERT or UPDATE statements to extract column names.
    """
    columns = []
    if dml_word == "INSERT":
        i = start_idx
        while i < len(tokens):
            token = tokens[i]
            if token.is_group and isinstance(token, sqlparse.sql.Parenthesis):
                # Inside parenthesis, columns may be listed as an IdentifierList or single Identifier
                for subtoken in token.tokens:
                    if isinstance(subtoken, IdentifierList):
                        for ident in subtoken.get_identifiers():
                            columns.append(ident.get_name())
                    elif isinstance(subtoken, Identifier):
                        columns.append(subtoken.get_name())
                return columns
            i += 1
    elif dml_word == "UPDATE":
        found_set = False
        i = start_idx
        while i < len(tokens):
            token = tokens[i]
            if token.ttype is Keyword and token.value.upper() == "SET":
                found_set = True
                i += 1
                columns.extend(_parse_update_set_list(tokens, i))
                break
            i += 1
    return columns

def _parse_update_set_list(tokens, start_i: int) -> list:
    """
    Parse the tokens following the SET keyword in an UPDATE statement.
    """
    columns = []
    i = start_i
    while i < len(tokens):
        token = tokens[i]
        if token.ttype is Keyword and token.value.upper() in ("WHERE", "FROM"):
            break
        if isinstance(token, Identifier):
            columns.append(token.get_name())
        i += 1
    return columns


# For standalone testing
if __name__ == '__main__':
    sample_sql = """
    WITH cte AS (
        SELECT id, name FROM Orders
    )
    SELECT cte.id, cte.name, cust.CustomerName
    FROM cte
    JOIN Customers AS cust ON cte.id = cust.OrderID
    WHERE cust.Country = 'USA'
    """
    op = detect_operation_type(sample_sql)
    deps = parse_sql_dependencies(sample_sql)
    print("Operation Type:", op)
    print("Dependencies:", json.dumps(deps, indent=2))