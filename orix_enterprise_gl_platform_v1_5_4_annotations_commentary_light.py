# orix_enterprise_gl_platform.py
# Enterprise-grade PyQt6 prototype (single-file, embedded demo data)
# Install: pip install PyQt6 pandas numpy
# Run:     python orix_enterprise_gl_platform.py

import sys
import re
import json
import zipfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt
from PyQt6.QtGui import QAction, QFont, QGuiApplication, QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QInputDialog,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QStackedWidget, QStatusBar, QDockWidget,
    QStyledItemDelegate, QStyleOptionViewItem, QTableView, QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QMenu
)

APP_NAME = "ORIX | Enterprise GL Platform (Prototype)"
APP_VERSION = "v1.5-demo"

# ----------------------------
# Helpers
# ----------------------------

def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, float) and np.isnan(x):
            return default
        return float(x)
    except Exception:
        return default

def fmt_money(x: Any) -> str:
    v = safe_float(x, 0.0)
    s = f"{abs(v):,.0f}" if abs(v) >= 1e6 else f"{abs(v):,.2f}"
    return f"({s})" if v < 0 else s

def fmt_big(x: Any) -> str:
    v = safe_float(x, 0.0)
    av = abs(v)
    if av >= 1e9:
        return f"{v/1e9:.2f}B"
    if av >= 1e6:
        return f"{v/1e6:.2f}M"
    if av >= 1e3:
        return f"{v/1e3:.2f}K"
    return f"{v:.2f}"

def fmt_pct(x: float) -> str:
    x = max(0.0, min(1.0, float(x)))
    return f"{x*100:.1f}%"

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def new_id(prefix: str) -> str:
    return f"{prefix}-{np.random.randint(10000, 99999)}"

def severity_from_amt(amt: Any, materiality: float) -> str:
    a = abs(safe_float(amt, 0.0))
    if a >= materiality:
        return "MATERIAL"
    if a >= materiality * 0.25:
        return "HIGH"
    if a >= materiality * 0.10:
        return "MEDIUM"
    return "LOW"

def sla_status(age_days: int, sla_days: int) -> str:
    if sla_days <= 0:
        return "AT_RISK"
    ratio = age_days / float(sla_days)
    if ratio >= 1.0:
        return "BREACHED"
    if ratio >= 0.7:
        return "AT_RISK"
    return "ON_TRACK"

# ----------------------------
# Embedded demo data (shape-safe)
# ----------------------------

def seed_data() -> Dict[str, Any]:
    entities = ["US_HOLDCO", "US_BANK", "UK_BRANCH"]
    books = ["GAAP", "STAT"]
    currencies = ["USD", "GBP"]
    products = ["LOANS", "DEPOSITS", "TRADING", "TREASURY"]
    accounts = [
        ("100100", "Cash & Due From Banks"),
        ("120200", "Loans - HFI"),
        ("200100", "Deposits"),
        ("310000", "Trading Assets"),
        ("510000", "Interest Income"),
        ("610000", "Interest Expense"),
        ("710000", "Provision for Credit Losses"),
    ]

    asof = date(2026, 1, 8)
    prior = asof - timedelta(days=31)

    rng = np.random.default_rng(7)
    rows: List[Dict[str, Any]] = []

    # GL balances (two closes)
    for d in [prior, asof]:
        for le in entities:
            for book in books:
                for ccy in currencies:
                    for acc, acc_name in accounts:
                        for prod in products:
                            base = float(rng.normal(0, 1))
                            scale = {
                                "100100": 2.2e9,
                                "120200": 6.8e9,
                                "200100": -7.1e9,
                                "310000": 1.9e9,
                                "510000": 0.45e9,
                                "610000": -0.25e9,
                                "710000": -0.12e9,
                            }[acc]
                            le_mult = {"US_HOLDCO": 1.0, "US_BANK": 0.9, "UK_BRANCH": 0.35}[le]
                            prod_mult = {"LOANS": 1.1, "DEPOSITS": 0.95, "TRADING": 1.0, "TREASURY": 0.7}[prod]
                            book_mult = {"GAAP": 1.0, "STAT": 0.8}[book]
                            ccy_mult = {"USD": 1.0, "GBP": 0.28}[ccy]

                            amt = (base * 0.015 + 1.0) * scale * le_mult * prod_mult * book_mult * ccy_mult
                            drift = 1.0 if d == prior else (1.0 + float(rng.normal(0.01, 0.006)))
                            amt *= drift

                            rows.append({
                                "as_of": d,
                                "legal_entity": le,
                                "book": book,
                                "ccy": ccy,
                                "account": acc,
                                "account_name": acc_name,
                                "product": prod,
                                "gl_amount": float(amt),
                            })

    gl = pd.DataFrame(rows)

    # SOR = GL + controlled recon noise on as-of slice
    sor = gl.rename(columns={"gl_amount": "sor_amount"}).copy()
    mask_asof = (sor["as_of"] == asof)
    sor_asof = sor.loc[mask_asof].copy()

    cond_asof = (sor_asof["account"].isin(["120200", "200100"])) & (sor_asof["product"].isin(["LOANS", "DEPOSITS"]))
    noise = rng.normal(0.002, 0.001, size=int(mask_asof.sum()))
    multipliers = np.where(cond_asof.to_numpy(), 1.0 + noise, 1.0)
    sor.loc[mask_asof, "sor_amount"] = sor_asof["sor_amount"].to_numpy() * multipliers

    # force a material break
    miss_mask = (
        (sor["as_of"] == asof) &
        (sor["legal_entity"] == "UK_BRANCH") &
        (sor["product"] == "TRADING") &
        (sor["account"] == "310000")
    )
    sor.loc[miss_mask, "sor_amount"] = sor.loc[miss_mask, "sor_amount"] * 0.92

    # CRRT and CR360 (aggregations)
    crrt = gl.groupby(["as_of", "legal_entity", "book", "ccy", "account"], as_index=False).agg(crrt_amount=("gl_amount", "sum"))
    cr360 = crrt.copy()
    cr360["cr360_amount"] = cr360["crrt_amount"] * (1.0 + rng.normal(0.0008, 0.0005, size=len(cr360)))

    # Feeds / ingestion runs
    feed_sources = [
        ("GL_CORE", "GL"),
        ("SUBLEDGER_SOR", "SOR"),
        ("CRRT_PIPE", "CRRT"),
        ("CR360_PIPE", "CR360"),
        ("ERA_SCCL", "ERA"),
        ("STARE_FORECAST", "STARE"),
    ]
    feed_rows: List[Dict[str, Any]] = []
    for src, layer in feed_sources:
        for d in [prior, asof]:
            status = "SUCCESS"
            latency_min = int(abs(rng.normal(18, 9)))
            records = int(abs(rng.normal(120000, 15000)))
            rejects = int(abs(rng.normal(180, 70)))
            if src == "STARE_FORECAST" and d == asof:
                status = "LATE"
                latency_min += 120
            if src == "SUBLEDGER_SOR" and d == asof:
                rejects += 420
            feed_rows.append({
                "as_of": d, "source": src, "layer": layer, "status": status,
                "latency_min": latency_min, "records": records, "rejects": rejects,
                "control_total": float(abs(rng.normal(1.8e10, 3.5e9))),
                "run_id": f"RUN-{src}-{d.strftime('%Y%m%d')}"
            })
    feed = pd.DataFrame(feed_rows)

    # Mapping repository (reg + analytics)
    mapping_rows = [
        ("FR2590", "L1", "Cash & Central Bank", ["100100"]),
        ("FR2590", "L2", "Loans Outstanding", ["120200"]),
        ("FR2590", "L3", "Trading Assets", ["310000"]),
        ("FR2590", "L4", "Deposits", ["200100"]),
        ("Y-9C", "HC-A1", "Cash and balances due", ["100100"]),
        ("Y-9C", "HC-C1", "Loans and leases", ["120200"]),
        ("Y-9C", "HC-L1", "Deposits", ["200100"]),
        ("Y-9C", "HC-B1", "Trading assets", ["310000"]),
        ("CCAR", "P&L1", "Net Interest Income", ["510000", "610000"]),
        ("CECL/ACL", "ACL1", "Provision / ACL expense", ["710000"]),
        ("STARE", "S1", "Forecast Loans", ["120200"]),
        ("ERA", "E1", "SCCL Recon Coverage", ["120200", "200100", "310000"]),
        ("FR Y-15", "Y15-1", "Systemic indicators (proxy)", ["100100","120200","200100","310000"]),
        ("FR 2052a (LCR)", "LCR-1", "HQLA (proxy)", ["100100","310000"]),
        ("FR 2052a (LCR)", "LCR-2", "Net cash outflows (proxy)", ["200100","510000","610000"]),
        ("NSFR", "NSFR-1", "Available stable funding (proxy)", ["200100"]),
        ("NSFR", "NSFR-2", "Required stable funding (proxy)", ["120200","310000"]),
        ("Call Report", "FFIEC-1", "Schedule RC-R (proxy)", ["100100","120200","200100"]),
    ]
    rep_map = []
    for rep, line, desc, accs in mapping_rows:
        for a in accs:
            rep_map.append({"report": rep, "report_line": line, "line_desc": desc, "account": a})
    map_df = pd.DataFrame(rep_map)

    # DQ rules / controls catalog
    rules = pd.DataFrame([
        {"rule_id":"DQ-001","rule_name":"Completeness - Required dimensions present","severity":"HIGH","owner":"Data Steward"},
        {"rule_id":"DQ-002","rule_name":"Balance - Assets = Liabilities + Equity (entity/book)","severity":"MATERIAL","owner":"Controller"},
        {"rule_id":"DQ-003","rule_name":"Timeliness - Feeds within SLA","severity":"MEDIUM","owner":"Ops"},
        {"rule_id":"DQ-004","rule_name":"Recon - GL vs SOR within tolerance","severity":"MATERIAL","owner":"Recon Lead"},
        {"rule_id":"DQ-005","rule_name":"Mapping - Report line coverage >= 99%","severity":"HIGH","owner":"Report Owner"},
    ])

    # ----------------------------
    # Enterprise governance artifacts (demo)
    # ----------------------------
    report_catalog = pd.DataFrame([
        {"report":"FR2590 (SCCL)","primary_grain":"Exposure-Atomic","primary_hierarchy":"A-Node→BE→CG→UP→CP→Category→Instrument→Netting/Collateral","owner":"Reg Reporting","criticality":"TIER-1","controls":"Hierarchy governance, limits checks, explain variance, evidence, certification"},
        {"report":"Y-9C","primary_grain":"GL-Line","primary_hierarchy":"A-Node→LE→Book→CCY→Account","owner":"Reg Reporting","criticality":"TIER-1","controls":"Mapping governance, recon, explain variance, evidence, certification"},
        {"report":"FR Y-15","primary_grain":"Hybrid (GL+Exposure)","primary_hierarchy":"A-Node→LE + selected activity grains","owner":"Reg Reporting","criticality":"TIER-2","controls":"Sourcing controls, recon, evidence"},
        {"report":"FR 2052a (LCR)","primary_grain":"Hybrid (Cashflow+Positions)","primary_hierarchy":"A-Node→LE→Product/Flow","owner":"Treasury","criticality":"TIER-1","controls":"Feed SLA, recon to GL control totals, evidence"},
        {"report":"NSFR","primary_grain":"Hybrid (Funding+Balances)","primary_hierarchy":"A-Node→LE→ASF/RSF buckets","owner":"Treasury","criticality":"TIER-2","controls":"Policy-based tolerances, evidence"},
        {"report":"Call Report","primary_grain":"GL-Line","primary_hierarchy":"A-Node→LE→Book→CCY→Account","owner":"Reg Reporting","criticality":"TIER-1","controls":"Mapping governance, recon, certification"},
        {"report":"CCAR","primary_grain":"Scenario-Aggregate","primary_hierarchy":"A-Node→LE→Scenario→Line","owner":"Finance","criticality":"TIER-2","controls":"Scenario governance, evidence"},
        {"report":"CECL/ACL","primary_grain":"Portfolio","primary_hierarchy":"A-Node→LE→Portfolio→Stage","owner":"Finance","criticality":"TIER-2","controls":"Model governance, evidence"},
    ])

    # Recon policy registry (used by recon engine)
    recon_policies = pd.DataFrame([
        {"policy_id":"POL-GL-SOR","domain":"GL↔SOR","report":"Enterprise","match_keys":"as_of,legal_entity,book,ccy,account,product","tolerance_type":"abs+%","tolerance_abs":1000.0,"tolerance_pct":0.0005,"owner":"Recon Lead","active":True},
        {"policy_id":"POL-CRRT-CR360","domain":"CRRT↔CR360","report":"Enterprise","match_keys":"as_of,legal_entity,book,ccy,account","tolerance_type":"abs","tolerance_abs":5000.0,"tolerance_pct":0.0,"owner":"Recon Lead","active":True},
        {"policy_id":"POL-FR2590","domain":"SCCL Controls","report":"FR2590 (SCCL)","match_keys":"as_of,a_node_id,booking_entity,connected_group_id,exposure_category","tolerance_type":"abs","tolerance_abs":5_000_000.0,"tolerance_pct":0.0,"owner":"SCCL Owner","active":True},
    ])

    # Mapping set governance (effective-dated)
    mapping_sets = pd.DataFrame([
        {"mapping_set_id":"MAP-202601","name":"Month-End Mapping","status":"APPROVED","effective_from":str(prior),"effective_to":"","approved_by":"Checker","approved_ts":now_str()},
        {"mapping_set_id":"MAP-202602","name":"Current Close Mapping","status":"DRAFT","effective_from":str(asof),"effective_to":"","approved_by":"","approved_ts":""},
    ])

    # Lightweight entitlements (demo)
    entitlements = pd.DataFrame([
        {"role":"Maker","can_edit":True,"can_submit":True,"can_approve":False,"can_certify":False,"can_view_trade_level":True},
        {"role":"Checker","can_edit":False,"can_submit":False,"can_approve":True,"can_certify":False,"can_view_trade_level":True},
        {"role":"Executive","can_edit":False,"can_submit":False,"can_approve":False,"can_certify":True,"can_view_trade_level":False},
        {"role":"Auditor","can_edit":False,"can_submit":False,"can_approve":False,"can_certify":False,"can_view_trade_level":False},
    ])

    # Close cycles (per as-of)
    close_cycles = pd.DataFrame([
        {"cycle_id":f"CYC-{prior.strftime('%Y%m%d')}","as_of":prior,"status":"CERTIFIED","certified_by":"Executive","certified_ts":now_str()},
        {"cycle_id":f"CYC-{asof.strftime('%Y%m%d')}","as_of":asof,"status":"IN_PROGRESS","certified_by":"","certified_ts":""},
    ])

    # Evidence registry (structured evidence metadata)
    evidence_registry = pd.DataFrame([
        {"evidence_id":"EVD-0001","evidence_type":"Source Extract","title":"GL Trial Balance","linked_object_type":"CYCLE","linked_object_id":f"CYC-{asof.strftime('%Y%m%d')}","owner":"Ops","ts":now_str(),"sha256":"demo-hash-01","retention":"7y"},
        {"evidence_id":"EVD-0002","evidence_type":"Calculation","title":"SCCL Aggregation Check","linked_object_type":"REPORT","linked_object_id":"FR2590 (SCCL)","owner":"SCCL Owner","ts":now_str(),"sha256":"demo-hash-02","retention":"7y"},
    ])

    presets = pd.DataFrame([
        {"preset":"Month-End Close (GAAP/USD)","legal_entity":"US_HOLDCO","book":"GAAP","ccy":"USD","materiality":1_000_000},
        {"preset":"Reg Submission (FR2590)","legal_entity":"US_HOLDCO","book":"GAAP","ccy":"USD","materiality":2_000_000},
        {"preset":"UK Branch (GAAP/GBP)","legal_entity":"UK_BRANCH","book":"GAAP","ccy":"GBP","materiality":500_000},
        {"preset":"STAT View (US Bank)","legal_entity":"US_BANK","book":"STAT","ccy":"USD","materiality":1_500_000},
    ])


    # ----------------------------
    # SCCL / FR2590 exposure hierarchy (demo)
    # ----------------------------
    # Org hierarchy (A-Node → Booking Entity)
    org_hier = pd.DataFrame([
        {"node_id":"A_US_CONSOL","node_name":"A-NODE: US Consolidated Perimeter","node_type":"A_NODE","parent_id":None},
        {"node_id":"B_US_BANK","node_name":"B-NODE: US Bank","node_type":"B_NODE","parent_id":"A_US_CONSOL"},
        {"node_id":"B_BD","node_name":"B-NODE: Broker-Dealer","node_type":"B_NODE","parent_id":"A_US_CONSOL"},
        {"node_id":"B_UK","node_name":"B-NODE: UK Branch","node_type":"B_NODE","parent_id":"A_US_CONSOL"},
        {"node_id":"LE_US_HOLDCO","node_name":"US_HOLDCO","node_type":"BOOKING_ENTITY","parent_id":"A_US_CONSOL"},
        {"node_id":"LE_US_BANK","node_name":"US_BANK","node_type":"BOOKING_ENTITY","parent_id":"B_US_BANK"},
        {"node_id":"LE_UK_BRANCH","node_name":"UK_BRANCH","node_type":"BOOKING_ENTITY","parent_id":"B_UK"},
    ])

    # Counterparty hierarchy (Counterparty → Ultimate Parent → Connected Group)
    cps = [
        ("CP1001","Alpha Energy LLC","UP900","Alpha Holdings","CG-A","Connected Group A"),
        ("CP1002","Beta Telecom Inc","UP901","Beta Group","CG-B","Connected Group B"),
        ("CP1003","Gamma Trading Co","UP900","Alpha Holdings","CG-A","Connected Group A"),
        ("CP1004","Delta Infra SPV","UP902","Delta Parent","CG-C","Connected Group C"),
        ("CP1005","Epsilon Retail Ltd","UP903","Epsilon Parent","CG-D","Connected Group D"),
        ("CP1006","Zeta Capital Mgmt","UP904","Zeta Parent","CG-E","Connected Group E"),
        ("CP1007","Omega Shipping BV","UP902","Delta Parent","CG-C","Connected Group C"),
        ("CP1008","Sigma Metals SA","UP905","Sigma Parent","CG-F","Connected Group F"),
    ]
    counterparty = pd.DataFrame([{
        "counterparty_id":cp,"counterparty_name":nm,
        "ultimate_parent_id":up,"ultimate_parent_name":upnm,
        "connected_group_id":cg,"connected_group_name":cgnm
    } for cp,nm,up,upnm,cg,cgnm in cps])

    # Netting / agreements
    netting = pd.DataFrame([
        {"netting_set_id":"NS-100","agreement_type":"ISDA/CSA","margining":"VM+IM","threshold":50_000_000},
        {"netting_set_id":"NS-200","agreement_type":"GMRA","margining":"VM","threshold":25_000_000},
        {"netting_set_id":"NS-300","agreement_type":"None","margining":"NONE","threshold":0},
    ])

    # Collateral catalog (allocated to netting sets / exposures downstream)
    collateral = pd.DataFrame([
        {"collateral_id":"COL-01","collateral_type":"Cash","ccy":"USD","haircut":0.00},
        {"collateral_id":"COL-02","collateral_type":"UST","ccy":"USD","haircut":0.02},
        {"collateral_id":"COL-03","collateral_type":"Gilt","ccy":"GBP","haircut":0.03},
        {"collateral_id":"COL-04","collateral_type":"Corp Bond","ccy":"USD","haircut":0.08},
    ])

    # Atomic SCCL exposures (illustrative). Grain ≈ instrument/trade/facility.
    exposure_categories = ["Loans/Commitments","Securities","Derivatives","SFT"]
    inst_types = {
        "Loans/Commitments":["FACILITY","TERM_LOAN","REVOLVER"],
        "Securities":["BOND","EQUITY"],
        "Derivatives":["IRS","FX_FWD","CDS"],
        "SFT":["REPO","REV_REPO","SEC_LEND"]
    }
    booking_entities = ["US_HOLDCO","US_BANK","UK_BRANCH"]

    sccl_rows: List[Dict[str, Any]] = []
    for d in [prior, asof]:
        for be in booking_entities:
            # keep demo small but structured
            for i, cp in enumerate(counterparty["counterparty_id"].tolist(), start=1):
                cg = counterparty[counterparty["counterparty_id"]==cp].iloc[0]["connected_group_id"]
                up = counterparty[counterparty["counterparty_id"]==cp].iloc[0]["ultimate_parent_id"]
                for cat in exposure_categories:
                    # 1-3 instruments per bucket
                    n_inst = 1 + int(rng.integers(1, 3))
                    for k in range(n_inst):
                        inst_id = f"{cat[:3].upper()}-{cp}-{i:02d}-{k:02d}-{d.strftime('%m%d')}"
                        it = str(rng.choice(inst_types[cat]))
                        # base sizes (bank-style magnitudes)
                        base = {
                            "Loans/Commitments": 250_000_000,
                            "Securities": 120_000_000,
                            "Derivatives": 60_000_000,
                            "SFT": 90_000_000,
                        }[cat]
                        be_mult = {"US_HOLDCO":1.00,"US_BANK":0.75,"UK_BRANCH":0.30}[be]
                        cp_mult = 0.6 + 0.9 * float(rng.random())
                        drift = 1.0 if d == prior else (1.0 + float(rng.normal(0.015, 0.01)))
                        gross = base * be_mult * cp_mult * drift
                        # netting/collateral only meaningful for derivatives/sft
                        ns = "NS-300"
                        col = None
                        if cat in ("Derivatives","SFT"):
                            ns = str(rng.choice(netting["netting_set_id"]))
                            col = str(rng.choice(collateral["collateral_id"]))
                        # simplistic netting & collateral impact
                        net_factor = 0.88 if cat == "Derivatives" else (0.92 if cat == "SFT" else 1.0)
                        col_hair = float(collateral[collateral["collateral_id"]==col]["haircut"].iloc[0]) if col else 0.0
                        col_cover = 0.35 if col else 0.0
                        net = gross * net_factor * (1.0 - (col_cover * (1.0 - col_hair)))
                        ead = net * (1.05 if cat == "Loans/Commitments" else (1.12 if cat == "Derivatives" else 1.00))
                        sccl_rows.append({
                            "as_of": d,
                            "a_node_id": "A_US_CONSOL",
                            "booking_entity": be,
                            "counterparty_id": cp,
                            "ultimate_parent_id": up,
                            "connected_group_id": cg,
                            "exposure_category": cat,
                            "instrument_id": inst_id,
                            "instrument_type": it,
                            "netting_set_id": ns,
                            "collateral_id": col if col else "",
                            "gross_exposure": float(gross),
                            "net_exposure": float(net),
                            "ead": float(ead),
                        })
    sccl_atomic = pd.DataFrame(sccl_rows)

    # Workstreams / operating model (report-family first). Used for routing and simplified UI.
    # This is a demo representation of enterprise ownership across reconciliation and regulatory workstreams.
    workstreams = pd.DataFrame([
        # CAR
        {"report_family":"CAR","workstream_code":"CAR_COMM","workstream_name":"CAR Commercial","role_type":"Data Provider","portfolio":"","owning_team":"CAR Commercial"},
        {"report_family":"CAR","workstream_code":"CAR_CONS","workstream_name":"CAR Consumer","role_type":"Data Provider","portfolio":"","owning_team":"CAR Consumer"},
        {"report_family":"CAR","workstream_code":"CAR_GL","workstream_name":"CAR GL","role_type":"Control Owner","portfolio":"","owning_team":"GL Control"},

        # STARE
        {"report_family":"STARE","workstream_code":"STARE","workstream_name":"STARE","role_type":"Report Preparer","portfolio":"","owning_team":"STARE"},

        # SCCL / FR2590 (report-specific; system-agnostic)
        {"report_family":"SCCL (FR2590)","workstream_code":"FR2590","workstream_name":"FR2590 (SCCL)","role_type":"Control Owner","portfolio":"","owning_team":"SCCL / Large Exposures"},

        # FR Y-14 (firmwide submission)
        {"report_family":"FR Y-14","workstream_code":"FRY14MQ_CONS","workstream_name":"FRY14M/Q Consumer","role_type":"Consumer","portfolio":"","owning_team":"FR Y-14 Consumer"},
        {"report_family":"FR Y-14","workstream_code":"FRY14Q","workstream_name":"FR‑Y 14Q","role_type":"Report Preparer","portfolio":"","owning_team":"FR‑Y 14Q Submission"},
        {"report_family":"FR Y-14","workstream_code":"FRY14M_AB","workstream_name":"FR‑Y 14M (Schedules A & B)","role_type":"Report Preparer","portfolio":"A&B","owning_team":"FR‑Y 14M Submission"},
        {"report_family":"FR Y-14","workstream_code":"FRY14M_D","workstream_name":"FR‑Y 14M (Schedule D)","role_type":"Report Preparer","portfolio":"D","owning_team":"FR‑Y 14M Submission"},

        # WMCRD / CPS
        {"report_family":"WMCRD","workstream_code":"WMCRD","workstream_name":"WMCRD","role_type":"Consumer","portfolio":"","owning_team":"WMCRD"},
        {"report_family":"Credit Portfolio Surveillance Team","workstream_code":"CPS","workstream_name":"Credit Portfolio Surveillance Team","role_type":"Consumer","portfolio":"","owning_team":"CPS Team"},

        # CRRT (controls + Basel portfolios + Y-14 support)
        {"report_family":"CRRT","workstream_code":"CRRT","workstream_name":"CRRT","role_type":"Control Owner","portfolio":"","owning_team":"CRRT"},
        {"report_family":"CRRT","workstream_code":"CRRT_FRY14Q","workstream_name":"CRRT FRY 14‑Q","role_type":"Data Provider","portfolio":"","owning_team":"CRRT FRY14‑Q"},

        # CRRT Basel portfolios
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_WFHL","workstream_name":"CRRT BASEL (Home Lending - WFHL)","role_type":"Data Provider","portfolio":"WFHL","owning_team":"CRRT Basel WFHL"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_WFA","workstream_name":"CRRT BASEL (Advisors - WFA)","role_type":"Data Provider","portfolio":"WFA","owning_team":"CRRT Basel WFA"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_WIM","workstream_name":"CRRT BASEL (Wealth Investment Management - WIM)","role_type":"Data Provider","portfolio":"WIM","owning_team":"CRRT Basel WIM"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_NASCA","workstream_name":"CRRT BASEL (Non Agency Servicer Cash Advances - NASCA)","role_type":"Data Provider","portfolio":"NASCA","owning_team":"CRRT Basel NASCA"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_SBL","workstream_name":"CRRT BASEL (Small Business Lending - SBL)","role_type":"Data Provider","portfolio":"SBL","owning_team":"CRRT Basel SBL"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_RBRM","workstream_name":"CRRT BASEL (Regional Business Relationship Management - RBRM)","role_type":"Data Provider","portfolio":"RBRM","owning_team":"CRRT Basel RBRM"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_DS","workstream_name":"CRRT BASEL (Dealer Services - DS)","role_type":"Data Provider","portfolio":"DS","owning_team":"CRRT Basel DS"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_BCD","workstream_name":"CRRT BASEL (Bank Card / Business Card - BCD)","role_type":"Data Provider","portfolio":"BCD","owning_team":"CRRT Basel BCD"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_PRC","workstream_name":"CRRT BASEL (Prime Card Service - PRC(CCS))","role_type":"Data Provider","portfolio":"PRC","owning_team":"CRRT Basel PRC(CCS)"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_PLL","workstream_name":"CRRT BASEL (Personal Lines and Leases - PLL)","role_type":"Data Provider","portfolio":"PLL","owning_team":"CRRT Basel PLL"},
        {"report_family":"CRRT","workstream_code":"CRRT_BASEL_RTL","workstream_name":"CRRT BASEL (WFF US Retailer - RTL)","role_type":"Data Provider","portfolio":"RTL","owning_team":"CRRT Basel RTL"},

        # CRRT Y-14Q Schedule H roles
        {"report_family":"CRRT","workstream_code":"CRRT_FRY14Q_H_PROV","workstream_name":"CRRT FRY14Q Schedule H Data Providers","role_type":"Data Provider","portfolio":"FRY14Q_H","owning_team":"CRRT Y‑14Q H Providers"},
        {"report_family":"CRRT","workstream_code":"CRRT_FRY14Q_H_PREP","workstream_name":"CRRT FRY14Q H Report Preparer","role_type":"Report Preparer","portfolio":"FRY14Q_H","owning_team":"CRRT Y‑14Q H Preparer"}
    ])



    return {
        "asof": asof, "prior": prior,
        "gl": gl, "sor": sor, "crrt": crrt, "cr360": cr360,
        "feed": feed, "map": map_df, "rules": rules, "presets": presets,
        "workstreams": workstreams,
        "org_hier": org_hier, "counterparty": counterparty, "netting": netting,
        "collateral": collateral, "sccl_atomic": sccl_atomic,
        "report_catalog": report_catalog, "recon_policies": recon_policies,
        "mapping_sets": mapping_sets, "entitlements": entitlements,
        "close_cycles": close_cycles, "evidence_registry": evidence_registry
    }

# ----------------------------
# Pandas -> Qt model
# ----------------------------



# ----------------------------
# Annotations (structured control metadata) vs Commentary (free text)
# ----------------------------
ANNOTATION_TYPES = [
    "(None)",
    "TIMING_ADJ_CHARGEOFF",
    "TIMING_ADJ_OTHER",
    "ALLOCATION_PENDING",
    "MAPPING_OVERRIDE",
    "POLICY_OVERRIDE_TOLERANCE",
    "KNOWN_ISSUE",
    "CONNECTED_GROUP_CHANGE",
    "FX_TRANSLATION",
]

# Rules drive workflow requirements (demo defaults)
ANNOTATION_RULES: Dict[str, Dict[str, Any]] = {
    "(None)": {"evidence_required": False, "approval_required": False, "default_scope": "Item"},
    "TIMING_ADJ_CHARGEOFF": {"evidence_required": True, "approval_required": True, "default_scope": "Ledger"},
    "TIMING_ADJ_OTHER": {"evidence_required": True, "approval_required": True, "default_scope": "Ledger"},
    "ALLOCATION_PENDING": {"evidence_required": True, "approval_required": True, "default_scope": "LOB"},
    "MAPPING_OVERRIDE": {"evidence_required": True, "approval_required": True, "default_scope": "Line"},
    "POLICY_OVERRIDE_TOLERANCE": {"evidence_required": True, "approval_required": True, "default_scope": "Line"},
    "KNOWN_ISSUE": {"evidence_required": False, "approval_required": True, "default_scope": "Cycle"},
    "CONNECTED_GROUP_CHANGE": {"evidence_required": True, "approval_required": True, "default_scope": "Cycle"},
    "FX_TRANSLATION": {"evidence_required": False, "approval_required": False, "default_scope": "Line"},
}

