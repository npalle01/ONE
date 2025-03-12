# authentication.py
import sys
import json
import hashlib
from datetime import datetime
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox
)
from core import logger, insert_audit_log  # Import from module1 (core.py)

def hash_password(password: str) -> str:
    """
    Returns the SHA-256 hash of the given password.
    (In production, consider using a stronger salted hash like bcrypt.)
    """
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def authenticate_user(conn, username: str, password: str) -> dict:
    """
    Authenticates a user given username and password.
    This function queries the USERS table.
    It supports both plain-text (for backward compatibility) and hashed passwords.
    Returns a dictionary with keys 'user_id', 'user_group', and 'username' on success.
    Raises a ValueError on failure.
    """
    cursor = conn.cursor()
    try:
        # Attempt to fetch user record. Expecting columns: USER_ID, USERNAME, PASSWORD, USER_GROUP.
        cursor.execute("""
            SELECT USER_ID, USERNAME, PASSWORD, USER_GROUP
            FROM USERS
            WHERE USERNAME = ?
        """, (username,))
        user = cursor.fetchone()
        if not user:
            logger.warning(f"Authentication failed for non-existent user: {username}")
            raise ValueError("Invalid credentials.")
        user_id, uname, stored_password, user_group = user

        # Check if stored password is in hashed format (e.g. length 64 for SHA-256)
        if len(stored_password) == 64:
            input_password_hash = hash_password(password)
            if input_password_hash != stored_password:
                logger.warning(f"Authentication failed for user {username}: invalid hashed password.")
                raise ValueError("Invalid credentials.")
        else:
            # Assume plain-text for legacy reasons (not recommended)
            if password != stored_password:
                logger.warning(f"Authentication failed for user {username}: invalid plain-text password.")
                raise ValueError("Invalid credentials.")

        logger.info(f"User {username} authenticated successfully.")
        return {"user_id": user_id, "username": uname, "user_group": user_group}
    except Exception as ex:
        logger.error(f"Error during authentication for user {username}: {ex}")
        raise

class LoginDialog(QDialog):
    """
    A robust login dialog that validates user credentials against the database.
    It supports secure (hashed) password checking and records audit logs for login attempts.
    """
    def __init__(self, conn, parent=None):
        super(LoginDialog, self).__init__(parent)
        self.connection = conn
        self.setWindowTitle("Login")
        self.resize(300, 150)
        self.user_info = None  # Will store a dict with user_id, username, user_group

        # Create UI elements
        layout = QVBoxLayout(self)

        user_label = QLabel("Username:")
        self.user_edit = QLineEdit()
        layout.addWidget(user_label)
        layout.addWidget(self.user_edit)

        pass_label = QLabel("Password:")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(pass_label)
        layout.addWidget(self.pass_edit)

        btn_layout = QHBoxLayout()
        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self.do_login)
        btn_layout.addWidget(login_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def do_login(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text().strip()
        if not username or not password:
            QMessageBox.warning(self, "Input Error", "Please enter both username and password.")
            return

        try:
            user_info = authenticate_user(self.connection, username, password)
            self.user_info = user_info
            # Record successful login audit log
            insert_audit_log(
                self.connection,
                action="LOGIN_SUCCESS",
                table_name="USERS",
                record_id=user_info["user_id"],
                actor=username,
                old_data=None,
                new_data={"login_time": datetime.now().isoformat()}
            )
            self.accept()
        except Exception as ex:
            # Record failed login audit log
            insert_audit_log(
                self.connection,
                action="LOGIN_FAILED",
                table_name="USERS",
                record_id=None,
                actor=username,
                old_data=None,
                new_data={"error": str(ex), "attempt_time": datetime.now().isoformat()}
            )
            QMessageBox.critical(self, "Authentication Failed", str(ex))