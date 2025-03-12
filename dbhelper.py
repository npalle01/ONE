#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
db_connection_helpers.py – Database Connection and Helper Module for the BRM Tool

Features:
  • Robust ODBC connection dialog with enhanced error handling and logging.
  • Helper functions:
      - fetch_all_dict: Returns query results as a list of dictionaries.
      - fetch_one_dict: Returns a single row as a dictionary.
      - insert_audit_log: Inserts audit records (including simulation logs with impacted record counts).
  • Secure LoginDialog that verifies credentials against the USERS table.
  • Advanced logging: All operations are logged with detailed information for tracing and simulations.
  
Dependencies:
  • pyodbc, PyQt5, logging, json, datetime

Usage:
  Import this module to establish the database connection, perform logging, and handle user login.
  
Example:
    from db_connection_helpers import DatabaseConnectionDialog, LoginDialog, fetch_all_dict
    # Create and display the connection dialog:
    dlg = DatabaseConnectionDialog()
    if dlg.exec_() == QDialog.Accepted:
        conn = dlg.get_connection()
        if conn:
            login = LoginDialog(conn)
            if login.exec_() == QDialog.Accepted:
                print(f"Logged in as user_id: {login.user_id}, group: {login.user_group}")
"""

import sys
import json
import logging
import pyodbc
from datetime import datetime
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
)

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('brm_tool_advanced.log')
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:%(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class DatabaseConnectionDialog(QtWidgets.QDialog):
    """
    Robust connection dialog for establishing an ODBC connection to SQL Server.
    
    The dialog presents a combo-box of available DSNs and an optional custom connection string.
    On successful connection, the connection object is returned.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.connection = None
        self.setWindowTitle("Database Connection – BRM Tool")
        self.resize(400, 200)

        layout = QVBoxLayout(self)
        label = QLabel("Select an ODBC DSN or provide a custom connection string:")
        layout.addWidget(label)

        self.dsn_combo = QtWidgets.QComboBox()
        try:
            dsn_dict = pyodbc.dataSources()
            for dsn_name, driver in dsn_dict.items():
                if "SQL SERVER" in driver.upper():
                    self.dsn_combo.addItem(f"DSN: {dsn_name}", dsn_name)
        except Exception as ex:
            logger.error(f"Error retrieving DSNs: {ex}")
        layout.addWidget(self.dsn_combo)

        self.conn_str_edit = QLineEdit()
        self.conn_str_edit.setPlaceholderText("Custom connection string (optional)")
        layout.addWidget(self.conn_str_edit)

        button_layout = QtWidgets.QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(connect_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def get_connection(self):
        override = self.conn_str_edit.text().strip()
        if override:
            conn_str = override
        else:
            dsn = self.dsn_combo.currentData()
            if not dsn:
                QMessageBox.critical(self, "Error", "No DSN selected or connection string provided.")
                return None
            conn_str = f"DSN={dsn};Trusted_Connection=yes;"
        try:
            conn = pyodbc.connect(conn_str)
            logger.info(f"Connected to database using: {conn_str}")
            return conn
        except Exception as ex:
            QMessageBox.critical(self, "Connection Error", f"Error connecting to database: {ex}")
            logger.error(f"Database connection failed with '{conn_str}': {ex}")
            return None


def fetch_all_dict(cursor):
    """
    Returns all rows from the cursor as a list of dictionaries.
    """
    try:
        rows = cursor.fetchall()
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return result
        return rows
    except Exception as ex:
        logger.error(f"Error fetching all rows as dict: {ex}")
        return []


def fetch_one_dict(cursor):
    """
    Returns one row from the cursor as a dictionary.
    """
    try:
        row = cursor.fetchone()
        if row and cursor.description:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return row
    except Exception as ex:
        logger.error(f"Error fetching one row as dict: {ex}")
        return None


def insert_audit_log(conn, action, table_name, record_id, actor, old_data, new_data):
    """
    Inserts an audit log record into the BRM_AUDIT_LOG table.
    
    Both old_data and new_data are stored as JSON strings.
    This function also logs the action for simulation tracking.
    """
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO BRM_AUDIT_LOG
            (ACTION, TABLE_NAME, RECORD_ID, ACTION_BY, OLD_DATA, NEW_DATA, ACTION_TIMESTAMP)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE())
        """, (
            action,
            table_name,
            str(record_id) if record_id is not None else None,
            actor,
            json.dumps(old_data) if old_data is not None else None,
            json.dumps(new_data) if new_data is not None else None
        ))
        conn.commit()
        logger.info(f"Audit log recorded for action '{action}' on table '{table_name}' (record {record_id}).")
    except Exception as ex:
        logger.error(f"Error inserting audit log: {ex}")


class LoginDialog(QDialog):
    """
    Secure login dialog for the BRM Tool.
    
    Validates the username and password against the USERS table.
    On successful login, the user_id and user_group are stored.
    """
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.user_id = None
        self.user_group = None
        self.setWindowTitle("Login – BRM Tool")
        self.resize(300, 150)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Username:"))
        self.username_edit = QLineEdit()
        layout.addWidget(self.username_edit)

        layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit)

        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self.do_login)
        layout.addWidget(login_btn)

        self.setLayout(layout)

    def do_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()
        if not username or not password:
            QMessageBox.warning(self, "Input Error", "Please enter both username and password.")
            return
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT USER_ID, USER_GROUP
                FROM USERS
                WHERE USERNAME = ? AND PASSWORD = ?
            """, (username, password))
            row = fetch_one_dict(cursor)
            if row:
                self.user_id = row["USER_ID"]
                self.user_group = row["USER_GROUP"]
                logger.info(f"User '{username}' logged in successfully.")
                self.accept()
            else:
                QMessageBox.warning(self, "Login Failed", "Invalid username or password.")
                logger.warning(f"Failed login attempt for username: {username}")
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"Error during login: {ex}")
            logger.error(f"Login error for username '{username}': {ex}")


# For standalone testing
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    conn_dlg = DatabaseConnectionDialog()
    if conn_dlg.exec_() == QDialog.Accepted:
        connection = conn_dlg.get_connection()
        if connection:
            login_dlg = LoginDialog(connection)
            if login_dlg.exec_() == QDialog.Accepted:
                print(f"Logged in as user_id: {login_dlg.user_id}, group: {login_dlg.user_group}")
    sys.exit(0)