ANNOTATION_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
ANNOTATION_SCOPES = ["Item", "Ledger", "LOB", "Line", "Cycle"]

class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: Optional[pd.DataFrame] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._df = df.copy() if df is not None else pd.DataFrame()

    def set_df(self, df: Optional[pd.DataFrame]):
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        # base formatting
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            try:
                v = self._df.iat[index.row(), index.column()]
                col = str(self._df.columns[index.column()]).lower()
                if isinstance(v, (float, np.floating, int, np.integer)) and any(
                    k in col for k in ["amount", "variance", "control", "balance", "cur", "prior", "abs_var", "latency"]
                ):
                    return fmt_money(v) if "latency" not in col else str(int(safe_float(v, 0.0)))
                return str(v)
            except Exception:
                return ""

        # lightweight role-based coloring for key columns (delegate does the rest)
        if role == Qt.ItemDataRole.ForegroundRole:
            try:
                col = str(self._df.columns[index.column()]).lower()
                v = str(self._df.iat[index.row(), index.column()])
                if "severity" in col:
                    return QBrush(QColor({"LOW":"#444444","MEDIUM":"#F2C94C","HIGH":"#F2994A","MATERIAL":"#EB5757"}.get(v, "#444444")))
                if "status" in col:
                    if v in ("BREAK","FAILED","LATE","BREACHED"):
                        return QBrush(QColor("#EB5757"))
                    if v in ("MATCH","SUCCESS","ON_TRACK","OK","READY"):
                        return QBrush(QColor("#27AE60"))
                    if v in ("AT_RISK","IN REVIEW","IN PROGRESS"):
                        return QBrush(QColor("#F2C94C"))
            except Exception:
                return None

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section]) if section < len(self._df.columns) else ""
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def get_row(self, row: int) -> Dict[str, Any]:
        if row < 0 or row >= len(self._df):
            return {}
        return self._df.iloc[row].to_dict()

# ----------------------------
# Delegate for enterprise "badge" feel
# ----------------------------

class BadgeDelegate(QStyledItemDelegate):
    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex):
        # Let default paint happen first
        super().paint(painter, option, index)

# ----------------------------
# Dialogs
# ----------------------------

class ColumnChooserDialog(QDialog):
    """Simple column chooser with optional saved-view name.

    Returns a list of visible column names when accepted.
    """
    def __init__(self, columns: List[str], visible: List[str], title: str = 'Columns', parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self.columns = list(columns)
        vis = set(visible or [])

        layout = QVBoxLayout(self)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText('Filter columns…')
        layout.addWidget(self.txt_filter)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for c in self.columns:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if (c in vis or not visible) else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        layout.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.btn_all = QPushButton('All')
        self.btn_none = QPushButton('None')
        self.btn_ok = QPushButton('Apply')
        self.btn_cancel = QPushButton('Cancel')
        self.btn_ok.setDefault(True)
        btns.addWidget(self.btn_all)
        btns.addWidget(self.btn_none)
        btns.addStretch(1)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.txt_filter.textChanged.connect(self._apply_filter)

    def _set_all(self, on: bool):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _apply_filter(self, t: str):
        q = (t or '').strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(q) and (q not in it.text().lower()))

    def visible_columns(self) -> List[str]:
        cols = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                cols.append(it.text())
        return cols


class BreakDialog(QDialog):
    def __init__(self, row: Dict[str, Any], mode: str, read_only: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Break Detail")
        self.setMinimumWidth(620)
        self.row = row.copy()
        self.mode = mode

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lbl_id = QLabel(str(self.row.get("break_id", "")))
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["OPEN", "IN REVIEW", "APPROVED", "CLOSED"])
        self.cmb_status.setCurrentText(str(self.row.get("status", "OPEN")))

        self.ed_owner = QLineEdit(str(self.row.get("owner", "Recon Analyst")))

        self.cmb_root = QComboBox()
        self.cmb_root.addItems(["UNCLASSIFIED", "TIMING", "MAPPING", "MISSING_FEED", "FX", "SIGN", "DUPLICATION", "THRESHOLD", "MANUAL_ADJ"])
        self.cmb_root.setCurrentText(str(self.row.get("root_cause", "UNCLASSIFIED")))

        # Annotation (structured control metadata)
        self.cmb_ann_type = QComboBox()
        self.cmb_ann_type.addItems(ANNOTATION_TYPES)
        self.cmb_ann_type.setCurrentText(str(self.row.get("annotation_type", "(None)")))

        self.cmb_ann_scope = QComboBox()
        self.cmb_ann_scope.addItems(ANNOTATION_SCOPES)
        # default scope derived from type
        _t = self.cmb_ann_type.currentText()
        _def_scope = ANNOTATION_RULES.get(_t, {}).get("default_scope", "Item")
        self.cmb_ann_scope.setCurrentText(str(self.row.get("annotation_scope", _def_scope)))

        self.cmb_ann_status = QComboBox()
        self.cmb_ann_status.addItems(ANNOTATION_STATUSES)
        self.cmb_ann_status.setCurrentText(str(self.row.get("annotation_status", "DRAFT")))

        self.lbl_ann_req = QLabel("")
        self.lbl_ann_req.setStyleSheet("color:#444444;")
        def _refresh_ann_req():
            t = self.cmb_ann_type.currentText()
            rule = ANNOTATION_RULES.get(t, ANNOTATION_RULES["(None)"])
            ev = "Evidence required" if rule.get("evidence_required") else "Evidence optional"
            ap = "Approval required" if rule.get("approval_required") else "Approval optional"
            self.lbl_ann_req.setText(f"{ev} • {ap} • Default scope: {rule.get('default_scope','Item')}")
        self.cmb_ann_type.currentTextChanged.connect(lambda _=None: _refresh_ann_req())
        _refresh_ann_req()

        # Mode-based guardrails (demo)
        if self.mode in ("Executive","Auditor"):
            read_only = True
        if self.mode == "Maker":
            # maker can set DRAFT/SUBMITTED only
            self.cmb_ann_status.clear()
            self.cmb_ann_status.addItems(["DRAFT","SUBMITTED"])
            self.cmb_ann_status.setCurrentText(str(self.row.get("annotation_status", "DRAFT")))
        elif self.mode == "Checker":
            # checker can approve/reject submitted items
            self.cmb_ann_status.clear()
            self.cmb_ann_status.addItems(["SUBMITTED","APPROVED","REJECTED"])
            self.cmb_ann_status.setCurrentText(str(self.row.get("annotation_status", "SUBMITTED")))

        self.ed_evidence = QLineEdit(str(self.row.get("evidence_ref", "")))
        self.ed_evidence.setPlaceholderText("Evidence URI / ticket / file reference")

        self.txt_notes = QTextEdit()
        self.txt_notes.setFixedHeight(160)
        self.txt_notes.setPlainText(str(self.row.get("notes", "")))

        sla_txt = f"Aging: {int(self.row.get('age_days', 0))}d | SLA: {int(self.row.get('sla_days', 2))}d | {self.row.get('sla_status', 'ON_TRACK')}"
        self.lbl_sla = QLabel(sla_txt)
        self.lbl_sla.setStyleSheet("color:#444444;")

        form.addRow("Break ID", self.lbl_id)
        form.addRow("Status", self.cmb_status)
        form.addRow("Owner", self.ed_owner)
        form.addRow("Root Cause", self.cmb_root)
        form.addRow("Annotation Type", self.cmb_ann_type)
        form.addRow("Annotation Scope", self.cmb_ann_scope)
        form.addRow("Annotation Status", self.cmb_ann_status)
        form.addRow("", self.lbl_ann_req)
        form.addRow("Evidence Ref", self.ed_evidence)
        form.addRow("SLA", self.lbl_sla)
        form.addRow("Commentary (free text)", self.txt_notes)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_close = QPushButton("Close")
        self.btn_save = QPushButton("Save")
        self.btn_save.setDefault(True)
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_save)
        layout.addLayout(btns)

        if read_only:
            for w in [self.cmb_status, self.ed_owner, self.cmb_root, self.cmb_ann_type, self.cmb_ann_scope, self.cmb_ann_status, self.ed_evidence, self.txt_notes, self.btn_save]:
                w.setEnabled(False)

        self.btn_close.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)

    def _save(self):
        self.row["status"] = self.cmb_status.currentText()
        self.row["owner"] = (self.ed_owner.text() or "").strip() or "Recon Analyst"
        self.row["root_cause"] = self.cmb_root.currentText()
        self.row["evidence_ref"] = (self.ed_evidence.text() or "").strip()
        # Annotation fields
        self.row["annotation_type"] = self.cmb_ann_type.currentText()
        self.row["annotation_scope"] = self.cmb_ann_scope.currentText()
        self.row["annotation_status"] = self.cmb_ann_status.currentText()
        self.row["annotation_effective"] = str(self.row.get("annotation_effective") or self.row.get("as_of") or "")
        self.row["annotation_expiry"] = str(self.row.get("annotation_expiry") or "")
        # Enforce evidence requirement on submit/approve (demo)
        rule = ANNOTATION_RULES.get(self.row["annotation_type"], ANNOTATION_RULES["(None)"])
        if self.row["annotation_status"] in ("SUBMITTED","APPROVED") and rule.get("evidence_required") and not self.row.get("evidence_ref"):
            QMessageBox.warning(self, "Evidence Required", "Selected annotation type requires Evidence Ref before submission/approval.")
            return
        self.row["notes"] = (self.txt_notes.toPlainText() or "").strip()
        self.accept()



