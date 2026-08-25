"""
Cloud deploy for ARL Flash Report (GitHub Actions).
Builds the T-1 report from DWH and writes to a target index.html path.
DWH creds come from env: DWH_SERVER, DWH_USER, DWH_PASSWORD (DWH_PORT optional).
Usage: python deploy_cloud.py <output_path>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_server import detect_report_date, get_report_data, build_html


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    rd = detect_report_date()
    print(f"Report date: {rd}")
    data = get_report_data(rd)
    html = build_html(data)
    with open(target, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Written {target} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
