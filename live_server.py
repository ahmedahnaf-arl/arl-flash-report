"""
ARL Live Flash Report Server
Usage: python live_server.py [--port PORT]
Auto-detects T-1 date, queries DWH live, renders HTML with Canvas charts.
"""
import http.server
import json
import os
import sys
import re
from html import escape as html_escape
import threading
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from socketserver import ThreadingMixIn

PORT = 8765
HOST = "0.0.0.0"  # Bind to all interfaces for LAN + tunnel access
ROOT = Path(__file__).parent.resolve()

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=203.202.241.211,1433;"
    "DATABASE=DWH;UID=mcp_user;PWD=iAOS@35o997;Encrypt=no;TrustServerCertificate=yes;"
    "Connection Timeout=30;"
)

def fmt(n, d=2):
    if n is None: return "—"
    try:
        s = f"{n:,.{d}f}"
        return s
    except (ValueError, TypeError):
        return "—"

def pct(a, b):
    if not b or b == 0: return None
    return ((a / b) - 1) * 100

def js_sig(v):
    if v is None: return "'N/A'"
    if v >= 20: return "'Strong +'"
    if v >= 0: return "'Positive'"
    if v >= -15: return "'Neutral'"
    if v >= -30: return "'Weak'"
    return "'Negative'"

def js(obj):
    if isinstance(obj, dict):
        return "{" + ",".join(f"{js(k)}:{js(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(js(i) for i in obj) + "]"
    if isinstance(obj, str):
        return f"'{obj}'"
    if obj is None:
        return "null"
    return str(obj)

class _ERPCursor:
    """Cursor backed by the live ERP (enterprise-api-gateway), not the DWH."""
    def __init__(self, erp_query):
        self._erp_query = erp_query
        self._rows = []

    def execute(self, sql):
        # DWH table names (schema 'DWH.' + 'Arc' suffix) -> ERP table names
        self._rows = self._erp_query(sql.replace("DWH.", "").replace("Arc", ""))

    def fetchall(self):
        return [tuple(r) for r in self._rows]

    def fetchone(self):
        return tuple(self._rows[0]) if self._rows else None


class _ERPConn:
    def __init__(self, erp_query):
        self._erp_query = erp_query

    def cursor(self):
        return _ERPCursor(self._erp_query)

    def close(self):
        pass


def get_conn():
    # Primary: live ERP via enterprise-api-gateway (the DWH copy is unreliable).
    # Preflight the gateway so an outage fails in seconds; otherwise fall back to DWH.
    try:
        import erp_client
        if erp_client.erp_available():
            return _ERPConn(erp_client.erp_query)
        print("ERP gateway unreachable — falling back to DWH.")
    except Exception as exc:
        print(f"ERP client unavailable ({exc.__class__.__name__}) — falling back to DWH.")
    # Cloud mode: DWH creds from environment (self-hosted runner uses pymssql)
    if os.environ.get("DWH_SERVER"):
        import pymssql
        return pymssql.connect(
            server=os.environ["DWH_SERVER"],
            port=int(os.environ.get("DWH_PORT", "1433")),
            user=os.environ["DWH_USER"],
            password=os.environ["DWH_PASSWORD"],
            database="DWH",
            timeout=120,
            login_timeout=30,
        )
    # Local mode: ODBC driver
    import pyodbc
    conn = pyodbc.connect(CONN_STR)
    conn.timeout = 120
    return conn

def detect_report_date():
    """Always return T-1 (yesterday) for a complete-day report."""
    return date.today() - timedelta(days=1)