class ImpactPreview(QDialog):
    def __init__(self, report: str, line: str, accs: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Impact Preview")
        self.setMinimumWidth(620)
        self.proposed = False
        self.justification = ""

        layout = QVBoxLayout(self)
        lbl = QLabel(
            f"Impact Preview (Read-only)\n\n"
            f"Report: {report}\nLine: {line}\n\n"
            f"Impacted accounts ({len(accs)}): {', '.join(accs) if accs else '—'}\n\n"
            "Governance:\n"
            "- Requires justification\n"
            "- Maker-checker approval\n"
            "- Audit logged"
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#444444;")
        layout.addWidget(lbl)

        form = QFormLayout()
        self.ed_just = QLineEdit()
        self.ed_just.setPlaceholderText("Justification (required to propose)")
        form.addRow("Justification", self.ed_just)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_prop = QPushButton("Propose Change")
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_prop)
        layout.addLayout(btns)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_prop.clicked.connect(self._propose)

    def _propose(self):
        j = (self.ed_just.text() or "").strip()
        if not j:
            QMessageBox.warning(self, "Justification Required", "Enter a justification to propose.")
            return
        self.proposed = True
        self.justification = j
        self.accept()

# ----------------------------
# Main window
# ----------------------------

@dataclass
class GlobalFilters:
    as_of: date
    legal_entity: str
    book: str
    ccy: str
    materiality: float


class EnterpriseDimTree(QWidget):
    """Reusable enterprise-wide dimension navigator.

    One consistent drill path across report tabs:
    A-Node → Booking Entity → Counterparty hierarchy → Exposure/Product → Instrument/Trade → Netting/Collateral.

    Updates MainWindow global filters (LE/Book/CCY) + SCCL filters (FR2590) without forcing a specific report.
    """

    def __init__(self, data: Dict[str, Any], on_change):
        super().__init__()
        self.data = data
        self.on_change = on_change  # callback(dim:str, value:str)
        self._building = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        hdr = QLabel("Enterprise Dim Tree")
        hdr.setStyleSheet("font-weight:900; font-size:14px;")
        lay.addWidget(hdr)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search (node/counterparty/instrument)…")
        self.ed_search.textChanged.connect(self._apply_search)
        lay.addWidget(self.ed_search)

        self.lbl_state = QLabel("—")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setStyleSheet("color:#444444;")
        lay.addWidget(self.lbl_state)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setStyleSheet("QTreeWidget { background: palette(base); color: palette(text); border: 1px solid #C8CCD4; border-radius: 8px; } QTreeWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }")
        lay.addWidget(self.tree, 1)

        hint = QLabel("Tip: Ctrl+Shift+D toggles this panel.")
        hint.setStyleSheet("color:#6F7787; font-size:11px;")
        lay.addWidget(hint)

        self.rebuild(global_filters=None, sccl_filters=None)

    def rebuild(self, global_filters: Optional[Any], sccl_filters: Optional[Dict[str, str]]):
        """Rebuild tree from current state; safe to call often (demo data sizes are small)."""
        self._building = True
        try:
            self.tree.clear()

            # --- Root sections
            sec_org = QTreeWidgetItem(["Org / Reporting Perimeter"])
            sec_org.setExpanded(True)
            self.tree.addTopLevelItem(sec_org)

            sec_book = QTreeWidgetItem(["Book / Currency"])
            sec_book.setExpanded(True)
            self.tree.addTopLevelItem(sec_book)

            sec_cp = QTreeWidgetItem(["Counterparty Hierarchy"])
            sec_cp.setExpanded(True)
            self.tree.addTopLevelItem(sec_cp)

            sec_exp = QTreeWidgetItem(["Exposure / Product"])
            sec_exp.setExpanded(True)
            self.tree.addTopLevelItem(sec_exp)

            sec_instr = QTreeWidgetItem(["Instrument / Netting / Collateral"])
            sec_instr.setExpanded(False)
            self.tree.addTopLevelItem(sec_instr)

            # --- Org hierarchy
            org = self.data.get("org_hier", pd.DataFrame())
            if org.empty:
                a_nodes = ["A_US_CONSOL"]
            else:
                a_nodes = org[org["node_type"] == "A_NODE"]["node_id"].drop_duplicates().tolist()

            atomic = self.data.get("sccl_atomic", pd.DataFrame())
            gl = self.data.get("gl", pd.DataFrame())

            for a in a_nodes:
                it_a = QTreeWidgetItem([a])
                it_a.setData(0, Qt.ItemDataRole.UserRole, {"dim": "a_node_id", "value": a})
                sec_org.addChild(it_a)

                bes = []
                if not atomic.empty and "a_node_id" in atomic.columns:
                    bes = sorted(atomic.loc[atomic["a_node_id"] == a, "booking_entity"].dropna().unique().tolist())
                if not bes and not gl.empty and "legal_entity" in gl.columns:
                    bes = sorted(gl["legal_entity"].dropna().unique().tolist())
                if not bes:
                    bes = ["US_HOLDCO"]
                for be in bes:
                    it_be = QTreeWidgetItem([be])
                    it_be.setData(0, Qt.ItemDataRole.UserRole, {"dim": "booking_entity", "value": be})
                    it_a.addChild(it_be)

            # --- Book / CCY
            books = sorted(gl["book"].drop_duplicates().tolist()) if not gl.empty and "book" in gl.columns else ["GAAP"]
            ccys = sorted(gl["ccy"].drop_duplicates().tolist()) if not gl.empty and "ccy" in gl.columns else ["USD"]

            it_books = QTreeWidgetItem(["Book"])
            it_ccy = QTreeWidgetItem(["Currency"])
            sec_book.addChild(it_books)
            sec_book.addChild(it_ccy)

            for b in books:
                it = QTreeWidgetItem([b])
                it.setData(0, Qt.ItemDataRole.UserRole, {"dim": "book", "value": b})
                it_books.addChild(it)

            for c in ccys:
                it = QTreeWidgetItem([c])
                it.setData(0, Qt.ItemDataRole.UserRole, {"dim": "ccy", "value": c})
                it_ccy.addChild(it)

            # --- Counterparty hierarchy
            cps = self.data.get("counterparty", pd.DataFrame())
            if cps.empty:
                sec_cp.addChild(QTreeWidgetItem(["(No counterparty data)"]))
            else:
                for cg_id, cg_df in cps.groupby("connected_group_id"):
                    cg_name = cg_df["connected_group_name"].iloc[0] if "connected_group_name" in cg_df.columns else ""
                    it_cg = QTreeWidgetItem([f"{cg_id}  {cg_name}".strip()])
                    it_cg.setData(0, Qt.ItemDataRole.UserRole, {"dim": "connected_group_id", "value": cg_id})
                    sec_cp.addChild(it_cg)

                    for up_id, up_df in cg_df.groupby("ultimate_parent_id"):
                        up_name = up_df["ultimate_parent_name"].iloc[0] if "ultimate_parent_name" in up_df.columns else ""
                        it_up = QTreeWidgetItem([f"{up_id}  {up_name}".strip()])
                        it_up.setData(0, Qt.ItemDataRole.UserRole, {"dim": "ultimate_parent_id", "value": up_id})
                        it_cg.addChild(it_up)

                        for _, row in up_df.drop_duplicates(subset=["counterparty_id"]).iterrows():
                            cp_id = str(row.get("counterparty_id", ""))
                            cp_name = str(row.get("counterparty_name", ""))
                            it_cp = QTreeWidgetItem([f"{cp_id}  {cp_name}".strip()])
                            it_cp.setData(0, Qt.ItemDataRole.UserRole, {"dim": "counterparty_id", "value": cp_id})
                            it_up.addChild(it_cp)

            # --- Exposure categories
            cats = sorted(atomic["exposure_category"].drop_duplicates().tolist()) if not atomic.empty and "exposure_category" in atomic.columns else []
            if not cats:
                cats = ["Loans", "Securities", "Derivatives", "SFT", "Commitments"]
            for cat in cats:
                it = QTreeWidgetItem([cat])
                it.setData(0, Qt.ItemDataRole.UserRole, {"dim": "exposure_category", "value": cat})
                sec_exp.addChild(it)

            # --- Instruments / mitigants (lightweight sample)
            if not atomic.empty:
                sample = atomic.head(120).copy()
                if "counterparty_id" in sample.columns:
                    for cp_id, sdf in sample.groupby("counterparty_id"):
                        it_cp_root = QTreeWidgetItem([f"{cp_id} • instruments"])
                        it_cp_root.setData(0, Qt.ItemDataRole.UserRole, {"dim": "counterparty_id", "value": str(cp_id)})
                        sec_instr.addChild(it_cp_root)

                        if "instrument_id" in sdf.columns:
                            for instr in sdf["instrument_id"].dropna().unique().tolist()[:10]:
                                it_instr = QTreeWidgetItem([str(instr)])
                                it_instr.setData(0, Qt.ItemDataRole.UserRole, {"dim": "instrument_id", "value": str(instr)})
                                it_cp_root.addChild(it_instr)

                                if "netting_set_id" in sdf.columns:
                                    nets = [n for n in sdf.loc[sdf["instrument_id"] == instr, "netting_set_id"].dropna().unique().tolist()][:3]
                                else:
                                    nets = []
                                if "collateral_id" in sdf.columns:
                                    cols = [c for c in sdf.loc[sdf["instrument_id"] == instr, "collateral_id"].dropna().unique().tolist()][:3]
                                else:
                                    cols = []

                                if nets:
                                    it_nroot = QTreeWidgetItem(["Netting"])
                                    it_instr.addChild(it_nroot)
                                    for n in nets:
                                        itn = QTreeWidgetItem([str(n)])
                                        itn.setData(0, Qt.ItemDataRole.UserRole, {"dim": "netting_set_id", "value": str(n)})
                                        it_nroot.addChild(itn)

                                if cols:
                                    it_croot = QTreeWidgetItem(["Collateral"])
                                    it_instr.addChild(it_croot)
                                    for c in cols:
                                        itc = QTreeWidgetItem([str(c)])
                                        itc.setData(0, Qt.ItemDataRole.UserRole, {"dim": "collateral_id", "value": str(c)})
                                        it_croot.addChild(itc)

            # --- State label
            gf_txt = ""
            if global_filters is not None:
                gf_txt = (
                    f"GL: LE={getattr(global_filters, 'legal_entity', '—')} | "
                    f"Book={getattr(global_filters, 'book', '—')} | CCY={getattr(global_filters, 'ccy', '—')}"
                )
            sf_txt = ""
            if sccl_filters:
                sf_txt = (
                    f"SCCL: A={sccl_filters.get('a_node_id', '(All)')} | "
                    f"BE={sccl_filters.get('booking_entity', '(All)')} | "
                    f"CG={sccl_filters.get('connected_group_id', '(All)')} | "
                    f"UP={sccl_filters.get('ultimate_parent_id', '(All)')} | "
                    f"CP={sccl_filters.get('counterparty_id', '(All)')} | "
                    f"Cat={sccl_filters.get('exposure_category', '(All)')}"
                )
            self.lbl_state.setText((gf_txt + ("\n" if gf_txt and sf_txt else "") + sf_txt) or "—")

            self.tree.expandToDepth(1)
            self._apply_search(self.ed_search.text())
        finally:
            self._building = False

    def _apply_search(self, text: str):
        t = (text or "").strip().lower()
        if not t:
            def show_all(item: QTreeWidgetItem):
                item.setHidden(False)
                for i in range(item.childCount()):
                    show_all(item.child(i))
            for i in range(self.tree.topLevelItemCount()):
                show_all(self.tree.topLevelItem(i))
            return

        def match_or_desc(item: QTreeWidgetItem) -> bool:
            me = (item.text(0) or "").lower()
            ok = t in me
            child_ok = False
            for i in range(item.childCount()):
                if match_or_desc(item.child(i)):
                    child_ok = True
            item.setHidden(not (ok or child_ok))
            if child_ok:
                item.setExpanded(True)
            return ok or child_ok

        for i in range(self.tree.topLevelItemCount()):
            match_or_desc(self.tree.topLevelItem(i))

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int):
        if self._building:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload or not isinstance(payload, dict):
            return
        dim = payload.get("dim")
        val = payload.get("value")
        if dim and val is not None:
            self.on_change(str(dim), str(val))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1600, 940)

        self.data = seed_data()
        self.current_user = "Maker"
        self.mode = "Maker"  # Maker, Checker, Executive, Auditor

        self.filters = GlobalFilters(
            as_of=self.data["asof"],
            legal_entity="US_HOLDCO",
            book="GAAP",
            ccy="USD",
            materiality=1_000_000.0
        )

        # SCCL (FR2590) drilldown filters (kept separate from GL filters)
        self.sccl_filters: Dict[str, str] = {
            "a_node_id": "A_US_CONSOL",
            "booking_entity": "(All)",
            "connected_group_id": "(All)",
            "ultimate_parent_id": "(All)",
            "counterparty_id": "(All)",
            "exposure_category": "(All)",
            "instrument_id": "(All)",
            "netting_set_id": "(All)",
            "collateral_id": "(All)",
        }

        self.breaks = pd.DataFrame(columns=[
            "break_id","created_ts","as_of",
            "report_family","workstream_code","workstream_name","owning_team",
            "recon_type","legal_entity","book","ccy",
            "account","account_name","product","gl_amount","other_amount","variance","abs_var",
            "severity","root_cause","owner","status","sla_days","age_days","sla_status",
            "annotation_type","annotation_scope","annotation_status","annotation_effective","annotation_expiry",
            "notes","evidence_ref"
        ])
        self.audit = pd.DataFrame(columns=["ts","user","action","object_type","object_id","details"])
        self.variance_expl = pd.DataFrame(columns=["key","as_of","legal_entity","book","ccy","reason","annotation_type","annotation_scope","evidence_ref","narrative","carry_forward","status","maker","ts_created","ts_updated","submitted_ts","checker","approved_ts","decision_notes"])

        # SCCL (FR2590) explainability (Connected Group / Counterparty level)
        self.sccl_expl = pd.DataFrame(columns=["key","as_of","a_node_id","booking_entity","connected_group_id","ultimate_parent_id","counterparty_id","exposure_category","reason","annotation_type","annotation_scope","evidence_ref","narrative","carry_forward","status","maker","ts_created","ts_updated","submitted_ts","checker","approved_ts","decision_notes"])
        self._selected_sccl_key: Optional[str] = None

        # Enterprise governance tables (report-agnostic)
        self.report_catalog = self.data.get("report_catalog", pd.DataFrame())
        self.recon_policies = self.data.get("recon_policies", pd.DataFrame())
        self.mapping_sets = self.data.get("mapping_sets", pd.DataFrame())
        self.entitlements = self.data.get("entitlements", pd.DataFrame())
        self.workstreams = self.data.get("workstreams", pd.DataFrame())
        # Workstream selection (report-family first UI)
        self.selected_report_family: str = "All"
        self.selected_workstream_code: str = "(All)"
        self.close_cycles = self.data.get("close_cycles", pd.DataFrame())
        self.evidence_registry = self.data.get("evidence_registry", pd.DataFrame())

        # Certification state (persisted locally to mimic enterprise close controls)
        self.certifications: Dict[str, Any] = {}

        self._accs_by_line: Dict[str, List[str]] = {}
        self._selected_variance_key: Optional[str] = None

        # Table view persistence (column chooser + saved views)
        self._table_seq = 0
        self._table_registry: Dict[str, QTableView] = {}
        self._table_models: Dict[str, DataFrameModel] = {}
        # Structure: {table_key: {"active": str, "views": {name: [cols]}}}
        self._table_views: Dict[str, Any] = {}

        # Persisted state (enterprise-like user context)
        self._state_path = self._state_file()
        self._loaded_state = self._load_state_raw()
        self._apply_state_to_models(self._loaded_state)

        self._build_menu()
        self._build_ui()
        self._apply_theme()

        # Apply persisted state to widgets after UI is constructed
        self._apply_state_to_widgets(self._loaded_state)
        self.apply_mode_rules()
        self.refresh_all()

    # ---------- menu
    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")

        act_reset = QAction("Reset Demo", self)
        act_reset.triggered.connect(self.reset_demo)
        file_menu.addAction(act_reset)

        act_export = QAction("Export Current Table (CSV)...", self)
        act_export.triggered.connect(self.export_current_table)
        file_menu.addAction(act_export)

        act_copy = QAction("Copy Executive Summary", self)
        act_copy.triggered.connect(self.copy_exec_summary)
        file_menu.addAction(act_copy)

        act_copy_ctx = QAction("Copy Context Snapshot", self)
        act_copy_ctx.triggered.connect(self.copy_context_snapshot)
        file_menu.addAction(act_copy_ctx)

        act_exp_ctx = QAction("Export Context Snapshot (JSON)...", self)
        act_exp_ctx.triggered.connect(self.export_context_snapshot)
        file_menu.addAction(act_exp_ctx)

        act_pack = QAction("Export Close Pack (ZIP)...", self)
        act_pack.triggered.connect(self.export_close_pack)
        file_menu.addAction(act_pack)

        file_menu.addSeparator()
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        sim_menu = mb.addMenu("&Simulate")
        act_day = QAction("Advance Aging +1 day", self)
        act_day.triggered.connect(self.advance_aging)
        sim_menu.addAction(act_day)

        help_menu = mb.addMenu("&Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    def about(self):
        QMessageBox.information(
            self, "About",
            f"{APP_NAME}\n{APP_VERSION}\n\n"
            "What’s covered:\n"
            "- Landing dashboard + confidence scoring\n"
            "- Feed health & ingestion controls (BCBS239)\n"
            "- GL explorer + explain-this-number\n"
            "- Recon workspace (GL↔SOR, CRRT↔CR360)\n"
            "- Break lifecycle with SLA + audit timeline\n"
            "- Variance management + narrative builder\n"
            "- Regulatory reporting workspace (FR2590, Y-9C, FR-Y, CCAR, CECL/ACL, STARE, ERA)\n"
            "- Lineage + mapping governance + impact preview\n"
            "- Audit & evidence vault + admin governance"
        )

    # ---------- Persisted context (user-controlled)
    def _state_file(self) -> Path:
        # Per-user state file (local, lightweight)
        return Path.home() / ".orix_enterprise_gl_state.json"

    def _load_state_raw(self) -> Dict[str, Any]:
        try:
            p = self._state_file()
            if not p.exists():
                return {}
            raw = json.loads(p.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _apply_state_to_models(self, st: Dict[str, Any]):
        """Apply persisted state to in-memory model objects (safe defaults if invalid)."""
        if not st:
            return

        # Mode
        mode = str(st.get("mode", "") or "").strip()
        if mode in ["Maker", "Checker", "Executive", "Auditor"]:
            self.mode = mode
            self.current_user = mode

        # Global filters
        gf = st.get("global_filters", {}) if isinstance(st.get("global_filters", {}), dict) else {}
        try:
            if "as_of" in gf:
                self.filters.as_of = date.fromisoformat(str(gf["as_of"]))
        except Exception:
            pass

        le = str(gf.get("legal_entity", "") or "")
        if le and le in set(self.data["gl"]["legal_entity"].unique()):
            self.filters.legal_entity = le

        book = str(gf.get("book", "") or "")
        if book and book in set(self.data["gl"]["book"].unique()):
            self.filters.book = book

        ccy = str(gf.get("ccy", "") or "")
        if ccy and ccy in set(self.data["gl"]["ccy"].unique()):
            self.filters.ccy = ccy

        try:
            mat = float(gf.get("materiality", self.filters.materiality))
            if 100_000 <= mat <= 25_000_000:
                self.filters.materiality = mat
        except Exception:
            pass

        # SCCL filters
        sf = st.get("sccl_filters", {}) if isinstance(st.get("sccl_filters", {}), dict) else {}
        for k in list(self.sccl_filters.keys()):
            if k in sf:
                self.sccl_filters[k] = str(sf.get(k))


        # Table column views
        tv = st.get('table_views', {}) if isinstance(st.get('table_views', {}), dict) else {}
        # Expect: {table_key: {active: str, views: {name: [cols]}}}
        if isinstance(tv, dict):
            self._table_views = tv

        # Certifications (close-cycle) — stored as {"YYYY-MM-DD": {status,...}}
        cert = st.get("certifications", {}) if isinstance(st.get("certifications", {}), dict) else {}
        if isinstance(cert, dict):
            self.certifications = cert

    def _apply_state_to_widgets(self, st: Dict[str, Any]):
        if not st:
            return

        # Mode dropdown
        mode = str(st.get("mode", "") or "").strip()
        if mode:
            self.cmb_mode.blockSignals(True)
            if mode == "Auditor":
                self.cmb_mode.setCurrentText("Auditor (Read-only)")
            elif mode in ["Maker", "Checker", "Executive"]:
                self.cmb_mode.setCurrentText(mode)
            self.cmb_mode.blockSignals(False)

        # Global filter widgets
        def _set_combo_by_data(cmb: QComboBox, target):
            for i in range(cmb.count()):
                if cmb.itemData(i) == target:
                    cmb.setCurrentIndex(i)
                    return True
            return False

        self.cmb_asof.blockSignals(True)
        _set_combo_by_data(self.cmb_asof, self.filters.as_of)
        self.cmb_asof.blockSignals(False)

        for cmb, val in [(self.cmb_le, self.filters.legal_entity), (self.cmb_book, self.filters.book), (self.cmb_ccy, self.filters.ccy)]:
            cmb.blockSignals(True)
            cmb.setCurrentText(val)
            cmb.blockSignals(False)

        self.spn_mat.blockSignals(True)
        self.spn_mat.setValue(int(self.filters.materiality))
        self.spn_mat.blockSignals(False)

        # Dim dock visibility (optional)
        vis = st.get("dim_dock_visible")
        if isinstance(vis, bool) and hasattr(self, "dim_dock"):
            self.dim_dock.setVisible(vis)

        # Ensure dim tree reflects the loaded state
        if hasattr(self, "dim_tree"):
            self.dim_tree.rebuild(self.filters, self.sccl_filters)

        # Apply saved table column views after widgets exist
        self._apply_table_views_to_all()
        self.update_context_header()

    def _save_state(self):
        """Persist context (filters + SCCL filters + mode + dim panel) locally."""
        try:
            p = self._state_file()
            payload = {
                "version": APP_VERSION,
                "saved_ts": now_str(),
                "mode": self.mode,
                "dim_dock_visible": bool(self.dim_dock.isVisible()) if hasattr(self, "dim_dock") else True,
                "global_filters": {
                    "as_of": str(self.filters.as_of),
                    "legal_entity": self.filters.legal_entity,
                    "book": self.filters.book,
                    "ccy": self.filters.ccy,
                    "materiality": float(self.filters.materiality),
                },
                "sccl_filters": dict(self.sccl_filters),
                "table_views": self._table_views,
                "certifications": self.certifications,
            }
            p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            # State persistence should never break the app
            pass

    def _breadcrumbs(self) -> str:
        a = self.sccl_filters.get("a_node_id", "(All)")
        be = self.sccl_filters.get("booking_entity", "(All)")
        cg = self.sccl_filters.get("connected_group_id", "(All)")
        up = self.sccl_filters.get("ultimate_parent_id", "(All)")
        cp = self.sccl_filters.get("counterparty_id", "(All)")
        cat = self.sccl_filters.get("exposure_category", "(All)")
        return (
            f"A={a} → BE={be} → CG={cg} → UP={up} → CP={cp} → Cat={cat}"
        )

    
    # ---------- Workstream routing (enterprise operating model)
    def list_report_families(self) -> List[str]:
        # Report-family first ordering for simplified enterprise operations (mapped to the provided workstream list)
        preferred = [
            "CAR",
            "STARE",
            "SCCL (FR2590)",
            "FR Y-14",
            "WMCRD",
            "Credit Portfolio Surveillance Team",
            "CRRT",
        ]
        if self.workstreams is None or self.workstreams.empty:
            return ["All"] + preferred
        fams = [str(x) for x in sorted(set(self.workstreams["report_family"].astype(str).tolist()))]
        ordered = []
        for f in preferred:
            if f in fams:
                ordered.append(f)
        for f in fams:
            if f not in ordered:
                ordered.append(f)
        return ["All"] + ordered

    def list_workstreams(self, report_family: str) -> pd.DataFrame:
        ws = self.workstreams.copy() if self.workstreams is not None else pd.DataFrame()
        if ws.empty:
            return ws
        if report_family and report_family != "All":
            ws = ws[ws["report_family"].astype(str) == report_family].copy()
        ws = ws.sort_values(["report_family","workstream_name"]).reset_index(drop=True)
        return ws

    def route_break(self, recon_type: str, product: str = "", account: str = "") -> Dict[str, str]:
        # Simple deterministic demo routing. In a real implementation this comes from the Routing Rules registry.
        rt = (recon_type or "").lower()
        if "gl vs sor" in rt:
            fam, code = "CAR", "CAR_GL"
        elif "crrt" in rt or "cr360" in rt:
            fam, code = "CRRT", "CRRT"
        elif "sccl" in rt or "fr2590" in rt:
            fam, code = "SCCL (FR2590)", "FR2590"
        else:
            fam, code = "CAR", "CAR_GL"

        ws = self.workstreams.copy() if self.workstreams is not None else pd.DataFrame()
        name = code
        team = code
        if not ws.empty:
            hit = ws[(ws["report_family"] == fam) & (ws["workstream_code"] == code)]
            if not hit.empty:
                row = hit.iloc[0].to_dict()
                name = str(row.get("workstream_name", code))
                team = str(row.get("owning_team", code))
        return {"report_family": fam, "workstream_code": code, "workstream_name": name, "owning_team": team}
    def route_feed(self, source: str, layer: str) -> Dict[str, str]:
        s = (source or "").upper()
        l = (layer or "").upper()
        if "SCCL" in s or "FR2590" in s or l == "ERA":
            fam, code = "SCCL (FR2590)", "FR2590"
        elif l == "STARE" or "STARE" in s:
            fam, code = "STARE", "STARE"
        elif l in ("CRRT","CR360") or "CRRT" in s or "CR360" in s:
            fam, code = "CRRT", "CRRT"
        elif l in ("GL","SOR") or "GL" in s:
            fam, code = "CAR", "CAR_GL"
        else:
            fam, code = "CAR", "CAR_GL"

        ws = self.workstreams.copy() if self.workstreams is not None else pd.DataFrame()
        name = code
        team = code
        if not ws.empty:
            hit = ws[(ws["report_family"] == fam) & (ws["workstream_code"] == code)]
            if not hit.empty:
                row = hit.iloc[0].to_dict()
                name = str(row.get("workstream_name", code))
                team = str(row.get("owning_team", code))
        return {"report_family": fam, "workstream_code": code, "workstream_name": name, "owning_team": team}
    # ---------- Workstream Hub UI handlers
    def _refresh_workstream_lists(self):
        fam = getattr(self, "selected_report_family", "All")
        if hasattr(self, "lst_families") and self.lst_families.count() > 0:
            # ensure selection matches state
            for i in range(self.lst_families.count()):
                if (self.lst_families.item(i).data(Qt.ItemDataRole.UserRole) or self.lst_families.item(i).text()) == fam:
                    self.lst_families.blockSignals(True)
                    self.lst_families.setCurrentRow(i)
                    self.lst_families.blockSignals(False)
                    break

        if not hasattr(self, "lst_workstreams"):
            return

        self.lst_workstreams.blockSignals(True)
        self.lst_workstreams.clear()
        ws = self.list_workstreams(fam)
        self.lst_workstreams.addItem(QListWidgetItem("(All)"))
        if ws is not None and not ws.empty:
            for _, r in ws.iterrows():
                it = QListWidgetItem(str(r.get("workstream_name","")))
                it.setData(Qt.ItemDataRole.UserRole, str(r.get("workstream_code","")))
                self.lst_workstreams.addItem(it)
        self.lst_workstreams.setCurrentRow(0)
        self.lst_workstreams.blockSignals(False)

        self.selected_workstream_code = "(All)"
        self.update_workstream_cockpit()
        self.refresh_queue()

    def on_report_family_changed(self, _idx: int):
        fam = "All"
        if hasattr(self, "lst_families") and self.lst_families.currentItem():
            fam = self.lst_families.currentItem().data(Qt.ItemDataRole.UserRole) or "All"
        self.selected_report_family = str(fam)
        self.selected_workstream_code = "(All)"
        self._refresh_workstream_lists()

    def on_workstream_changed(self, _idx: int):
        code = "(All)"
        if hasattr(self, "lst_workstreams") and self.lst_workstreams.currentItem():
            code = self.lst_workstreams.currentItem().data(Qt.ItemDataRole.UserRole) or self.lst_workstreams.currentItem().text()
        if code in (None, "", "(All)"):
            self.selected_workstream_code = "(All)"
        else:
            self.selected_workstream_code = str(code)
        self.update_workstream_cockpit()
        self.refresh_queue()

    def update_workstream_cockpit(self):
        if not hasattr(self, "lbl_ws_name"):
            return
        fam = getattr(self, "selected_report_family", "All")
        ws_code = getattr(self, "selected_workstream_code", "(All)")
        title = f"{fam} / {ws_code}" if ws_code != "(All)" else f"{fam}"
        if fam == "All":
            title = "All workstreams"
        # Resolve workstream name + team if selected
        team = ""
        ws_name = ""
        if ws_code != "(All)" and self.workstreams is not None and not self.workstreams.empty:
            hit = self.workstreams[self.workstreams["workstream_code"].astype(str) == ws_code]
            if not hit.empty:
                ws_name = str(hit.iloc[0].get("workstream_name",""))
                team = str(hit.iloc[0].get("owning_team",""))
        if ws_name:
            title = ws_name
        self.lbl_ws_name.setText(title)

        # Compute health KPIs for current filters
        b = self.breaks.copy() if hasattr(self, "breaks") and self.breaks is not None else pd.DataFrame()
        q = self.build_work_queue()

        # Apply the same filters as queue for KPI consistency
        if fam != "All" and not q.empty and "report_family" in q.columns:
            q = q[q["report_family"].astype(str) == fam].copy()
        if ws_code != "(All)" and not q.empty and "workstream_code" in q.columns:
            q = q[q["workstream_code"].astype(str) == ws_code].copy()

        # Breaks KPIs (use breaks dataframe for accurate material calc)
        open_breaks = 0
        mat_breaks = 0
        if not b.empty:
            bb = b[b["status"].isin(["OPEN","IN REVIEW"])].copy()
            if fam != "All" and "report_family" in bb.columns:
                bb = bb[bb["report_family"].astype(str) == fam].copy()
            if ws_code != "(All)" and "workstream_code" in bb.columns:
                bb = bb[bb["workstream_code"].astype(str) == ws_code].copy()
            open_breaks = len(bb)
            mat_breaks = int((bb["abs_var"].fillna(0.0).astype(float) >= float(self.filters.materiality)).sum()) if "abs_var" in bb.columns else 0

        late_feeds = 0
        if not q.empty:
            late_feeds = len(q[(q["domain"] == "Feeds") & (q["status"].isin(["LATE","FAILED"]))])
        pending_apr = 0
        if not q.empty:
            pending_apr = len(q[q["domain"] == "Approvals"])

        self.lbl_ws_kpi1.setText(f"Open Breaks: {open_breaks}")
        self.lbl_ws_kpi2.setText(f"Material Breaks: {mat_breaks}")
        self.lbl_ws_kpi3.setText(f"Late/Failed Feeds: {late_feeds}")
        self.lbl_ws_kpi4.setText(f"Pending Approvals: {pending_apr}")

        health = "ON_TRACK"
        if late_feeds > 0 or mat_breaks > 0:
            health = "AT_RISK"
        if late_feeds > 0 and mat_breaks > 0:
            health = "BREACHED"
        self.lbl_ws_health.setText(health)





# ---------- UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Left nav
        nav = QFrame()
        nav.setObjectName("Nav")
        nav.setFixedWidth(320)
        nav_l = QVBoxLayout(nav)
        nav_l.setSpacing(10)

        title = QLabel("ORIX")
        title.setObjectName("AppTitle")
        nav_l.addWidget(title)

        sub = QLabel("Enterprise GL • Recon • Reg Reporting")
        sub.setStyleSheet("color:#444444;")
        nav_l.addWidget(sub)

        ws = QGroupBox("Workspace")
        wsl = QFormLayout(ws)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Maker", "Checker", "Executive", "Auditor (Read-only)"])
        self.cmb_mode.currentIndexChanged.connect(self.on_mode_changed)
        wsl.addRow("Mode", self.cmb_mode)

        self.cmb_preset = QComboBox()
        for p in self.data["presets"]["preset"].tolist():
            self.cmb_preset.addItem(p)
        self.cmb_preset.currentIndexChanged.connect(self.apply_preset)
        wsl.addRow("Presets", self.cmb_preset)

        self.chk_changes = QCheckBox("Show changes since last close")
        self.chk_changes.stateChanged.connect(self.refresh_all)
        wsl.addRow("", self.chk_changes)
        nav_l.addWidget(ws)

        self.nav_list = QListWidget()
        for p in [
            "1. Landing Dashboard",
            "2. Feed Health & Ingestion",
            "3. GL Explorer",
            "4. Reconciliation Workspace",
            "5. Variance Management",
            "6. Regulatory Reporting",
            "7. Lineage & BCBS239",
            "8. Audit & Evidence Vault",
            "9. Admin & Governance",
            "10. Close & Certification",
            "11. Report Catalog & Policies",
            "12. Work Queues & Routing",
        ]:
            self.nav_list.addItem(QListWidgetItem(p))
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.on_nav)
        nav_l.addWidget(self.nav_list, 1)

        # Filters
        filters = QGroupBox("Global Filters")
        fl = QFormLayout(filters)

        self.cmb_asof = QComboBox()
        dates = sorted(self.data["gl"]["as_of"].unique())
        for d in dates:
            self.cmb_asof.addItem(str(d), d)
        self.cmb_asof.setCurrentIndex(len(dates) - 1)
        self.cmb_asof.currentIndexChanged.connect(self.update_filters)
        fl.addRow("As-of", self.cmb_asof)

        self.cmb_le = QComboBox()
        for le in sorted(self.data["gl"]["legal_entity"].unique()):
            self.cmb_le.addItem(le)
        self.cmb_le.setCurrentText(self.filters.legal_entity)
        self.cmb_le.currentTextChanged.connect(self.update_filters)
        fl.addRow("Legal Entity", self.cmb_le)

        self.cmb_book = QComboBox()
        for b in sorted(self.data["gl"]["book"].unique()):
            self.cmb_book.addItem(b)
        self.cmb_book.setCurrentText(self.filters.book)
        self.cmb_book.currentTextChanged.connect(self.update_filters)
        self.cmb_book.setToolTip("GAAP = external reporting basis; STAT = statutory/local basis.")
        fl.addRow("Book", self.cmb_book)

        self.cmb_ccy = QComboBox()
        for c in sorted(self.data["gl"]["ccy"].unique()):
            self.cmb_ccy.addItem(c)
        self.cmb_ccy.setCurrentText(self.filters.ccy)
        self.cmb_ccy.currentTextChanged.connect(self.update_filters)
        fl.addRow("CCY", self.cmb_ccy)

        self.spn_mat = QSpinBox()
        self.spn_mat.setRange(100_000, 25_000_000)
        self.spn_mat.setSingleStep(100_000)
        self.spn_mat.setValue(int(self.filters.materiality))
        self.spn_mat.valueChanged.connect(self.update_filters)
        fl.addRow("Materiality", self.spn_mat)

        self.ed_user = QLineEdit(self.current_user)
        self.ed_user.textChanged.connect(lambda t: setattr(self, "current_user", (t or "").strip() or "User"))
        fl.addRow("User", self.ed_user)

        nav_l.addWidget(filters)

        # Main stack
        self.stack = QStackedWidget()
        self.p_dashboard = self._page_dashboard()
        self.p_feed = self._page_feed()
        self.p_gl = self._page_gl()
        self.p_recon = self._page_recon()
        self.p_var = self._page_var()
        self.p_report = self._page_report()
        self.p_lineage = self._page_lineage()
        self.p_audit = self._page_audit()
        self.p_admin = self._page_admin()
        self.p_close = self._page_close()
        self.p_catalog = self._page_catalog()
        self.p_queue = self._page_queue()

        for p in [
            self.p_dashboard, self.p_feed, self.p_gl, self.p_recon, self.p_var, self.p_report,
            self.p_lineage, self.p_audit, self.p_admin, self.p_close, self.p_catalog, self.p_queue
        ]:
            self.stack.addWidget(p)


        # Enterprise dimension tree (dock) — shared drill-path across workspaces
        self.dim_dock = QDockWidget("Enterprise Dim Tree", self)
        self.dim_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.dim_tree = EnterpriseDimTree(self.data, self.on_dim_tree_changed)
        self.dim_dock.setWidget(self.dim_tree)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dim_dock)

        act_toggle_dims = QAction("Toggle Enterprise Dim Tree", self)
        act_toggle_dims.setShortcut("Ctrl+Shift+D")
        act_toggle_dims.triggered.connect(lambda: (self.dim_dock.setVisible(not self.dim_dock.isVisible()), self._save_state()))
        self.addAction(act_toggle_dims)

        root.addWidget(nav)

        # Main area: persistent context header + page stack
        main_area = QWidget()
        main_l = QVBoxLayout(main_area)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(8)

        ctx = QFrame()
        ctx.setObjectName('CtxBar')
        ctx_l = QHBoxLayout(ctx)
        ctx_l.setContentsMargins(10, 6, 10, 6)
        ctx_l.setSpacing(10)

        self.lbl_ctx_main = QLabel('')
        self.lbl_ctx_main.setStyleSheet('font-weight:600;')
        self.lbl_ctx_breadcrumb = QLabel('')
        self.lbl_ctx_breadcrumb.setStyleSheet('color:#5A6772;')

        btn_copy_ctx = QPushButton('Copy Context')
        btn_copy_ctx.clicked.connect(self.copy_context_snapshot)
        btn_export_ctx = QPushButton('Export Snapshot')
        btn_export_ctx.clicked.connect(self.export_context_snapshot)

        ctx_l.addWidget(self.lbl_ctx_main, 0)
        ctx_l.addStretch(1)
        ctx_l.addWidget(self.lbl_ctx_breadcrumb, 0)
        ctx_l.addStretch(1)
        ctx_l.addWidget(btn_copy_ctx)
        ctx_l.addWidget(btn_export_ctx)

        main_l.addWidget(ctx)
        main_l.addWidget(self.stack, 1)

        root.addWidget(main_area, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

    # ---------- theme
    def _apply_theme(self):
        """Use a light, Windows-native friendly look for demos.

        - Avoids dark QSS that hurts readability on projectors.
        - Keeps the UI mostly platform-native (Qt style + palette).
        """
        # Prefer Windows style when available (falls back silently on other OSes)
        app = QApplication.instance()
        if app is not None:
            try:
                app.setStyle("Windows")
            except Exception:
                pass

        # Use a readable default UI font
        self.setFont(QFont("Segoe UI", 10))

        # Clear any heavy global styling and keep things native/light
        self.setStyleSheet("""
        QLabel#AppTitle { font-size: 20px; font-weight: 700; }
        QFrame#Nav { border-right: 1px solid #C8C8C8; }
        QFrame#CtxBar { border: 1px solid #D6D6D6; border-radius: 6px; }
        """)


    # ---------- Enterprise table UX: column chooser + saved views
    def _new_table_key(self) -> str:
        self._table_seq += 1
        return f"tbl_{self._table_seq:02d}"

    def _register_table(self, table_key: str, tbl: QTableView, model: DataFrameModel):
        self._table_registry[table_key] = tbl
        self._table_models[table_key] = model
        tbl.setObjectName(table_key)

        # Track active table for menu actions / export (best-effort)
        tbl.clicked.connect(lambda _ix, k=table_key: setattr(self, '_active_table_key', k))
        tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tbl.customContextMenuRequested.connect(lambda pos, k=table_key: self._show_table_menu(k, pos))

    def _show_table_menu(self, table_key: str, pos):
        tbl = self._table_registry.get(table_key)
        model = self._table_models.get(table_key)
        if tbl is None or model is None:
            return
        cols = list(getattr(model, '_df', pd.DataFrame()).columns)
        if not cols:
            return

        menu = QMenu(tbl)

        # Apply saved view submenu
        views = self._table_views.get(table_key, {}).get('views', {}) if isinstance(self._table_views.get(table_key, {}), dict) else {}
        active = self._table_views.get(table_key, {}).get('active', 'Default') if isinstance(self._table_views.get(table_key, {}), dict) else 'Default'
        sub_apply = menu.addMenu('Apply Saved View')
        if isinstance(views, dict) and views:
            for name in sorted(views.keys()):
                act = QAction(name, tbl)
                act.setCheckable(True)
                act.setChecked(name == active)
                act.triggered.connect(lambda _=False, n=name: self._apply_named_view(table_key, n))
                sub_apply.addAction(act)
        else:
            act = QAction('Default', tbl)
            act.setEnabled(False)
            sub_apply.addAction(act)

        menu.addSeparator()

        act_cols = QAction('Columns…', tbl)
        act_cols.triggered.connect(lambda: self._choose_columns(table_key))
        menu.addAction(act_cols)

        act_save = QAction('Save Current as View…', tbl)
        act_save.triggered.connect(lambda: self._save_view_as(table_key))
        menu.addAction(act_save)

        act_reset = QAction('Reset Columns (Default)', tbl)
        act_reset.triggered.connect(lambda: self._reset_view(table_key))
        menu.addAction(act_reset)

        menu.addSeparator()
        act_copy = QAction('Copy Context Snapshot', tbl)
        act_copy.triggered.connect(self.copy_context_snapshot)
        menu.addAction(act_copy)

        menu.exec(tbl.viewport().mapToGlobal(pos))

    def _ensure_table_view_struct(self, table_key: str, all_cols: List[str]):
        if table_key not in self._table_views or not isinstance(self._table_views.get(table_key), dict):
            self._table_views[table_key] = {'active': 'Default', 'views': {'Default': list(all_cols)}}
        tv = self._table_views.get(table_key, {})
        if 'views' not in tv or not isinstance(tv.get('views'), dict):
            tv['views'] = {'Default': list(all_cols)}
        if 'Default' not in tv['views']:
            tv['views']['Default'] = list(all_cols)
        if 'active' not in tv:
            tv['active'] = 'Default'

    def _current_visible_columns(self, table_key: str) -> List[str]:
        tbl = self._table_registry.get(table_key)
        model = self._table_models.get(table_key)
        if tbl is None or model is None:
            return []
        cols = list(getattr(model, '_df', pd.DataFrame()).columns)
        vis = []
        for i, c in enumerate(cols):
            if not tbl.isColumnHidden(i):
                vis.append(str(c))
        return vis

    def _apply_named_view(self, table_key: str, view_name: str):
        tv = self._table_views.get(table_key, {})
        if not isinstance(tv, dict):
            return
        views = tv.get('views', {})
        if not isinstance(views, dict) or view_name not in views:
            return
        tv['active'] = view_name
        self._apply_table_view(table_key)
        self._save_state()

    def _choose_columns(self, table_key: str):
        model = self._table_models.get(table_key)
        tbl = self._table_registry.get(table_key)
        if model is None or tbl is None:
            return
        cols = list(getattr(model, '_df', pd.DataFrame()).columns)
        if not cols:
            return
        self._ensure_table_view_struct(table_key, cols)
        current = self._current_visible_columns(table_key)
        dlg = ColumnChooserDialog(cols, current, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dlg.visible_columns()
        # Store as an Adhoc view and activate
        tv = self._table_views[table_key]
        tv.setdefault('views', {})
        tv['views']['Adhoc'] = chosen
        tv['active'] = 'Adhoc'
        self._apply_table_view(table_key)
        self._save_state()

    def _save_view_as(self, table_key: str):
        tv = self._table_views.get(table_key)
        if not isinstance(tv, dict):
            # Initialize from current state
            model = self._table_models.get(table_key)
            cols = list(getattr(model, '_df', pd.DataFrame()).columns) if model is not None else []
            self._ensure_table_view_struct(table_key, cols)
            tv = self._table_views.get(table_key)
        name, ok = QInputDialog.getText(self, 'Save View', 'View name:')
        if not ok:
            return
        name = (name or '').strip()
        if not name:
            return
        tv.setdefault('views', {})
        tv['views'][name] = self._current_visible_columns(table_key)
        tv['active'] = name
        self._save_state()

    def _reset_view(self, table_key: str):
        model = self._table_models.get(table_key)
        cols = list(getattr(model, '_df', pd.DataFrame()).columns) if model is not None else []
        self._ensure_table_view_struct(table_key, cols)
        self._table_views[table_key]['active'] = 'Default'
        self._apply_table_view(table_key)
        self._save_state()

    def _apply_table_view(self, table_key: str):
        tbl = self._table_registry.get(table_key)
        model = self._table_models.get(table_key)
        if tbl is None or model is None:
            return
        cols = list(getattr(model, '_df', pd.DataFrame()).columns)
        if not cols:
            return
        self._ensure_table_view_struct(table_key, cols)
        tv = self._table_views.get(table_key, {})
        active = tv.get('active', 'Default')
        views = tv.get('views', {})
        visible = views.get(active) if isinstance(views, dict) else None
        if not isinstance(visible, list) or not visible:
            visible = list(cols)
        visible_set = set(map(str, visible))
        for i, c in enumerate(cols):
            tbl.setColumnHidden(i, str(c) not in visible_set)

    def _apply_table_views_to_all(self):
        for k in list(self._table_registry.keys()):
            try:
                self._apply_table_view(k)
            except Exception:
                continue

    # ---------- Context header + shareable snapshot
    def _context_snapshot(self) -> Dict[str, Any]:
        return {
            'app': APP_NAME,
            'version': APP_VERSION,
            'ts': now_str(),
            'mode': self.mode,
            'active_page': self.nav_list.currentItem().text() if hasattr(self, 'nav_list') and self.nav_list.currentItem() else '',
            'global_filters': {
                'as_of': str(self.filters.as_of),
                'legal_entity': self.filters.legal_entity,
                'book': self.filters.book,
                'ccy': self.filters.ccy,
                'materiality': float(self.filters.materiality),
                'tolerance': float(self.spn_tol.value()) if hasattr(self, 'spn_tol') else None,
            },
            'sccl_filters': dict(self.sccl_filters),
            'breadcrumbs': self._breadcrumbs(),
        }

    def copy_context_snapshot(self):
        snap = self._context_snapshot()
        QGuiApplication.clipboard().setText(json.dumps(snap, indent=2))
        self.status.showMessage('Context snapshot copied to clipboard', 2500)

    def export_context_snapshot(self):
        snap = self._context_snapshot()
        default_name = f"context_snapshot_{self.filters.as_of}.json"
        path, _ = QFileDialog.getSaveFileName(self, 'Export Context Snapshot', default_name, 'JSON Files (*.json)')
        if not path:
            return
        Path(path).write_text(json.dumps(snap, indent=2), encoding='utf-8')
        self.log('EXPORT', 'CONTEXT', path, 'context snapshot')
        QMessageBox.information(self, 'Exported', f'Saved: {path}')

    def export_close_pack(self):
        """Export a demo close pack (zip) suitable for LT walkthrough: snapshot, exceptions, explanations, evidence, audit."""
        default_name = f"close_pack_{self.cycle_id()}_{now_str().replace(':','').replace(' ','_')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, 'Export Close Pack (ZIP)', default_name, 'ZIP Files (*.zip)')
        if not path:
            return

        # Build a staging folder next to the zip (safe temp)
        staging = Path(path).with_suffix('')
        try:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)

            # Executive summary (text)
            (staging / 'executive_summary.txt').write_text(self.exec_summary(), encoding='utf-8')

            # Context
            (staging / 'context_snapshot.json').write_text(json.dumps(self._context_snapshot(), indent=2), encoding='utf-8')

            # Gates
            self.close_gate_status().to_csv(staging / 'close_gates.csv', index=False)

            # Core data artifacts (csv)
            self.recon_gl_sor().to_csv(staging / 'recon_gl_sor.csv', index=False)
            if not self.breaks.empty:
                self.breaks.to_csv(staging / 'breaks.csv', index=False)
            if not self.variance_expl.empty:
                self.variance_expl.to_csv(staging / 'variance_explanations_gl.csv', index=False)
            if not self.sccl_expl.empty:
                self.sccl_expl.to_csv(staging / 'variance_explanations_sccl.csv', index=False)
            if not self.evidence_registry.empty:
                self.evidence_registry.to_csv(staging / 'evidence_registry.csv', index=False)
            if not self.audit.empty:
                self.audit.to_csv(staging / 'audit_log.csv', index=False)

            # Report catalog / policies / mapping
            if self.report_catalog is not None and not self.report_catalog.empty:
                self.report_catalog.to_csv(staging / 'report_catalog.csv', index=False)
            if self.recon_policies is not None and not self.recon_policies.empty:
                self.recon_policies.to_csv(staging / 'recon_policies.csv', index=False)
            if self.mapping_sets is not None and not self.mapping_sets.empty:
                self.mapping_sets.to_csv(staging / 'mapping_sets.csv', index=False)

            # Zip it
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                for fp in staging.rglob('*'):
                    if fp.is_file():
                        z.write(fp, arcname=str(fp.relative_to(staging)))

            self.log('EXPORT', 'CLOSE_PACK', path, f"cycle={self.cycle_id()}")
            QMessageBox.information(self, 'Exported', f'Saved: {path}')
        except Exception as e:
            QMessageBox.warning(self, 'Failed', f'Export failed: {e}')
        finally:
            try:
                shutil.rmtree(staging, ignore_errors=True)
            except Exception:
                pass

    def update_context_header(self):
        if not hasattr(self, 'lbl_ctx_main') or not hasattr(self, 'lbl_ctx_breadcrumb'):
            return
        self.lbl_ctx_main.setText(
            f"As-of {self.filters.as_of} | LE {self.filters.legal_entity} | Book {self.filters.book} | CCY {self.filters.ccy} | Mode {self.mode}"
        )
        self.lbl_ctx_breadcrumb.setText(self._breadcrumbs())



    def _table(self, table_key: Optional[str] = None) -> Tuple[QTableView, DataFrameModel]:
        """Create a QTableView with enterprise-friendly defaults + column chooser support."""
        tbl = QTableView()
        tbl.setAlternatingRowColors(True)
        tbl.setSortingEnabled(True)
        tbl.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        tbl.setSelectionMode(QTableView.SelectionMode.SingleSelection)

        model = DataFrameModel(pd.DataFrame())
        tbl.setModel(model)
        tbl.setItemDelegate(BadgeDelegate(tbl))
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.verticalHeader().setVisible(False)

        # Register table for saved column views
        key = table_key or self._new_table_key()
        self._register_table(key, tbl, model)

        return tbl, model

    def _kpi(self, title: str, tooltip: str) -> Tuple[QGroupBox, QLabel, QLabel]:
        g = QGroupBox(title)
        v = QVBoxLayout(g)
        v.setSpacing(3)
        val = QLabel("0")
        val.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        sub = QLabel("")
        sub.setStyleSheet("color:#444444;")
        g.setToolTip(tooltip)
        v.addWidget(val)
        v.addWidget(sub)
        return g, val, sub

    # ---------- Pages
    def _page_dashboard(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        h = QLabel("Landing Dashboard")
        h.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(h)

        self.lbl_ctx_banner = QLabel("")
        self.lbl_ctx_banner.setStyleSheet("color:#444444;")
        layout.addWidget(self.lbl_ctx_banner)

        # Close-cycle + freshness + change summary banner (projector-friendly)
        self.frm_cycle = QFrame()
        self.frm_cycle.setStyleSheet("border: 1px solid #D6D6D6; border-radius: 6px; padding: 6px;")
        bl = QHBoxLayout(self.frm_cycle)
        bl.setContentsMargins(10, 6, 10, 6)
        self.lbl_cycle_badge = QLabel("")
        self.lbl_cycle_badge.setStyleSheet("font-weight:600;")
        self.lbl_fresh = QLabel("")
        self.lbl_fresh.setStyleSheet("color:#5A6772;")
        self.lbl_changed = QLabel("")
        self.lbl_changed.setStyleSheet("color:#5A6772;")
        bl.addWidget(self.lbl_cycle_badge)
        bl.addStretch(1)
        bl.addWidget(self.lbl_fresh)
        bl.addStretch(1)
        bl.addWidget(self.lbl_changed)
        self.chk_changes = QCheckBox("Show Δ vs prior")
        self.chk_changes.setChecked(True)
        self.chk_changes.stateChanged.connect(self.refresh_dashboard)
        bl.addWidget(self.chk_changes)
        layout.addWidget(self.frm_cycle)

        row = QHBoxLayout()
        b1, self.k_material, self.k_material_sub = self._kpi("Material Breaks", "abs(variance) >= materiality")
        b2, self.k_open, self.k_open_sub = self._kpi("Open Breaks", "Open + In Review")
        b3, self.k_feeds, self.k_feeds_sub = self._kpi("Feeds Late/Failed", "Timeliness control exceptions")
        b4, self.k_recon, self.k_recon_sub = self._kpi("Recon Completion", "1 - (#break rows / total)")
        b5, self.k_conf, self.k_conf_sub = self._kpi("Confidence Score", "Composite score: breaks, SLA, feeds, rejects")
        for b in [b1, b2, b3, b4, b5]:
            row.addWidget(b)
        layout.addLayout(row)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)

        self.lbl_dash_left = QLabel("Top Breaks (GL↔SOR)")
        ll.addWidget(self.lbl_dash_left)

        self.tbl_top, self.m_top = self._table('dashboard_top')
        ll.addWidget(self.tbl_top, 1)

        ll.addWidget(QLabel('Action Queue (Exception-first)'))
        self.tbl_actions, self.m_actions = self._table('dashboard_actions')
        self.tbl_actions.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        ll.addWidget(self.tbl_actions)

        btns = QHBoxLayout()
        self.btn_create_largest = QPushButton("Create Break for Largest Variance")
        self.btn_create_largest.clicked.connect(self.create_largest_break)
        self.btn_copy_exec = QPushButton("Copy Executive Summary")
        self.btn_copy_exec.clicked.connect(self.copy_exec_summary)
        btns.addWidget(self.btn_create_largest)
        btns.addWidget(self.btn_copy_exec)
        btns.addStretch(1)
        ll.addLayout(btns)

        self.grp_intel = QGroupBox("Break Intelligence")
        il = QHBoxLayout(self.grp_intel)
        self.lbl_root = QLabel("Top Root Cause: —"); self.lbl_root.setStyleSheet("color:#444444;")
        self.lbl_repeat = QLabel("Repeat Offenders: —"); self.lbl_repeat.setStyleSheet("color:#444444;")
        self.lbl_sla = QLabel("SLA Risk: —"); self.lbl_sla.setStyleSheet("color:#444444;")
        il.addWidget(self.lbl_root); il.addWidget(self.lbl_repeat); il.addWidget(self.lbl_sla)
        ll.addWidget(self.grp_intel)

        right = QWidget()
        rl = QVBoxLayout(right)

        rl.addWidget(QLabel("Feed Health Snapshot"))
        self.tbl_feed_snap, self.m_feed_snap = self._table('dashboard_feeds')
        rl.addWidget(self.tbl_feed_snap, 1)

        rl.addWidget(QLabel("Report Readiness"))
        self.tbl_ready, self.m_ready = self._table('dashboard_readiness')
        self.tbl_ready.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(self.tbl_ready)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([980, 600])
        layout.addWidget(split, 1)
        return w

    def _page_feed(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        hdr = QLabel("Feed Health & Ingestion Control")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        ll.addWidget(hdr)

        self.tbl_feed, self.m_feed = self._table('feeds_main')
        ll.addWidget(self.tbl_feed, 1)

        ll.addWidget(QLabel("Reject Samples (Illustrative)"))
        self.tbl_rej, self.m_rej = self._table('feeds_rejects')
        ll.addWidget(self.tbl_rej)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Actions"))
        self.cmb_feed = QComboBox()
        rl.addWidget(self.cmb_feed)

        self.btn_rerun = QPushButton("Re-run Ingestion (log)")
        self.btn_rerun.clicked.connect(self.rerun_feed)
        rl.addWidget(self.btn_rerun)

        self.btn_inc = QPushButton("Create Incident (log)")
        self.btn_inc.clicked.connect(self.create_incident)
        rl.addWidget(self.btn_inc)

        rl.addWidget(QLabel("BCBS239 Controls / Rules"))
        self.tbl_rules, self.m_rules = self._table()
        self.tbl_rules.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(self.tbl_rules, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([1080, 480])
        layout.addWidget(split)
        return w

    def _page_gl(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("GL Explorer")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        top = QHBoxLayout()
        top.addWidget(QLabel("Search account/name:"))
        self.ed_gl = QLineEdit("120200")
        self.ed_gl.textChanged.connect(self.refresh_gl)
        top.addWidget(self.ed_gl, 1)
        layout.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Balances (Account × Product)"))
        self.tbl_gl, self.m_gl = self._table('gl_explorer')
        self.tbl_gl.clicked.connect(self.on_gl_selected)
        ll.addWidget(self.tbl_gl, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Explain This Number"))
        self.lbl_explain = QLabel("Select a row to see mapping, lineage, and risk drivers.")
        self.lbl_explain.setWordWrap(True)
        self.lbl_explain.setStyleSheet("color:#444444;")
        rl.addWidget(self.lbl_explain)

        rl.addWidget(QLabel("Report Mappings"))
        self.tbl_map_acc, self.m_map_acc = self._table()
        self.tbl_map_acc.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(self.tbl_map_acc, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([980, 560])
        layout.addWidget(split, 1)
        return w

    def _page_recon(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Reconciliation Workspace")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        self.tabs = QTabWidget()

        # GL vs SOR
        t1w = QWidget()
        t1 = QVBoxLayout(t1w)
        c1 = QHBoxLayout()
        c1.addWidget(QLabel("Tolerance (abs):"))
        self.spn_tol = QSpinBox()
        self.spn_tol.setRange(0, 100_000_000)
        self.spn_tol.setSingleStep(10_000)
        self.spn_tol.valueChanged.connect(self.refresh_recon)
        c1.addWidget(self.spn_tol)
        c1.addStretch(1)
        self.btn_create_breaks = QPushButton("Create Break(s) for Selected Rows")
        self.btn_create_breaks.clicked.connect(self.create_breaks_from_selected)
        c1.addWidget(self.btn_create_breaks)
        t1.addLayout(c1)

        self.tbl_recon, self.m_recon = self._table('recon_main')
        self.tbl_recon.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        t1.addWidget(self.tbl_recon, 1)

        # CRRT vs CR360
        t2w = QWidget()
        t2 = QVBoxLayout(t2w)
        c2 = QHBoxLayout()
        c2.addWidget(QLabel("Tolerance (CRRT↔CR360):"))
        self.spn_tol2 = QSpinBox()
        self.spn_tol2.setRange(0, 100_000_000)
        self.spn_tol2.setSingleStep(10_000)
        self.spn_tol2.valueChanged.connect(self.refresh_recon)
        c2.addWidget(self.spn_tol2)
        c2.addStretch(1)
        t2.addLayout(c2)

        self.tbl_recon2, self.m_recon2 = self._table()
        t2.addWidget(self.tbl_recon2, 1)

        # Breaks (work items) + timeline
        t3w = QWidget()
        t3 = QVBoxLayout(t3w)

        top = QHBoxLayout()
        self.ed_break_search = QLineEdit()
        self.ed_break_search.setPlaceholderText("Search breaks (account, product, root cause, id)...")
        self.ed_break_search.textChanged.connect(self.refresh_breaks)
        top.addWidget(self.ed_break_search, 1)

        self.cmb_break_status = QComboBox()
        self.cmb_break_status.addItems(["(All)", "OPEN", "IN REVIEW", "APPROVED", "CLOSED"])
        self.cmb_break_status.currentIndexChanged.connect(self.refresh_breaks)
        top.addWidget(QLabel("Status:"))
        top.addWidget(self.cmb_break_status)

        self.btn_open_break = QPushButton("Open Break Detail")
        self.btn_open_break.clicked.connect(self.open_break)
        top.addWidget(self.btn_open_break)
        t3.addLayout(top)

        split = QSplitter(Qt.Orientation.Vertical)

        p1 = QWidget(); p1l = QVBoxLayout(p1)
        self.tbl_breaks, self.m_breaks = self._table('recon_breaks')
        self.tbl_breaks.clicked.connect(self.refresh_timeline)
        p1l.addWidget(self.tbl_breaks, 1)

        p2 = QWidget(); p2l = QVBoxLayout(p2)
        p2l.addWidget(QLabel("Change History Timeline"))
        self.tbl_timeline, self.m_timeline = self._table()
        self.tbl_timeline.setSelectionMode(QTableView.SelectionMode.NoSelection)
        p2l.addWidget(self.tbl_timeline, 1)

        split.addWidget(p1)
        split.addWidget(p2)
        split.setSizes([560, 260])

        t3.addWidget(split, 1)

        self.tabs.addTab(t1w, "GL ↔ SOR")
        self.tabs.addTab(t2w, "CRRT ↔ CR360")
        self.tabs.addTab(t3w, "Breaks (Work Items)")
        layout.addWidget(self.tabs, 1)
        return w

    def _page_var(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Variance Management")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Variance Population (Current vs Prior Close)"))
        self.tbl_var, self.m_var = self._table('variance_main')
        self.tbl_var.clicked.connect(self.on_var_selected)
        ll.addWidget(self.tbl_var, 1)

        right = QWidget()
        rl = QVBoxLayout(right)

        
        box = QGroupBox("Explainability Capture — Workflow (Maker/Checker) + Carry-Forward")
        form = QFormLayout(box)

        self.lbl_var = QLabel("(Select a variance row)")
        self.lbl_var.setStyleSheet("color:#444444;")

        self.lbl_var_status = QLabel("Status: —")
        self.lbl_var_status.setStyleSheet("color:#444444;")

        self.cmb_reason = QComboBox()
        self.cmb_reason.addItems([
            "Volume change", "Rate/Spread change", "Mix change", "Reclass/Mapping change", "Timing/Accrual",
            "FX impact", "One-time event", "Model/Forecast update (STARE)", "Credit loss update (CECL/ACL)"
        ])


        # Annotation (structured metadata) vs Commentary (free text narrative)
        self.cmb_var_ann_type = QComboBox()
        self.cmb_var_ann_type.addItems(ANNOTATION_TYPES)
        self.cmb_var_ann_type.setCurrentText("(None)")

        self.cmb_var_ann_scope = QComboBox()
        self.cmb_var_ann_scope.addItems(ANNOTATION_SCOPES)
        self.cmb_var_ann_scope.setCurrentText("Line")

        self.ed_var_evidence = QLineEdit("")
        self.ed_var_evidence.setPlaceholderText("Evidence Ref (required for some annotation types)")

        self.lbl_var_ann_req = QLabel("")
        self.lbl_var_ann_req.setStyleSheet("color:#444444;")
        def _refresh_var_ann_req():
            t = self.cmb_var_ann_type.currentText()
            rule = ANNOTATION_RULES.get(t, ANNOTATION_RULES["(None)"])
            ev = "Evidence required" if rule.get("evidence_required") else "Evidence optional"
            ap = "Approval required" if rule.get("approval_required") else "Approval optional"
            self.lbl_var_ann_req.setText(f"{ev} • {ap} • Default scope: {rule.get('default_scope','Item')}")
        self.cmb_var_ann_type.currentTextChanged.connect(lambda _=None: _refresh_var_ann_req())
        _refresh_var_ann_req()

        self.txt_var = QTextEdit()
        self.txt_var.setFixedHeight(120)

        self.chk_var_carry = QCheckBox("Carry-forward to next close (user controlled)")
        self.chk_var_carry.setChecked(True)

        # Actions
        btn_row1 = QHBoxLayout()
        self.btn_save_var = QPushButton("Save Draft")
        self.btn_save_var.clicked.connect(self.save_var_expl)
        self.btn_var_submit = QPushButton("Submit for Approval")
        self.btn_var_submit.clicked.connect(self.submit_var_expl)
        btn_row1.addWidget(self.btn_save_var)
        btn_row1.addWidget(self.btn_var_submit)

        btn_row2 = QHBoxLayout()
        self.btn_var_approve = QPushButton("Approve (Checker)")
        self.btn_var_approve.clicked.connect(self.approve_var_expl)
        self.btn_var_reject = QPushButton("Reject (Checker)")
        self.btn_var_reject.clicked.connect(self.reject_var_expl)
        btn_row2.addWidget(self.btn_var_approve)
        btn_row2.addWidget(self.btn_var_reject)

        # Rollover: pull prior-close explanation for same slice (preview) + bulk carry-forward
        self.chk_var_autofill = QCheckBox("Auto-fill from prior close if available")
        self.chk_var_autofill.setChecked(True)
        self.btn_var_roll = QPushButton("Rollover Prior Explanation → Current (Preview)")
        self.btn_var_roll.clicked.connect(self.rollover_var_expl)
        self.btn_var_bulk_roll = QPushButton("Bulk Carry-Forward Rollover (Approved → Drafts)")
        self.btn_var_bulk_roll.clicked.connect(self.bulk_rollover_var)

        form.addRow("Selected", self.lbl_var)
        form.addRow("Workflow", self.lbl_var_status)
        form.addRow("Reason", self.cmb_reason)
        form.addRow("Annotation Type", self.cmb_var_ann_type)
        form.addRow("Annotation Scope", self.cmb_var_ann_scope)
        form.addRow("Evidence Ref", self.ed_var_evidence)
        form.addRow("", self.lbl_var_ann_req)
        form.addRow("Commentary (free text)", self.txt_var)
        form.addRow("", self.chk_var_carry)
        form.addRow("", btn_row1)
        form.addRow("", btn_row2)
        form.addRow("", self.chk_var_autofill)
        form.addRow("", self.btn_var_roll)
        form.addRow("", self.btn_var_bulk_roll)

        rl.addWidget(box)

        nb = QGroupBox("Narrative Builder (Regulator-ready Draft)")
        nbl = QVBoxLayout(nb)
        self.txt_narr = QTextEdit()
        self.txt_narr.setFixedHeight(240)
        nbl.addWidget(self.txt_narr)
        nb_btn = QHBoxLayout()
        self.btn_build = QPushButton("Build Narrative")
        self.btn_build.clicked.connect(self.build_narrative)
        self.btn_copy_narr = QPushButton("Copy to Clipboard")
        self.btn_copy_narr.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.txt_narr.toPlainText()))
        nb_btn.addWidget(self.btn_build); nb_btn.addWidget(self.btn_copy_narr); nb_btn.addStretch(1)
        nbl.addLayout(nb_btn)
        rl.addWidget(nb)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([920, 640])
        layout.addWidget(split, 1)
        return w

    def _page_report(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Regulatory Reporting Workspace")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        top = QHBoxLayout()
        top.addWidget(QLabel("Report:"))
        self.cmb_report = QComboBox()
        self.cmb_report.addItems(["FR2590", "Y-9C", "FR Y-15", "FR 2052a (LCR)", "NSFR", "Call Report", "FR Y (Other)", "CCAR", "CECL/ACL", "STARE", "ERA"])
        self.cmb_report.currentTextChanged.connect(self.refresh_reporting)
        top.addWidget(self.cmb_report)

        self.lbl_report = QLabel("")
        self.lbl_report.setStyleSheet("color:#444444;")
        top.addWidget(self.lbl_report, 1)

        self.btn_cert = QPushButton("Certify Selected Line (log)")
        self.btn_cert.clicked.connect(self.certify_line)
        top.addWidget(self.btn_cert)

        self.btn_lock = QPushButton("Lock Report Cycle (log)")
        self.btn_lock.clicked.connect(self.lock_report)
        top.addWidget(self.btn_lock)

        layout.addLayout(top)

        self.report_tabs = QTabWidget()

        # -------------------------
        # Tab 1: Classic report lines (mapping → drilldown)
        # -------------------------
        t_lines = QWidget()
        t1 = QVBoxLayout(t_lines)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Report Lines"))
        self.tbl_lines, self.m_lines = self._table('report_lines')
        self.tbl_lines.clicked.connect(self.on_line_selected)
        ll.addWidget(self.tbl_lines, 1)

        self.btn_impact = QPushButton("Impact Preview for Selected Line (Mapping)")
        self.btn_impact.clicked.connect(self.impact_preview)
        ll.addWidget(self.btn_impact)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Line Drilldown (GL by mapped accounts)"))
        self.tbl_drill, self.m_drill = self._table()
        self.tbl_drill.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(self.tbl_drill, 1)

        split.addWidget(left); split.addWidget(right)
        split.setSizes([940, 600])
        t1.addWidget(split, 1)

        # -------------------------
        # Tab 2: SCCL / FR2590 exposure drilldown (enterprise hierarchy)
        # -------------------------
        t_sccl = QWidget()
        t2 = QVBoxLayout(t_sccl)

        filt = QGroupBox("SCCL Hierarchy Filters (A-Node → Booking Entity → Connected Group → Ultimate Parent → Counterparty → Exposure Category)")
        fl = QHBoxLayout(filt)

        fl.addWidget(QLabel("A-Node:"))
        self.cmb_sccl_anode = QComboBox()
        self.cmb_sccl_anode.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_anode)

        fl.addWidget(QLabel("Booking Entity:"))
        self.cmb_sccl_be = QComboBox()
        self.cmb_sccl_be.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_be)

        fl.addWidget(QLabel("Connected Group:"))
        self.cmb_sccl_cg = QComboBox()
        self.cmb_sccl_cg.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_cg)

        fl.addWidget(QLabel("Ultimate Parent:"))
        self.cmb_sccl_up = QComboBox()
        self.cmb_sccl_up.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_up)

        fl.addWidget(QLabel("Counterparty:"))
        self.cmb_sccl_cp = QComboBox()
        self.cmb_sccl_cp.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_cp)

        fl.addWidget(QLabel("Category:"))
        self.cmb_sccl_cat = QComboBox()
        self.cmb_sccl_cat.currentIndexChanged.connect(self.on_sccl_filter_changed)
        fl.addWidget(self.cmb_sccl_cat)

        fl.addStretch(1)
        t2.addWidget(filt)

        split2 = QSplitter(Qt.Orientation.Horizontal)

        left2 = QWidget(); l2 = QVBoxLayout(left2)
        l2.addWidget(QLabel("SCCL Variance (Current vs Prior Close) — aggregated view"))
        self.tbl_sccl, self.m_sccl = self._table()
        self.tbl_sccl.clicked.connect(self.on_sccl_selected)
        l2.addWidget(self.tbl_sccl, 1)

        right2 = QWidget(); r2 = QVBoxLayout(right2)

        box_sel = QGroupBox("Selected Slice")
        bsl = QVBoxLayout(box_sel)
        self.lbl_sccl_selected = QLabel("(Select a row)")
        self.lbl_sccl_selected.setWordWrap(True)
        self.lbl_sccl_selected.setStyleSheet("color:#444444;")
        bsl.addWidget(self.lbl_sccl_selected)
        r2.addWidget(box_sel)

        self.lbl_sccl_explain = QLabel("")
        self.lbl_sccl_explain.setWordWrap(True)
        self.lbl_sccl_explain.setStyleSheet("color:#444444;")
        r2.addWidget(self.lbl_sccl_explain)

        
        # Details (Atomic vs Mitigation): use tabs inside a resizable splitter to reduce clutter
        self.sccl_right_split = QSplitter(Qt.Orientation.Vertical)

        self.sccl_detail_tabs = QTabWidget()

        # Atomic tab
        t_atomic = QWidget()
        la = QVBoxLayout(t_atomic)
        la.setContentsMargins(0, 0, 0, 0)
        la.addWidget(QLabel("Instrument / Trade Drilldown (Atomic)"))
        self.lbl_sccl_trade_restricted = QLabel(
            "Trade-level view is restricted by role/entitlement. Switch to Maker/Checker to view atomic trades."
        )
        self.lbl_sccl_trade_restricted.setStyleSheet("color:#8A4B00;")
        self.lbl_sccl_trade_restricted.setVisible(False)
        la.addWidget(self.lbl_sccl_trade_restricted)
        self.tbl_sccl_trades, self.m_sccl_trades = self._table()
        self.tbl_sccl_trades.setSelectionMode(QTableView.SelectionMode.NoSelection)
        la.addWidget(self.tbl_sccl_trades, 1)
        self.sccl_detail_tabs.addTab(t_atomic, "Atomic")

        # Mitigation tab
        t_mitig = QWidget()
        lm = QVBoxLayout(t_mitig)
        lm.setContentsMargins(0, 0, 0, 0)
        lm.addWidget(QLabel("Netting / Collateral Context (Mitigation)"))
        self.tbl_sccl_mitig, self.m_sccl_mitig = self._table()
        self.tbl_sccl_mitig.setSelectionMode(QTableView.SelectionMode.NoSelection)
        lm.addWidget(self.tbl_sccl_mitig, 1)
        self.sccl_detail_tabs.addTab(t_mitig, "Mitigation")

        # Add tabs to splitter (explanation panel is added after it is built)
        self.sccl_right_split.addWidget(self.sccl_detail_tabs)
        self.sccl_right_split.setStretchFactor(0, 3)

        r2.addWidget(self.sccl_right_split, 3)

        
        box_ex = QGroupBox("Explained Variance (SCCL) — Workflow (Maker/Checker) + Carry-Forward")
        exf = QFormLayout(box_ex)

        self.lbl_sccl_status = QLabel("Status: —")
        self.lbl_sccl_status.setStyleSheet("color:#444444;")

        self.cmb_sccl_reason = QComboBox()
        self.cmb_sccl_reason.addItems([
            "Volume change (drawdown/repayment)", "New trades / positions", "Maturity / runoff",
            "Netting set change", "Collateral / margin change", "Guarantee / credit protection",
            "Connected group change (governance)", "Reclass / taxonomy change", "FX impact", "One-time event"
        ])


        # Annotation (structured metadata) vs Commentary (free text narrative)
        self.cmb_sccl_ann_type = QComboBox()
        self.cmb_sccl_ann_type.addItems(ANNOTATION_TYPES)
        self.cmb_sccl_ann_type.setCurrentText("(None)")

        self.cmb_sccl_ann_scope = QComboBox()
        self.cmb_sccl_ann_scope.addItems(ANNOTATION_SCOPES)
        self.cmb_sccl_ann_scope.setCurrentText("Line")

        self.ed_sccl_evidence = QLineEdit("")
        self.ed_sccl_evidence.setPlaceholderText("Evidence Ref (required for some annotation types)")

        self.lbl_sccl_ann_req = QLabel("")
        self.lbl_sccl_ann_req.setStyleSheet("color:#444444;")
        def _refresh_sccl_ann_req():
            t = self.cmb_sccl_ann_type.currentText()
            rule = ANNOTATION_RULES.get(t, ANNOTATION_RULES["(None)"])
            ev = "Evidence required" if rule.get("evidence_required") else "Evidence optional"
            ap = "Approval required" if rule.get("approval_required") else "Approval optional"
            self.lbl_sccl_ann_req.setText(f"{ev} • {ap} • Default scope: {rule.get('default_scope','Item')}")
        self.cmb_sccl_ann_type.currentTextChanged.connect(lambda _=None: _refresh_sccl_ann_req())
        _refresh_sccl_ann_req()

        self.txt_sccl_var = QTextEdit()
        self.txt_sccl_var.setFixedHeight(110)

        self.chk_sccl_carry = QCheckBox("Carry-forward to next close (user controlled)")
        self.chk_sccl_carry.setChecked(True)

        self.chk_sccl_autofill = QCheckBox("Auto-fill from prior close if available")
        self.chk_sccl_autofill.setChecked(True)

        self.btn_sccl_roll = QPushButton("Rollover Prior Explanation → Current (Preview)")
        self.btn_sccl_roll.clicked.connect(self.rollover_sccl_expl)

        # Workflow buttons
        btn_sc1 = QHBoxLayout()
        self.btn_sccl_save = QPushButton("Save Draft")
        self.btn_sccl_save.clicked.connect(self.save_sccl_expl)
        self.btn_sccl_submit = QPushButton("Submit for Approval")
        self.btn_sccl_submit.clicked.connect(self.submit_sccl_expl)
        btn_sc1.addWidget(self.btn_sccl_save)
        btn_sc1.addWidget(self.btn_sccl_submit)

        btn_sc2 = QHBoxLayout()
        self.btn_sccl_approve = QPushButton("Approve (Checker)")
        self.btn_sccl_approve.clicked.connect(self.approve_sccl_expl)
        self.btn_sccl_reject = QPushButton("Reject (Checker)")
        self.btn_sccl_reject.clicked.connect(self.reject_sccl_expl)
        btn_sc2.addWidget(self.btn_sccl_approve)
        btn_sc2.addWidget(self.btn_sccl_reject)

        self.btn_sccl_bulk_roll = QPushButton("Bulk Carry-Forward Rollover (Approved → Drafts)")
        self.btn_sccl_bulk_roll.clicked.connect(self.bulk_rollover_sccl)

        exf.addRow("Workflow", self.lbl_sccl_status)
        exf.addRow("Reason", self.cmb_sccl_reason)
        exf.addRow("Narrative", self.txt_sccl_var)
        exf.addRow("", self.chk_sccl_carry)
        exf.addRow("", btn_sc1)
        exf.addRow("", btn_sc2)
        exf.addRow("", self.chk_sccl_autofill)
        exf.addRow("", self.btn_sccl_roll)
        exf.addRow("", self.btn_sccl_bulk_roll)

        # Place explanation panel in the right-side splitter (resizable)
        if hasattr(self, "sccl_right_split"):
            self.sccl_right_split.addWidget(box_ex)
            self.sccl_right_split.setStretchFactor(0, 3)
            self.sccl_right_split.setStretchFactor(1, 2)
        else:
            r2.addWidget(box_ex)

        split2.addWidget(left2)
        split2.addWidget(right2)
        split2.setSizes([960, 580])
        t2.addWidget(split2, 1)

        self.report_tabs.addTab(t_lines, "Report Lines")
        self.report_tabs.addTab(t_sccl, "SCCL (FR2590) Drilldown")

        # -------------------------
        # Tab 3: Report Catalog (enterprise-wide)
        # -------------------------
        t_cat = QWidget()
        t3 = QVBoxLayout(t_cat)
        t3.addWidget(QLabel("Reg Report Catalog — grain, hierarchy, controls"))

        catalog = pd.DataFrame([
            {"report":"FR2590 (SCCL)","primary_grain":"Instrument/Trade/Facility (atomic exposure)","hierarchy":"A-Node → Booking Entity → Connected Group → Ultimate Parent → Counterparty → Category → Instrument → Netting/Collateral","key_controls":"Maker/Checker explanations, connected-group governance, lineage to SORs"},
            {"report":"Y-9C","primary_grain":"GL Account/Balance (legal entity/book/ccy)","hierarchy":"Reporting Entity → Legal Entity → Account → Product","key_controls":"Mapping governance, certification, audit evidence"},
            {"report":"FR Y-15","primary_grain":"Aggregates derived from risk+GL (proxy)","hierarchy":"Reporting Entity → Measure families → Sub-measures","key_controls":"Methodology sign-off, data-quality thresholds"},
            {"report":"FR 2052a (LCR)","primary_grain":"Position/flow + HQLA buckets (proxy)","hierarchy":"Entity → HQLA level → Product/Flow","key_controls":"Time-bucket controls, intraday completeness"},
            {"report":"NSFR","primary_grain":"Balance-sheet + funding factors (proxy)","hierarchy":"Entity → ASF/RSF buckets → Product","key_controls":"Factor tables versioning, approvals"},
            {"report":"Call Report","primary_grain":"GL account to schedule line (proxy)","hierarchy":"Bank entity → Schedule → Line → Account mapping","key_controls":"Schedule mapping governance"},
            {"report":"CCAR","primary_grain":"Scenario projections + P&L components","hierarchy":"Scenario → Entity → Portfolio → Measure","key_controls":"Model run controls, approvals"},
            {"report":"CECL/ACL","primary_grain":"Portfolio/segment + allowance","hierarchy":"Entity → Portfolio → Segment → Measure","key_controls":"Model + overlay governance"},
            {"report":"STARE","primary_grain":"Forecast balances + assumptions","hierarchy":"Scenario → Entity → Driver → Measure","key_controls":"Assumption governance"},
            {"report":"ERA","primary_grain":"GL recon + SCCL accountability scope","hierarchy":"Entity → Source system → Account/Product","key_controls":"Accountability + SLA enforcement"},
        ])

        self.tbl_catalog, self.m_catalog = self._table()
        self.tbl_catalog.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.m_catalog.set_df(catalog)
        t3.addWidget(self.tbl_catalog, 1)

        self.report_tabs.addTab(t_cat, "Report Catalog")

        layout.addWidget(self.report_tabs, 1)
        return w


    def _page_lineage(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Lineage & Mapping (BCBS239)")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        hint = QLabel("Traceability and governance. Mapping changes require justification; all actions are audit logged.")
        hint.setStyleSheet("color:#444444;")
        layout.addWidget(hint)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Mapping Repository"))
        self.tbl_map, self.m_map = self._table('lineage_mapping')
        self.tbl_map.setSelectionMode(QTableView.SelectionMode.NoSelection)
        ll.addWidget(self.tbl_map, 1)

        right = QWidget(); rl = QVBoxLayout(right)
        hl = QHBoxLayout()
        hl.addWidget(QLabel("Account:"))
        self.cmb_acc = QComboBox()
        self.cmb_acc.currentTextChanged.connect(self.refresh_lineage_side)
        hl.addWidget(self.cmb_acc, 1)
        rl.addLayout(hl)

        self.lbl_lineage = QLabel("")
        self.lbl_lineage.setWordWrap(True)
        self.lbl_lineage.setStyleSheet("color:#444444;")
        rl.addWidget(self.lbl_lineage)

        rl.addWidget(QLabel("Related Report Lines"))
        self.tbl_rel, self.m_rel = self._table()
        self.tbl_rel.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(self.tbl_rel, 1)

        split.addWidget(left); split.addWidget(right)
        split.setSizes([920, 640])
        layout.addWidget(split, 1)
        return w

    def _page_audit(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Audit & Evidence Vault")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        tabs = QTabWidget()

        # Audit log
        t1 = QWidget(); l1 = QVBoxLayout(t1)
        self.tbl_audit, self.m_audit = self._table('audit_log')
        self.tbl_audit.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l1.addWidget(self.tbl_audit, 1)
        tabs.addTab(t1, "Audit Log")

        # Evidence registry (structured)
        t2 = QWidget(); l2 = QVBoxLayout(t2)
        bar = QHBoxLayout()
        self.btn_evd_break = QPushButton("Create Evidence for Selected Break")
        self.btn_evd_break.clicked.connect(self.create_evidence_for_selected_break)
        bar.addWidget(self.btn_evd_break)
        self.btn_evd_cycle = QPushButton("Attach Evidence to Current Cycle")
        self.btn_evd_cycle.clicked.connect(self.attach_evidence_to_cycle_demo)
        bar.addWidget(self.btn_evd_cycle)
        bar.addStretch(1)
        l2.addLayout(bar)

        self.tbl_evd_reg, self.m_evd_reg = self._table('evidence_registry')
        self.tbl_evd_reg.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l2.addWidget(self.tbl_evd_reg, 1)
        tabs.addTab(t2, "Evidence Registry")

        # Evidence index from breaks (quick view)
        t3 = QWidget(); l3 = QVBoxLayout(t3)
        l3.addWidget(QLabel("Evidence Index (from Breaks)"))
        self.tbl_evid, self.m_evid = self._table('evidence_from_breaks')
        self.tbl_evid.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l3.addWidget(self.tbl_evid, 1)
        tabs.addTab(t3, "Break Evidence")

        layout.addWidget(tabs, 1)
        return w

    def _page_admin(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Admin & Governance")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        split = QSplitter(Qt.Orientation.Horizontal)

        rbac = pd.DataFrame([
            {"role":"Maker","can_create_break":"Y","can_close_break":"N","can_submit_expl":"Y","can_approve_expl":"N","can_certify":"N","data_export":"Limited"},
            {"role":"Checker","can_create_break":"N","can_close_break":"Y","can_submit_expl":"N","can_approve_expl":"Y","can_certify":"N","data_export":"Controlled"},
            {"role":"Executive","can_create_break":"N","can_close_break":"N","can_submit_expl":"N","can_approve_expl":"N","can_certify":"Y","data_export":"Controlled"},
            {"role":"Auditor","can_create_break":"N","can_close_break":"N","can_submit_expl":"N","can_approve_expl":"N","can_certify":"N","data_export":"Read-only"},
            {"role":"Admin","can_create_break":"Y","can_close_break":"Y","can_submit_expl":"Y","can_approve_expl":"Y","can_certify":"Y","data_export":"Admin"},
        ])
        cal = pd.DataFrame([
            {"cycle":"Month-End Close","cutoff":"T+1 18:00","recon_due":"T+2 12:00","certify_due":"T+3 17:00"},
            {"cycle":"FR2590","cutoff":"T+1 20:00","recon_due":"T+2 14:00","certify_due":"T+3 12:00"},
            {"cycle":"Y-9C","cutoff":"T+2 18:00","recon_due":"T+4 12:00","certify_due":"T+5 17:00"},
            {"cycle":"CCAR/STARE","cutoff":"Scenario freeze","recon_due":"Model run+1d","certify_due":"Review+2d"},
            {"cycle":"CECL/ACL","cutoff":"Quarter-end","recon_due":"T+3 12:00","certify_due":"T+5 17:00"},
        ])

        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("RBAC Matrix"))
        tbl1, _ = self._table()
        tbl1.setModel(DataFrameModel(rbac))
        tbl1.setSelectionMode(QTableView.SelectionMode.NoSelection)
        ll.addWidget(tbl1, 1)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Close Calendar"))
        tbl2, _ = self._table()
        tbl2.setModel(DataFrameModel(cal))
        tbl2.setSelectionMode(QTableView.SelectionMode.NoSelection)
        rl.addWidget(tbl2, 1)

        split.addWidget(left); split.addWidget(right)
        split.setSizes([760, 760])
        layout.addWidget(split, 1)
        return w

    def _page_close(self) -> QWidget:
        """Enterprise close-cycle governance with hard gates + certification."""
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Close & Certification")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        hint = QLabel("Cycle-based governance: feeds → DQ → recon → breaks → explanations → evidence → certification.")
        hint.setStyleSheet("color:#5A6772;")
        layout.addWidget(hint)

        top = QHBoxLayout()
        self.lbl_close_status = QLabel("")
        self.lbl_close_status.setStyleSheet("font-weight:600;")
        top.addWidget(self.lbl_close_status)
        top.addStretch(1)
        self.btn_cycle_refresh = QPushButton("Refresh Gates")
        self.btn_cycle_refresh.clicked.connect(self.refresh_close)
        top.addWidget(self.btn_cycle_refresh)
        self.btn_cycle_cert = QPushButton("Certify Cycle")
        self.btn_cycle_cert.clicked.connect(self.certify_current_cycle)
        top.addWidget(self.btn_cycle_cert)
        layout.addLayout(top)

        self.tbl_gates, self.m_gates = self._table("close_gates")
        self.tbl_gates.setSelectionMode(QTableView.SelectionMode.NoSelection)
        layout.addWidget(self.tbl_gates, 1)

        # Certification evidence checklist
        layout.addWidget(QLabel("Evidence Registry (cycle-linked)"))
        self.tbl_evd_cycle, self.m_evd_cycle = self._table("evd_cycle")
        self.tbl_evd_cycle.setSelectionMode(QTableView.SelectionMode.NoSelection)
        layout.addWidget(self.tbl_evd_cycle, 1)
        return w

    def _page_catalog(self) -> QWidget:
        """Report catalog + policy registry + mapping governance (report-agnostic)."""
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Report Catalog & Policies")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        tabs = QTabWidget()

        # Report catalog
        t1 = QWidget(); l1 = QVBoxLayout(t1)
        btns = QHBoxLayout()
        b_onboard = QPushButton("Onboard Report (Demo)")
        b_onboard.clicked.connect(self.onboard_report_demo)
        btns.addWidget(b_onboard)
        btns.addStretch(1)
        l1.addLayout(btns)
        self.tbl_report_cat, self.m_report_cat = self._table("report_catalog")
        self.tbl_report_cat.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l1.addWidget(self.tbl_report_cat, 1)
        tabs.addTab(t1, "Report Catalog")

        # Recon policy registry
        t2 = QWidget(); l2 = QVBoxLayout(t2)
        self.tbl_policies, self.m_policies = self._table("recon_policies")
        self.tbl_policies.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l2.addWidget(self.tbl_policies, 1)
        tabs.addTab(t2, "Recon Policies")

        # Mapping governance
        t3 = QWidget(); l3 = QVBoxLayout(t3)
        mb = QHBoxLayout()
        self.btn_map_propose = QPushButton("Propose Mapping Change")
        self.btn_map_propose.clicked.connect(self.propose_mapping_change_demo)
        mb.addWidget(self.btn_map_propose)
        self.btn_map_approve = QPushButton("Approve Latest (Checker)")
        self.btn_map_approve.clicked.connect(self.approve_mapping_change_demo)
        mb.addWidget(self.btn_map_approve)
        mb.addStretch(1)
        l3.addLayout(mb)
        self.tbl_map_sets, self.m_map_sets = self._table("mapping_sets")
        self.tbl_map_sets.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l3.addWidget(self.tbl_map_sets, 1)
        tabs.addTab(t3, "Mapping Governance")

        # Entitlements
        t4 = QWidget(); l4 = QVBoxLayout(t4)
        self.tbl_ent, self.m_ent = self._table("entitlements")
        self.tbl_ent.setSelectionMode(QTableView.SelectionMode.NoSelection)
        l4.addWidget(self.tbl_ent, 1)
        tabs.addTab(t4, "Entitlements")

        layout.addWidget(tabs, 1)
        return w

    
    def _page_queue(self) -> QWidget:
        """Workstream Hub (report-family first) + enterprise queues and routing."""
        w = QWidget()
        layout = QVBoxLayout(w)

        hdr = QLabel("Workstreams, Queues & Routing")
        hdr.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(hdr)

        hint = QLabel("Select a report family → workstream. The queue is automatically filtered and routed by ownership rules.")
        hint.setStyleSheet("color:#5A6772;")
        layout.addWidget(hint)

        # Top hub: Report Family + Workstream selection + cockpit
        top = QSplitter(Qt.Orientation.Horizontal)

        # Left: Report families
        left = QFrame()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        fam_box = QGroupBox("Report Families")
        fam_l = QVBoxLayout(fam_box)
        self.lst_families = QListWidget()
        self.lst_families.setMinimumWidth(260)
        self.lst_families.setSpacing(2)
        self.lst_families.setStyleSheet("""
            QListWidget { background: white; }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background: #E6F0FF; color: #111; }
        """)
        for f in self.list_report_families():
            # Display counts for each family (except All) and keep the true key in UserRole
            if f == "All":
                it = QListWidgetItem("All (Firmwide)")
                it.setData(Qt.ItemDataRole.UserRole, "All")
            else:
                try:
                    cnt = int((self.workstreams["report_family"].astype(str) == f).sum()) if self.workstreams is not None else 0
                except Exception:
                    cnt = 0
                it = QListWidgetItem(f"{f}  ({cnt})")
                it.setData(Qt.ItemDataRole.UserRole, f)
            self.lst_families.addItem(it)
        self.lst_families.setCurrentRow(0)
        self.lst_families.currentRowChanged.connect(self.on_report_family_changed)
        fam_l.addWidget(self.lst_families, 1)
        ll.addWidget(fam_box, 1)

        ws_box = QGroupBox("Workstreams")
        ws_l = QVBoxLayout(ws_box)
        self.lst_workstreams = QListWidget()
        self.lst_workstreams.setMinimumWidth(420)
        self.lst_workstreams.setSpacing(2)
        self.lst_workstreams.setStyleSheet("""
            QListWidget { background: white; }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background: #E6F0FF; color: #111; }
        """)
        self.lst_workstreams.currentRowChanged.connect(self.on_workstream_changed)
        ws_l.addWidget(self.lst_workstreams, 1)
        ll.addWidget(ws_box, 2)

        top.addWidget(left)

        # Right: cockpit + queue table
        right = QFrame()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        cockpit = QGroupBox("Workstream Cockpit")
        cl = QGridLayout(cockpit)
        cl.setHorizontalSpacing(14)
        cl.setVerticalSpacing(8)

        self.lbl_ws_name = QLabel("All workstreams")
        self.lbl_ws_name.setStyleSheet("font-weight:600;")
        self.lbl_ws_health = QLabel("—")
        self.lbl_ws_health.setStyleSheet("color:#5A6772;")

        cl.addWidget(QLabel("Selected:"), 0, 0)
        cl.addWidget(self.lbl_ws_name, 0, 1)
        cl.addWidget(QLabel("Health:"), 0, 2)
        cl.addWidget(self.lbl_ws_health, 0, 3)

        self.lbl_ws_kpi1 = QLabel("Open Breaks: —")
        self.lbl_ws_kpi2 = QLabel("Material Breaks: —")
        self.lbl_ws_kpi3 = QLabel("Late/Failed Feeds: —")
        self.lbl_ws_kpi4 = QLabel("Pending Approvals: —")
        for i, lbl in enumerate([self.lbl_ws_kpi1, self.lbl_ws_kpi2, self.lbl_ws_kpi3, self.lbl_ws_kpi4]):
            lbl.setStyleSheet("color:#2A2F35;")
            cl.addWidget(lbl, 1, i)

        rl.addWidget(cockpit)

        # Queue controls
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Domain:"))
        self.cmb_queue = QComboBox()
        self.cmb_queue.addItems(["All", "Recon", "Feeds", "Approvals", "Evidence"])
        self.cmb_queue.currentIndexChanged.connect(self.refresh_queue)
        bar.addWidget(self.cmb_queue)

        bar.addSpacing(12)
        bar.addWidget(QLabel("Scope:"))
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItems(["All", "My Work", "Team Queue"])
        self.cmb_scope.currentIndexChanged.connect(self.refresh_queue)
        bar.addWidget(self.cmb_scope)

        bar.addStretch(1)
        self.btn_queue_assign = QPushButton("Assign to Me")
        self.btn_queue_assign.clicked.connect(self.assign_selected_queue_item)
        bar.addWidget(self.btn_queue_assign)
        rl.addLayout(bar)

        self.tbl_queue, self.m_queue = self._table("work_queue")
        rl.addWidget(self.tbl_queue, 1)

        top.addWidget(right)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        layout.addWidget(top, 1)

        # Initialize lists
        self._refresh_workstream_lists()
        return w

    # ---------- Navigation / mode / preset / filters
    def on_nav(self, idx: int):
        self.stack.setCurrentIndex(max(0, min(idx, self.stack.count() - 1)))
        item = self.nav_list.currentItem().text() if self.nav_list.currentItem() else ""
        if hasattr(self, "dim_tree"):
            self.dim_tree.rebuild(self.filters, self.sccl_filters)

        # Apply saved table column views after widgets exist
        self._apply_table_views_to_all()
        self.update_context_header()

        self.status.showMessage(f"Viewing: {item}", 2500)


    def on_dim_tree_changed(self, dim: str, value: str):
        """Callback from EnterpriseDimTree. Applies selection to the right filter set and refreshes."""
        try:
            if dim == "booking_entity":
                self.filters.legal_entity = value
                if hasattr(self, "cmb_le"):
                    self.cmb_le.blockSignals(True)
                    self.cmb_le.setCurrentText(value)
                    self.cmb_le.blockSignals(False)

                # also sync SCCL booking entity when present
                if hasattr(self, "cmb_sccl_be"):
                    self.sccl_filters["booking_entity"] = value
                    self.cmb_sccl_be.blockSignals(True)
                    self.cmb_sccl_be.setCurrentText(value)
                    self.cmb_sccl_be.blockSignals(False)

            elif dim == "book":
                self.filters.book = value
                if hasattr(self, "cmb_book"):
                    self.cmb_book.blockSignals(True)
                    self.cmb_book.setCurrentText(value)
                    self.cmb_book.blockSignals(False)

            elif dim == "ccy":
                self.filters.ccy = value
                if hasattr(self, "cmb_ccy"):
                    self.cmb_ccy.blockSignals(True)
                    self.cmb_ccy.setCurrentText(value)
                    self.cmb_ccy.blockSignals(False)

            elif dim in {
                "a_node_id", "connected_group_id", "ultimate_parent_id", "counterparty_id", "exposure_category",
                "instrument_id", "netting_set_id", "collateral_id"
            }:
                self.sccl_filters[dim] = value

                # push into SCCL filter dropdowns if present
                if dim == "a_node_id" and hasattr(self, "cmb_sccl_anode"):
                    self.cmb_sccl_anode.blockSignals(True)
                    self.cmb_sccl_anode.setCurrentText(value)
                    self.cmb_sccl_anode.blockSignals(False)
                if dim == "connected_group_id" and hasattr(self, "cmb_sccl_cg"):
                    self.cmb_sccl_cg.blockSignals(True)
                    self.cmb_sccl_cg.setCurrentText(value)
                    self.cmb_sccl_cg.blockSignals(False)
                if dim == "ultimate_parent_id" and hasattr(self, "cmb_sccl_up"):
                    self.cmb_sccl_up.blockSignals(True)
                    self.cmb_sccl_up.setCurrentText(value)
                    self.cmb_sccl_up.blockSignals(False)
                if dim == "counterparty_id" and hasattr(self, "cmb_sccl_cp"):
                    self.cmb_sccl_cp.blockSignals(True)
                    self.cmb_sccl_cp.setCurrentText(value)
                    self.cmb_sccl_cp.blockSignals(False)
                if dim == "exposure_category" and hasattr(self, "cmb_sccl_cat"):
                    self.cmb_sccl_cat.blockSignals(True)
                    self.cmb_sccl_cat.setCurrentText(value)
                    self.cmb_sccl_cat.blockSignals(False)

            self.refresh_all()
        except Exception as e:
            if hasattr(self, "status"):
                self.status.showMessage(f"Dim tree update failed: {e}", 8000)


    def on_mode_changed(self):
        txt = self.cmb_mode.currentText()
        self.mode = "Auditor" if "Auditor" in txt else ("Executive" if "Executive" in txt else ("Checker" if "Checker" in txt else "Maker"))
        self.current_user = self.mode
        self.apply_mode_rules()
        self.refresh_all()

    def apply_preset(self):
        name = self.cmb_preset.currentText()
        row = self.data["presets"][self.data["presets"]["preset"] == name]
        if row.empty:
            return
        r = row.iloc[0].to_dict()

        self.cmb_le.blockSignals(True)
        self.cmb_book.blockSignals(True)
        self.cmb_ccy.blockSignals(True)
        self.spn_mat.blockSignals(True)

        self.cmb_le.setCurrentText(r["legal_entity"])
        self.cmb_book.setCurrentText(r["book"])
        self.cmb_ccy.setCurrentText(r["ccy"])
        self.spn_mat.setValue(int(r["materiality"]))

        self.cmb_le.blockSignals(False)
        self.cmb_book.blockSignals(False)
        self.cmb_ccy.blockSignals(False)
        self.spn_mat.blockSignals(False)

        self.update_filters()

    def update_filters(self):
        self.filters.as_of = self.cmb_asof.currentData()
        self.filters.legal_entity = self.cmb_le.currentText()
        self.filters.book = self.cmb_book.currentText()
        self.filters.ccy = self.cmb_ccy.currentText()
        self.filters.materiality = float(self.spn_mat.value())
        self.refresh_all()

    def apply_mode_rules(self):
        """
        Enterprise RBAC controls:
          - Maker: create/edit explanations, submit, rollover, create breaks
          - Checker: approve/reject submitted items (no narrative edits)
          - Executive: certify/lock, read-only for narratives
          - Auditor: fully read-only
        """
        is_auditor = (self.mode == "Auditor")
        is_exec = (self.mode == "Executive")
        is_checker = (self.mode == "Checker")
        is_maker = (self.mode == "Maker")

        # Button enablement
        def _set_enabled(name: str, enabled: bool):
            if hasattr(self, name):
                getattr(self, name).setEnabled(bool(enabled))

        # Break lifecycle / recon actions: Maker+Checker+Exec (Auditor no)
        for b in ["btn_create_largest","btn_create_breaks","btn_open_break","btn_rerun","btn_inc"]:
            _set_enabled(b, not is_auditor)

        # Narrative editing: Maker only
        if hasattr(self, "txt_var"): self.txt_var.setReadOnly(not is_maker)
        if hasattr(self, "txt_sccl_var"): self.txt_sccl_var.setReadOnly(not is_maker)

        # Variance workflow buttons
        _set_enabled("btn_save_var", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_var_submit", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_var_roll", (is_maker or is_checker) and not is_auditor and not is_exec)  # preview ok
        _set_enabled("btn_var_bulk_roll", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_var_approve", is_checker and not is_auditor)
        _set_enabled("btn_var_reject", is_checker and not is_auditor)

        # SCCL workflow buttons
        _set_enabled("btn_sccl_save", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_sccl_submit", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_sccl_roll", (is_maker or is_checker) and not is_auditor and not is_exec)
        _set_enabled("btn_sccl_bulk_roll", is_maker and not is_auditor and not is_exec)
        _set_enabled("btn_sccl_approve", is_checker and not is_auditor)
        _set_enabled("btn_sccl_reject", is_checker and not is_auditor)

        # Executive controls
        _set_enabled("btn_cert", is_exec and not is_auditor)
        _set_enabled("btn_lock", is_exec and not is_auditor)

        # Data entitlements: trade-level drilldowns (typical bank restriction)
        trade_ok = True
        try:
            if not self.entitlements.empty and "role" in self.entitlements.columns:
                r = self.entitlements[self.entitlements["role"] == self.mode]
                if not r.empty and "can_view_trade_level" in r.columns:
                    trade_ok = bool(r.iloc[0]["can_view_trade_level"])
        except Exception:
            trade_ok = True
        if hasattr(self, "tbl_sccl_trades"):
            self.tbl_sccl_trades.setVisible(trade_ok)
        if hasattr(self, "tbl_sccl_mitig"):
            self.tbl_sccl_mitig.setVisible(trade_ok)
        if hasattr(self, "lbl_sccl_trade_restricted"):
            self.lbl_sccl_trade_restricted.setVisible(not trade_ok)

        # Hide noisy operational widgets in Executive view (keep drilldowns available)
        if hasattr(self, "tbl_top"): self.tbl_top.setVisible(not is_exec)
        if hasattr(self, "tbl_feed_snap"): self.tbl_feed_snap.setVisible(not is_exec)
        if hasattr(self, "tbl_ready"): self.tbl_ready.setVisible(not is_exec)
        if hasattr(self, "btn_create_largest"): self.btn_create_largest.setVisible(not is_exec)
        if hasattr(self, "lbl_dash_left"): self.lbl_dash_left.setText("Executive Snapshot" if is_exec else "Top Breaks (GL↔SOR)")


    def gl_filtered(self, d: Optional[date] = None) -> pd.DataFrame:
        dd = d if d is not None else self.filters.as_of
        gl = self.data["gl"]
        return gl[
            (gl["as_of"] == dd) &
            (gl["legal_entity"] == self.filters.legal_entity) &
            (gl["book"] == self.filters.book) &
            (gl["ccy"] == self.filters.ccy)
        ].copy()

    def sor_filtered(self, d: Optional[date] = None) -> pd.DataFrame:
        dd = d if d is not None else self.filters.as_of
        sor = self.data["sor"]
        return sor[
            (sor["as_of"] == dd) &
            (sor["legal_entity"] == self.filters.legal_entity) &
            (sor["book"] == self.filters.book) &
            (sor["ccy"] == self.filters.ccy)
        ].copy()

    # ---------- Core computations
    def recon_gl_sor(self) -> pd.DataFrame:
        gl = self.gl_filtered()
        sor = self.sor_filtered()
        key = ["as_of","legal_entity","book","ccy","account","account_name","product"]
        if gl.empty:
            return pd.DataFrame(columns=key + ["gl_amount","sor_amount","variance","abs_var","status","severity"])
        g = gl[key + ["gl_amount"]].copy()
        o = sor[key + ["sor_amount"]].copy() if not sor.empty else pd.DataFrame(columns=key + ["sor_amount"])
        m = g.merge(o, on=key, how="left")
        m["sor_amount"] = m["sor_amount"].fillna(0.0)
        m["variance"] = m["gl_amount"] - m["sor_amount"]
        m["abs_var"] = m["variance"].abs()
        tol = float(self.spn_tol.value())
        m["status"] = np.where(m["abs_var"] <= tol, "MATCH", "BREAK")
        m["severity"] = m["variance"].apply(lambda x: severity_from_amt(x, self.filters.materiality))
        return m

    def recon_crrt_cr360(self) -> pd.DataFrame:
        d = self.filters.as_of
        crrt = self.data["crrt"]
        cr360 = self.data["cr360"]
        c1 = crrt[
            (crrt["as_of"] == d) &
            (crrt["legal_entity"] == self.filters.legal_entity) &
            (crrt["book"] == self.filters.book) &
            (crrt["ccy"] == self.filters.ccy)
        ].copy()
        c2 = cr360[
            (cr360["as_of"] == d) &
            (cr360["legal_entity"] == self.filters.legal_entity) &
            (cr360["book"] == self.filters.book) &
            (cr360["ccy"] == self.filters.ccy)
        ].copy()
        key = ["as_of","legal_entity","book","ccy","account"]
        if c1.empty:
            return pd.DataFrame(columns=key + ["crrt_amount","cr360_amount","variance","abs_var","status"])
        m = c1.merge(c2[key + ["cr360_amount"]], on=key, how="left")
        m["cr360_amount"] = m["cr360_amount"].fillna(0.0)
        m["variance"] = m["crrt_amount"] - m["cr360_amount"]
        m["abs_var"] = m["variance"].abs()
        tol2 = float(self.spn_tol2.value())
        m["status"] = np.where(m["abs_var"] <= tol2, "MATCH", "BREAK")
        return m

    def variance_pop(self) -> pd.DataFrame:
        cur = self.gl_filtered(self.filters.as_of)
        prior = self.gl_filtered(self.data["prior"])
        if cur.empty:
            return pd.DataFrame(columns=["account","account_name","product","cur","prior","variance","abs_var","severity"])
        c = cur.groupby(["account","account_name","product"], as_index=False).agg(cur=("gl_amount","sum"))
        p = prior.groupby(["account","account_name","product"], as_index=False).agg(prior=("gl_amount","sum")) if not prior.empty else pd.DataFrame(columns=["account","account_name","product","prior"])
        v = c.merge(p, on=["account","account_name","product"], how="left").fillna(0.0)
        v["variance"] = v["cur"] - v["prior"]
        v["abs_var"] = v["variance"].abs()
        v["severity"] = v["variance"].apply(lambda x: severity_from_amt(x, self.filters.materiality))
        if self.chk_changes.isChecked():
            v = v[v["abs_var"] > 0].copy()
        return v.sort_values("abs_var", ascending=False)

    def report_lines(self, report: str) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        m = self.data["map"].copy()
        if report == "FR Y (Other)":
            m = m[m["report"] == "Y-9C"].copy()
            m["report"] = report
        else:
            m = m[m["report"] == report].copy()

        gl = self.gl_filtered()
        cols = ["report_line","line_desc","amount","recon_abs_var","recon_status","mapped_accounts"]
        if m.empty or gl.empty:
            return pd.DataFrame(columns=cols), {}

        joined = m.merge(gl, on="account", how="left")
        joined["gl_amount"] = joined["gl_amount"].fillna(0.0)
        lines = joined.groupby(["report_line","line_desc"], as_index=False).agg(
            amount=("gl_amount","sum"),
            mapped_accounts=("account","nunique")
        )
        accs_by_line = m.groupby("report_line")["account"].apply(lambda x: sorted(set(x))).to_dict()

        recon = self.recon_gl_sor()
        by_acc = recon.groupby("account", as_index=False).agg(abs_var=("abs_var","sum")) if not recon.empty else pd.DataFrame(columns=["account","abs_var"])

        def risk(accs: List[str]) -> float:
            if not accs or by_acc.empty:
                return 0.0
            return float(by_acc[by_acc["account"].isin(accs)]["abs_var"].sum())

        lines["recon_abs_var"] = lines["report_line"].apply(lambda ln: risk(accs_by_line.get(ln, [])))
        lines["recon_status"] = np.where(lines["recon_abs_var"] <= self.filters.materiality * 0.001, "OK", "AT_RISK")
        return lines.sort_values("recon_abs_var", ascending=False), accs_by_line


    # ---------- SCCL (FR2590) Exposure Drilldown (A-Node → Booking Entity → CP → Group → Category → Instrument → Netting/Collateral → Measures)

    def sccl_atomic_filtered(self, d: Optional[date] = None) -> pd.DataFrame:
        """Return SCCL atomic rows filtered by the enterprise hierarchy.

        Hierarchy alignment:
          A-Node (Reporting Perimeter) → Booking Entity → Counterparty
          (→ Ultimate Parent → Connected Group) → Exposure Category → Instrument/Trade
          → Netting/Collateral → Measures
        """
        dd = d if d is not None else self.filters.as_of
        df = self.data.get("sccl_atomic", pd.DataFrame()).copy()
        if df.empty:
            return df

        # As-of is always applied first
        if "as_of" in df.columns:
            df = df[df["as_of"] == dd].copy()

        # Apply hierarchical filters (when present)
        filter_cols = [
            ("a_node_id", "a_node_id"),
            ("booking_entity", "booking_entity"),
            ("counterparty_id", "counterparty_id"),
            ("ultimate_parent_id", "ultimate_parent_id"),
            ("connected_group_id", "connected_group_id"),
            ("exposure_category", "exposure_category"),
            ("instrument_id", "instrument_id"),
            ("netting_set_id", "netting_set_id"),
            ("collateral_id", "collateral_id"),
        ]

        for fkey, col in filter_cols:
            val = self.sccl_filters.get(fkey, "(All)")
            if not val or val == "(All)":
                continue
            if col in df.columns:
                df = df[df[col].astype(str) == str(val)].copy()

        return df

    def sccl_agg(self) -> pd.DataFrame:

        cur = self.sccl_atomic_filtered(self.filters.as_of)
        prior = self.sccl_atomic_filtered(self.data["prior"])

        if cur.empty and prior.empty:
            return pd.DataFrame(columns=[
                "connected_group_id","ultimate_parent_id","counterparty_id","exposure_category","booking_entity",
                "cur_ead","prior_ead","variance","abs_var","severity","status"
            ])

        group_cols = ["connected_group_id","ultimate_parent_id","counterparty_id","exposure_category","booking_entity"]
        c = cur.groupby(group_cols, as_index=False).agg(cur_ead=("ead","sum"), cur_gross=("gross_exposure","sum"), cur_net=("net_exposure","sum")) if not cur.empty else pd.DataFrame(columns=group_cols+["cur_ead","cur_gross","cur_net"])
        p = prior.groupby(group_cols, as_index=False).agg(prior_ead=("ead","sum")) if not prior.empty else pd.DataFrame(columns=group_cols+["prior_ead"])

        v = c.merge(p, on=group_cols, how="outer").fillna(0.0)
        v["variance"] = v["cur_ead"] - v["prior_ead"]
        v["abs_var"] = v["variance"].abs()
        v["severity"] = v["variance"].apply(lambda x: severity_from_amt(x, self.filters.materiality))
        v["status"] = np.where(v["abs_var"] >= self.filters.materiality, "AT_RISK", "OK")

        # Friendly names
        cp = self.data.get("counterparty", pd.DataFrame())
        if not cp.empty:
            v = v.merge(cp[["counterparty_id","counterparty_name","ultimate_parent_id","ultimate_parent_name","connected_group_id","connected_group_name"]].drop_duplicates(),
                        on=["counterparty_id","connected_group_id","ultimate_parent_id"], how="left")
        v["counterparty_name"] = v.get("counterparty_name", pd.Series([""]*len(v)))
        v["ultimate_parent_name"] = v.get("ultimate_parent_name", pd.Series([""]*len(v)))
        v["connected_group_name"] = v.get("connected_group_name", pd.Series([""]*len(v)))

        # Order
        cols = ["connected_group_id","connected_group_name","ultimate_parent_id","ultimate_parent_name","counterparty_id","counterparty_name","booking_entity","exposure_category",
                "cur_ead","prior_ead","variance","abs_var","status","severity"]
        for ccol in cols:
            if ccol not in v.columns:
                v[ccol] = ""
        return v[cols].sort_values("abs_var", ascending=False)

    def _sccl_key_from_row(self, r: Dict[str, Any]) -> str:
        return "|".join([
            "SCCL",
            str(self.filters.as_of),
            str(self.sccl_filters.get("a_node_id","A_US_CONSOL")),
            str(r.get("booking_entity","")),
            str(r.get("connected_group_id","")),
            str(r.get("ultimate_parent_id","")),
            str(r.get("counterparty_id","")),
            str(r.get("exposure_category","")),
        ])

    def refresh_sccl(self):
        # Populate dropdowns safely (if tab exists)
        if not hasattr(self, "cmb_sccl_anode"):
            return

        org = self.data.get("org_hier", pd.DataFrame())
        cps = self.data.get("counterparty", pd.DataFrame())
        atomic = self.data.get("sccl_atomic", pd.DataFrame())

        # A-node
        a_nodes = org[org["node_type"] == "A_NODE"]["node_id"].tolist() if not org.empty else ["A_US_CONSOL"]
        self.cmb_sccl_anode.blockSignals(True)
        self.cmb_sccl_anode.clear()
        self.cmb_sccl_anode.addItem("(All)")
        for a in a_nodes:
            self.cmb_sccl_anode.addItem(a)
        cur_a = self.sccl_filters.get("a_node_id","A_US_CONSOL")
        self.cmb_sccl_anode.setCurrentText(cur_a if cur_a in [self.cmb_sccl_anode.itemText(i) for i in range(self.cmb_sccl_anode.count())] else "A_US_CONSOL")
        self.cmb_sccl_anode.blockSignals(False)

        # Booking entity
        bes = sorted(atomic["booking_entity"].unique().tolist()) if not atomic.empty else ["US_HOLDCO","US_BANK","UK_BRANCH"]
        self.cmb_sccl_be.blockSignals(True)
        self.cmb_sccl_be.clear()
        self.cmb_sccl_be.addItem("(All)")
        for b in bes:
            self.cmb_sccl_be.addItem(b)
        cur_be = self.sccl_filters.get("booking_entity","(All)")
        self.cmb_sccl_be.setCurrentText(cur_be if cur_be in [self.cmb_sccl_be.itemText(i) for i in range(self.cmb_sccl_be.count())] else "(All)")
        self.cmb_sccl_be.blockSignals(False)

        
        # Connected group + ultimate parent + counterparty
        self.cmb_sccl_cg.blockSignals(True)
        self.cmb_sccl_cg.clear()
        self.cmb_sccl_cg.addItem("(All)")
        if not cps.empty:
            for cg in sorted(cps["connected_group_id"].unique().tolist()):
                self.cmb_sccl_cg.addItem(cg)
        self.cmb_sccl_cg.setCurrentText(self.sccl_filters.get("connected_group_id","(All)"))
        self.cmb_sccl_cg.blockSignals(False)

        self.cmb_sccl_up.blockSignals(True)
        self.cmb_sccl_up.clear()
        self.cmb_sccl_up.addItem("(All)")
        if not cps.empty:
            cg = self.sccl_filters.get("connected_group_id","(All)")
            sub_up = cps if cg == "(All)" else cps[cps["connected_group_id"] == cg]
            for up in sorted(sub_up["ultimate_parent_id"].unique().tolist()):
                self.cmb_sccl_up.addItem(up)
        self.cmb_sccl_up.setCurrentText(self.sccl_filters.get("ultimate_parent_id","(All)"))
        self.cmb_sccl_up.blockSignals(False)

        self.cmb_sccl_cp.blockSignals(True)
        self.cmb_sccl_cp.clear()
        self.cmb_sccl_cp.addItem("(All)")
        if not cps.empty:
            cg = self.sccl_filters.get("connected_group_id","(All)")
            up = self.sccl_filters.get("ultimate_parent_id","(All)")
            sub = cps
            if cg != "(All)":
                sub = sub[sub["connected_group_id"] == cg]
            if up != "(All)":
                sub = sub[sub["ultimate_parent_id"] == up]
            for cp in sorted(sub["counterparty_id"].unique().tolist()):
                self.cmb_sccl_cp.addItem(cp)
        self.cmb_sccl_cp.setCurrentText(self.sccl_filters.get("counterparty_id","(All)"))
        self.cmb_sccl_cp.blockSignals(False)

        # Exposure category
        cats = sorted(atomic["exposure_category"].unique().tolist()) if not atomic.empty else ["Loans/Commitments","Securities","Derivatives","SFT"]
        self.cmb_sccl_cat.blockSignals(True)
        self.cmb_sccl_cat.clear()
        self.cmb_sccl_cat.addItem("(All)")
        for c in cats:
            self.cmb_sccl_cat.addItem(c)
        self.cmb_sccl_cat.setCurrentText(self.sccl_filters.get("exposure_category","(All)"))
        self.cmb_sccl_cat.blockSignals(False)

        # Table
        agg = self.sccl_agg()
        self.m_sccl.set_df(agg)

        # Clear side panels
        self.lbl_sccl_explain.setText("Select a row to see instrument-level drilldown, netting/collateral drivers, and capture an explanation.")
        self.m_sccl_trades.set_df(pd.DataFrame(columns=["instrument_id","instrument_type","netting_set_id","collateral_id","gross_exposure","net_exposure","ead"]))
        self.m_sccl_mitig.set_df(pd.DataFrame(columns=["netting_set_id","agreement_type","margining","threshold","collateral_id","collateral_type","ccy","haircut"]))
        self._selected_sccl_key = None
        self.txt_sccl_var.setPlainText("")
        if hasattr(self,"cmb_sccl_ann_type"): self.cmb_sccl_ann_type.setCurrentText("(None)")
        if hasattr(self,"cmb_sccl_ann_scope"): self.cmb_sccl_ann_scope.setCurrentText("Line")
        if hasattr(self,"ed_sccl_evidence"): self.ed_sccl_evidence.setText("")
        if hasattr(self, "lbl_sccl_status"): self.lbl_sccl_status.setText("Status: —")
        if hasattr(self, "chk_sccl_carry"): self.chk_sccl_carry.setChecked(True)

    def on_sccl_filter_changed(self):
        self.sccl_filters["a_node_id"] = self.cmb_sccl_anode.currentText()
        self.sccl_filters["booking_entity"] = self.cmb_sccl_be.currentText()
        self.sccl_filters["connected_group_id"] = self.cmb_sccl_cg.currentText()
        self.sccl_filters["ultimate_parent_id"] = self.cmb_sccl_up.currentText()
        self.sccl_filters["counterparty_id"] = self.cmb_sccl_cp.currentText()
        self.sccl_filters["exposure_category"] = self.cmb_sccl_cat.currentText()

        # Re-sync dependent lists when hierarchy changes
        if self.sender() == self.cmb_sccl_cg:
            self.sccl_filters["ultimate_parent_id"] = "(All)"
            self.sccl_filters["counterparty_id"] = "(All)"
        if self.sender() == self.cmb_sccl_up:
            self.sccl_filters["counterparty_id"] = "(All)"

        self.refresh_sccl()

    def on_sccl_selected(self, idx: QModelIndex):
        row = self.m_sccl.get_row(idx.row())
        if not row:
            return
        self._selected_sccl_key = self._sccl_key_from_row(row)

        # Drilldown to atomic instruments for the selected row
        cur = self.sccl_atomic_filtered(self.filters.as_of)
        if cur.empty:
            return

        filt = (
            (cur["booking_entity"] == row.get("booking_entity")) &
            (cur["connected_group_id"] == row.get("connected_group_id")) &
            (cur["ultimate_parent_id"] == row.get("ultimate_parent_id")) &
            (cur["counterparty_id"] == row.get("counterparty_id")) &
            (cur["exposure_category"] == row.get("exposure_category"))
        )
        trades = cur[filt].copy()
        trades = trades.sort_values("ead", ascending=False)[["instrument_id","instrument_type","netting_set_id","collateral_id","gross_exposure","net_exposure","ead"]]
        self.m_sccl_trades.set_df(trades)

        # Mitigants (netting + collateral)
        net = self.data.get("netting", pd.DataFrame())
        col = self.data.get("collateral", pd.DataFrame())
        ns_ids = sorted(set(trades["netting_set_id"].astype(str).tolist()))
        col_ids = sorted(set([c for c in trades["collateral_id"].astype(str).tolist() if c]))

        net_sub = net[net["netting_set_id"].isin(ns_ids)].copy() if not net.empty else pd.DataFrame()
        col_sub = col[col["collateral_id"].isin(col_ids)].copy() if (not col.empty and col_ids) else pd.DataFrame()

        blocks = []
        if not net_sub.empty:
            tmp = net_sub.copy()
            tmp["collateral_id"] = ""
            tmp["collateral_type"] = ""
            tmp["ccy"] = ""
            tmp["haircut"] = ""
            blocks.append(tmp)

        if not col_sub.empty:
            tmp = col_sub.copy()
            tmp["netting_set_id"] = ""
            tmp["agreement_type"] = ""
            tmp["margining"] = ""
            tmp["threshold"] = 0
            blocks.append(tmp)

        if blocks:
            mit = pd.concat(blocks, ignore_index=True)
        else:
            mit = pd.DataFrame(columns=["netting_set_id","agreement_type","margining","threshold","collateral_id","collateral_type","ccy","haircut"])

        mit = mit[["netting_set_id","agreement_type","margining","threshold","collateral_id","collateral_type","ccy","haircut"]].head(25)
        self.m_sccl_mitig.set_df(mit)

        self.lbl_sccl_selected.setText(
            f"{row.get('connected_group_id')} / {row.get('ultimate_parent_id')} / {row.get('counterparty_id')} • {row.get('exposure_category')} • {row.get('booking_entity')}\n"
            f"Cur EAD: {fmt_money(row.get('cur_ead',0.0))} | Prior: {fmt_money(row.get('prior_ead',0.0))} | Var: {fmt_money(row.get('variance',0.0))}"
        )

        # Load existing SCCL explanation (if any)
        ex = self.sccl_expl[self.sccl_expl["key"] == self._selected_sccl_key].copy()
        if not ex.empty:
            e = ex.iloc[0].to_dict()
            self.lbl_sccl_status.setText(f"Status: {e.get('status','DRAFT')}")
            if hasattr(self, "chk_sccl_carry"):
                self.chk_sccl_carry.setChecked(bool(e.get("carry_forward", True)))

            # Structured annotation
            if hasattr(self,"cmb_sccl_ann_type"):
                at = str(e.get("annotation_type","(None)"))
                self.cmb_sccl_ann_type.setCurrentText(at if at in [self.cmb_sccl_ann_type.itemText(i) for i in range(self.cmb_sccl_ann_type.count())] else "(None)")
            if hasattr(self,"cmb_sccl_ann_scope"):
                sc = str(e.get("annotation_scope","Line"))
                self.cmb_sccl_ann_scope.setCurrentText(sc if sc in [self.cmb_sccl_ann_scope.itemText(i) for i in range(self.cmb_sccl_ann_scope.count())] else "Line")
            if hasattr(self,"ed_sccl_evidence"):
                self.ed_sccl_evidence.setText(str(e.get("evidence_ref","")))
            reason = str(e.get("reason",""))
            if reason and reason in [self.cmb_sccl_reason.itemText(i) for i in range(self.cmb_sccl_reason.count())]:
                self.cmb_sccl_reason.setCurrentText(reason)
            self.txt_sccl_var.setPlainText(str(e.get("narrative","")))
        else:
            self.lbl_sccl_status.setText("Status: —")
            if hasattr(self, "chk_sccl_carry"):
                self.chk_sccl_carry.setChecked(True)

            self.txt_sccl_var.setPlainText("")
            if hasattr(self,"cmb_sccl_ann_type"): self.cmb_sccl_ann_type.setCurrentText("(None)")
            if hasattr(self,"cmb_sccl_ann_scope"): self.cmb_sccl_ann_scope.setCurrentText("Line")
            if hasattr(self,"ed_sccl_evidence"): self.ed_sccl_evidence.setText("")
            if self.chk_sccl_autofill.isChecked():
                # try prior close (preview)
                prior_key = self._selected_sccl_key.replace(str(self.filters.as_of), str(self.data["prior"]))
                prior = self.sccl_expl[self.sccl_expl["key"] == prior_key].copy()
                if not prior.empty:
                    e = prior.iloc[0].to_dict()
                    reason = str(e.get("reason",""))
                    if reason and reason in [self.cmb_sccl_reason.itemText(i) for i in range(self.cmb_sccl_reason.count())]:
                        self.cmb_sccl_reason.setCurrentText(reason)
                    self.txt_sccl_var.setPlainText(str(e.get("narrative","")))
                    if hasattr(self, "chk_sccl_carry"):
                        self.chk_sccl_carry.setChecked(bool(e.get("carry_forward", True)))
                    self.status.showMessage("Loaded prior-close SCCL explanation for preview (not saved).", 4500)

        self.lbl_sccl_explain.setText(
            "Explain this SCCL number:\n"
            "- Instrument/trade list supports examiner drilldown\n"
            "- Netting + collateral show mitigation context\n"
            "- Save narrative is audit logged (maker/checker can be extended)\n"
        )

    def rollover_sccl_expl(self):
        if not self._selected_sccl_key:
            QMessageBox.information(self, "Select SCCL row", "Select an SCCL row first.")
            return
        prior_key = self._selected_sccl_key.replace(str(self.filters.as_of), str(self.data["prior"]))
        prior = self.sccl_expl[self.sccl_expl["key"] == prior_key].copy()
        if prior.empty:
            QMessageBox.information(self, "No prior explanation", "No prior-close SCCL explanation found for this row.")
            return
        e = prior.iloc[0].to_dict()
        reason = str(e.get("reason",""))
        if reason and reason in [self.cmb_sccl_reason.itemText(i) for i in range(self.cmb_sccl_reason.count())]:
            self.cmb_sccl_reason.setCurrentText(reason)
        self.txt_sccl_var.setPlainText(str(e.get("narrative","")))
        if hasattr(self, "chk_sccl_carry"):
            self.chk_sccl_carry.setChecked(bool(e.get("carry_forward", True)))
        self.status.showMessage("Prior SCCL explanation rolled into editor (preview). Click 'Save Draft' to persist for current close.", 5500)

    def save_sccl_expl(self):
        """
        Save Draft (Maker): SCCL explanation at Connected Group / Counterparty slice.
        Key: SCCL|asof|a_node|booking|cg|up|cp|cat
        """
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can save/edit narratives.")
            return
        if not self._selected_sccl_key:
            QMessageBox.information(self, "Select SCCL row", "Select an SCCL row first.")
            return
        narrative = (self.txt_sccl_var.toPlainText() or "").strip()
        if not narrative:
            QMessageBox.warning(self, "Narrative required", "Enter an SCCL explanation narrative.")
            return

        existing = self.sccl_expl[self.sccl_expl["key"] == self._selected_sccl_key].copy()
        if not existing.empty:
            st = str(existing.iloc[0].get("status","DRAFT"))
            if st in ("SUBMITTED","APPROVED"):
                QMessageBox.warning(self, "Locked", f"Item is {st}. Maker cannot edit unless it is rejected or recalled.")
                return

        parts = self._selected_sccl_key.split("|")
        # SCCL|asof|a_node|booking|cg|up|cp|cat
        _, _, a_node, booking, cg, up, cp, cat = (parts + [""]*8)[:8]

        now = now_str()
        row = {
            "key": self._selected_sccl_key,
            "as_of": self.filters.as_of,
            "a_node_id": a_node,
            "booking_entity": booking,
            "connected_group_id": cg,
            "ultimate_parent_id": up,
            "counterparty_id": cp,
            "exposure_category": cat,
            "reason": self.cmb_sccl_reason.currentText(),
            "annotation_type": (self.cmb_sccl_ann_type.currentText() if hasattr(self,"cmb_sccl_ann_type") else "(None)"),
            "annotation_scope": (self.cmb_sccl_ann_scope.currentText() if hasattr(self,"cmb_sccl_ann_scope") else "Line"),
            "evidence_ref": (self.ed_sccl_evidence.text().strip() if hasattr(self,"ed_sccl_evidence") else ""),
            "narrative": narrative,
            "carry_forward": bool(self.chk_sccl_carry.isChecked()) if hasattr(self, "chk_sccl_carry") else True,
            "status": "DRAFT",
            "maker": self.current_user,
            "ts_created": (existing.iloc[0].get("ts_created") if not existing.empty else now),
            "ts_updated": now,
            "submitted_ts": (existing.iloc[0].get("submitted_ts") if not existing.empty else ""),
            "checker": (existing.iloc[0].get("checker") if not existing.empty else ""),
            "approved_ts": (existing.iloc[0].get("approved_ts") if not existing.empty else ""),
            "decision_notes": (existing.iloc[0].get("decision_notes") if not existing.empty else ""),
        }

        self.sccl_expl = self.sccl_expl[self.sccl_expl["key"] != self._selected_sccl_key]
        self.sccl_expl = pd.concat([self.sccl_expl, pd.DataFrame([row])], ignore_index=True)
        if hasattr(self, "lbl_sccl_status"): self.lbl_sccl_status.setText("Status: DRAFT")

        self.log("SAVE_DRAFT", "SCCL", self._selected_sccl_key, f"reason={row['reason']}; carry={row['carry_forward']}; narrative={narrative[:200]}")
        self.refresh_audit()
        QMessageBox.information(self, "Saved", "Draft saved and audit logged.")

    def submit_sccl_expl(self):
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can submit.")
            return
        if not self._selected_sccl_key:
            QMessageBox.information(self, "Select SCCL row", "Select an SCCL row first.")
            return
        ex = self.sccl_expl[self.sccl_expl["key"] == self._selected_sccl_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No draft", "Save a draft first.")
            return
        st = str(ex.iloc[0].get("status","DRAFT"))
        if st != "DRAFT":
            QMessageBox.warning(self, "Wrong status", f"Only DRAFT can be submitted. Current: {st}")
            return
        # Enforce evidence requirement for selected annotation type
        ann_t = str(ex.iloc[0].get("annotation_type","(None)"))
        ev_ref = str(ex.iloc[0].get("evidence_ref","")).strip()
        rule = ANNOTATION_RULES.get(ann_t, ANNOTATION_RULES["(None)"])
        if rule.get("evidence_required") and not ev_ref:
            QMessageBox.warning(self, "Evidence Required", f"Annotation type {ann_t} requires Evidence Ref before submission.")
            return
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "status"] = "SUBMITTED"
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "submitted_ts"] = now_str()
        if hasattr(self, "lbl_sccl_status"): self.lbl_sccl_status.setText("Status: SUBMITTED")
        self.log("SUBMIT", "SCCL", self._selected_sccl_key, "Submitted for approval")
        self.refresh_audit()
        QMessageBox.information(self, "Submitted", "Submitted to Checker.")

    def approve_sccl_expl(self):
        if self.mode != "Checker":
            QMessageBox.information(self, "Not permitted", "Only Checker can approve.")
            return
        if not self._selected_sccl_key:
            QMessageBox.information(self, "Select SCCL row", "Select an SCCL row first.")
            return
        ex = self.sccl_expl[self.sccl_expl["key"] == self._selected_sccl_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No item", "No explanation found.")
            return
        st = str(ex.iloc[0].get("status",""))
        if st != "SUBMITTED":
            QMessageBox.warning(self, "Wrong status", f"Only SUBMITTED can be approved. Current: {st}")
            return
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "status"] = "APPROVED"
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "checker"] = self.current_user
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "approved_ts"] = now_str()
        if hasattr(self, "lbl_sccl_status"): self.lbl_sccl_status.setText("Status: APPROVED")
        self.log("APPROVE", "SCCL", self._selected_sccl_key, f"Approved by {self.current_user}")
        self.refresh_audit()
        QMessageBox.information(self, "Approved", "SCCL explanation approved.")

    def reject_sccl_expl(self):
        if self.mode != "Checker":
            QMessageBox.information(self, "Not permitted", "Only Checker can reject.")
            return
        if not self._selected_sccl_key:
            QMessageBox.information(self, "Select SCCL row", "Select an SCCL row first.")
            return
        ex = self.sccl_expl[self.sccl_expl["key"] == self._selected_sccl_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No item", "No explanation found.")
            return
        st = str(ex.iloc[0].get("status",""))
        if st != "SUBMITTED":
            QMessageBox.warning(self, "Wrong status", f"Only SUBMITTED can be rejected. Current: {st}")
            return
        note, ok = QInputDialog.getText(self, "Reject SCCL explanation", "Reason / notes (required):")
        if not ok or not (note or "").strip():
            return
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "status"] = "REJECTED"
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "checker"] = self.current_user
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "approved_ts"] = now_str()
        self.sccl_expl.loc[self.sccl_expl["key"] == self._selected_sccl_key, "decision_notes"] = note.strip()
        if hasattr(self, "lbl_sccl_status"): self.lbl_sccl_status.setText("Status: REJECTED")
        self.log("REJECT", "SCCL", self._selected_sccl_key, f"{self.current_user}: {note.strip()[:200]}")
        self.refresh_audit()
        QMessageBox.information(self, "Rejected", "SCCL explanation rejected and returned to Maker.")

    def bulk_rollover_sccl(self):
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can run bulk rollover.")
            return

        prior_asof = self.data["prior"]
        cur_asof = self.filters.as_of
        prior = self.sccl_expl[
            (self.sccl_expl["as_of"] == prior_asof) &
            (self.sccl_expl["status"] == "APPROVED") &
            (self.sccl_expl["carry_forward"] == True)
        ].copy()

        if prior.empty:
            QMessageBox.information(self, "Nothing to rollover", "No prior approved carry-forward SCCL explanations found.")
            return

        created = 0
        now = now_str()
        for _, r in prior.iterrows():
            key = str(r["key"])
            new_key = key.replace(str(prior_asof), str(cur_asof))
            if not self.sccl_expl[self.sccl_expl["key"] == new_key].empty:
                continue
            row = r.to_dict()
            row.update({
                "key": new_key,
                "as_of": cur_asof,
                "status": "DRAFT",
                "maker": self.current_user,
                "ts_created": now,
                "ts_updated": now,
                "submitted_ts": "",
                "checker": "",
                "approved_ts": "",
                "decision_notes": "",
            })
            self.sccl_expl = pd.concat([self.sccl_expl, pd.DataFrame([row])], ignore_index=True)
            created += 1

        self.log("BULK_ROLLOVER", "SCCL", str(cur_asof), f"Created {created} SCCL draft explanations from prior carry-forward")
        self.refresh_audit()
        QMessageBox.information(self, "Bulk rollover complete", f"Created {created} SCCL draft explanations for current close.")

    # ---------- Confidence scoring
    def confidence(self) -> Tuple[str, int, Dict[str, Any]]:
        recon = self.recon_gl_sor()
        breaks = recon[recon["status"] == "BREAK"].copy() if not recon.empty else pd.DataFrame()
        material = breaks[breaks["abs_var"] >= self.filters.materiality].copy() if not breaks.empty else pd.DataFrame()

        feeds_today = self.data["feed"][self.data["feed"]["as_of"] == self.filters.as_of].copy()
        late = feeds_today[feeds_today["status"].isin(["LATE","FAILED"])].copy()
        rejects = int(feeds_today["rejects"].sum()) if not feeds_today.empty else 0

        open_b = self.breaks[self.breaks["status"].isin(["OPEN","IN REVIEW"])] if not self.breaks.empty else pd.DataFrame()
        breached = open_b[open_b["sla_status"] == "BREACHED"] if not open_b.empty else pd.DataFrame()

        score = 100
        score -= min(40, len(material) * 8)
        score -= min(20, len(late) * 8)
        score -= 10 if rejects > 600 else (5 if rejects > 250 else 0)
        score -= min(20, len(breached) * 10)
        score = int(max(0, min(100, score)))
        rating = "HIGH" if score >= 80 else ("MEDIUM" if score >= 60 else "LOW")
        return rating, score, {"material_breaks": len(material), "late_feeds": len(late), "rejects": rejects, "sla_breaches": len(breached)}

    # ---------- Enterprise close-cycle governance
    def cycle_id(self, as_of: Optional[date] = None) -> str:
        d = as_of or self.filters.as_of
        return f"CYC-{d.strftime('%Y%m%d')}"

    def is_certified(self, as_of: Optional[date] = None) -> bool:
        d = as_of or self.filters.as_of
        key = str(d)
        st = self.certifications.get(key, {}) if isinstance(self.certifications, dict) else {}
        if isinstance(st, dict) and st.get("status") == "CERTIFIED":
            return True
        # fallback to seed close_cycles
        try:
            cc = self.close_cycles
            row = cc[cc["as_of"] == d]
            if not row.empty and str(row.iloc[0].get("status")) == "CERTIFIED":
                return True
        except Exception:
            pass
        return False

    def close_gate_status(self) -> pd.DataFrame:
        """Returns a gate checklist for the current close cycle (report-agnostic)."""
        as_of = self.filters.as_of
        cid = self.cycle_id(as_of)

        # Gate 1: Feeds complete (no LATE/FAILED for Tier-1 sources)
        feeds_today = self.data.get("feed", pd.DataFrame())
        ft = feeds_today[feeds_today["as_of"] == as_of] if not feeds_today.empty else pd.DataFrame()
        tier1 = ft[ft["source"].isin(["GL_CORE", "SUBLEDGER_SOR", "CRRT_PIPE", "CR360_PIPE", "ERA_SCCL"])].copy() if not ft.empty else pd.DataFrame()
        g1 = "READY" if (tier1.empty or not tier1["status"].isin(["LATE", "FAILED"]).any()) else "BLOCKED"
        g1d = f"Late/failed: {int(tier1['status'].isin(['LATE','FAILED']).sum())} (tier-1)" if not tier1.empty else "No feeds"

        # Gate 2: DQ rules passed (demo: use rules list + feed SLA as proxy)
        g2 = "READY" if g1 == "READY" else "AT_RISK"
        g2d = "DQ checks (proxy)" if g2 == "READY" else "Dependent on feed timeliness"

        # Gate 3: Recon coverage (GL↔SOR)
        recon = self.recon_gl_sor()
        cov = 0.0
        if recon is not None and not recon.empty:
            cov = float((recon["status"] == "MATCH").mean())
        g3 = "READY" if cov >= 0.98 else ("AT_RISK" if cov >= 0.95 else "BLOCKED")
        g3d = f"Coverage={cov*100:.1f}% (target 98%)"

        # Gate 4: Material breaks resolved/waived
        b = self.breaks.copy() if not self.breaks.empty else pd.DataFrame()
        b = b[b["as_of"] == as_of] if not b.empty else b
        mat = b[b["abs_var"] >= self.filters.materiality] if not b.empty else pd.DataFrame()
        open_mat = mat[mat["status"].isin(["OPEN", "IN REVIEW"])].copy() if not mat.empty else pd.DataFrame()
        g4 = "READY" if open_mat.empty else "BLOCKED"
        g4d = f"Open material breaks: {len(open_mat)}"

        # Gate 5: Material variances explained + approved (GL + SCCL)
        def _pending(df: pd.DataFrame) -> int:
            if df is None or df.empty:
                return 0
            dfx = df[df.get("as_of") == as_of] if "as_of" in df.columns else df
            return int((dfx.get("status") == "SUBMITTED").sum()) if "status" in dfx.columns else 0

        pend_gl = _pending(self.variance_expl)
        pend_sccl = _pending(self.sccl_expl)
        g5 = "READY" if (pend_gl + pend_sccl) == 0 else "AT_RISK"
        g5d = f"Pending approvals: GL={pend_gl}, SCCL={pend_sccl}"

        # Gate 6: Evidence complete (demo: open breaks must have evidence_ref)
        missing_evd = 0
        if not b.empty:
            open_b = b[b["status"].isin(["OPEN", "IN REVIEW"])].copy()
            if not open_b.empty:
                missing_evd = int((open_b["evidence_ref"].fillna("").astype(str).str.strip() == "").sum())
        g6 = "READY" if missing_evd == 0 else "AT_RISK"
        g6d = f"Open breaks missing evidence: {missing_evd}"

        # Gate 7: Executive certification
        g7 = "READY" if self.is_certified(as_of) else "BLOCKED"
        g7d = "Certified" if g7 == "READY" else "Not certified"

        return pd.DataFrame([
            {"cycle_id": cid, "gate": "1. Feeds complete", "status": g1, "details": g1d},
            {"cycle_id": cid, "gate": "2. Data quality checks", "status": g2, "details": g2d},
            {"cycle_id": cid, "gate": "3. Recon coverage", "status": g3, "details": g3d},
            {"cycle_id": cid, "gate": "4. Material breaks", "status": g4, "details": g4d},
            {"cycle_id": cid, "gate": "5. Explanations approvals", "status": g5, "details": g5d},
            {"cycle_id": cid, "gate": "6. Evidence completeness", "status": g6, "details": g6d},
            {"cycle_id": cid, "gate": "7. Certification", "status": g7, "details": g7d},
        ])

    def certify_current_cycle(self):
        if self.mode != "Executive":
            QMessageBox.warning(self, "Not allowed", "Only Executive mode can certify the close.")
            return
        as_of = self.filters.as_of
        gates = self.close_gate_status()
        blocked = gates[gates["status"] == "BLOCKED"]
        if not blocked.empty:
            QMessageBox.warning(self, "Certification blocked", "Cannot certify while gates are BLOCKED. Resolve blockers first.")
            return
        key = str(as_of)
        self.certifications[key] = {"status": "CERTIFIED", "certified_by": self.current_user, "certified_ts": now_str(), "cycle_id": self.cycle_id(as_of)}
        self.log("CERTIFY", "CYCLE", self.cycle_id(as_of), f"Certified by {self.current_user}")
        self._save_state()
        self.refresh_all()

    # ---------- Audit
    def log(self, action: str, obj_type: str, obj_id: str, details: str):
        self.audit = pd.concat([self.audit, pd.DataFrame([{
            "ts": now_str(), "user": self.current_user, "action": action,
            "object_type": obj_type, "object_id": obj_id, "details": details
        }])], ignore_index=True)

    # ---------- Refresh chain
    def refresh_all(self):
        # smart defaults for tolerances
        self.spn_tol.blockSignals(True)
        self.spn_tol.setValue(max(0, int(self.filters.materiality * 0.001)))
        self.spn_tol.blockSignals(False)

        self.spn_tol2.blockSignals(True)
        self.spn_tol2.setValue(max(0, int(self.filters.materiality * 0.0005)))
        self.spn_tol2.blockSignals(False)

        self.apply_mode_rules()
        self.refresh_dashboard()
        self.refresh_feed()
        self.refresh_gl()
        self.refresh_recon()
        self.refresh_breaks()
        self.refresh_variance()
        self.refresh_reporting()
        self.refresh_sccl()
        self.refresh_lineage()
        self.refresh_audit()
        self.refresh_close()
        self.refresh_catalog()
        self.refresh_queue()

        # Update shared dim tree and persist user context (enterprise-like experience)
        if hasattr(self, "dim_tree"):
            self.dim_tree.rebuild(self.filters, self.sccl_filters)

        # Apply saved table column views after widgets exist
        self._apply_table_views_to_all()
        self.update_context_header()

        self.status.showMessage(
            f"{self.filters.as_of} | {self.filters.legal_entity} | {self.filters.book} | {self.filters.ccy} | "
            f"Mat={int(self.filters.materiality):,} | Mode={self.mode} | {self._breadcrumbs()}",
            6000
        )
        if hasattr(self, 'lbl_ws_name'):
            self.update_workstream_cockpit()
        self._save_state()

    def refresh_dashboard(self):
        self.lbl_ctx_banner.setText(f"Context: Actual (Posted Balances) • LE={self.filters.legal_entity} • Book={self.filters.book} • CCY={self.filters.ccy} • {self._breadcrumbs()}")

        # Cycle banner: certification + gates + freshness + what changed
        try:
            cid = self.cycle_id()
            gates = self.close_gate_status()
            blocked = int((gates["status"] == "BLOCKED").sum()) if not gates.empty else 0
            at_risk = int((gates["status"] == "AT_RISK").sum()) if not gates.empty else 0
            st = "CERTIFIED" if self.is_certified(self.filters.as_of) else "IN_PROGRESS"
            if hasattr(self, "lbl_cycle_badge"):
                self.lbl_cycle_badge.setText(f"Cycle {cid}: {st}  |  Gates: blocked={blocked}, at-risk={at_risk}")
        except Exception:
            pass

        try:
            ft = self.data.get("feed", pd.DataFrame())
            cur = ft[ft["as_of"] == self.filters.as_of].copy() if ft is not None and not ft.empty else pd.DataFrame()
            tier1 = cur[cur["source"].isin(["GL_CORE", "SUBLEDGER_SOR", "CRRT_PIPE", "CR360_PIPE", "ERA_SCCL"])].copy() if not cur.empty else pd.DataFrame()
            mx = int(tier1["latency_mins"].max()) if (not tier1.empty and "latency_mins" in tier1.columns) else 0
            late_cnt = int(tier1["status"].isin(["LATE", "FAILED"]).sum()) if not tier1.empty else 0
            rej = int(tier1["rejects"].sum()) if (not tier1.empty and "rejects" in tier1.columns) else 0
            if hasattr(self, "lbl_fresh"):
                self.lbl_fresh.setText(f"Freshness (tier-1): max latency {mx} mins | late/failed {late_cnt} | rejects {rej}")
        except Exception:
            pass

        try:
            if hasattr(self, "chk_changes") and self.chk_changes.isChecked():
                prior = self.data.get("prior")
                gl = self.data.get("gl", pd.DataFrame())
                cur = gl[(gl["as_of"] == self.filters.as_of) & (gl["legal_entity"] == self.filters.legal_entity) & (gl["book"] == self.filters.book) & (gl["ccy"] == self.filters.ccy)]
                prv = gl[(gl["as_of"] == prior) & (gl["legal_entity"] == self.filters.legal_entity) & (gl["book"] == self.filters.book) & (gl["ccy"] == self.filters.ccy)]
                d_gl = float(cur["amount"].sum() - prv["amount"].sum()) if (cur is not None and prv is not None) else 0.0
                sc = self.data.get("sccl_atomic", pd.DataFrame())
                sc_cur = sc[sc["as_of"] == self.filters.as_of] if sc is not None and not sc.empty else pd.DataFrame()
                sc_prv = sc[sc["as_of"] == prior] if sc is not None and not sc.empty else pd.DataFrame()
                d_ead = float(sc_cur["ead"].sum() - sc_prv["ead"].sum()) if (not sc_cur.empty and not sc_prv.empty) else 0.0
                if hasattr(self, "lbl_changed"):
                    self.lbl_changed.setText(f"Δ since last close: GL={fmt_big(d_gl)} | SCCL EAD={fmt_big(d_ead)}")
            else:
                if hasattr(self, "lbl_changed"):
                    self.lbl_changed.setText("Changes since last close: (disabled)")
        except Exception:
            pass

        recon = self.recon_gl_sor()
        breaks = recon[recon["status"] == "BREAK"].copy() if not recon.empty else pd.DataFrame()
        material_breaks = breaks[breaks["abs_var"] >= self.filters.materiality].copy() if not breaks.empty else pd.DataFrame()
        feeds_today = self.data["feed"][self.data["feed"]["as_of"] == self.filters.as_of].copy()
        late = feeds_today[feeds_today["status"].isin(["LATE","FAILED"])].copy()

        completion = 1.0 - (len(breaks) / max(len(recon), 1)) if not recon.empty else 1.0
        rating, score, meta = self.confidence()

        open_cnt = len(self.breaks[self.breaks["status"].isin(["OPEN","IN REVIEW"])]) if not self.breaks.empty else 0

        self.k_material.setText(str(len(material_breaks)))
        self.k_material_sub.setText(f"Threshold: {fmt_money(self.filters.materiality)}")

        self.k_open.setText(str(open_cnt))
        self.k_open_sub.setText(f"SLA breaches: {meta['sla_breaches']}")

        self.k_feeds.setText(str(len(late)))
        self.k_feeds_sub.setText(f"Rejects: {meta['rejects']}")

        self.k_recon.setText(fmt_pct(completion))
        self.k_recon_sub.setText(f"Tolerance: {fmt_money(self.spn_tol.value())}")

        self.k_conf.setText(f"{rating} ({score})")
        self.k_conf_sub.setText(f"Material={meta['material_breaks']} • Late={meta['late_feeds']}")

        top = recon.sort_values("abs_var", ascending=False).head(14)[
            ["product","account","account_name","gl_amount","sor_amount","variance","abs_var","status","severity"]
        ].copy() if not recon.empty else pd.DataFrame()
        if self.chk_changes.isChecked() and not top.empty:
            top = top[top["abs_var"] > 0].copy()
        self.m_top.set_df(top)

        snap = feeds_today[["source","layer","status","latency_min","records","rejects","run_id"]].copy() if not feeds_today.empty else pd.DataFrame()
        self.m_feed_snap.set_df(snap)

        readiness = pd.DataFrame([
            {"Report":"FR2590","Confidence":rating,"Status":"IN PROGRESS"},
            {"Report":"Y-9C","Confidence":"MEDIUM" if rating == "HIGH" else rating,"Status":"IN PROGRESS"},
            {"Report":"FR Y (Other)","Confidence":"LOW" if rating != "HIGH" else "MEDIUM","Status":"AT RISK"},
            {"Report":"CCAR","Confidence":"HIGH","Status":"READY"},
            {"Report":"CECL/ACL","Confidence":"MEDIUM","Status":"IN PROGRESS"},
            {"Report":"STARE","Confidence":"LOW" if (feeds_today[feeds_today["source"]=="STARE_FORECAST"]["status"].astype(str).eq("LATE").any()) else "MEDIUM","Status":"AT RISK"},
            {"Report":"ERA","Confidence":"MEDIUM","Status":"IN PROGRESS"},
        ])
        self.m_ready.set_df(readiness)


        # Action Queue (exception-first)
        actions: List[Dict[str, Any]] = []

        # Slice breaks to current context
        bctx = self.breaks.copy()
        if not bctx.empty:
            bctx = bctx[(bctx["as_of"] == self.filters.as_of) &
                        (bctx["legal_entity"] == self.filters.legal_entity) &
                        (bctx["book"] == self.filters.book) &
                        (bctx["ccy"] == self.filters.ccy)].copy()

        open_b_ctx = bctx[bctx["status"].isin(["OPEN", "IN REVIEW"])].copy() if not bctx.empty else pd.DataFrame()

        # Break actions (material and/or SLA at risk)
        if not open_b_ctx.empty:
            open_b_ctx["is_material"] = open_b_ctx["abs_var"].apply(lambda x: abs(safe_float(x, 0.0)) >= self.filters.materiality)
            # Prioritize: material first, then SLA breached, then biggest variance
            def _prio_row(r):
                if bool(r.get('is_material')) or str(r.get('sla_status')) == 'BREACHED':
                    return 'P1'
                if str(r.get('sla_status')) == 'AT_RISK':
                    return 'P2'
                return 'P3'

            tmp = open_b_ctx.copy()
            tmp["priority"] = tmp.apply(_prio_row, axis=1)
            tmp = tmp.sort_values(["priority", "abs_var"], ascending=[True, False]).head(10)
            for _, r in tmp.iterrows():
                actions.append({
                    "Priority": r.get("priority", "P2"),
                    "Type": "Break",
                    "Item": r.get("break_id", ""),
                    "Status": r.get("status", ""),
                    "Owner": r.get("owner", ""),
                    "SLA": r.get("sla_status", ""),
                    "Age(d)": int(r.get("age_days", 0)),
                    "Abs_Var": safe_float(r.get("abs_var", 0.0)),
                })

        # Feed actions (late / failed)
        if not late.empty:
            for _, r in late.head(6).iterrows():
                actions.append({
                    "Priority": "P1",
                    "Type": "Feed",
                    "Item": r.get("source", ""),
                    "Status": r.get("status", ""),
                    "Owner": "Data Ops",
                    "SLA": "—",
                    "Age(d)": "",
                    "Abs_Var": "",
                })

        # Pending approvals (variance + SCCL)
        pend_v = self.variance_expl[self.variance_expl["status"].astype(str).eq("SUBMITTED")].copy() if not self.variance_expl.empty else pd.DataFrame()
        if not pend_v.empty:
            for _, r in pend_v.head(6).iterrows():
                actions.append({
                    "Priority": "P1",
                    "Type": "Variance Approval",
                    "Item": r.get("key", ""),
                    "Status": "SUBMITTED",
                    "Owner": r.get("maker", ""),
                    "SLA": "—",
                    "Age(d)": "",
                    "Abs_Var": "",
                })

        pend_s = self.sccl_expl[self.sccl_expl["status"].astype(str).eq("SUBMITTED")].copy() if not self.sccl_expl.empty else pd.DataFrame()
        if not pend_s.empty:
            for _, r in pend_s.head(6).iterrows():
                actions.append({
                    "Priority": "P1",
                    "Type": "SCCL Approval",
                    "Item": r.get("key", ""),
                    "Status": "SUBMITTED",
                    "Owner": r.get("maker", ""),
                    "SLA": "—",
                    "Age(d)": "",
                    "Abs_Var": "",
                })

        # Missing evidence (open breaks)
        if not open_b_ctx.empty and "evidence_ref" in open_b_ctx.columns:
            miss = open_b_ctx[open_b_ctx["evidence_ref"].astype(str).str.strip().eq("")].copy()
            miss = miss.sort_values(["sla_status", "abs_var"], ascending=[False, False]).head(6)
            for _, r in miss.iterrows():
                actions.append({
                    "Priority": "P2",
                    "Type": "Evidence Missing",
                    "Item": r.get("break_id", ""),
                    "Status": r.get("status", ""),
                    "Owner": r.get("owner", ""),
                    "SLA": r.get("sla_status", ""),
                    "Age(d)": int(r.get("age_days", 0)),
                    "Abs_Var": safe_float(r.get("abs_var", 0.0)),
                })

        adf = pd.DataFrame(actions)
        self.m_actions.set_df(adf)

        # break intelligence
        b = self.breaks.copy()
        # Enterprise context slice: Breaks list follows the same global context as other workspaces
        if not b.empty:
            b = b[(b["as_of"] == self.filters.as_of) &
                  (b["legal_entity"] == self.filters.legal_entity) &
                  (b["book"] == self.filters.book) &
                  (b["ccy"] == self.filters.ccy)].copy()
        open_b = b[b["status"].isin(["OPEN","IN REVIEW"])].copy() if not b.empty else pd.DataFrame()
        if open_b.empty:
            self.lbl_root.setText("Top Root Cause: —")
            self.lbl_repeat.setText("Repeat Offenders: —")
            self.lbl_sla.setText("SLA Risk: —")
        else:
            self.lbl_root.setText(f"Top Root Cause: {open_b['root_cause'].value_counts().index[0]}")
            offenders = ", ".join(open_b["account"].value_counts().head(2).index.tolist())
            self.lbl_repeat.setText(f"Repeat Offenders: {offenders}")
            self.lbl_sla.setText(f"SLA Risk: {len(open_b[open_b['sla_status'].isin(['AT_RISK','BREACHED'])])}")

    def refresh_feed(self):
        f = self.data["feed"][self.data["feed"]["as_of"] == self.filters.as_of].copy()
        self.m_feed.set_df(f)
        self.cmb_feed.blockSignals(True)
        self.cmb_feed.clear()
        for s in f["source"].tolist():
            self.cmb_feed.addItem(s)
        self.cmb_feed.blockSignals(False)

        if not f.empty:
            rej = pd.DataFrame({
                "source": np.random.choice(f["source"], 30),
                "error_code": np.random.choice(["MISSING_DIM","INVALID_ACCOUNT","BAD_CCY","DUP_KEY","CONTROL_MISMATCH"], 30),
                "sample_key": [f"K{np.random.randint(100000,999999)}" for _ in range(30)],
                "detail": np.random.choice(
                    ["Missing cost_center","Account not in COA","Currency mismatch","Duplicate reference id","Control total variance"], 30
                ),
            })
        else:
            rej = pd.DataFrame(columns=["source","error_code","sample_key","detail"])
        self.m_rej.set_df(rej)
        self.m_rules.set_df(self.data["rules"].copy())

    def refresh_gl(self):
        q = (self.ed_gl.text() or "").strip().lower()
        gl = self.gl_filtered()
        if gl.empty:
            self.m_gl.set_df(pd.DataFrame(columns=["account","account_name","product","gl_amount"]))
            self.m_map_acc.set_df(pd.DataFrame(columns=["report","report_line","line_desc"]))
            self.lbl_explain.setText("No data for current filters.")
            return
        tb = gl.groupby(["account","account_name","product"], as_index=False).agg(gl_amount=("gl_amount","sum"))
        if q:
            tb = tb[
                tb["account"].astype(str).str.contains(q, case=False) |
                tb["account_name"].astype(str).str.lower().str.contains(q)
            ].copy()
        tb = tb.sort_values(["account","product"])
        self.m_gl.set_df(tb)
        self.m_map_acc.set_df(pd.DataFrame(columns=["report","report_line","line_desc"]))
        self.lbl_explain.setText("Select a row to see mapping, lineage, and risk drivers.")

    def on_gl_selected(self, idx: QModelIndex):
        r = self.m_gl.get_row(idx.row())
        acc = str(r.get("account",""))
        prod = str(r.get("product",""))
        amt = r.get("gl_amount", 0.0)

        mm = self.data["map"][self.data["map"]["account"] == acc][["report","report_line","line_desc"]].drop_duplicates().copy()
        self.m_map_acc.set_df(mm)

        open_b = self.breaks[self.breaks["status"].isin(["OPEN","IN REVIEW"])] if not self.breaks.empty else pd.DataFrame()
        slice_b = open_b[(open_b["account"] == acc) & (open_b["product"] == prod)] if not open_b.empty else pd.DataFrame()
        contrib = "No open breaks for this slice." if slice_b.empty else f"Open breaks: {len(slice_b)} • SLA: {slice_b['sla_status'].value_counts().to_dict()}"

        self.lbl_explain.setText(
            f"Context: {self.filters.as_of} | LE={self.filters.legal_entity} | Book={self.filters.book} | CCY={self.filters.ccy}\n"
            f"SCCL Path: {self._breadcrumbs()}\n\n"
            f"Account {acc} | Product {prod}\nAmount: {fmt_money(amt)}\n\n"
            f"Why it matters:\n- Mapped to {mm['report'].nunique()} report(s)\n- {contrib}\n\n"
            "Lineage:\nGL_CORE + SUBLEDGER_SOR → Enterprise GL Mart → CRRT → CR360 → Reporting"
        )

    def refresh_recon(self):
        recon = self.recon_gl_sor()
        view = recon.sort_values("abs_var", ascending=False)[
            ["product","account","account_name","gl_amount","sor_amount","variance","abs_var","status","severity"]
        ].copy() if not recon.empty else pd.DataFrame(columns=["product","account","account_name","gl_amount","sor_amount","variance","abs_var","status","severity"])
        self.m_recon.set_df(view)

        recon2 = self.recon_crrt_cr360()
        view2 = recon2.sort_values("abs_var", ascending=False)[
            ["account","crrt_amount","cr360_amount","variance","abs_var","status"]
        ].copy() if not recon2.empty else pd.DataFrame(columns=["account","crrt_amount","cr360_amount","variance","abs_var","status"])
        self.m_recon2.set_df(view2)

    def refresh_breaks(self):
        b = self.breaks.copy()
        st = self.cmb_break_status.currentText()
        if st != "(All)" and not b.empty:
            b = b[b["status"] == st].copy()

        q = (self.ed_break_search.text() or "").strip().lower()
        if q and not b.empty:
            cols = ["break_id","account","product","root_cause","owner","status","severity"]
            mask = False
            for c in cols:
                mask = mask | b[c].astype(str).str.lower().str.contains(q)
            b = b[mask].copy()

        # prioritize SLA risk then severity then magnitude
        order = ["BREACHED","AT_RISK","ON_TRACK"]
        if not b.empty:
            b["sla_rank"] = b["sla_status"].apply(lambda x: order.index(x) if x in order else 9)
            b = b.sort_values(["sla_rank","severity","abs_var"], ascending=[True, False, False]).drop(columns=["sla_rank"])
        self.m_breaks.set_df(b)
        self.refresh_timeline()

    def refresh_timeline(self):
        sel = self.tbl_breaks.selectionModel().selectedRows()
        if not sel or self.m_breaks._df.empty:
            self.m_timeline.set_df(pd.DataFrame(columns=["ts","user","action","details"]))
            return
        bid = self.m_breaks.get_row(sel[0].row()).get("break_id","")
        a = self.audit[(self.audit["object_type"] == "BREAK") & (self.audit["object_id"] == bid)].copy()
        self.m_timeline.set_df(a.sort_values("ts")[["ts","user","action","details"]].copy() if not a.empty else pd.DataFrame(columns=["ts","user","action","details"]))

    def refresh_variance(self):
        v = self.variance_pop()
        view = v.head(50)[["account","account_name","product","cur","prior","variance","abs_var","severity"]].copy() if not v.empty else pd.DataFrame(columns=["account","account_name","product","cur","prior","variance","abs_var","severity"])
        self.m_var.set_df(view)
        self._selected_variance_key = None
        self.lbl_var.setText("(Select a variance row)")
        self.txt_var.setPlainText("")
        if hasattr(self,"cmb_var_ann_type"): self.cmb_var_ann_type.setCurrentText("(None)")
        if hasattr(self,"cmb_var_ann_scope"): self.cmb_var_ann_scope.setCurrentText("Line")
        if hasattr(self,"ed_var_evidence"): self.ed_var_evidence.setText("")
        if hasattr(self, "lbl_var_status"): self.lbl_var_status.setText("Status: —")
        if hasattr(self, "chk_var_carry"): self.chk_var_carry.setChecked(True)

    def refresh_reporting(self):
        rep = self.cmb_report.currentText()
        if rep == "STARE":
            self.lbl_report.setText("Forecast / Stress Scenario view (not posted actuals)")
        elif rep == "ERA":
            self.lbl_report.setText("ERA (SCCL accountability) - actuals & recon governance")
        else:
            self.lbl_report.setText("Actual / posted balances reporting view")

        lines, accs_by_line = self.report_lines(rep)
        self._accs_by_line = accs_by_line
        self.m_lines.set_df(lines[["report_line","line_desc","amount","recon_abs_var","recon_status","mapped_accounts"]] if not lines.empty else pd.DataFrame(columns=["report_line","line_desc","amount","recon_abs_var","recon_status","mapped_accounts"]))
        self.m_drill.set_df(pd.DataFrame(columns=["account","account_name","product","amount"]))

    def refresh_lineage(self):
        self.m_map.set_df(self.data["map"].sort_values(["report","report_line","account"]).copy())
        gl = self.gl_filtered()
        accs = sorted(gl["account"].unique().tolist()) if not gl.empty else sorted(self.data["map"]["account"].unique().tolist())

        self.cmb_acc.blockSignals(True)
        self.cmb_acc.clear()
        for a in accs:
            self.cmb_acc.addItem(str(a))
        self.cmb_acc.blockSignals(False)

        if accs:
            self.cmb_acc.setCurrentIndex(0)
            self.refresh_lineage_side()

    def refresh_lineage_side(self):
        acc = (self.cmb_acc.currentText() or "").strip()
        if not acc:
            return
        rel = self.data["map"][self.data["map"]["account"] == acc][["report","report_line","line_desc"]].drop_duplicates().copy()
        self.m_rel.set_df(rel)

        self.lbl_lineage.setText(
            f"Account: {acc}\nEntity: {self.filters.legal_entity} | Book: {self.filters.book} | CCY: {self.filters.ccy} | As-of: {self.filters.as_of}\n\n"
            "Lineage Path:\n"
            "1) Source Systems: GL_CORE + SUBLEDGER_SOR\n"
            "2) Enterprise GL Data Mart (governed)\n"
            "3) CRRT (aggregation)\n"
            "4) CR360 (consumer layer)\n"
            "5) Outputs: FR2590, Y-9C, FR-Y, CCAR, CECL/ACL, STARE, ERA\n\n"
            "Governance:\n"
            "- DQ rules (completeness, timeliness, balancing)\n"
            "- Maker/Checker for mapping changes\n"
            "- Immutable audit trail"
        )

    def refresh_audit(self):
        self.m_audit.set_df(self.audit.sort_values("ts", ascending=False).copy() if not self.audit.empty else pd.DataFrame(columns=["ts","user","action","object_type","object_id","details"]))
        b = self.breaks.copy()
        evid = b[b["evidence_ref"].astype(str).str.len() > 0][["break_id","as_of","recon_type","severity","status","evidence_ref","notes"]].copy() if not b.empty else pd.DataFrame(columns=["break_id","as_of","recon_type","severity","status","evidence_ref","notes"])
        self.m_evid.set_df(evid)
        if hasattr(self, "m_evd_reg"):
            self.m_evd_reg.set_df(self.evidence_registry.copy() if self.evidence_registry is not None else pd.DataFrame())

    def refresh_close(self):
        """Refresh close gates and cycle-linked evidence."""
        if not hasattr(self, "m_gates"):
            return
        gates = self.close_gate_status()
        self.m_gates.set_df(gates)
        # Cycle evidence
        evd = self.evidence_registry.copy() if not self.evidence_registry.empty else pd.DataFrame(columns=["evidence_id","evidence_type","title","linked_object_type","linked_object_id","owner","ts","sha256","retention"])
        cid = self.cycle_id()
        evd_c = evd[(evd["linked_object_type"] == "CYCLE") & (evd["linked_object_id"] == cid)].copy() if not evd.empty else evd
        if hasattr(self, "m_evd_cycle"):
            self.m_evd_cycle.set_df(evd_c)
        # Banner
        status = "CERTIFIED" if self.is_certified(self.filters.as_of) else "IN_PROGRESS"
        if hasattr(self, "lbl_close_status"):
            self.lbl_close_status.setText(f"Cycle {cid} • As-of {self.filters.as_of} • Status: {status}")

    def refresh_catalog(self):
        if hasattr(self, "m_report_cat"):
            self.m_report_cat.set_df(self.report_catalog.copy() if self.report_catalog is not None else pd.DataFrame())
        if hasattr(self, "m_policies"):
            self.m_policies.set_df(self.recon_policies.copy() if self.recon_policies is not None else pd.DataFrame())
        if hasattr(self, "m_map_sets"):
            self.m_map_sets.set_df(self.mapping_sets.copy() if self.mapping_sets is not None else pd.DataFrame())
        if hasattr(self, "m_ent"):
            self.m_ent.set_df(self.entitlements.copy() if self.entitlements is not None else pd.DataFrame())

    def build_work_queue(self) -> pd.DataFrame:
        """Unified enterprise queue across domains: feeds, breaks, approvals, evidence."""
        items: List[Dict[str, Any]] = []
        as_of = self.filters.as_of

        # Feeds
        ft = self.data.get("feed", pd.DataFrame())
        if ft is not None and not ft.empty:
            cur = ft[ft["as_of"] == as_of].copy()
            for _, r in cur.iterrows():
                if str(r.get("status")) in ("LATE", "FAILED") or int(safe_float(r.get("rejects"), 0)) > 500:
                    rt = self.route_feed(str(r.get("source","")), str(r.get("layer","")))
                    sev = "P1" if str(r.get("status")) in ("FAILED",) else "P2"
                    items.append({
                        "item_id": f"FEED:{r.get('run_id')}",
                        "domain": "Feeds",
                        "priority": sev,
                        "report_family": rt.get("report_family",""),
                        "workstream_code": rt.get("workstream_code",""),
                        "workstream_name": rt.get("workstream_name",""),
                        "owner_team": rt.get("owning_team","Ops"),
                        "status": str(r.get("status")),
                        "sla": "T+0",
                        "summary": f"{r.get('source')} {r.get('status')} (rejects={int(safe_float(r.get('rejects'),0))})",
                        "object_type": "FEED",
                        "object_id": str(r.get("run_id")),
                        "assigned_to": "",
                    })

        # Breaks
        b = self.breaks.copy() if not self.breaks.empty else pd.DataFrame()
        b = b[b["as_of"] == as_of] if not b.empty else b
        if not b.empty:
            for _, r in b.iterrows():
                if str(r.get("status")) in ("OPEN", "IN REVIEW"):
                    pr = "P1" if safe_float(r.get("abs_var"), 0) >= self.filters.materiality else "P2"
                    items.append({
                        "item_id": f"BRK:{r.get('break_id')}",
                        "domain": "Recon",
                        "priority": pr,
                        "report_family": str(r.get("report_family","")),
                        "workstream_code": str(r.get("workstream_code","")),
                        "workstream_name": str(r.get("workstream_name","")),
                        "owner_team": str(r.get("owning_team","Recon")),
                        "status": str(r.get("status")),
                        "sla": f"{int(safe_float(r.get('sla_days'),2))}d",
                        "summary": f"{r.get('recon_type')} {r.get('account')} {r.get('product')} var={fmt_big(r.get('variance'))}",
                        "object_type": "BREAK",
                        "object_id": str(r.get("break_id")),
                        "assigned_to": str(r.get("owner")) if r.get("owner") else "",
                    })

        # Approvals (GL + SCCL)
        for df, dom in [(self.variance_expl, "Variance"), (self.sccl_expl, "SCCL")]:
            if df is None or df.empty:
                continue
            cur = df[df["as_of"] == as_of].copy() if "as_of" in df.columns else df
            cur = cur[cur["status"] == "SUBMITTED"].copy() if "status" in cur.columns else pd.DataFrame()
            for _, r in cur.iterrows():
                rt = self.route_break("FR2590 (SCCL)" if dom == "SCCL" else "GL vs SOR")
                items.append({
                    "item_id": f"APR:{dom}:{r.get('key')}",
                    "domain": "Approvals",
                    "priority": "P2",
                    "report_family": rt.get("report_family",""),
                    "workstream_code": rt.get("workstream_code",""),
                    "workstream_name": rt.get("workstream_name",""),
                    "owner_team": rt.get("owning_team","Reg Reporting"),
                    "status": "SUBMITTED",
                    "sla": "T+1",
                    "summary": f"{dom} approval pending ({r.get('reason')})",
                    "object_type": "EXPLANATION",
                    "object_id": str(r.get("key")),
                    "assigned_to": "",
                })

        # Evidence completeness (open breaks missing evidence)
        if not b.empty:
            miss = b[(b["status"].isin(["OPEN", "IN REVIEW"])) & (b["evidence_ref"].fillna("").astype(str).str.strip() == "")].copy()
            for _, r in miss.iterrows():
                items.append({
                    "item_id": f"EVD:{r.get('break_id')}",
                    "domain": "Evidence",
                    "priority": "P2",
                    "report_family": str(r.get("report_family","")),
                    "workstream_code": str(r.get("workstream_code","")),
                    "workstream_name": str(r.get("workstream_name","")),
                    "owner_team": str(r.get("owning_team","Ops")),
                    "status": "MISSING",
                    "sla": "T+1",
                    "summary": f"Evidence missing for break {r.get('break_id')}",
                    "object_type": "BREAK",
                    "object_id": str(r.get("break_id")),
                    "assigned_to": str(r.get("owner")) if r.get("owner") else "",
                })

        out = pd.DataFrame(items)
        if out.empty:
            return pd.DataFrame(columns=["item_id","domain","priority","owner_team","status","sla","summary","object_type","object_id","assigned_to"])
        # Priority sort
        pr_order = {"P1": 0, "P2": 1, "P3": 2}
        out["_p"] = out["priority"].map(pr_order).fillna(9)
        out = out.sort_values(["_p", "domain"]).drop(columns=["_p"])
        return out

    def refresh_queue(self):
        if not hasattr(self, "m_queue"):
            return
        q = self.build_work_queue()

        # Domain filter (All / Recon / Feeds / Approvals / Evidence)
        sel_dom = self.cmb_queue.currentText() if hasattr(self, "cmb_queue") else "All"
        if sel_dom and sel_dom != "All" and not q.empty:
            q = q[q["domain"] == sel_dom].copy()

        # Report family + workstream filters (report-family first)
        fam = getattr(self, "selected_report_family", "All")
        ws_code = getattr(self, "selected_workstream_code", "(All)")
        if fam and fam != "All" and not q.empty and "report_family" in q.columns:
            q = q[q["report_family"].astype(str) == fam].copy()
        if ws_code and ws_code != "(All)" and not q.empty and "workstream_code" in q.columns:
            q = q[q["workstream_code"].astype(str) == ws_code].copy()

        # Scope filter (All / My Work / Team Queue)
        scope = self.cmb_scope.currentText() if hasattr(self, "cmb_scope") else "All"
        if not q.empty and "assigned_to" in q.columns:
            if scope == "My Work":
                q = q[q["assigned_to"].astype(str) == str(self.current_user)].copy()
            elif scope == "Team Queue":
                # Team queue is driven by workstream owning team (if selected), otherwise show all
                team = ""
                if ws_code and ws_code != "(All)" and self.workstreams is not None and not self.workstreams.empty:
                    hit = self.workstreams[self.workstreams["workstream_code"].astype(str) == ws_code]
                    if not hit.empty:
                        team = str(hit.iloc[0].get("owning_team",""))
                if team:
                    q = q[q["owner_team"].astype(str) == team].copy()

        self.m_queue.set_df(q)

    # --- Governance demo actions
    def onboard_report_demo(self):
        """Adds a sample report entry to the enterprise report catalog (demo-only)."""
        if self.report_catalog is None:
            self.report_catalog = pd.DataFrame()
        name, ok = QInputDialog.getText(self, "Onboard Report", "Report name (demo):")
        if not ok or not str(name).strip():
            return
        r = {
            "report": str(name).strip(),
            "primary_grain": "GL-Line",
            "primary_hierarchy": "A-Node→LE→Book→CCY→Account",
            "owner": "Reg Reporting",
            "criticality": "TIER-2",
            "controls": "Mapping governance, recon, explain variance, evidence, certification",
        }
        self.report_catalog = pd.concat([self.report_catalog, pd.DataFrame([r])], ignore_index=True)
        self.log("ONBOARD", "REPORT", r["report"], "Added to report catalog")
        self.refresh_catalog()

    def propose_mapping_change_demo(self):
        """Creates a draft mapping set to illustrate mapping governance + impact preview."""
        if self.mode == "Auditor" or self.mode == "Executive":
            QMessageBox.information(self, "Not allowed", "Use Maker/Checker to propose mapping changes.")
            return
        if self.mapping_sets is None:
            self.mapping_sets = pd.DataFrame(columns=["mapping_set_id","name","status","effective_from","effective_to","approved_by","approved_ts"])
        mid = f"MAP-{datetime.now().strftime('%Y%m%d%H%M')}"
        reason, ok = QInputDialog.getText(self, "Mapping Change", "Reason / ticket (demo):")
        if not ok:
            return
        row = {
            "mapping_set_id": mid,
            "name": f"Change - {reason[:24] if reason else 'demo'}",
            "status": "DRAFT",
            "effective_from": str(self.filters.as_of),
            "effective_to": "",
            "approved_by": "",
            "approved_ts": "",
        }
        self.mapping_sets = pd.concat([self.mapping_sets, pd.DataFrame([row])], ignore_index=True)
        self.log("PROPOSE", "MAPPING_SET", mid, f"Reason={reason}")
        self.refresh_catalog()

    def approve_mapping_change_demo(self):
        """Approves the newest draft mapping set (Checker-only in spirit; enforced lightly for demo)."""
        if self.mode not in ("Checker", "Executive"):
            QMessageBox.information(self, "Not allowed", "Switch to Checker to approve mapping changes.")
            return
        if self.mapping_sets is None or self.mapping_sets.empty:
            return
        drafts = self.mapping_sets[self.mapping_sets["status"] == "DRAFT"].copy()
        if drafts.empty:
            QMessageBox.information(self, "Nothing to approve", "No draft mapping sets found.")
            return
        idx = drafts.index[-1]
        self.mapping_sets.loc[idx, "status"] = "APPROVED"
        self.mapping_sets.loc[idx, "approved_by"] = self.current_user
        self.mapping_sets.loc[idx, "approved_ts"] = now_str()
        mid = str(self.mapping_sets.loc[idx, "mapping_set_id"])
        self.log("APPROVE", "MAPPING_SET", mid, "Approved mapping set")
        self.refresh_catalog()

    def create_evidence_for_selected_break(self):
        """Creates a structured evidence record and links it to an existing break (demo: uses break notes/metadata)."""
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        if not hasattr(self, "tbl_breaks"):
            QMessageBox.information(self, "Info", "Go to Reconciliation Workspace / Breaks to select a break first.")
            return
        sel = self.tbl_breaks.selectionModel().selectedRows() if hasattr(self.tbl_breaks, "selectionModel") else []
        if not sel:
            QMessageBox.information(self, "Select a break", "Select a break in the Breaks table (Reconciliation Workspace) then retry.")
            return
        br = self.m_breaks.get_row(sel[0].row())
        bid = str(br.get("break_id", ""))
        if not bid:
            return
        title, ok = QInputDialog.getText(self, "Evidence", "Evidence title (demo):")
        if not ok or not str(title).strip():
            return
        evid_id = new_id("EVD")
        rec = {
            "evidence_id": evid_id,
            "evidence_type": "Screenshot/Export",
            "title": str(title).strip(),
            "linked_object_type": "BREAK",
            "linked_object_id": bid,
            "owner": self.current_user,
            "ts": now_str(),
            "sha256": f"demo:{evid_id}",
            "retention": "7y",
        }
        self.evidence_registry = pd.concat([self.evidence_registry, pd.DataFrame([rec])], ignore_index=True) if self.evidence_registry is not None else pd.DataFrame([rec])
        # Link on break row
        try:
            cur = self.breaks.loc[self.breaks["break_id"] == bid, "evidence_ref"].astype(str).fillna("")
            prev = cur.iloc[0] if not cur.empty else ""
            link = evid_id if not prev else (prev + ";" + evid_id)
            self.breaks.loc[self.breaks["break_id"] == bid, "evidence_ref"] = link
        except Exception:
            pass
        self.log("EVIDENCE", "BREAK", bid, f"evidence_id={evid_id} title={title}")
        self.refresh_breaks()
        self.refresh_audit()
        self.refresh_close()
        QMessageBox.information(self, "Evidence created", f"Evidence {evid_id} linked to break {bid}.")

    def attach_evidence_to_cycle_demo(self):
        """Creates a cycle-linked evidence placeholder (demo) to illustrate certification evidence pack."""
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        title, ok = QInputDialog.getText(self, "Cycle Evidence", "Evidence title for current cycle (demo):")
        if not ok or not str(title).strip():
            return
        evid_id = new_id("EVD")
        rec = {
            "evidence_id": evid_id,
            "evidence_type": "Close Pack",
            "title": str(title).strip(),
            "linked_object_type": "CYCLE",
            "linked_object_id": self.cycle_id(),
            "owner": self.current_user,
            "ts": now_str(),
            "sha256": f"demo:{evid_id}",
            "retention": "7y",
        }
        self.evidence_registry = pd.concat([self.evidence_registry, pd.DataFrame([rec])], ignore_index=True) if self.evidence_registry is not None else pd.DataFrame([rec])
        self.log("EVIDENCE", "CYCLE", self.cycle_id(), f"evidence_id={evid_id} title={title}")
        self.refresh_audit()
        self.refresh_close()

    def assign_selected_queue_item(self):
        if not hasattr(self, "tbl_queue"):
            return
        sel = self.tbl_queue.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Select an item", "Select a queue item first.")
            return
        row = self.m_queue.get_row(sel[0].row())
        obj_type = str(row.get("object_type", ""))
        obj_id = str(row.get("object_id", ""))
        if obj_type == "BREAK" and obj_id:
            try:
                self.breaks.loc[self.breaks["break_id"] == obj_id, "owner"] = self.current_user
                self.log("ASSIGN", "BREAK", obj_id, f"Assigned to {self.current_user}")
                self.refresh_breaks()
            except Exception:
                pass
        QMessageBox.information(self, "Assigned", f"Assigned: {row.get('item_id')} to {self.current_user}")
        self.refresh_queue()

    # ---------- Actions
    def create_largest_break(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        recon = self.recon_gl_sor()
        if recon.empty:
            QMessageBox.warning(self, "No data", "No reconciliation data.")
            return
        row = recon.sort_values("abs_var", ascending=False).iloc[0].to_dict()
        self.create_break_from_row(row, "GL vs SOR", "Created from dashboard")
        QMessageBox.information(self, "Created", "Break created from largest variance.")

    def create_breaks_from_selected(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        sel = self.tbl_recon.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Select rows", "Select reconciliation rows first.")
            return
        for s in sel:
            self.create_break_from_row(self.m_recon.get_row(s.row()), "GL vs SOR", "")
        QMessageBox.information(self, "Created", f"Created {len(sel)} break(s).")

    def create_break_from_row(self, r: Dict[str, Any], recon_type: str, notes: str):
        bid = new_id("BRK")
        sla_days = 2 if recon_type == "GL vs SOR" else 1
        age_days = 0
        rt = self.route_break(recon_type, str(r.get("product","")), str(r.get("account","")))
        b = {
            "break_id": bid,
            "created_ts": now_str(),
            "as_of": self.filters.as_of,
            "report_family": rt.get("report_family",""),
            "workstream_code": rt.get("workstream_code",""),
            "workstream_name": rt.get("workstream_name",""),
            "owning_team": rt.get("owning_team",""),
            "recon_type": recon_type,
            "legal_entity": self.filters.legal_entity,
            "book": self.filters.book,
            "ccy": self.filters.ccy,
            "account": r.get("account",""),
            "account_name": r.get("account_name",""),
            "product": r.get("product",""),
            "gl_amount": safe_float(r.get("gl_amount"), 0.0),
            "other_amount": safe_float(r.get("sor_amount", r.get("cr360_amount", 0.0)), 0.0),
            "variance": safe_float(r.get("variance"), 0.0),
            "abs_var": abs(safe_float(r.get("variance"), 0.0)),
            "severity": severity_from_amt(r.get("variance"), self.filters.materiality),
            "root_cause": "UNCLASSIFIED",
            "owner": "Recon Analyst",
            "status": "OPEN",
            "sla_days": sla_days,
            "age_days": age_days,
            "sla_status": sla_status(age_days, sla_days),
            "notes": notes,
            "evidence_ref": "",
        }
        self.breaks = pd.concat([self.breaks, pd.DataFrame([b])], ignore_index=True)
        self.log("CREATE", "BREAK", bid, f"{recon_type} | {b['account']} {b['product']} | var={fmt_big(b['variance'])}")
        self.refresh_breaks()
        self.refresh_dashboard()
        self.refresh_audit()

    def open_break(self):
        sel = self.tbl_breaks.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Select break", "Select a break first.")
            return
        bid = self.m_breaks.get_row(sel[0].row()).get("break_id","")
        idxs = self.breaks.index[self.breaks["break_id"] == bid]
        if len(idxs) == 0:
            return
        row = self.breaks.loc[idxs[0]].to_dict()
        dlg = BreakDialog(row, mode=self.mode, read_only=(self.mode == "Auditor"), parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for k, v in dlg.row.items():
                if k in self.breaks.columns:
                    self.breaks.loc[idxs[0], k] = v
            self.log("UPDATE", "BREAK", bid, f"status={dlg.row.get('status')} root={dlg.row.get('root_cause')}")
            self.refresh_breaks()
            self.refresh_dashboard()
            self.refresh_audit()

    def on_var_selected(self, idx: QModelIndex):
        r = self.m_var.get_row(idx.row())
        acc = str(r.get("account",""))
        prod = str(r.get("product",""))
        cur_key = f"{acc}|{prod}|{self.filters.as_of}|{self.filters.legal_entity}|{self.filters.book}|{self.filters.ccy}"
        self._selected_variance_key = cur_key

        self.lbl_var.setText(f"{acc} | {prod} | abs_var={fmt_money(r.get('abs_var',0.0))}")

        # Load existing explanation (current close) if present
        existing = self.variance_expl[self.variance_expl["key"] == cur_key].copy()
        if not existing.empty:
            ex = existing.iloc[0].to_dict()
            # best-effort set reason if it exists in list
            reason = str(ex.get("reason",""))
            if reason:
                self.cmb_reason.setCurrentText(reason) if reason in [self.cmb_reason.itemText(i) for i in range(self.cmb_reason.count())] else None
            # Structured annotation
            if hasattr(self,"cmb_var_ann_type"):
                at = str(ex.get("annotation_type","(None)"))
                self.cmb_var_ann_type.setCurrentText(at if at in [self.cmb_var_ann_type.itemText(i) for i in range(self.cmb_var_ann_type.count())] else "(None)")
            if hasattr(self,"cmb_var_ann_scope"):
                sc = str(ex.get("annotation_scope","Line"))
                self.cmb_var_ann_scope.setCurrentText(sc if sc in [self.cmb_var_ann_scope.itemText(i) for i in range(self.cmb_var_ann_scope.count())] else "Line")
            if hasattr(self,"ed_var_evidence"):
                self.ed_var_evidence.setText(str(ex.get("evidence_ref","")))
            self.txt_var.setPlainText(str(ex.get("narrative","")))
            if hasattr(self, "chk_var_carry"):
                self.chk_var_carry.setChecked(bool(ex.get("carry_forward", True)))
            if hasattr(self, "lbl_var_status"):
                self.lbl_var_status.setText(f"Status: {ex.get('status','DRAFT')}")
            return

        # No current explanation; optionally auto-fill from prior close for user to review
        self.txt_var.setPlainText("")
        if hasattr(self,"cmb_var_ann_type"): self.cmb_var_ann_type.setCurrentText("(None)")
        if hasattr(self,"cmb_var_ann_scope"): self.cmb_var_ann_scope.setCurrentText("Line")
        if hasattr(self,"ed_var_evidence"): self.ed_var_evidence.setText("")
        if hasattr(self, "chk_var_autofill") and self.chk_var_autofill.isChecked():
            prior_key = f"{acc}|{prod}|{self.data['prior']}|{self.filters.legal_entity}|{self.filters.book}|{self.filters.ccy}"
            prior = self.variance_expl[self.variance_expl["key"] == prior_key].copy()
            if not prior.empty:
                ex = prior.iloc[0].to_dict()
                reason = str(ex.get("reason",""))
                if reason:
                    self.cmb_reason.setCurrentText(reason) if reason in [self.cmb_reason.itemText(i) for i in range(self.cmb_reason.count())] else None
                self.txt_var.setPlainText(str(ex.get("narrative","")))
                if hasattr(self, "chk_var_carry"):
                    self.chk_var_carry.setChecked(bool(ex.get("carry_forward", True)))
                if hasattr(self, "lbl_var_status"):
                    self.lbl_var_status.setText("Status: —")
                self.status.showMessage("Loaded prior-close explanation for preview (not saved).", 4500)

    def save_var_expl(self):
        """
        Save Draft (Maker): captures explained variance + carry-forward flag.
        Workflow: DRAFT → SUBMITTED → APPROVED/REJECTED
        """
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can save/edit narratives.")
            return
        if not self._selected_variance_key:
            QMessageBox.information(self, "Select variance", "Select a variance row first.")
            return

        narrative = (self.txt_var.toPlainText() or "").strip()
        if not narrative:
            QMessageBox.warning(self, "Narrative required", "Enter an explanation narrative.")
            return

        existing = self.variance_expl[self.variance_expl["key"] == self._selected_variance_key].copy()
        if not existing.empty:
            st = str(existing.iloc[0].get("status","DRAFT"))
            if st in ("SUBMITTED","APPROVED"):
                QMessageBox.warning(self, "Locked", f"Item is {st}. Maker cannot edit unless it is rejected or recalled.")
                return

        now = now_str()
        row = {
            "key": self._selected_variance_key,
            "as_of": self.filters.as_of,
            "legal_entity": self.filters.legal_entity,
            "book": self.filters.book,
            "ccy": self.filters.ccy,
            "reason": self.cmb_reason.currentText(),
            "annotation_type": (self.cmb_var_ann_type.currentText() if hasattr(self,"cmb_var_ann_type") else "(None)"),
            "annotation_scope": (self.cmb_var_ann_scope.currentText() if hasattr(self,"cmb_var_ann_scope") else "Line"),
            "evidence_ref": (self.ed_var_evidence.text().strip() if hasattr(self,"ed_var_evidence") else ""),
            "narrative": narrative,
            "carry_forward": bool(self.chk_var_carry.isChecked()) if hasattr(self, "chk_var_carry") else True,
            "status": "DRAFT",
            "maker": self.current_user,
            "ts_created": (existing.iloc[0].get("ts_created") if not existing.empty else now),
            "ts_updated": now,
            "submitted_ts": (existing.iloc[0].get("submitted_ts") if not existing.empty else ""),
            "checker": (existing.iloc[0].get("checker") if not existing.empty else ""),
            "approved_ts": (existing.iloc[0].get("approved_ts") if not existing.empty else ""),
            "decision_notes": (existing.iloc[0].get("decision_notes") if not existing.empty else ""),
        }

        self.variance_expl = self.variance_expl[self.variance_expl["key"] != self._selected_variance_key]
        self.variance_expl = pd.concat([self.variance_expl, pd.DataFrame([row])], ignore_index=True)
        if hasattr(self, "lbl_var_status"): self.lbl_var_status.setText("Status: DRAFT")

        self.log("SAVE_DRAFT", "VARIANCE", self._selected_variance_key, f"reason={row['reason']}; carry={row['carry_forward']}; narrative={narrative[:200]}")
        self.refresh_audit()
        QMessageBox.information(self, "Saved", "Draft saved and audit logged.")

    def submit_var_expl(self):
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can submit.")
            return
        if not self._selected_variance_key:
            QMessageBox.information(self, "Select variance", "Select a variance row first.")
            return
        ex = self.variance_expl[self.variance_expl["key"] == self._selected_variance_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No draft", "Save a draft first.")
            return
        st = str(ex.iloc[0].get("status","DRAFT"))
        if st != "DRAFT":
            QMessageBox.warning(self, "Wrong status", f"Only DRAFT can be submitted. Current: {st}")
            return
        # Enforce evidence requirement for selected annotation type
        ann_t = str(ex.iloc[0].get("annotation_type","(None)"))
        ev_ref = str(ex.iloc[0].get("evidence_ref","")).strip()
        rule = ANNOTATION_RULES.get(ann_t, ANNOTATION_RULES["(None)"])
        if rule.get("evidence_required") and not ev_ref:
            QMessageBox.warning(self, "Evidence Required", f"Annotation type {ann_t} requires Evidence Ref before submission.")
            return
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "status"] = "SUBMITTED"
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "submitted_ts"] = now_str()
        if hasattr(self, "lbl_var_status"): self.lbl_var_status.setText("Status: SUBMITTED")
        self.log("SUBMIT", "VARIANCE", self._selected_variance_key, "Submitted for approval")
        self.refresh_audit()
        QMessageBox.information(self, "Submitted", "Submitted to Checker.")

    def approve_var_expl(self):
        if self.mode != "Checker":
            QMessageBox.information(self, "Not permitted", "Only Checker can approve.")
            return
        if not self._selected_variance_key:
            QMessageBox.information(self, "Select variance", "Select a variance row first.")
            return
        ex = self.variance_expl[self.variance_expl["key"] == self._selected_variance_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No item", "No explanation found.")
            return
        st = str(ex.iloc[0].get("status",""))
        if st != "SUBMITTED":
            QMessageBox.warning(self, "Wrong status", f"Only SUBMITTED can be approved. Current: {st}")
            return
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "status"] = "APPROVED"
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "checker"] = self.current_user
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "approved_ts"] = now_str()
        if hasattr(self, "lbl_var_status"): self.lbl_var_status.setText("Status: APPROVED")
        self.log("APPROVE", "VARIANCE", self._selected_variance_key, f"Approved by {self.current_user}")
        self.refresh_audit()
        QMessageBox.information(self, "Approved", "Explanation approved.")

    def reject_var_expl(self):
        if self.mode != "Checker":
            QMessageBox.information(self, "Not permitted", "Only Checker can reject.")
            return
        if not self._selected_variance_key:
            QMessageBox.information(self, "Select variance", "Select a variance row first.")
            return
        ex = self.variance_expl[self.variance_expl["key"] == self._selected_variance_key].copy()
        if ex.empty:
            QMessageBox.warning(self, "No item", "No explanation found.")
            return
        st = str(ex.iloc[0].get("status",""))
        if st != "SUBMITTED":
            QMessageBox.warning(self, "Wrong status", f"Only SUBMITTED can be rejected. Current: {st}")
            return
        note, ok = QInputDialog.getText(self, "Reject explanation", "Reason / notes (required):")
        if not ok or not (note or "").strip():
            return
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "status"] = "REJECTED"
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "checker"] = self.current_user
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "approved_ts"] = now_str()
        self.variance_expl.loc[self.variance_expl["key"] == self._selected_variance_key, "decision_notes"] = note.strip()
        if hasattr(self, "lbl_var_status"): self.lbl_var_status.setText("Status: REJECTED")
        self.log("REJECT", "VARIANCE", self._selected_variance_key, f"{self.current_user}: {note.strip()[:200]}")
        self.refresh_audit()
        QMessageBox.information(self, "Rejected", "Explanation rejected and returned to Maker.")

    def bulk_rollover_var(self):
        """
        Bulk create drafts for current close from PRIOR close explanations where:
          - status == APPROVED
          - carry_forward == True
          - current key does not exist
        """
        if self.mode != "Maker":
            QMessageBox.information(self, "Not permitted", "Only Maker can run bulk rollover.")
            return

        prior_asof = self.data["prior"]
        cur_asof = self.filters.as_of
        prior = self.variance_expl[
            (self.variance_expl["as_of"] == prior_asof) &
            (self.variance_expl["status"] == "APPROVED") &
            (self.variance_expl["carry_forward"] == True)
        ].copy()

        if prior.empty:
            QMessageBox.information(self, "Nothing to rollover", "No prior approved carry-forward explanations found.")
            return

        created = 0
        now = now_str()
        for _, r in prior.iterrows():
            key = str(r["key"])
            parts = key.split("|")
            if len(parts) < 6:
                continue
            acc, prod, _, le, book, ccy = parts[:6]
            new_key = f"{acc}|{prod}|{cur_asof}|{le}|{book}|{ccy}"
            if not self.variance_expl[self.variance_expl["key"] == new_key].empty:
                continue
            row = r.to_dict()
            row.update({
                "key": new_key,
                "as_of": cur_asof,
                "status": "DRAFT",
                "maker": self.current_user,
                "ts_created": now,
                "ts_updated": now,
                "submitted_ts": "",
                "checker": "",
                "approved_ts": "",
                "decision_notes": "",
            })
            self.variance_expl = pd.concat([self.variance_expl, pd.DataFrame([row])], ignore_index=True)
            created += 1

        self.log("BULK_ROLLOVER", "VARIANCE", str(cur_asof), f"Created {created} draft explanations from prior carry-forward")
        self.refresh_audit()
        QMessageBox.information(self, "Bulk rollover complete", f"Created {created} draft explanations for current close.")

    def rollover_var_expl(self):
        """User-controlled rollover: copy prior-close explanation text into the editor for review."""
        if not self._selected_variance_key:
            QMessageBox.information(self, "Select variance", "Select a variance row first.")
            return

        # current key includes current as-of; derive prior key by swapping date token
        parts = self._selected_variance_key.split("|")
        if len(parts) < 6:
            QMessageBox.warning(self, "Key error", "Unexpected variance key format.")
            return

        acc, prod, _, le, book, ccy = parts[:6]
        prior_key = f"{acc}|{prod}|{self.data['prior']}|{le}|{book}|{ccy}"
        prior = self.variance_expl[self.variance_expl["key"] == prior_key].copy()
        if prior.empty:
            QMessageBox.information(self, "No prior explanation", "No prior-close explanation found for this slice.")
            return

        ex = prior.iloc[0].to_dict()
        reason = str(ex.get("reason",""))
        if reason:
            # set current reason if available
            if reason in [self.cmb_reason.itemText(i) for i in range(self.cmb_reason.count())]:
                self.cmb_reason.setCurrentText(reason)
        self.txt_var.setPlainText(str(ex.get("narrative","")))
        if hasattr(self, "chk_var_carry"):
            self.chk_var_carry.setChecked(bool(ex.get("carry_forward", True)))
        self.status.showMessage("Prior explanation rolled into editor (preview). Click 'Save Draft' to persist for current close.", 5500)

    def build_narrative(self):
        rep = self.cmb_report.currentText()
        rating, score, meta = self.confidence()
        feeds_today = self.data["feed"][self.data["feed"]["as_of"] == self.filters.as_of].copy()
        late = feeds_today[feeds_today["status"].isin(["LATE","FAILED"])][["source","status","latency_min","rejects"]].copy()

        ex = self.variance_expl[
            (self.variance_expl["as_of"] == self.filters.as_of) &
            (self.variance_expl["legal_entity"] == self.filters.legal_entity) &
            (self.variance_expl["book"] == self.filters.book) &
            (self.variance_expl["ccy"] == self.filters.ccy)
        ].copy()

        b = self.breaks.copy()
        open_b = b[b["status"].isin(["OPEN","IN REVIEW"])].copy() if not b.empty else pd.DataFrame()

        lines: List[str] = []
        lines.append("Regulatory / Close Narrative Draft")
        lines.append(f"As-of: {self.filters.as_of} | Entity: {self.filters.legal_entity} | Book: {self.filters.book} | CCY: {self.filters.ccy}")
        lines.append(f"Report Context: {rep}")
        lines.append("")
        lines.append("1) Overall Confidence")
        lines.append(f"- Rating: {rating} (Score: {score}/100)")
        lines.append(f"- Material breaks (detected): {meta['material_breaks']} | SLA breaches: {meta['sla_breaches']} | Late feeds: {meta['late_feeds']} | Rejects: {meta['rejects']}")
        lines.append("")
        lines.append("2) Timeliness & Data Quality (BCBS239)")
        if late.empty:
            lines.append("- All critical feeds met SLA.")
        else:
            lines.append("- Exceptions observed:")
            for _, r in late.iterrows():
                lines.append(f"  • {r['source']}: {r['status']} (latency {int(r['latency_min'])} min, rejects {int(r['rejects'])})")
        lines.append("")
        lines.append("3) Reconciliation Exceptions")
        if open_b.empty:
            lines.append("- No open breaks; reconciliation within tolerance.")
        else:
            lines.append(f"- Open breaks: {len(open_b)}")
            top = open_b.sort_values("abs_var", ascending=False).head(5)
            for _, r in top.iterrows():
                lines.append(f"  • {r['break_id']} | {r['account']} {r.get('product','')} | abs_var {fmt_big(r['abs_var'])} | root {r['root_cause']} | SLA {r['sla_status']}")
        lines.append("")
        lines.append("4) Explainability Drivers")
        if ex.empty:
            lines.append("- No saved variance explanations for this slice.")
        else:
            for _, r in ex.sort_values("ts").iterrows():
                lines.append(f"  • {r['reason']}: {r['narrative']}")
        lines.append("")
        lines.append("5) Governance & Controls")
        lines.append("- All actions are audit logged (break lifecycle, certifications, incidents).")
        lines.append("- Mapping changes require justification and maker-checker approval.")
        lines.append("- Auditor mode provides read-only access.")
        self.txt_narr.setPlainText("\n".join(lines))

    def on_line_selected(self, idx: QModelIndex):
        r = self.m_lines.get_row(idx.row())
        line = r.get("report_line","")
        if not line:
            return
        accs = self._accs_by_line.get(line, [])
        gl = self.gl_filtered()
        if gl.empty or not accs:
            self.m_drill.set_df(pd.DataFrame(columns=["account","account_name","product","amount"]))
            return
        drill = gl[gl["account"].isin(accs)].groupby(["account","account_name","product"], as_index=False).agg(amount=("gl_amount","sum"))
        self.m_drill.set_df(drill.sort_values("amount", ascending=False))

    def impact_preview(self):
        sel = self.tbl_lines.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Select line", "Select a report line first.")
            return
        r = self.m_lines.get_row(sel[0].row())
        line = r.get("report_line","")
        rep = self.cmb_report.currentText()
        accs = self._accs_by_line.get(line, [])
        dlg = ImpactPreview(rep, line, accs, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.proposed:
            cid = new_id("CHG")
            self.log("PROPOSE", "MAPPING_CHANGE", cid, f"report={rep} line={line} accs={accs} just='{dlg.justification}'")
            self.refresh_audit()
            QMessageBox.information(self, "Proposed", f"Change proposed and audit logged: {cid}")

    def certify_line(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        sel = self.tbl_lines.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Select line", "Select a line to certify.")
            return
        r = self.m_lines.get_row(sel[0].row())
        line = r.get("report_line","")
        rep = self.cmb_report.currentText()
        self.log("CERTIFY", "REPORT_LINE", f"{rep}-{line}", f"Certified as_of={self.filters.as_of}")
        self.refresh_audit()
        QMessageBox.information(self, "Certified", "Certified (audit logged).")

    def lock_report(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        rep = self.cmb_report.currentText()
        self.log("LOCK", "REPORT", rep, f"Locked as_of={self.filters.as_of}")
        self.refresh_audit()
        QMessageBox.information(self, "Locked", "Locked (audit logged).")

    def rerun_feed(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        src = (self.cmb_feed.currentText() or "").strip()
        if not src:
            return
        self.log("RERUN", "FEED", src, f"Rerun requested as_of={self.filters.as_of}")
        self.refresh_audit()
        QMessageBox.information(self, "Logged", "Rerun request logged.")

    def create_incident(self):
        if self.mode == "Auditor":
            QMessageBox.information(self, "Read-only", "Auditor mode is read-only.")
            return
        src = (self.cmb_feed.currentText() or "").strip() or "(none)"
        inc = new_id("INC")
        self.log("CREATE", "INCIDENT", inc, f"Incident for feed={src} as_of={self.filters.as_of}")
        self.refresh_audit()
        QMessageBox.information(self, "Incident", f"Incident created: {inc}")

    def copy_exec_summary(self):
        rating, score, meta = self.confidence()
        txt = (
            "Executive Summary\n"
            f"As-of: {self.filters.as_of} | Entity: {self.filters.legal_entity} | Book: {self.filters.book} | CCY: {self.filters.ccy}\n"
            f"Confidence: {rating} ({score}/100)\n"
            f"Material breaks: {meta['material_breaks']} | SLA breaches: {meta['sla_breaches']} | Late feeds: {meta['late_feeds']} | Rejects: {meta['rejects']}\n"
        )
        QGuiApplication.clipboard().setText(txt)
        QMessageBox.information(self, "Copied", "Executive summary copied to clipboard.")

    def reset_demo(self):
        self.data = seed_data()
        self.breaks = self.breaks.iloc[0:0].copy()
        self.audit = self.audit.iloc[0:0].copy()
        self.variance_expl = self.variance_expl.iloc[0:0].copy()
        self.refresh_all()
        QMessageBox.information(self, "Reset", "Demo reset completed.")

    def advance_aging(self):
        if self.breaks.empty:
            QMessageBox.information(self, "Nothing to age", "No breaks exist yet.")
            return
        self.breaks["age_days"] = self.breaks["age_days"].apply(lambda x: int(x) + 1)
        self.breaks["sla_status"] = self.breaks.apply(lambda r: sla_status(int(r["age_days"]), int(r["sla_days"])), axis=1)
        self.log("SIMULATE", "SYSTEM", "AGING+1", "Advanced break aging by 1 day")
        self.refresh_all()

    def export_current_table(self):
        if self.mode == "Auditor":
            # auditors can still export in many orgs, but keep it strict here
            QMessageBox.information(self, "Read-only", "Export disabled in Auditor mode for this prototype.")
            return

        # map current page to primary table/model
        idx = self.stack.currentIndex()
        mapping = {
            0: ("dashboard_top_breaks.csv", self.m_top._df),
            1: ("feeds.csv", self.m_feed._df),
            2: ("gl_explorer.csv", self.m_gl._df),
            3: ("recon.csv", self.m_recon._df),
            4: ("variance.csv", self.m_var._df),
            5: ("report_lines.csv", self.m_lines._df),
            6: ("mapping.csv", self.m_map._df),
            7: ("audit.csv", self.m_audit._df),
        }
        default_name, df = mapping.get(idx, ("export.csv", pd.DataFrame()))
        if df is None or df.empty:
            QMessageBox.information(self, "Nothing to export", "Current view has no rows.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default_name, "CSV Files (*.csv)")
        if not path:
            return
        df.to_csv(path, index=False)
        self.log("EXPORT", "CSV", path, f"rows={len(df)}")
        QMessageBox.information(self, "Exported", f"Saved: {path}")

# ----------------------------
# Entrypoint
# ----------------------------

def main():
    app = QApplication(sys.argv)
    # Light, native demo look
    try:
        app.setStyle("Windows")
    except Exception:
        pass
    app.setPalette(app.style().standardPalette())
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
