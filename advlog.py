#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
advanced_logging.py – Advanced Logging Module for the BRM Tool

Features:
  • Configures logging for the entire application.
  • Provides helper functions to log errors, simulation details, and audit events.
  • Includes a function (log_simulation_result) that captures and logs:
      - Simulation name
      - Number of records impacted
      - Success/fail outcome
      - Additional custom message details
  • Uses standard formatting and can easily be extended to log to multiple handlers (e.g., file, console, remote).

Usage:
  Import functions such as log_simulation_result or log_event in your modules to record simulation outcomes.
  
Example:
    from advanced_logging import log_simulation_result
    log_simulation_result("DryRun Simulation", record_count=125, success=True, message="All validations passed")
"""

import logging
import json

# Configure a global logger
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
logging.basicConfig(
    filename="brm_tool_production.log",
    level=logging.DEBUG,
    format=LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("BRMTool")

# Optionally add a console handler for development
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(LOG_FORMAT)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


def log_event(event_name: str, details: dict):
    """
    Log a general event with the provided details.
    
    Args:
        event_name (str): The name of the event (e.g., 'RuleCreated', 'SimulationRun').
        details (dict): A dictionary containing event details.
    """
    try:
        logger.info(f"{event_name} - {json.dumps(details)}")
    except Exception as ex:
        logger.error(f"Error logging event {event_name}: {ex}")


def log_simulation_result(simulation_name: str, record_count: int, success: bool, message: str):
    """
    Log the result of a simulation (e.g., dry run) capturing:
      - Simulation name
      - Number of records impacted
      - Success flag
      - Message details
    
    Args:
        simulation_name (str): Name or description of the simulation.
        record_count (int): Number of records impacted by the simulation.
        success (bool): True if simulation passed; False otherwise.
        message (str): Additional message details.
    """
    event_details = {
        "simulation": simulation_name,
        "record_count": record_count,
        "success": success,
        "message": message
    }
    log_event("SimulationResult", event_details)


def log_error(module_name: str, error_message: str, exception_obj: Exception = None):
    """
    Log an error event with module context.
    
    Args:
        module_name (str): Name of the module where the error occurred.
        error_message (str): A descriptive error message.
        exception_obj (Exception, optional): The exception object if available.
    """
    details = {"module": module_name, "error": error_message}
    if exception_obj:
        details["exception"] = str(exception_obj)
    logger.error(f"Error in {module_name} - {json.dumps(details)}")


# For standalone testing:
if __name__ == '__main__':
    log_simulation_result("DryRunTest", record_count=200, success=True, message="Test passed with no issues.")
    log_error("advanced_logging", "This is a test error", Exception("Test exception"))