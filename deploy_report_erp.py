"""
Deploy the ARL flash report using the LIVE ERP (via enterprise-api-gateway MCP)
as the data source, instead of the stalled DWH.
"""
import os
import subprocess
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_server
from erp_client import erp_query

PAGES_DIR = r"C:\Users\Hp\Documents\Default Project\arl-flash-pages"
OUTPUT = os.path.join(PAGES_DIR, "index.html")


class _FakeCursor:
    def execute(self, sql):
        sql2 = sql.replace("DWH.", "").replace("Arc", "")
        self._rows = erp_query(sql2)

    def fetchall(self):
        return [tuple(r) for r in self._rows]

    def fetchone(self):
        return tuple(self._rows[0]) if self._rows else None


class _FakeConn:
    def cursor(self):
        return _FakeCursor()

    def close(self):
        pass


def deploy():
    live_server.get_conn = lambda: _FakeConn()

    rd = date.today() - timedelta(days=1)  # T-1
    print(f"Report date: {rd}")
    data = live_server.get_report_data(rd)
    html = live_server.build_html(data)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML written: {OUTPUT} ({len(html)} bytes)")

    os.chdir(PAGES_DIR)
    subprocess.run(["git", "add", "index.html"], check=True, capture_output=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        print("No changes — already up to date.")
        return

    subprocess.run(["git", "commit", "-m", f"Update report for {rd.strftime('%Y-%m-%d')}"], check=True, capture_output=True)
    subprocess.run(["git", "push"], check=True, capture_output=True)
    print("Deployed! https://ahmedahnaf-arl.github.io/arl-flash-report-live/")


if __name__ == "__main__":
    deploy()