def get_report_data(report_date):
    """Run ALL DWH queries and return structured data."""
    rd = report_date
    de = rd.day  # days elapsed
    dm = 31  # Will auto-detect, but Aug = 31
    mf = round(de / dm, 10)

    # Determine days in month
    import calendar
    dm = calendar.monthrange(rd.year, rd.month)[1]
    de = rd.day
    mf = round(de / dm, 10)

    # Previous month for MoM
    if rd.month == 1:
        prev_month = 12
        prev_year = rd.year - 1
    else:
        prev_month = rd.month - 1
        prev_year = rd.year

    # Same period last year
    yoy_year = rd.year - 1

    # FY start
    if rd.month >= 7:
        fy_year = rd.year
    else:
        fy_year = rd.year - 1

    rd_str = rd.strftime("%Y-%m-%d")
    next_str = (rd + timedelta(days=1)).strftime("%Y-%m-%d")
    month_start = rd.strftime("%Y-%m-01")
    prev_start = f"{prev_year}-{prev_month:02d}-01"
    prev_end = (date(prev_year, prev_month, 1) + timedelta(days=de)).strftime("%Y-%m-%d")
    yoy_start = f"{yoy_year}-{rd.month:02d}-01"
    yoy_end = (date(yoy_year, rd.month, 1) + timedelta(days=de)).strftime("%Y-%m-%d")
    fy_start = f"{fy_year}-07-01"
    cy_start = f"{rd.year}-01-01"

    conn = get_conn()
    c = conn.cursor()

    # 1. Revenue sub-schedule (net of returns; SBU 0 = unallocated cement -> ACCL 58)
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{rd_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS daily,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{(rd - timedelta(days=1)).strftime("%Y-%m-%d")}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS dod,
          SUM(CASE WHEN j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mtd,
          SUM(CASE WHEN j.dteTransactionDate>='{prev_start}' AND j.dteTransactionDate<'{prev_end}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mom,
          SUM(CASE WHEN j.dteTransactionDate>='{yoy_start}' AND j.dteTransactionDate<'{yoy_end}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS yoy,
          SUM(CASE WHEN j.dteTransactionDate>='{fy_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS fy_ytd,
          SUM(CASE WHEN j.dteTransactionDate>='{cy_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS cy_ytd
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END ORDER BY sbu
    """)
    gl_rows = {row[0]: {
        'd': round(float(row[1]), 6) if row[1] else 0.0,
        'dod': round(float(row[2]), 6) if row[2] else 0.0,
        'm': round(float(row[3]), 6) if row[3] else 0.0,
        'mom': round(float(row[4]), 6) if row[4] else 0.0,
        'yoy': round(float(row[5]), 6) if row[5] else 0.0,
        'fy': round(float(row[6]), 6) if row[6] else 0.0,
        'cy': round(float(row[7]), 6) if row[7] else 0.0,
    } for row in c.fetchall()}

    # 2. GL 3010005 freight SBUs (net)
    c.execute(f"""
        SELECT j.intSBUId,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{rd_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS daily,
          SUM(CASE WHEN CAST(j.dteTransactionDate AS DATE)='{(rd - timedelta(days=1)).strftime("%Y-%m-%d")}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS dod,
          SUM(CASE WHEN j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}' THEN -j.numAmount/10000000.0 ELSE 0 END) AS mtd
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode='3010005' AND j.isActive=1
          AND j.intSBUId IN (64,79,80,81,88,110)
          AND j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}'
        GROUP BY j.intSBUId ORDER BY j.intSBUId
    """)
    fr_d = {}; fr_m = {}
    for row in c.fetchall():
        fr_d[row[0]] = round(float(row[1]), 6) if row[1] else 0.0
        fr_m[row[0]] = round(float(row[3]), 6) if row[3] else 0.0

    # 3. Reconciliation totals (net of returns)
    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010001' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g1all = round(c.fetchone()[0] or 0, 6)

    # Excluded from the report SBU scope: entities that are not tracker rows.
    # 77=DyTCL, 86=HRML, 87=FAL, 119=unmapped, 123=AENL.
    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010001' AND isActive=1 AND intSBUId IN (65,68,75,76,78,89,92,95,112,119) AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    excl = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010005' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g5all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010002' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g2all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010002' AND isActive=1 AND intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119) AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g2report = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010006' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g6all = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010006' AND isActive=1 AND intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119) AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g6report = round(c.fetchone()[0] or 0, 6)

    c.execute(f"SELECT SUM(-numAmount)/10000000.0 FROM DWH.fin.tblAccountingJournalArc WHERE strGeneralLedgerCode='3010004' AND isActive=1 AND dteTransactionDate>='{month_start}' AND dteTransactionDate<'{next_str}'")
    g4all = round(c.fetchone()[0] or 0, 6)

    # 4. Daily volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate='{rd_str}' AND h.intBusinessAreaId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY h.intBusinessAreaId
    """)
    dv = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 5. MTD volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate>='{month_start}' AND h.dteDeliveryDate<'{next_str}' AND h.intBusinessAreaId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY h.intBusinessAreaId
    """)
    mv = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 6. MoM volumes
    c.execute(f"""
        SELECT h.intBusinessAreaId,
          SUM(CASE WHEN ri.strUOM='Kilogram' THEN ri.numQuantity/1000.0 WHEN ri.strUOM IN ('Ton','Metric Ton') THEN ri.numQuantity WHEN ri.strUOM='Litre' THEN ri.numQuantity/1000.0 ELSE ri.numQuantity END)
        FROM DWH.sms.tblDeliveryHeaderArc h
        JOIN DWH.sms.tblDeliveryRowArc ri ON h.intDeliveryId=ri.intDeliveryId
        JOIN DWH.itm.tblItemArc i ON ri.intItemId=i.intItemId
        WHERE h.dteDeliveryDate>='{prev_start}' AND h.dteDeliveryDate<'{prev_end}' AND h.intBusinessAreaId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY h.intBusinessAreaId
    """)
    mov = {row[0]: round(row[1], 2) for row in c.fetchall() if row[1]}

    # 7. ABSL channel split
    c.execute(f"""
        SELECT h.intDistributionChannelId, SUM(h.numTotalNetValue)/10000000.0
        FROM DWH.sms.tblDeliveryHeaderArc h
        WHERE h.dteDeliveryDate>='{month_start}' AND h.dteDeliveryDate<'{next_str}'
          AND h.intBusinessAreaId=98 AND h.intDistributionChannelId IN (111,128,129)
        GROUP BY h.intDistributionChannelId
    """)
    asphalt_rev = 0; benzol_rev = 0
    for row in c.fetchall():
        if row[0] == 111: asphalt_rev = row[1]
        elif row[0] in (128, 129): benzol_rev += row[1]
    total_del = asphalt_rev + benzol_rev
    asphalt_ratio = round(asphalt_rev / total_del, 4) if total_del > 0 else 0.74
    benzol_ratio = round(benzol_rev / total_del, 4) if total_del > 0 else 0.26

    # 8. Daily trends (GL revenue sub-schedule, net)
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu, CAST(j.dteTransactionDate AS DATE) AS dt, SUM(-j.numAmount)/10000000.0 AS daily_rev
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}'
          AND j.intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END, CAST(j.dteTransactionDate AS DATE)
        ORDER BY sbu, dt
    """)
    td = [{'d': str(row[1]), 's': row[0], 'v': round(row[2], 6)} for row in c.fetchall()]

    # 8b. Daily revenue in BDT (actual, for expanded detail table)
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu, CAST(j.dteTransactionDate AS DATE) AS dt, SUM(-j.numAmount) AS daily_rev_bdt
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.dteTransactionDate>='{month_start}' AND j.dteTransactionDate<'{next_str}'
          AND j.intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END, CAST(j.dteTransactionDate AS DATE)
        ORDER BY sbu, dt
    """)
    td_bdt = {}
    for row in c.fetchall():
        td_bdt.setdefault(row[0], {})[str(row[1])] = float(row[2] or 0)

    # 8c. Sales order counts (number of orders, actual)
    c.execute(f"""
        SELECT CASE WHEN intSUBID=0 THEN 58 ELSE intSUBID END AS sbu, CAST(dteSalesOrderDate AS DATE) AS d, COUNT(*) AS orders
        FROM DWH.oms.tblSalesOrderHeaderArc
        WHERE dteSalesOrderDate >= '{month_start}' AND dteSalesOrderDate < '{next_str}'
          AND intSUBID NOT IN (65,68,75,76,78,89,92,95,112,119) AND isActive = 1
        GROUP BY CASE WHEN intSUBID=0 THEN 58 ELSE intSUBID END, CAST(dteSalesOrderDate AS DATE)
        ORDER BY sbu, d
    """)
    ord_td = [{'d': str(row[1]), 's': row[0], 'c': int(row[2])} for row in c.fetchall()]
    ord_mtd = {}
    ord_daily = {}
    for _t in ord_td:
        _s = _t['s']
        ord_mtd[_s] = ord_mtd.get(_s, 0) + _t['c']
        if _t['d'] == rd_str:
            ord_daily[_s] = ord_daily.get(_s, 0) + _t['c']

    # 8d. FY daily revenue history (Cr) per SBU — for date-range filter
    c.execute(f"""
        SELECT CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END AS sbu, CAST(j.dteTransactionDate AS DATE) AS dt, SUM(-j.numAmount)/10000000.0 AS daily_rev
        FROM DWH.fin.tblAccountingJournalArc j
        WHERE j.strGeneralLedgerCode IN ('3010001','3010002','3010005','3010006') AND j.isActive=1
          AND j.dteTransactionDate>='{fy_start}' AND j.dteTransactionDate<'{next_str}'
          AND j.intSBUId NOT IN (65,68,75,76,78,89,92,95,112,119)
        GROUP BY CASE WHEN j.intSBUId=0 THEN 58 ELSE j.intSBUId END, CAST(j.dteTransactionDate AS DATE)
        ORDER BY sbu, dt
    """)
    hist_rev = {}
    for row in c.fetchall():
        hist_rev.setdefault(row[0], {})[str(row[1])] = round(float(row[2] or 0), 6)

    # 8e. FY daily sales-order history per SBU — for date-range filter
    c.execute(f"""
        SELECT CASE WHEN intSUBID=0 THEN 58 ELSE intSUBID END AS sbu, CAST(dteSalesOrderDate AS DATE) AS d, COUNT(*) AS orders
        FROM DWH.oms.tblSalesOrderHeaderArc
        WHERE dteSalesOrderDate >= '{fy_start}' AND dteSalesOrderDate < '{next_str}'
          AND intSUBID NOT IN (65,68,75,76,78,89,92,95,112,119) AND isActive = 1
        GROUP BY CASE WHEN intSUBID=0 THEN 58 ELSE intSUBID END, CAST(dteSalesOrderDate AS DATE)
        ORDER BY sbu, d
    """)
    hist_ord = {}
    for row in c.fetchall():
        hist_ord.setdefault(row[0], {})[str(row[1])] = int(row[2])

    # October 2026 forecast targets from the October Revenue tracker. Do not
    # carry a prior month's targets into a later reporting period.
    if rd.year == 2026 and rd.month == 10:
        targets = {
            'APFIL': 21.59775, 'AEL': 147.0649584, 'ACCL': 182.112,
            'ARMCL': 47.4212522, 'BTL_Coal': 2.12, 'iBOS': 2.69295,
            'BPL': 0.10, 'AITL': 1.00, 'NTL': 50.00,
            'ABSL': 8.6044392, 'ACL': 8.73656, 'AIL': 119.30805,
            'AAFL': 110.8065204, 'ALEL': 23.8562654, 'AAIL': 4.5079216,
            'ATL': 1.40, 'AEFL': 0.50, 'ABL': 2.025, 'AMXL': 4.65,
            'NJL': 0.2984, 'AMPL': 0.50,
            'AASL': 1.3953092, 'ALL': 6.56462, 'ALCL': 8.50, 'SATHS': 0.0,
        }
    else:
        targets = {}

    # 10. SBU Map
    sbu_map = {19: 'APFIL', 36: 'AEL', 58: 'ACCL', 64: 'ASLL', 69: 'ARMCL', 72: 'BTL_Coal',
               77: 'DyTCL', 79: 'AOCN', 80: 'ASLL-1', 81: 'AMTL', 82: 'iBOS', 83: 'BPL',
               84: 'AITL', 86: 'HRML', 87: 'FAL', 88: 'ASeLL', 91: 'NTL', 98: 'ABSL',
               99: 'ACL', 102: 'AIL', 103: 'ALL', 109: 'AAFL', 110: 'ASeLLC', 111: 'SATHS',
               114: 'ALEL', 115: 'AAIL', 116: 'ALCL', 118: 'ATL', 120: 'AEFL', 122: 'AASL',
               123: 'AENL', 124: 'ABL', 126: 'ACEL', 128: 'AMXL', 129: 'NJL', 132: 'AMPL'}

    conn.close()

    # Freight defaults
    for sbu_id in [64, 79, 80, 81, 88, 110]:
        if sbu_id not in fr_d:
            fr_d[sbu_id] = 0
            fr_m[sbu_id] = 0
        if sbu_id not in gl_rows:
            gl_rows[sbu_id] = {'d': 0, 'dod': 0, 'm': 0, 'mom': 0, 'yoy': 0, 'fy': 0, 'cy': 0}

    # No FX conversion: fin.tblAccountingJournal.numAmount is already the BDT
    # ledger amount. Applying a USD/AED multiplier here multiplied real BDT
    # postings (e.g. ASLL-1 1.41 Cr -> 173.9 Cr) and inflated freight ~6x.
    FX_RATES = {}
    fx_extra = 0.0  # extra BDT to add to full-GL freight total so reconciliation stays consistent
    for _sbu, _rate in FX_RATES.items():
        _g = gl_rows.get(_sbu)
        if _g:
            for _k in ('d', 'dod', 'm', 'mom', 'yoy', 'fy', 'cy'):
                _g[_k] = round(float(_g[_k] or 0) * _rate, 6)
        _raw_m = float(fr_m.get(_sbu, 0) or 0)
        fr_d[_sbu] = round(float(fr_d.get(_sbu, 0) or 0) * _rate, 6)
        fr_m[_sbu] = round(_raw_m * _rate, 6)
        fx_extra += _raw_m * (_rate - 1)
        for _t in td:
            if _t['s'] == _sbu:
                _t['v'] = round(float(_t['v'] or 0) * _rate, 6)
        if _sbu in td_bdt:
            for _d in td_bdt[_sbu]:
                td_bdt[_sbu][_d] = round(td_bdt[_sbu][_d] * _rate, 2)
        if _sbu in hist_rev:
            for _d in hist_rev[_sbu]:
                hist_rev[_sbu][_d] = round(hist_rev[_sbu][_d] * _rate, 6)
    g5all = round(float(g5all) + fx_extra, 6)

    # Compute reconciliation
    rpt_gl1 = round(float(g1all) - float(excl), 6)
    rpt_frt = round(sum(float(v) for v in fr_m.values()), 6)
    rpt_tot = round(rpt_gl1 + float(g2report) + rpt_frt + float(g6report), 6)
    full_rev_tot = round(float(g1all) + float(g2all) + float(g5all) + float(g6all), 6)
    full_tot = round(full_rev_tot + float(g4all), 6)
    gap = round(full_tot - rpt_tot, 6)

    month_pct = round(mf * 100, 1)
    period = f"{rd.strftime('%b')} 1–{de}"
    day_label = f"{de}/{dm}"

    return {
        'report_date': rd,
        'rd_str': rd_str,
        'de': de, 'dm': dm, 'mf': mf, 'month_pct': month_pct,
        'period': period, 'day_label': day_label,
        'gl': gl_rows, 'fr_d': fr_d, 'fr_m': fr_m,
        'dv': dv, 'mv': mv, 'mov': mov, 'td': td,
        'td_bdt': td_bdt, 'ord_td': ord_td, 'ord_mtd': ord_mtd, 'ord_daily': ord_daily,
        'hist_rev': hist_rev, 'hist_ord': hist_ord,
        'g1all': g1all, 'excl': excl, 'g5all': g5all, 'g2all': g2all, 'g2report': g2report,
        'g6all': g6all, 'g6report': g6report, 'g4all': g4all, 'full_rev_tot': full_rev_tot,
        'rpt_gl1': rpt_gl1, 'rpt_frt': rpt_frt, 'rpt_tot': rpt_tot,
        'full_tot': full_tot, 'gap': gap,
        'asphalt': asphalt_ratio, 'benzol': benzol_ratio,
        'targets': targets, 'sbu_map': sbu_map,
    }

OCTOBER_TRACKER_ROWS = [
    ('', 'G2G (Bongo & MTS & Shipping BADC/BCIC)', 755799665, 687623989, 'Composite tracker line; no single ERP SBU ID/value ties to this group. Tracker is authoritative.'),
    ('ACCL', 'Akij Cement Company Ltd.', 1694025365, 1821120000, 'ERP SBU 58: 169.402537 Cr — matches.'),
    ('AIL', 'Akij Ispat Ltd.', 1053155498, 1193080500, 'ERP SBU 102: 105.315550 Cr — matches.'),
    ('APFIL', 'Akij Poly Fibre Industries Ltd.', 228334304, 215977500, 'ERP SBU 19: 22.833430 Cr — matches.'),
    ('ARMCL', 'Akij Ready Mix Concrete Ltd.', 418710796, 474212522, 'ERP SBU 69: 41.871080 Cr — matches.'),
    ('ABSL', 'Akij Building Solutions — Asphalt', 29091772, 59000000, 'ERP SBU 98 parent total: 4.496119 Cr across both tracker lines; tracker split retained.'),
    ('ABSL', 'Akij Building — Lube-Oil & Bitumen', 15869420, 27044392, 'Included in ERP SBU 98 parent total above; tracker line retained.'),
    ('AEL', 'Akij Essentials Ltd. — Manufacturing', 1266867098, 1430600000, 'ERP SBU 36 parent total: 130.630217 Cr across Manufacturing, Export and Trading — matches combined.'),
    ('', 'Akij Essentials Ltd. — Export', 27711572, 28249584, 'Included in ERP SBU 36 parent total above; tracker line retained.'),
    ('', 'Akij Essentials Ltd. — Trading', 11723500, 11800000, 'Included in ERP SBU 36 parent total above; tracker line retained.'),
    ('BTL', 'Bongo & Daily — Coal', 26817518, 21200000, 'ERP SBU 72: 2.658520 Cr; tracker is higher by 0.023232 Cr and is used.'),
    ('ACL', 'Akij Commodities Ltd. — Cotton', 10494931, 79365600, 'ERP SBU 99 parent total: 1.877223 Cr across Cotton, F&B and Fruits — matches combined.'),
    ('ACL', 'Akij Commodities Ltd. — F&B', 8277302, 8000000, 'Included in ERP SBU 99 parent total above; tracker line retained.'),
    ('', 'Akij Commodities Ltd. — Fruits', 0, 0, 'Included in ERP SBU 99 parent total above; zero actual.'),
    ('ASLL', 'Akij Shipping Line Ltd. (group total)', 3983649653, 2840946250, 'ERP shipping roll-up (SBU 64, 79, 80, 81, 88, 110, BDT ledger): 84.315621 Cr. Tracker is authoritative.'),
    ('ALEL', 'Akij Light Engineering Ltd.', 250204758, 238562654, 'ERP SBU 114: 25.020476 Cr — matches.'),
    ('ATL', 'Akij Telecom Ltd.', 18042401, 14000000, 'ERP SBU 118: 1.804240 Cr — matches.'),
    ('AITL', 'Akij Infotech Ltd.', 1774105, 10000000, 'ERP SBU 84: 0.177411 Cr — matches.'),
    ('BPL', 'Blue Pill Limited', 1748875, 1000000, 'ERP SBU 83: 0.174888 Cr — matches.'),
    ('iBOS', 'iBOS Limited', 23634103, 26929500, 'ERP SBU 82: 2.363410 Cr — matches.'),
    ('AAFL', 'Akij Agro Feed Ltd.', 1160864376, 1108065204, 'ERP SBU 109: 116.086438 Cr — matches.'),
    ('ABL', 'Akij Breeders Ltd.', 21539580, 20250000, 'ERP SBU 124: 2.153958 Cr — matches.'),
    ('NTL', 'Nobayon Traders Ltd.', 442058586, 500000000, 'ERP SBU 91: 44.205859 Cr — matches.'),
    ('AASL', 'Akij Air Service Ltd.', 2745676, 13953092, 'ERP SBU 122: 0.274568 Cr — matches.'),
    ('ALL', 'Akij Logistics Ltd.', 73705531, 65646200, 'ERP SBU 103: 8.098586 Cr; tracker is lower by 0.728033 Cr and is used.'),
    ('AMXL', 'Akij Movex Ltd.', 46747459, 46500000, 'ERP SBU 128: 4.674746 Cr — matches.'),
    ('ALCL', 'AKIJ LifeCare Ltd.', 85680122, 85000000, 'ERP SBU 116: 8.568012 Cr — matches.'),
    ('AAIL', 'Akij Automobile Industries Ltd.', 50106400, 45079216, 'ERP SBU 115: 5.010640 Cr — matches.'),
    ('NJL', 'Nextjobz Ltd.', 3040165, 2984000, 'ERP SBU 129: 0.304017 Cr — matches.'),
    ('AEFL', 'Akij Electrofab Ltd.', 4881750, 5000000, 'ERP SBU 120: 0.488175 Cr — matches.'),
    ('ACEL', 'AKIJ Consumer Electronics Ltd.', 9975288, 13000000, 'ERP SBU 126: 0.997529 Cr — matches.'),
    ('AMPL', 'Akij Mediplex Ltd.', 5450020, 5000000, 'ERP SBU 132: 0.545002 Cr — matches.'),
    ('SATHS', 'South Asian Travel & Hajj Service', 0, 0, 'ERP SBU 111: zero revenue; retained because it is in the tracker.'),
]


def build_tracker_html(data):
    """Month-end portal view sourced directly from the October Revenue tracker."""
    actual_total = sum(row[2] for row in OCTOBER_TRACKER_ROWS)
    forecast_total = sum(row[3] for row in OCTOBER_TRACKER_ROWS)
    if actual_total != 11732727589 or forecast_total != 11099190203 or len(OCTOBER_TRACKER_ROWS) != 33:
        raise ValueError('October Revenue tracker snapshot failed its control totals.')

    body_rows = []
    for sl, (code, label, actual, forecast, erp_note) in enumerate(OCTOBER_TRACKER_ROWS, 1):
        actual_cr = actual / 10000000
        forecast_cr = forecast / 10000000
        achievement = (actual / forecast * 100) if forecast else 0.0
        body_rows.append(
            '<tr>'
            f'<td>{sl}</td><td>{html_escape(code) if code else "—"}</td>'
            f'<td>{html_escape(label)}</td><td class="num">{actual:,.0f}</td>'
            f'<td class="num">{actual_cr:,.4f}</td><td class="num">{forecast:,.0f}</td>'
            f'<td class="num">{forecast_cr:,.4f}</td><td class="num">{achievement:.1f}%</td>'
            f'<td>{html_escape(erp_note)}</td></tr>'
        )
    body_rows.append(
        '<tr class="total"><td></td><td></td><td>Tracker Total</td>'
        f'<td class="num">{actual_total:,.0f}</td><td class="num">{actual_total / 10000000:,.4f}</td>'
        f'<td class="num">{forecast_total:,.0f}</td><td class="num">{forecast_total / 10000000:,.4f}</td>'
        f'<td class="num">{actual_total / forecast_total * 100:.1f}%</td><td>Sheet totals verified against all 33 lines.</td></tr>'
    )
    report_date = 'October 31, 2026'
    rows_html = '\n'.join(body_rows)
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"><title>ARL October 2026 Revenue Actuals — Tracker Source</title>
<style>
:root{color-scheme:dark;--bg:#0f172a;--panel:#1e293b;--line:#334155;--text:#e2e8f0;--muted:#94a3b8;--cyan:#38bdf8;--green:#86efac;--amber:#fbbf24;--red:#fca5a5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1600px;margin:auto;padding:24px}h1{margin:0;color:#f8fafc;font-size:1.75rem}h2{color:var(--cyan);margin:0 0 12px}a{color:var(--cyan)}.meta,.muted{color:var(--muted)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;text-align:center}.card .label{color:var(--muted);font-size:.85rem;text-transform:uppercase}.card .value{font-size:1.7rem;font-weight:750;margin:6px 0}.value.green{color:var(--green)}.controls{display:flex;gap:10px;margin-bottom:12px}.controls input{width:min(400px,100%);padding:10px;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:7px}
.table-wrap{overflow:auto;max-height:72vh}table{width:100%;border-collapse:collapse;min-width:1250px}th,td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{position:sticky;top:0;background:#111d32;color:#cbd5e1;text-align:left;z-index:1}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.total{font-weight:750;background:#14253b}.erp-note{min-width:330px;color:#cbd5e1}.badge{display:inline-block;padding:3px 8px;border-radius:99px;background:#123c35;color:var(--green);font-size:.8rem}.warning{border-left:4px solid var(--amber)}.source{font-size:.9rem}.source-note{color:var(--muted)}#gate{position:fixed;inset:0;z-index:20;display:grid;place-items:center;background:#050b16ee;padding:16px}#gate[hidden]{display:none}.gate-card{width:min(390px,100%);background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px}.gate-card input,.gate-card button{width:100%;padding:11px;margin-top:10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--text)}.gate-card button{background:var(--cyan);color:#082f49;font-weight:700;cursor:pointer}#login-error{color:var(--red);margin-top:8px}
.portal-nav{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}.portal-nav a{padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:#cbd5e1;text-decoration:none;font-size:.92rem;font-weight:600}.portal-nav a:hover{border-color:var(--cyan);color:#f8fafc}.portal-nav a.active{background:var(--cyan);border-color:var(--cyan);color:#082f49}
@media(max-width:640px){main{padding:12px}h1{font-size:1.4rem}.panel{padding:12px}}
</style></head><body>
<div id="gate"><div class="gate-card"><h2>ARL Flash Report Sign In</h2><input id="user" autocomplete="username" placeholder="Username"><input id="pass" autocomplete="current-password" type="password" placeholder="Password"><button id="signin">Sign In</button><div id="login-error"></div></div></div>
<main>
<nav class="portal-nav"><a href="index.html">1 · ERP Flash Report</a><a class="active" href="october-tracker.html">2 · October Revenue Tracker</a></nav>
<header><h1>AKIJ RESOURCE — October SBU Revenue Actuals</h1>
<div class="meta">Report Date: __REPORT_DATE__ | Period: October 1–31, 2026 | Actuals source: October Revenue tracker · ERP MCP cross-check</div></header>
<section class="cards">
<div class="card"><div class="label">Actual Revenue</div><div class="value">__ACTUAL_CR__ Cr</div><div class="muted">BDT __ACTUAL_BDT__</div></div>
<div class="card"><div class="label">Forecast Revenue</div><div class="value">__FORECAST_CR__ Cr</div><div class="muted">BDT __FORECAST_BDT__</div></div>
<div class="card"><div class="label">Forecast Achievement</div><div class="value green">__ACHIEVEMENT__%</div><div class="muted">Actual ÷ forecast</div></div>
<div class="card"><div class="label">Tracker Lines</div><div class="value">33</div><div class="muted">All rows from Sheet1</div></div>
</section>
<section class="panel source"><b>Source of portal actuals:</b> Column K, “Actual Sales Revenue … As per Sub-Schedule,” from the <a href="https://docs.google.com/spreadsheets/d/16sYaGTlSWXTquoGf-ZI_e-Cr8VV-tFUEJ7FrvgxzxRA/edit?gid=0#gid=0" target="_blank" rel="noopener">October Revenue spreadsheet</a>. Forecasts use column J. Each row is shown exactly at tracker-line level; AEL, ACL, ABSL and the ASLL group are not split using ERP-derived ratios. The sheet is authoritative where ERP values differ.
<br><span class="source-note">The ERP cross-check uses October net revenue GLs through enterprise MCP, mapped through fin.tblBusinessArea. The comparison notes identify parent-level matches, mapped variances, and composite lines without a one-to-one ERP SBU.</span></section>
<section class="panel warning"><h2>ERP cross-check and portal scope</h2>
<p>ERP parent totals match the tracker for ACCL, AIL, APFIL, ARMCL, AEL combined, ABSL combined, ACL combined, ALEL, ATL, AITL, BPL, iBOS, AAFL, ABL, NTL, AASL, AMXL, ALCL, AAIL, NJL, AEFL, ACEL and AMPL.</p>
<p>Tracker values retained as authoritative where mapped ERP totals differ: BTL Coal (2.6818 vs ERP 2.6585 Cr); ALL (7.3706 vs ERP 8.0986 Cr); ASLL group (398.3650 vs ERP six-entity BDT roll-up 84.3156 Cr). G2G is a composite tracker line with no single matching ERP SBU total; its tracker actual is retained.</p>
<p>Removed from the portal because they are not tracker rows: DyTCL (ERP SBU 77, previously mislabeled DTL_Coal), HRML (86), FAL (87), and AENL (123, previously labeled AEL_Eng). Individual shipping entities are consolidated into the tracker’s ASLL group row.</p>
<p><b>Tracker total used by this page:</b> __ACTUAL_CR__ Cr. Per-row ERP cross-check results are shown in the last column; where ERP and the tracker differ, the tracker figure is presented. Page 1 carries the live ERP dashboard for the current reporting date.</p></section>
<section class="panel"><h2>Monthly actuals by tracker line</h2><div class="controls"><input id="filter" type="search" placeholder="Filter by code or SBU name"></div>
<div class="table-wrap"><table id="actuals"><thead><tr><th>#</th><th>Tracker code</th><th>SBU / tracker line</th><th class="num">Actual (BDT)</th><th class="num">Actual (Cr)</th><th class="num">Forecast (BDT)</th><th class="num">Forecast (Cr)</th><th class="num">Achievement</th><th>ERP MCP cross-match</th></tr></thead><tbody>__ROWS__</tbody></table></div></section>
<footer class="muted">Generated from the October Revenue tracker · ERP MCP used for cross-check only · No non-tracker SBUs included.</footer>
</main><script>
const filter=document.getElementById('filter');filter.addEventListener('input',()=>{const q=filter.value.toLowerCase();document.querySelectorAll('#actuals tbody tr:not(.total)').forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(q));});
const AUTH={'arl.admin':'Flash@2026','cbdo':'CBDO@ARL26'};const gate=document.getElementById('gate');
function signIn(){const u=document.getElementById('user').value.trim(),p=document.getElementById('pass').value;if(AUTH[u]===p){sessionStorage.setItem('arl_flash_auth','1');gate.hidden=true;}else document.getElementById('login-error').textContent='Invalid credentials';}
document.getElementById('signin').addEventListener('click',signIn);document.getElementById('pass').addEventListener('keydown',e=>{if(e.key==='Enter')signIn();});if(sessionStorage.getItem('arl_flash_auth'))gate.hidden=true;
</script></body></html>'''.replace('__REPORT_DATE__', report_date) \
        .replace('__ACTUAL_CR__', f'{actual_total / 10000000:,.4f}') \
        .replace('__ACTUAL_BDT__', f'{actual_total:,.0f}') \
        .replace('__FORECAST_CR__', f'{forecast_total / 10000000:,.4f}') \
        .replace('__FORECAST_BDT__', f'{forecast_total:,.0f}') \
        .replace('__ACHIEVEMENT__', f'{actual_total / forecast_total * 100:.2f}') \
        .replace('__ROWS__', rows_html)


def build_html(data):
    """Page 1 — the ERP flash dashboard (unchanged layout)."""
    rd = data['report_date']
    date_str = rd.strftime("%B %d, %Y")
    title_date = rd.strftime("%b %d, %Y")

    de = data['de']; dm = data['dm']; mf = data['mf']
    month_pct = data['month_pct']
    target_note = (
        '<b>October 2026 forecasts (from the October Revenue tracker):</b> '
        'AEL combines Manufacturing, Export and Trading (147.06 Cr); ABSL is shown as one SBU '
        '(8.60 Cr combined forecast); Shipping has a shared 284.09 Cr forecast across six entities, '
        'with no reliable per-entity allocation.'
        if rd.year == 2026 and rd.month == 10 else
        '<b>Targets:</b> No current-period forecast target source is loaded; target achievement is suppressed.'
    )
    tracker_recon_html = ''
    if rd == date(2026, 10, 31):
        tracker_total_cr = 1173.2727589  # October Revenue!K34, BDT converted to Cr
        tracker_variance = tracker_total_cr - data['rpt_tot']
        tracker_recon_html = f'''<div class="recon-card">
<h3>Page 2 — October Revenue Tracker</h3>
<p>ERP-mapped SBU total on this page: <b>{fmt(data['rpt_tot'])} Cr</b> · Tracker actuals (page 2): <b>{fmt(tracker_total_cr)} Cr</b> · Variance: <b>{fmt(tracker_variance)} Cr</b>.</p>
<p>This page stays ERP GL-based. The tracker sheet is presented unchanged on page 2, where its figures are authoritative.</p>
<p><a href="october-tracker.html">&rarr; Open the October Revenue tracker (page 2)</a></p>
</div>'''

    # Format trend data as JS
    td_js = js(data['td'])
    td_bdt_js = js(data['td_bdt'])
    ord_td_js = js(data['ord_td'])
    ord_mtd_js = js(data['ord_mtd'])
    ord_daily_js = js(data['ord_daily'])
    hist_rev_js = js(data['hist_rev'])
    hist_ord_js = js(data['hist_ord'])

    # Compute KPI totals
    total_daily = 0; total_mtd = 0; total_fy = 0; total_cy = 0; ach_list = []
    for sid, g in data['gl'].items():
        daily = (g['d'] or 0)
        mtd = (g['m'] or 0)
        total_daily += daily; total_mtd += mtd
        total_fy += (g['fy'] or 0); total_cy += (g['cy'] or 0)
        # Ach% available from JS-side computation only — skip Python check

    proj_me = round(total_mtd / de * dm, 2) if de > 0 else 0
    run_rate = round(total_mtd / de, 2) if de > 0 else 0

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARL Daily SBU Sales Flash Report — {title_date}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;font-size:17px}}
#app{{padding:1.5rem 2rem;max-width:1500px;margin:0 auto}}
#loading{{text-align:center;padding:3rem;color:#94a3b8;font-size:1.15rem}}
header{{border-bottom:1px solid #334155;padding-bottom:1rem;margin-bottom:1.5rem}}
header h1{{font-size:1.8rem;color:#f8fafc}}
header .meta{{color:#94a3b8;font-size:1rem;margin-top:0.25rem}}
.portal-nav{{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}}
.portal-nav a{{padding:8px 14px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#cbd5e1;text-decoration:none;font-size:.92rem;font-weight:600}}
.portal-nav a:hover{{border-color:#38bdf8;color:#f8fafc}}
.portal-nav a.active{{background:#38bdf8;border-color:#38bdf8;color:#0f172a}}
.kpi-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:1.5rem}}
.kpi-card{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1.1rem;text-align:center;transition:transform 0.2s,box-shadow 0.2s}}
.kpi-card:hover{{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,0.4)}}
.kpi-card .label{{color:#94a3b8;font-size:0.9rem;text-transform:uppercase;letter-spacing:0.05rem}}
.kpi-card .val{{font-size:1.85rem;font-weight:700;color:#f8fafc;margin:0.3rem 0;animation:kpiPop 0.6s ease-out}}
.kpi-card .sub{{font-size:0.9rem;color:#94a3b8}}
@keyframes kpiPop{{0%{{transform:scale(0.92);opacity:0.4}}60%{{transform:scale(1.04)}}100%{{transform:scale(1);opacity:1}}}}
@media (max-width:768px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}}.charts-row{{grid-template-columns:1fr}}.insights-row{{grid-template-columns:1fr}}.summary-chart-box .canvas-row{{flex-direction:column;align-items:center}}.canvas-row canvas{{width:100%;height:auto}}.recon-grid{{grid-template-columns:1fr}}}}
@media (max-width:480px){{.kpi-row{{grid-template-columns:1fr}}}}
.charts-row{{display:grid;grid-template-columns:2fr 1fr;gap:1rem;margin-bottom:1.5rem}}
.chart-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem;box-shadow:0 4px 12px rgba(0,0,0,0.25);transition:box-shadow 0.2s}}
.chart-box:hover{{box-shadow:0 6px 20px rgba(56,189,248,0.08)}}
.chart-box h3{{font-size:1.05rem;color:#94a3b8;margin-bottom:0.75rem;text-transform:uppercase}}
.bar-wrap{{display:flex;flex-direction:column;gap:5px}}
.bar-item{{display:flex;align-items:center;gap:0.5rem}}
.bar-item .lbl{{width:90px;font-size:0.9rem;text-align:right;color:#94a3b8;flex-shrink:0}}
.bar-item .bar-bg{{flex:1;height:20px;background:#1e293b;border-radius:3px;overflow:hidden;position:relative}}
.bar-item .bar-fill{{height:100%;border-radius:3px;transition:width 0.5s}}
.bar-item .bar-val{{width:80px;font-size:0.9rem;color:#cbd5e1;flex-shrink:0;text-align:right}}
.insights-row{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1.5rem}}
.insight-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem}}
.insight-box h3{{font-size:1rem;color:#f8fafc;margin-bottom:0.75rem;padding-bottom:0.5rem;border-bottom:1px solid #334155}}
.insight-box ul{{list-style:none;font-size:0.95rem;line-height:1.6}}
.insight-box li{{color:#cbd5e1;padding:0.2rem 0}}
.insight-box li.neg{{color:#fca5a5}}
.insight-box li.pos{{color:#86efac}}
.recon-card{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1.5rem;margin-bottom:1.5rem}}
.recon-card h3{{color:#38bdf8;margin-bottom:1rem;font-size:1.15rem}}
.recon-grid{{display:grid;grid-template-columns:1fr 1fr;gap:2rem}}
.recon-col h4{{color:#94a3b8;font-size:0.95rem;text-transform:uppercase;margin-bottom:0.75rem}}
.recon-col table{{width:100%;font-size:1rem}}
.recon-col td{{padding:0.35rem 0.5rem;color:#cbd5e1}}
.recon-col .total td{{border-top:1px solid #475569;font-weight:700;color:#f8fafc}}
.recon-col .val{{text-align:right;font-family:monospace}}
.recon-note{{color:#fbbf24;font-size:0.95rem;margin-top:1rem;padding:0.6rem;background:#422006;border-radius:0.5rem}}
.scorecard-table{{width:100%;border-collapse:collapse;font-size:0.98rem;background:#1e293b;border-radius:0.75rem;overflow:hidden;border:1px solid #334155}}
.scorecard-table th{{background:#0f172a;color:#94a3b8;padding:0.6rem 0.5rem;text-align:left;font-weight:600;position:sticky;top:0;z-index:2;font-size:0.9rem;text-transform:uppercase}}
.scorecard-table th.num{{text-align:right}}
.scorecard-table td{{padding:0.55rem 0.6rem;border-bottom:1px solid #1e293b;transition:background 0.15s}}
.scorecard-table tbody tr{{transition:box-shadow 0.15s}}
.scorecard-table tbody tr:hover{{background:#1e3a5f;box-shadow:inset 3px 0 0 #38bdf8}}
.scorecard-table tbody tr.top-performer{{background:#1a2f1a}}
.scorecard-table tbody tr.top-performer:hover{{background:#1e3a2e;box-shadow:inset 3px 0 0 #4ade80}}
.scorecard-table td.num{{text-align:right;font-family:monospace}}
.scorecard-wrap{{overflow-x:auto;border-radius:0.75rem;margin-bottom:1.5rem;-webkit-overflow-scrolling:touch}}
.scorecard-controls{{display:flex;gap:0.75rem;margin-bottom:0.75rem;align-items:center;flex-wrap:wrap}}
.scorecard-controls select,.scorecard-controls input{{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:0.5rem;padding:0.5rem 0.85rem;font-size:0.95rem}}
.scorecard-controls select:focus,.scorecard-controls input:focus{{outline:none;border-color:#38bdf8}}
.scorecard-controls input{{min-width:220px}}
.scorecard-controls label{{color:#94a3b8;font-size:0.9rem;margin-right:0.25rem}}
.date-filter{{display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;margin-bottom:0.75rem;padding:0.75rem;background:#1e293b;border:1px solid #334155;border-radius:0.6rem}}
.date-filter label{{color:#94a3b8;font-size:0.85rem}}
.date-filter input[type=date]{{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:0.45rem;padding:0.4rem 0.6rem;font-size:0.9rem}}
.date-filter input[type=date]:focus{{outline:none;border-color:#38bdf8}}
.date-filter button{{background:#38bdf8;color:#0f172a;border:none;border-radius:0.45rem;padding:0.4rem 0.9rem;font-weight:700;font-size:0.85rem;cursor:pointer}}
.date-filter button.reset{{background:#334155;color:#e2e8f0}}
.date-filter button:hover{{filter:brightness(1.1)}}
.date-filter .df-status{{color:#38bdf8;font-size:0.85rem}}
.chart-stats{{display:flex;gap:1rem;margin-bottom:0.75rem;font-size:0.9rem;color:#94a3b8;flex-wrap:wrap}}
.chart-stats span{{background:#0f172a;padding:0.25rem 0.6rem;border-radius:0.35rem;border:1px solid #334155}}
.chart-stats b{{color:#38bdf8}}
.mom-up{{color:#4ade80}}
.mom-down{{color:#f87171}}
.mom-neu{{color:#fbbf24}}
footer{{text-align:center;color:#64748b;font-size:0.85rem;padding:1.5rem 0;border-top:1px solid #1e293b;margin-top:1.5rem}}
.flag-card{{background:#451a03;border:1px solid #d97706;border-radius:0.75rem;padding:1rem;margin-bottom:1rem;font-size:0.95rem;color:#fcd34d}}
.flag-card b{{color:#fbbf24}}
.vol-cell{{color:#7dd3fc}}
.chart-toggle{{cursor:pointer;color:#38bdf8;font-size:0.85rem;display:inline-block;margin-left:0.3rem;transition:transform 0.2s}}
.chart-toggle.open{{transform:rotate(90deg)}}
.chart-row{{display:none}}
.chart-row.open{{display:table-row}}
.chart-row td{{padding:0;border:none;background:#0f172a}}
.chart-canvas-wrap{{padding:0.75rem 1rem}}
.chart-canvas-wrap canvas{{background:#1a2332;border-radius:0.5rem;border:1px solid #334155;cursor:pointer}}
.sbu-detail{{padding:0 1rem 0.75rem 1rem}}
.sbu-detail-summary{{display:flex;gap:0.75rem;flex-wrap:wrap;margin:0.5rem 0}}
.sbu-detail-summary span{{background:#1e293b;border:1px solid #334155;border-radius:0.4rem;padding:0.35rem 0.7rem;font-size:0.85rem;color:#cbd5e1}}
.sbu-detail-summary b{{color:#38bdf8}}
.sbu-detail-table{{overflow-x:auto;border:1px solid #334155;border-radius:0.5rem;background:#1e293b}}
.sbu-detail-table table{{width:100%;border-collapse:collapse;font-size:0.88rem}}
.sbu-detail-table th{{background:#0f172a;color:#94a3b8;padding:0.4rem 0.6rem;text-align:left;font-weight:600;font-size:0.78rem;text-transform:uppercase;position:sticky;top:0}}
.sbu-detail-table th.num{{text-align:right}}
.sbu-detail-table td{{padding:0.3rem 0.6rem;border-top:1px solid #1e293b;text-align:left}}
.sbu-detail-table td.num{{text-align:right;font-family:monospace}}
.sbu-detail-table td.rev{{color:#4ade80}}
.sbu-detail-table tfoot td{{background:#0f172a;font-weight:700;color:#f8fafc;border-top:2px solid #334155}}
.sbu-detail-table tfoot td.num{{font-family:monospace}}
.summary-chart-box{{background:#1e293b;border:1px solid #334155;border-radius:0.75rem;padding:1rem;margin-bottom:1.5rem;box-shadow:0 4px 12px rgba(0,0,0,0.25)}}
.summary-chart-box h3{{font-size:1.05rem;color:#94a3b8;margin-bottom:0.75rem;text-transform:uppercase}}
.summary-chart-box .canvas-row{{display:flex;gap:1rem;flex-wrap:wrap;justify-content:center}}
.summary-chart-box canvas{{background:#1a2332;border-radius:0.5rem;border:1px solid #334155;cursor:crosshair}}
#login-overlay{{position:fixed;inset:0;background:rgba(15,23,42,0.98);z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column}}
#login-overlay.hidden{{display:none}}
#login-box{{background:#1e293b;padding:2.5rem;border-radius:1rem;border:1px solid #334155;width:380px;text-align:center}}
#login-box h2{{color:#38bdf8;margin-bottom:0.5rem;font-size:1.5rem}}
#login-box p{{color:#94a3b8;margin-bottom:1.5rem;font-size:1rem}}
#login-box input{{width:100%;padding:0.85rem;margin:0.35rem 0;border-radius:0.5rem;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:1.05rem}}
#login-box input:focus{{outline:none;border-color:#38bdf8}}
#login-box button{{width:100%;padding:0.85rem;margin-top:1rem;background:#38bdf8;color:#0f172a;border:none;border-radius:0.5rem;font-weight:700;font-size:1.15rem;cursor:pointer}}
#login-box .err{{color:#f87171;margin-top:0.5rem;font-size:0.95rem}}
#loading-overlay{{position:fixed;inset:0;background:rgba(15,23,42,0.95);z-index:9998;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#94a3b8;font-size:1.25rem}}
#loading-overlay.hidden{{display:none}}
.spinner{{width:40px;height:40px;border:3px solid #334155;border-top:3px solid #38bdf8;border-radius:50%;animation:spin 1s linear infinite;margin-bottom:1rem}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body>
<div id="login-overlay"><div id="login-box">
<h2>ARL Flash Report</h2><p>{date_str}</p>
<input type="text" id="un" placeholder="Username"><input type="password" id="pw" placeholder="Password">
<button onclick="auth()">Sign In</button><div class="err" id="login-err"></div>
</div></div>
<div id="loading-overlay"><div class="spinner"></div><span>Querying DWH live... this may take 30-45 seconds</span></div>
<div id="app">
<header>
<nav class="portal-nav"><a class="active" href="index.html">1 · ERP Flash Report</a><a href="october-tracker.html">2 · October Revenue Tracker</a></nav>
<h1>AKIJ RESOURCE — Daily SBU Sales Flash Report</h1>
<div class="meta">Report Date: {date_str} | Period: {data['period']} (Day {data['day_label']}, {month_pct}%) | Source: ERP GL 3010001, 3010002, 3010005, 3010006 (Revenue sub-schedule) | FY 2026-27 | Live</div>
</header>

<div class="flag-card">
<b>Basis:</b> Revenue = net of sales returns (GL 3010001, 3010002, 3010005 and 3010006, credits − debits). Unallocated cement deliveries (intSBUId=0) map to ACCL (58). ABSL is included as one SBU; ACEL is the tracker name for report SBU 126.<br>
{target_note}
</div>

<div class="kpi-row" id="kpi-row"></div>

<div class="summary-chart-box">
<h3>Portfolio Daily Revenue Trend — {data['period']} (BDT Cr)</h3>
<div class="chart-stats" id="portfolio-stats"></div>
<div class="canvas-row">
<canvas id="portfolio-daily" width="640" height="280"></canvas>
<canvas id="top5-stacked" width="440" height="280"></canvas>
</div>
</div>

<div class="charts-row">
<div class="chart-box"><h3>MTD Revenue — Top 15 SBUs (Cr)</h3><div class="bar-wrap" id="mtd-chart"></div></div>
<div class="chart-box"><h3>MoM Momentum Distribution</h3><div class="bar-wrap" id="mom-chart"></div></div>
</div>

<div class="insights-row" id="insights-row"></div>

<div class="recon-card">
<h3>Revenue Reconciliation — MTD {data['period']}</h3>
<div class="recon-grid">
<div class="recon-col">
<h4>Our Report Total (sub-schedule)</h4>
<table>
<tr><td>GL 3010001 Sales (Local)</td><td class="val" id="rpt-gross">—</td></tr>
<tr><td style="font-size:0.9rem;color:#94a3b8;padding-left:1.5rem">All named ERP SBUs (unmapped journal IDs excluded)</td></tr>
<tr><td>GL 3010002 Sales (Foreign)</td><td class="val" id="rpt-3010002">—</td></tr>
<tr><td>GL 3010005 Freight (ASLL, AOCN, AMTL, ASeLL, ASLL-1, ASeLLC)</td><td class="val" id="rpt-freight">—</td></tr>
<tr><td>GL 3010006 Agency Income</td><td class="val" id="rpt-3010006">—</td></tr>
<tr class="total"><td>Report Total</td><td class="val" id="rpt-total">—</td></tr>
</table>
</div>
<div class="recon-col">
<h4>Full GL Reconciliation (all entities)</h4>
<table>
<tr><td>GL 3010001 Sales (Local)</td><td class="val" id="full-3010001">—</td></tr>
<tr><td>GL 3010002 Sales (Foreign)</td><td class="val" id="full-3010002">—</td></tr>
<tr><td>GL 3010005 Freight Income</td><td class="val" id="full-3010005">—</td></tr>
<tr><td>GL 3010006 Agency Income</td><td class="val" id="full-3010006">—</td></tr>
<tr class="total"><td>Revenue Subtotal (3010001+2+5+6)</td><td class="val" id="full-revenue-total">—</td></tr>
<tr><td>GL 3010004 Other Income (non-operating)</td><td class="val" id="full-3010004">—</td></tr>
<tr class="total"><td>Full GL Total incl. Other Income</td><td class="val" id="full-total">—</td></tr>
</table>
</div>
</div>
<div class="recon-note" id="recon-note"></div>
</div>
{tracker_recon_html}

<div class="date-filter" id="date-filter">
<label>Date range:</label>
<input type="date" id="df-start">
<label>to</label>
<input type="date" id="df-end">
<button onclick="applyDateFilter()">Apply</button>
<button class="reset" onclick="resetDateFilter()">Reset to MTD</button>
<span class="df-status" id="df-status"></span>
</div>
<div class="scorecard-controls">
<label>Sort by:</label>
<select id="scorecard-sort" onchange="sortScorecard()">
<option value="mtd_rev">MTD Revenue (default)</option>
<option value="daily_rev">Daily Revenue</option>
<option value="code">SBU Code A–Z</option>
<option value="mtd_ach_pct">Ach% High–Low</option>
<option value="mom_pct">MoM% High–Low</option>
<option value="yoy_pct">YoY% High–Low</option>
<option value="proj_rev">Projected M/E</option>
</select>
<input type="text" id="scorecard-filter" placeholder="Filter SBUs..." oninput="filterScorecard()">
</div>
<div class="scorecard-wrap">
<table class="scorecard-table">
<thead id="scorecard-head">
<tr>
<th>SBU</th><th class="num">Daily Rev</th><th class="num">DoD%</th><th class="num">MTD Rev</th><th class="num">Monthly Tgt</th><th class="num">MTD Tgt</th><th class="num">Ach%</th>
<th class="num">MoM%</th><th class="num">YoY%</th><th class="num">FY YTD</th><th class="num">CY YTD</th><th class="num">Proj M/E</th><th>Signal</th>
<th class="num">MTD Vol</th><th class="num">Daily Vol</th><th></th></tr>
</thead>
<tbody id="scorecard-body"></tbody>
</table>
</div>
<footer>Powered by ARL Live Flash Report Engine · ERP GL 3010001, 3010002, 3010005, 3010006 (Revenue sub-schedule) · sms.tblDeliveryHeader · Generated live on {date_str} · Next refresh: reload page</footer>
</div>

<script>
const CREDS={{ 'arl.admin':'Flash@2026', 'cbdo':'CBDO@ARL26' }};
function auth(){{
  let u=document.getElementById('un').value.trim(), p=document.getElementById('pw').value;
  if(CREDS[u]===p){{ document.getElementById('login-overlay').classList.add('hidden'); sessionStorage.setItem('arl_flash_auth','1'); }}
  else document.getElementById('login-err').textContent='Invalid credentials';
}}
window.addEventListener('DOMContentLoaded',()=>{{ if(sessionStorage.getItem('arl_flash_auth')) document.getElementById('login-overlay').classList.add('hidden'); }});
document.getElementById('pw').addEventListener('keydown',e=>{{ if(e.key==='Enter') auth(); }});
const DE={de}, DM={dm};
const M_FACTOR={mf};
const SBU_MAP={js(data['sbu_map'])};
const MONTH_TARGETS={js(data['targets'])};
const TD={td_js};
const TD_BDT={td_bdt_js};
const ORD_TD={ord_td_js};
const ORD_MTD={ord_mtd_js};
const ORD_DAILY={ord_daily_js};
const HIST_REV={hist_rev_js};
const HIST_ORD={hist_ord_js};
const FR_D={js(data['fr_d'])};
const FR_M={js(data['fr_m'])};
const DV={js(data['dv'])};
const MV={js(data['mv'])};
const MOV={js(data['mov'])};
const GL={js(data['gl'])};
const ABSL_ASPH={data['asphalt']}, ABSL_BENZ={data['benzol']};
const FREIGHT_IDS=new Set([64,79,80,81,88,110]);
const RECON={{g1all:{data['g1all']},excl:{data['excl']},g5all:{data['g5all']},g2all:{data['g2all']},g6all:{data['g6all']},g4all:{data['g4all']},
  rpt_gl1:{data['rpt_gl1']},rpt_g2:{data['g2report']},rpt_frt:{data['rpt_frt']},rpt_g6:{data['g6report']},
  rpt_tot:{data['rpt_tot']},full_rev_tot:{data['full_rev_tot']},full_tot:{data['full_tot']},gap:{data['gap']}}};

function fmt(n,d){{ if(n==null||isNaN(n)) return '—'; let s=n.toFixed(d||2); return s.replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,',') }}
function pct(a,b){{ if(!b||b===0) return null; return ((a/b)-1)*100 }}
function momSig(v){{ if(v==null||isNaN(v)) return 'N/A'; if(v>=20) return 'Strong +'; if(v>=0) return 'Positive'; if(v>=-15) return 'Neutral'; if(v>=-30) return 'Weak'; return 'Negative' }}
function momCls(v){{ if(v==null||isNaN(v)) return 'mom-neu'; if(v>=20) return 'mom-up'; if(v>=0) return 'mom-up'; if(v>=-15) return 'mom-neu'; return 'mom-down' }}

function buildSBU(id){{
  let g=GL[id], name=SBU_MAP[id]||('SBU_'+id), fr_d=FR_D[id]||0, fr_m=FR_M[id]||0;
  let daily=(g?(g.d||0):0);
  let mtd=(g?(g.m||0):0);
  let dod=((g?g.dod:0)||0);
  let dv=DV[id]||0, mv=MV[id]||0, movv=MOV[id]||0;
  let has_vol=mv>0||!!DV[id];
  let moTgt=MONTH_TARGETS[name]||null;
  let mtdTgt=moTgt?(moTgt*M_FACTOR):null;
  let ach=(mtdTgt&&mtd>0)?(mtd/mtdTgt*100):null;
  let momPct=(g?g.mom:0)>0?pct(mtd,(g?g.mom:0)):null;
  let yoyPct=(g?g.yoy:0)>0?pct(mtd,(g?g.yoy:0)):null;
  let proj=mtd>0?(mtd/DE*DM):0;
  return [{{id,code:name,name,src:'GL 3010001+2+5+6',
    daily_rev:daily,dod_rev:dod,mtd_rev:mtd,mom_rev:(g?g.mom:0)||0,
    yoy_rev:(g?g.yoy:0)||0,fy_ytd_rev:(g?g.fy:0)||0,cy_ytd_rev:(g?g.cy:0)||0,
    daily_vol:dv,mtd_vol:mv,mom_vol:movv,has_vol:has_vol,
    mtd_tgt_rev:mtdTgt,mo_tgt_rev:moTgt,
    mtd_ach_pct:ach,mom_pct:momPct,yoy_pct:yoyPct,
    proj_rev:proj,momentum:momSig(momPct),tgt:moTgt?('MTD='+fmt(mtdTgt)):'—'}}];
}}

function buildChannel(id,name,ratio){{
  let g=GL[id], base=g||{{}};
  let daily=(base.d||0)*ratio, mtd=(base.m||0)*ratio;
  let dod=(base.dod||0)*ratio, mom=(base.mom||0)*ratio, yoy=(base.yoy||0)*ratio;
  let fy=(base.fy||0)*ratio, cy=(base.cy||0)*ratio;
  let moTgt=name==='ABSL Asphalt'?MONTH_TARGETS['ABSL_Asphalt']:MONTH_TARGETS['Benzol'];
  let mtdTgt=moTgt?moTgt*M_FACTOR:null;
  let ach=mtdTgt&&mtd>0?(mtd/mtdTgt*100):null;
  let proj=mtd>0?(mtd/DE*DM):0;
  let momPct=mom>0?pct(mtd,mom):null;
  return {{id,code:name,name,src:'GL 3010001',
    daily_rev:daily,dod_rev:dod,mtd_rev:mtd,mom_rev:mom,
    yoy_rev:yoy,fy_ytd_rev:fy,cy_ytd_rev:cy,
    daily_vol:0,mtd_vol:0,mom_vol:0,has_vol:false,
    mtd_tgt_rev:mtdTgt,mo_tgt_rev:moTgt,
    mtd_ach_pct:ach,mom_pct:momPct,yoy_pct:null,
    proj_rev:proj,momentum:momSig(momPct),tgt:moTgt?('MTD='+fmt(mtdTgt)):'—'}};
}}

let ALL=[];
// Rows shown on page 1 — every named ERP SBU, so total revenue ties to the GL.
// Unnamed/unmapped journal IDs are excluded so no "SBU_xxx" rows appear.
let sortedIDs=Object.keys(SBU_MAP).map(Number).sort((a,b)=>a-b);
for(let id of sortedIDs){{ let r=buildSBU(id); if(Array.isArray(r)) ALL.push(...r); else ALL.push(r); }}

// KPI cards
let totalDaily=0,totalMTD=0,totalFY=0,totalCY=0,achList=[];
ALL.forEach(r=>{{ totalDaily+=r.daily_rev;totalMTD+=r.mtd_rev;totalFY+=r.fy_ytd_rev;totalCY+=r.cy_ytd_rev;if(r.mtd_ach_pct!=null)achList.push(r.mtd_ach_pct); }});
let avgAch=achList.length?(achList.reduce((a,b)=>a+b)/achList.length):null;
let projME=totalMTD>0?(totalMTD/DE*DM):0;
let kpiHTML='';
kpiHTML+=`<div class="kpi-card"><div class="label">Daily Revenue ({rd.strftime('%b')} {de})</div><div class="val">${{fmt(totalDaily)}} Cr</div><div class="sub">GL 3010001+2+5+6</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">MTD Revenue ({data['period']})</div><div class="val">${{fmt(totalMTD)}} Cr</div><div class="sub">${{DE}}/${{DM}} days (${{fmt(M_FACTOR*100,1)}}%)</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Projected Month-End</div><div class="val">${{fmt(projME)}} Cr</div><div class="sub">Run rate: ${{fmt(totalMTD/DE)}} Cr/day</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Avg MTD Achievement</div><div class="val">${{avgAch?fmt(avgAch,1)+'%':'N/A'}}</div><div class="sub">${{achList.length}} SBUs with targets</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">Yearly Revenue (CY YTD)</div><div class="val">${{fmt(totalCY)}} Cr</div><div class="sub">Jan 1 – {date_str}</div></div>`;
kpiHTML+=`<div class="kpi-card"><div class="label">YTD Revenue FY26-27</div><div class="val">${{fmt(totalFY)}} Cr</div><div class="sub">Jul 1 – {date_str}</div></div>`;
document.getElementById('kpi-row').innerHTML=kpiHTML;
const MTD_KPI_HTML=kpiHTML;

// MTD bar chart
let byMTD=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,15);
let mtdChartHTML='';
byMTD.forEach((r,i)=>{{
  let maxV=byMTD[0].mtd_rev, w=(r.mtd_rev/maxV*100).toFixed(0);
  let clr=i<3?'#38bdf8':i<6?'#818cf8':i<9?'#a78bfa':'#64748b';
  mtdChartHTML+=`<div class="bar-item"><div class="lbl">${{r.code}}</div><div class="bar-bg"><div class="bar-fill" style="width:${{w}}%;background:${{clr}}"></div></div><div class="bar-val">${{fmt(r.mtd_rev)}}</div></div>`;
}});
document.getElementById('mtd-chart').innerHTML=mtdChartHTML;

// MoM momentum
let momCats={{Strong:0,Positive:0,Neutral:0,Weak:0,Negative:0,'N/A':0}};
ALL.forEach(r=>{{ let m=r.momentum; if(!m||m==='N/A') momCats['N/A']++; else if(m.startsWith('Strong')) momCats.Strong++; else if(m==='Positive') momCats.Positive++; else if(m==='Neutral') momCats.Neutral++; else if(m==='Weak') momCats.Weak++; else momCats.Negative++; }});
let momHTML='',totalS=ALL.length;
['Strong','Positive','Neutral','Weak','Negative','N/A'].forEach(cat=>{{
  let cnt=momCats[cat], w=cnt/totalS*100;
  let clr=cat==='Strong'?'#4ade80':cat==='Positive'?'#86efac':cat==='Neutral'?'#fbbf24':cat==='Weak'?'#f97316':cat==='Negative'?'#f87171':'#64748b';
  momHTML+=`<div class="bar-item"><div class="lbl">${{cat}}</div><div class="bar-bg"><div class="bar-fill" style="width:${{w.toFixed(0)}}%;background:${{clr}}"></div></div><div class="bar-val">${{cnt}}</div></div>`;
}});
document.getElementById('mom-chart').innerHTML=momHTML;

// Insights
let top3=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,3);
let bottom3=[...ALL].filter(r=>r.mtd_rev>0&&r.mtd_tgt_rev!=null).sort((a,b)=>a.mtd_ach_pct-b.mtd_ach_pct).slice(0,3);
let riskSBUs=[...ALL].filter(r=>(r.momentum==='Negative'||r.momentum==='Weak')&&r.mtd_rev>0);
let dormantSBUs=[...ALL].filter(r=>r.mtd_rev===0&&r.mtd_vol===0&&r.id!==64&&r.id!==79&&r.id!==80&&r.id!==81&&r.id!==88&&r.id!==110);
let snapHTML='<div class="insight-box"><h3>Snapshot</h3><ul>';
snapHTML+=`<li>Total MTD Revenue: <b>${{fmt(totalMTD)}} Cr</b> across ${{ALL.filter(r=>r.mtd_rev>0).length}} active SBUs</li>`;
snapHTML+=`<li>Daily Revenue ({rd.strftime('%b')} {de}): <b>${{fmt(totalDaily)}} Cr</b></li>`;
snapHTML+=`<li>Month Progress: <b>${{DE}}/${{DM}} (${{fmt(M_FACTOR*100,1)}}%)</b></li>`;
snapHTML+=`<li>Projected Month-End: <b>${{fmt(projME)}} Cr</b></li>`;
snapHTML+=`<li>Avg Daily Run Rate: <b>${{fmt(totalMTD/DE)}} Cr/day</b></li>`;
snapHTML+=`<li>ERP Sync: Live query at load time</li>`;
snapHTML+='</ul></div>';
let hiHTML='<div class="insight-box"><h3>SBU Highlights</h3><ul>';
top3.forEach(r=>hiHTML+=`<li class="pos">${{r.code}}: MTD ${{fmt(r.mtd_rev)}} Cr — leader (#${{top3.indexOf(r)+1}})</li>`);
hiHTML+=`<li class="pos">AAFL (109): Daily ${{fmt(GL[109]?GL[109].d:0)}} Cr — strongest performer</li>`;
hiHTML+=`<li>AEL (36): MTD ${{fmt(GL[36]?GL[36].m:0)}} Cr, FY YTD ${{fmt(GL[36]?GL[36].fy:0)}} Cr</li>`;
hiHTML+=`<li>ACCL (58): MTD ${{fmt(GL[58]?GL[58].m:0)}} Cr</li>`;
hiHTML+='</ul></div>';
let rfHTML='<div class="insight-box"><h3>Risk Flags</h3><ul>';
if(riskSBUs.length) rfHTML+=riskSBUs.map(r=>`<li class="neg">${{r.code}}: ${{r.momentum}} MoM — MTD ${{fmt(r.mtd_rev)}} Cr</li>`).join('');
else rfHTML+='<li class="pos">No SBUs in Negative/Weak momentum range</li>';
if(dormantSBUs.length>0) rfHTML+=`<li>Zero-revenue SBUs: ${{dormantSBUs.map(r=>r.code).join(', ')}}</li>`;
rfHTML+='</ul></div>';
document.getElementById('insights-row').innerHTML=snapHTML+hiHTML+rfHTML;

// Reconciliation
document.getElementById('rpt-gross').textContent=fmt(RECON.rpt_gl1)+' Cr';
document.getElementById('rpt-3010002').textContent=fmt(RECON.rpt_g2)+' Cr';
document.getElementById('rpt-freight').textContent=fmt(RECON.rpt_frt)+' Cr';
document.getElementById('rpt-3010006').textContent=fmt(RECON.rpt_g6)+' Cr';
document.getElementById('rpt-total').textContent=fmt(RECON.rpt_tot)+' Cr';
document.getElementById('full-3010001').textContent=fmt(RECON.g1all)+' Cr';
document.getElementById('full-3010002').textContent=fmt(RECON.g2all)+' Cr';
document.getElementById('full-3010005').textContent=fmt(RECON.g5all)+' Cr';
document.getElementById('full-3010006').textContent=fmt(RECON.g6all)+' Cr';
document.getElementById('full-revenue-total').textContent=fmt(RECON.full_rev_tot)+' Cr';
document.getElementById('full-3010004').textContent=fmt(RECON.g4all)+' Cr';
document.getElementById('full-total').textContent=fmt(RECON.full_tot)+' Cr';
document.getElementById('recon-note').textContent='Difference between report total and full GL total: '+fmt(RECON.gap)+' Cr, which is GL 3010004 other income (non-operating). Revenue subtotals use GL 3010001, 3010002, 3010005 and 3010006, net of returns, with ledger amounts already in BDT (no FX multiplier applied).';

// Scorecard
let top3IDs=new Set([...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,3).map(r=>r.id));
let SCORECARD_SORT='mtd_rev';
let SCORECARD_FILTER='';
let RANGE_START=null, RANGE_END=null;
const MTD_HEAD=document.getElementById('scorecard-head').innerHTML;
function countDays(s,e){{ let a=new Date(s+'T00:00:00'), b=new Date(e+'T00:00:00'); return Math.round((b-a)/86400000)+1; }}
function applyDateFilter(){{
  let s=document.getElementById('df-start').value, e=document.getElementById('df-end').value;
  if(!s||!e){{ alert('Select both From and To dates'); return; }}
  if(s>e){{ let t=s; s=e; e=t; document.getElementById('df-start').value=s; document.getElementById('df-end').value=e; }}
  RANGE_START=s; RANGE_END=e;
  renderScorecard();
}}
function resetDateFilter(){{
  RANGE_START=null; RANGE_END=null;
  document.getElementById('df-start').value=''; document.getElementById('df-end').value='';
  document.getElementById('df-status').textContent='';
  renderScorecard();
}}
function renderRangeKPIs(){{
  let s=RANGE_START, e=RANGE_END, days=countDays(s,e);
  let totRev=0, totOrd=0, active=0;
  ALL.forEach(r=>{{
    let revMap=HIST_REV[r.id]||{{}}, ordMap=HIST_ORD[r.id]||{{}};
    let rev=0, ord=0;
    for(let d in revMap){{ if(d>=s&&d<=e) rev+=revMap[d]; }}
    for(let d in ordMap){{ if(d>=s&&d<=e) ord+=ordMap[d]; }}
    totRev+=rev; totOrd+=ord; if(rev>0||ord>0) active++;
  }});
  let html='';
  html+=`<div class="kpi-card"><div class="label">Range Revenue</div><div class="val">${{fmt(totRev)}} Cr</div><div class="sub">${{s}} → ${{e}}</div></div>`;
  html+=`<div class="kpi-card"><div class="label">Range Orders</div><div class="val">${{totOrd.toLocaleString('en-US')}}</div><div class="sub">Sales orders</div></div>`;
  html+=`<div class="kpi-card"><div class="label">Avg Daily Revenue</div><div class="val">${{fmt(totRev/days)}} Cr</div><div class="sub">${{days}} days</div></div>`;
  html+=`<div class="kpi-card"><div class="label">Avg Daily Orders</div><div class="val">${{(totOrd/days).toFixed(1)}}</div><div class="sub">${{days}} days</div></div>`;
  html+=`<div class="kpi-card"><div class="label">Days in Range</div><div class="val">${{days}}</div><div class="sub">${{s}} → ${{e}}</div></div>`;
  html+=`<div class="kpi-card"><div class="label">Active SBUs</div><div class="val">${{active}}</div><div class="sub">with revenue or orders</div></div>`;
  document.getElementById('kpi-row').innerHTML=html;
}}
function renderRangeScorecard(){{
  renderRangeKPIs();
  let s=RANGE_START, e=RANGE_END, days=countDays(s,e);
  let q=(SCORECARD_FILTER||'').toLowerCase();
  let rows=ALL.map(r=>{{
    let revMap=HIST_REV[r.id]||{{}}, ordMap=HIST_ORD[r.id]||{{}};
    let rev=0, ord=0;
    for(let d in revMap){{ if(d>=s&&d<=e) rev+=revMap[d]; }}
    for(let d in ordMap){{ if(d>=s&&d<=e) ord+=ordMap[d]; }}
    return {{ code:r.code, id:r.id, rev:rev, ord:ord }};
  }}).filter(x=>x.rev>0||x.ord>0).filter(x=>!q||x.code.toLowerCase().includes(q));
  rows.sort((a,b)=>b.rev-a.rev);
  document.getElementById('scorecard-head').innerHTML='<tr><th>SBU</th><th class="num">Revenue (Cr)</th><th class="num">Orders</th><th class="num">Avg Daily Rev (Cr)</th><th class="num">Avg Daily Orders</th><th class="num">Days</th></tr>';
  let tbodyHTML='', totRev=0, totOrd=0;
  rows.forEach((x,i)=>{{
    totRev+=x.rev; totOrd+=x.ord;
    let topCls=i<3?' top-performer':'';
    tbodyHTML+=`<tr class="${{topCls}}"><td>${{x.code}}</td><td class="num rev">${{fmt(x.rev)}}</td><td class="num">${{x.ord.toLocaleString('en-US')}}</td><td class="num">${{fmt(x.rev/days)}}</td><td class="num">${{(x.ord/days).toFixed(1)}}</td><td class="num">${{days}}</td></tr>`;
  }});
  tbodyHTML+=`<tr style="background:#0f172a;font-weight:700"><td>Total (${{rows.length}} SBUs)</td><td class="num rev">${{fmt(totRev)}}</td><td class="num">${{totOrd.toLocaleString('en-US')}}</td><td class="num">${{fmt(totRev/days)}}</td><td class="num">${{(totOrd/days).toFixed(1)}}</td><td class="num">${{days}}</td></tr>`;
  document.getElementById('scorecard-body').innerHTML=tbodyHTML;
  document.getElementById('df-status').textContent='Range: '+s+' → '+e+' ('+days+' days) · '+rows.length+' SBUs';
}}
function renderScorecard(){{
  if(RANGE_START&&RANGE_END){{ renderRangeScorecard(); return; }}
  document.getElementById('scorecard-head').innerHTML=MTD_HEAD;
  document.getElementById('kpi-row').innerHTML=MTD_KPI_HTML;
  let sorted=[...ALL];
  let sortBy=SCORECARD_SORT;
  if(sortBy==='mtd_rev'||sortBy==='daily_rev'||sortBy==='proj_rev') sorted.sort((a,b)=>b[sortBy]-a[sortBy]);
  else if(sortBy==='code') sorted.sort((a,b)=>a.code.localeCompare(b.code));
  else sorted.sort((a,b)=>(b[sortBy]||0)-(a[sortBy]||0));
  if(SCORECARD_FILTER){{ let q=SCORECARD_FILTER.toLowerCase(); sorted=sorted.filter(r=>r.code.toLowerCase().includes(q)); }}
  let tbodyHTML='';
  sorted.forEach((r,origIdx)=>{{
    let dodPct=r.dod_rev>0?pct(r.daily_rev,r.dod_rev):null;
    let topCls=top3IDs.has(r.id)?' top-performer':'',idx=ALL.indexOf(r);
    tbodyHTML+=`<tr class="sbu-row${{topCls}}" data-idx="${{idx}}" data-sbu="${{r.id}}">
<td>${{r.code}} <span style="font-size:0.85rem;color:#94a3b8">${{r.src}}</span> <span class="chart-toggle" data-idx="${{idx}}">&#9654;</span></td>
<td class="num">${{fmt(r.daily_rev)}}</td>
<td class="num ${{dodPct!=null&&dodPct>=0?'mom-up':dodPct!=null?'mom-down':''}}">${{dodPct!=null?fmt(dodPct,1)+'%':'—'}}</td>
<td class="num">${{fmt(r.mtd_rev)}}</td>
<td class="num" style="color:#38bdf8">${{r.mo_tgt_rev!=null?fmt(r.mo_tgt_rev):'—'}}</td>
<td class="num">${{r.mtd_tgt_rev!=null?fmt(r.mtd_tgt_rev):'—'}}</td>
<td class="num ${{r.mtd_ach_pct!=null&&r.mtd_ach_pct>=100?'mom-up':r.mtd_ach_pct!=null&&r.mtd_ach_pct<50?'mom-down':''}}">${{r.mtd_ach_pct!=null?fmt(r.mtd_ach_pct,1)+'%':'—'}}</td>
<td class="num ${{r.mom_pct!=null&&r.mom_pct>0?'mom-up':r.mom_pct!=null?'mom-down':''}}">${{r.mom_pct!=null?fmt(r.mom_pct,1)+'%':'—'}}</td>
<td class="num">${{r.yoy_pct!=null?fmt(r.yoy_pct,1)+'%':'—'}}</td>
<td class="num">${{fmt(r.fy_ytd_rev)}}</td>
<td class="num">${{fmt(r.cy_ytd_rev)}}</td>
<td class="num">${{fmt(r.proj_rev)}}</td>
<td class="${{momCls(r.mom_pct)}}">${{r.momentum}}</td>
<td class="num vol-cell">${{r.has_vol&&r.mtd_vol!=null?fmt(r.mtd_vol,1):'—'}}</td>
<td class="num vol-cell">${{r.has_vol&&r.daily_vol!=null?fmt(r.daily_vol,1):'—'}}</td>
<td></td></tr>
<tr class="chart-row" id="cr-${{idx}}"><td colspan="16"><div class="chart-canvas-wrap"><canvas id="c${{idx}}" width="560" height="200"></canvas></div><div class="sbu-detail" id="sd-${{idx}}"></div></td></tr>`;
  }});
  document.getElementById('scorecard-body').innerHTML=tbodyHTML;
  // Re-bind chart toggle handlers
  document.querySelectorAll('.chart-toggle').forEach(el=>{{
    el.addEventListener('click',function(e){{ e.stopPropagation(); let idx=this.dataset.idx; let row=document.getElementById('cr-'+idx); let isOpen=row.classList.contains('open'); row.classList.toggle('open'); this.classList.toggle('open'); if(!isOpen){{ drawSBUChart(idx); drawSBUDetail(idx); }} }});
  }});
  document.querySelectorAll('.sbu-row').forEach(el=>{{
    el.addEventListener('click',function(){{ let toggle=this.querySelector('.chart-toggle'); if(toggle) toggle.click(); }});
  }});
}}
renderScorecard();
function sortScorecard(){{ SCORECARD_SORT=document.getElementById('scorecard-sort').value; renderScorecard(); }}
function filterScorecard(){{ SCORECARD_FILTER=document.getElementById('scorecard-filter').value; renderScorecard(); }}

// === CHART FUNCTIONS ===
function drawAxes(ctx,w,h,pad,ymax,xlabels,ylabel){{
  ctx.strokeStyle='#334155';ctx.lineWidth=0.5;ctx.fillStyle='#94a3b8';ctx.font='11px monospace';
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom,ysteps=5;
  for(let i=0;i<=ysteps;i++){{ let y=pad.top+(cH/ysteps*i);ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();ctx.fillText(fmt(ymax-(ymax/ysteps*i),1),2,y+3); }}
  xlabels.forEach((l,i)=>{{ ctx.fillText(l,pad.left+(cW/(xlabels.length-1)*i)-8,h-2); }});
  if(ylabel){{ ctx.save();ctx.translate(8,pad.top+cH/2);ctx.rotate(-Math.PI/2);ctx.fillText(ylabel,-ctx.measureText(ylabel).width/2,0);ctx.restore(); }}
}}

function drawPortfolioDaily(){{
  let c=document.getElementById('portfolio-daily');if(!c)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:25,right:30,bottom:25,left:50}};
  let dtMap={{}};TD.forEach(t=>{{dtMap[t.d]=(dtMap[t.d]||0)+t.v;}});
  let dates=Object.keys(dtMap).sort(),vals=dates.map(d=>dtMap[d]);
  if(!dates.length){{
    ctx.fillStyle='#94a3b8';ctx.font='13px sans-serif';
    ctx.fillText('No daily revenue data yet for this period',20,40);
    let st=document.getElementById('portfolio-stats'); if(st) st.innerHTML='<span>No data available</span>';
    return;
  }}
  let ymax=Math.max(...vals)*1.2;
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  drawAxes(ctx,w,h,pad,ymax,dates.map(d=>d.slice(8)),'Cr');
  let barGap=4,barW=Math.max(6,cW/dates.length-barGap);
  let bars=[]; // store for hover
  vals.forEach((v,i)=>{{
    let x=pad.left+(cW/(vals.length-1)*i)-barW/2,hb=(v/ymax*cH);
    let grad=ctx.createLinearGradient(0,pad.top+cH-hb,0,pad.top+cH);
    grad.addColorStop(0,'#38bdf8');grad.addColorStop(1,'#1d4ed8');
    ctx.fillStyle=grad;ctx.fillRect(x,pad.top+cH-hb,barW,hb);
    ctx.fillStyle='#e2e8f0';ctx.font='10px monospace';ctx.fillText(fmt(v,2),x-4,pad.top+cH-hb-2);
    bars.push({{x:x, w:barW, v:v, d:dates[i]}});
  }});
  let cum=0,cumVals=vals.map(v=>cum+=v);
  ctx.strokeStyle='#fbbf24';ctx.lineWidth=2;ctx.setLineDash([4,3]);ctx.beginPath();
  cumVals.forEach((cv,i)=>{{ let x=pad.left+(cW/(cumVals.length-1)*i),y=pad.top+cH-(cv/Math.max(...cumVals)*1.1*cH);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y); }});
  ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle='#fbbf24';ctx.font='10px monospace';ctx.fillText('MTD:'+fmt(cum,2),pad.left+cW-55,pad.top+10);
  // Summary stats
  let avgDaily=vals.reduce((a,b)=>a+b,0)/vals.length,peakDay=dates[vals.indexOf(Math.max(...vals))];
  let trendDir='Stable',firstHalf=vals.slice(0,Math.floor(vals.length/2)).reduce((a,b)=>a+b,0);
  let secondHalf=vals.slice(Math.ceil(vals.length/2)).reduce((a,b)=>a+b,0);
  if(secondHalf>firstHalf*1.1) trendDir='Rising \u2191'; else if(firstHalf>secondHalf*1.1) trendDir='Dipping \u2193';
  document.getElementById('portfolio-stats').innerHTML=`<span>Avg Daily: <b>${{fmt(avgDaily)}} Cr</b></span><span>Peak: <b>${{peakDay.slice(5)}} (${{fmt(Math.max(...vals))}} Cr)</b></span><span>Trend: <b>${{trendDir}}</b></span><span>Range: <b>${{fmt(Math.min(...vals))}}–${{fmt(Math.max(...vals))}} Cr</b></span>`;
  // Hover tooltip
  let tip=document.createElement('div');tip.id='pd-tip';tip.style.cssText='position:absolute;display:none;background:#0f172a;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:13px;pointer-events:none;border:1px solid #38bdf8;white-space:nowrap;z-index:99';
  let wrap=c.parentElement;if(wrap.style.position!=='relative') wrap.style.position='relative';wrap.appendChild(tip);
  let oldHover=null;
  c.onmousemove=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=null;
    bars.forEach(b=>{{if(mx>=b.x&&mx<=b.x+b.w&&my>=pad.top&&my<=pad.top+cH)found=b;}});
    if(found){{
      tip.style.display='block';tip.style.left=(e.clientX-rect.left+12)+'px';tip.style.top=(e.clientY-rect.top-22)+'px';
      tip.textContent=found.d.slice(5)+': '+fmt(found.v,2)+' Cr';
      if(oldHover!==found){{ c.style.cursor='pointer'; oldHover=found; }}
    }}else{{ tip.style.display='none';oldHover=null;c.style.cursor='crosshair'; }}
  }};
  c.onmouseleave=function(){{ tip.style.display='none';oldHover=null; }};
}}

function drawTop5Stacked(){{
  let c=document.getElementById('top5-stacked');if(!c)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:25,right:20,bottom:25,left:45}};
  ctx.clearRect(0,0,w,h);
  let byMTD=[...ALL].filter(r=>r.mtd_rev>0).sort((a,b)=>b.mtd_rev-a.mtd_rev).slice(0,5);
  let colors=['#38bdf8','#818cf8','#c084fc','#f472b6','#fbbf24'];
  let dates=[...new Set(TD.map(t=>t.d))].sort();
  if(!dates.length){{
    ctx.fillStyle='#94a3b8';ctx.font='13px sans-serif';
    ctx.fillText('No daily data yet',20,40);
    return;
  }}
  let cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  let maxStack=0;
  dates.forEach(d=>{{ let stack=byMTD.reduce((s,r)=>s+(TD.filter(t=>t.d===d&&t.s===r.id).reduce((a,b)=>a+b.v,0)),0);maxStack=Math.max(maxStack,stack); }});
  maxStack*=1.15;
  drawAxes(ctx,w,h,pad,maxStack,dates.map(d=>d.slice(8)),'Cr');
  byMTD.forEach((r,i)=>{{ ctx.fillStyle=colors[i];ctx.fillRect(w-130,8+i*14,10,10);ctx.fillStyle='#e2e8f0';ctx.font='11px sans-serif';ctx.fillText(r.code,w-116,17+i*14); }});
  let barGap=3,barW=Math.max(8,cW/dates.length-barGap);
  let segments=[]; // store for hover
  dates.forEach((d,di)=>{{
    let x=pad.left+(cW/(dates.length-1)*di)-barW/2,sy=pad.top+cH;
    byMTD.forEach((r,si)=>{{ let v=TD.filter(t=>t.d===d&&t.s===r.id).reduce((a,b)=>a+b.v,0);sy-=(v/maxStack*cH);ctx.fillStyle=colors[si];ctx.fillRect(x,sy,barW,v/maxStack*cH);segments.push({{x:x,w:barW,t:sy,h:v/maxStack*cH,sbu:r.code,v:v,di:di,si:si}}); }});
  }});
  // Hover tooltip
  let tip=document.createElement('div');tip.id='t5-tip';tip.style.cssText='position:absolute;display:none;background:#0f172a;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:13px;pointer-events:none;border:1px solid #38bdf8;white-space:nowrap;z-index:99';
  let wrap=c.parentElement;if(wrap.style.position!=='relative') wrap.style.position='relative';wrap.appendChild(tip);
  c.onmousemove=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=segments.filter(s=>mx>=s.x&&mx<=s.x+s.w&&my>=s.t&&my<=s.t+s.h).pop();
    if(found){{
      tip.style.display='block';tip.style.left=(e.clientX-rect.left+12)+'px';tip.style.top=(e.clientY-rect.top-22)+'px';
      tip.textContent=found.sbu+': '+fmt(found.v,2)+' Cr';
      c.style.cursor='pointer';
    }}else{{ tip.style.display='none';c.style.cursor='crosshair'; }}
  }};
  c.onmouseleave=function(){{ tip.style.display='none'; }};
}}

function drawSBUChart(idx){{
  let r=ALL[idx],c=document.getElementById('c'+idx);if(!c||!r)return;
  let ctx=c.getContext('2d'),w=c.width,h=c.height,pad={{top:20,right:30,bottom:22,left:50}};
  ctx.clearRect(0,0,w,h);
  let days=TD.filter(t=>t.s===r.id);
  if(!days.length){{ctx.fillStyle='#64748b';ctx.font='13px sans-serif';ctx.fillText('No daily data for '+r.code,20,40);return;}}
  let dates=[...new Set(days.map(t=>t.d))].sort(),vals=dates.map(d=>days.filter(t=>t.d===d).reduce((a,b)=>a+b.v,0));
  let ymax=Math.max(...vals)*1.3||1,cW=w-pad.left-pad.right,cH=h-pad.top-pad.bottom;
  ctx.fillStyle='#f8fafc';ctx.font='bold 13px sans-serif';ctx.fillText(r.code+' Daily Revenue Trend (Cr) — Click bars for values',pad.left,pad.top-5);
  drawAxes(ctx,w,h,pad,ymax,dates.map(d=>d.slice(8)),'');
  let barGap=3,barW=Math.max(8,cW/dates.length-barGap);
  let sbuBars=[];
  let palette=['#38bdf8','#818cf8','#c084fc','#f472b6','#fbbf24','#4ade80','#fb923c'];
  vals.forEach((v,i)=>{{ let x=pad.left+(cW/(vals.length-1)*i)-barW/2,hb=(v/ymax*cH);let clr=palette[i%palette.length];ctx.fillStyle=i===vals.length-1?'#38bdf8':clr;ctx.fillRect(x,pad.top+cH-hb,barW,hb);ctx.fillStyle='#e2e8f0';ctx.font='10px monospace';ctx.fillText(fmt(v,2),x-3,pad.top+cH-hb-2);sbuBars.push({{x:x,w:barW,v:v,d:dates[i]}}); }});
  let cum=0,cumVals=vals.map(v=>cum+=v);
  ctx.strokeStyle='#fbbf24';ctx.lineWidth=2;ctx.setLineDash([4,3]);ctx.beginPath();
  cumVals.forEach((cv,i)=>{{ ctx.lineTo(pad.left+(cW/(cumVals.length-1)*i),pad.top+cH-(cv/Math.max(...cumVals)*1.15*cH)); }});
  ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#fbbf24';ctx.font='10px monospace';ctx.fillText('MTD:'+fmt(cum,2),pad.left+cW-55,pad.top+10);
  if(r.mtd_tgt_rev!=null){{ let tY=pad.top+cH-((r.mtd_tgt_rev/DE)/ymax*cH);ctx.strokeStyle='#f87171';ctx.lineWidth=1;ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(pad.left,tY);ctx.lineTo(pad.left+cW,tY);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#f87171';ctx.font='10px monospace';ctx.fillText('Tgt/day:'+fmt(r.mtd_tgt_rev/DE,2),pad.left,tY-3); }}
  // Click to show value
  c.onclick=function(e){{
    let rect=c.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;
    let found=sbuBars.find(b=>mx>=b.x&&mx<=b.x+b.w&&my>=pad.top&&my<=pad.top+cH);
    if(found){{ let old=c.dataset.selected; if(old==found.d){{ delete c.dataset.selected;ctx.clearRect(0,0,w,h);drawSBUChart(idx);return; }}
      c.dataset.selected=found.d;ctx.save();ctx.fillStyle='#fbbf24';ctx.font='bold 11px sans-serif';
      ctx.fillText(found.d.slice(5)+': '+fmt(found.v,2)+' Cr',found.x+found.w/2-30,pad.top+cH-(found.v/ymax*cH)-10);ctx.restore();
    }}
  }};
}}

function drawSBUDetail(idx){{
  let r=ALL[idx],el=document.getElementById('sd-'+idx);
  if(!el||!r)return;
  let sbu=r.id;
  let bdtMap=TD_BDT[sbu]||{{}};
  let ordMap={{}};
  ORD_TD.forEach(t=>{{ if(t.s===sbu) ordMap[t.d]=(ordMap[t.d]||0)+t.c; }});
  let dates=[...new Set([...Object.keys(bdtMap),...Object.keys(ordMap)])].sort();
  let moTgt=r.mo_tgt_rev;
  let dayTgtBdt = moTgt!=null ? moTgt*10000000/DM : null;
  let moTgtBdt = moTgt!=null ? moTgt*10000000 : null;
  let dailyOrders=ORD_DAILY[sbu]||0;
  let mtdOrders=ORD_MTD[sbu]||0;
  let bdt=n=>Math.round(n).toLocaleString('en-US');
  let sumRev=0,sumOrd=0;
  let rows='';
  dates.forEach(d=>{{
    let rev=bdtMap[d]||0, ord=ordMap[d]||0;
    sumRev+=rev; sumOrd+=ord;
    rows+=`<tr><td>${{d.slice(5)}}</td><td class="num rev">${{bdt(rev)}}</td><td class="num">${{ord.toLocaleString('en-US')}}</td><td class="num">${{dayTgtBdt!=null?bdt(dayTgtBdt):'—'}}</td></tr>`;
  }});
  let sumTgt = dayTgtBdt!=null ? dayTgtBdt*dates.length : null;
  el.innerHTML=`
    <div class="sbu-detail-summary">
      <span>Daily Orders: <b>${{dailyOrders.toLocaleString('en-US')}}</b></span>
      <span>MTD Orders: <b>${{mtdOrders.toLocaleString('en-US')}}</b></span>
      <span>Daily Rev Target: <b>${{dayTgtBdt!=null?bdt(dayTgtBdt)+' BDT':'—'}}</b></span>
      <span>Monthly Rev Target: <b>${{moTgtBdt!=null?bdt(moTgtBdt)+' BDT':'—'}}</b></span>
    </div>
    <div class="sbu-detail-table"><table>
      <thead><tr><th>Date</th><th class="num">Revenue (BDT)</th><th class="num">Orders</th><th class="num">Rev Target (BDT)</th></tr></thead>
      <tbody>${{rows}}</tbody>
      <tfoot><tr><td>Total</td><td class="num rev">${{bdt(sumRev)}}</td><td class="num">${{sumOrd.toLocaleString('en-US')}}</td><td class="num">${{sumTgt!=null?bdt(sumTgt):'—'}}</td></tr></tfoot>
    </table></div>`;
}}

window.addEventListener('load',function(){{ document.getElementById('loading-overlay').classList.add('hidden'); try{{ drawPortfolioDaily(); drawTop5Stacked(); }}catch(e){{ }} }});
// Set date filter bounds from available FY history
(function(){{
  let mn=null,mx=null;
  Object.values(HIST_REV).forEach(m=>Object.keys(m).forEach(d=>{{ if(!mn||d<mn)mn=d; if(!mx||d>mx)mx=d; }}));
  let ds=document.getElementById('df-start'), de=document.getElementById('df-end');
  if(mn){{ ds.min=mn; de.min=mn; }} if(mx){{ ds.max=mx; de.max=mx; }}
}})();
</script>
</body>
</html>'''


class LiveHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')

        if path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            import json as _json
            try:
                conn = get_conn()
                c = conn.cursor()
                c.execute("SELECT 1")
                conn.close()
                self.wfile.write(_json.dumps({"status":"ok","db":"connected"}).encode())
            except Exception as e:
                self.wfile.write(_json.dumps({"status":"error","db":str(e)}).encode())
            return

        if path in ('', '/', '/report'):
            try:
                rd = detect_report_date()
                data = get_report_data(rd)
                html = build_html(data)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                import traceback
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                err = traceback.format_exc()
                self.wfile.write(err.encode())
                print(f"ERROR: {e}", flush=True)
            return

        # Serve static files
        if path.startswith('/'):
            path = path[1:]
        file_path = ROOT / (path or 'index.html')
        if file_path.exists() and file_path.suffix in ('.html', '.js', '.css', '.ico'):
            self.send_response(200)
            ct = 'text/html' if file_path.suffix == '.html' else 'text/javascript' if file_path.suffix == '.js' else 'text/css'
            self.send_header('Content-Type', ct)
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
            return

        return super().do_GET()

    def log_message(self, fmt, *args):
        print(f'[{datetime.now().strftime("%H:%M:%S")}] {args[0]}', flush=True)


class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in separate threads so a slow DWH query doesn't block other requests."""
    daemon_threads = True

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', PORT)))
    ap.add_argument('--host', default=os.environ.get('HOST', HOST))
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    PORT, HOST = args.port, args.host

    os.chdir(str(ROOT))
    server = ThreadedHTTPServer((HOST, PORT), LiveHandler)
    url = f'http://{HOST}:{PORT}'
    print(f'ARL Live Flash Report running at {url}', flush=True)
    print('Auto-detects T-1 date · Fresh DWH queries on every load', flush=True)
    print('Press Ctrl+C to stop', flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.shutdown()
