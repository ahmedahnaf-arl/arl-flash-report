"""
Cloud deploy for ARL Flash Report (GitHub Actions).
Builds the T-1 report from the live ERP (via enterprise-api-gateway) and writes
both portal pages:
  page 1 — <output_path>          (ERP flash dashboard)
  page 2 — october-tracker.html   (October Revenue tracker) in the same folder
Usage: python deploy_cloud.py <output_path>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_server import detect_report_date, get_report_data, build_html, build_tracker_html


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    tracker_target = os.path.join(os.path.dirname(os.path.abspath(target)), "october-tracker.html")

    rd = detect_report_date()
    print(f"Report date: {rd}")
    data = get_report_data(rd)

    html = build_html(data)
    with open(target, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Written {target} ({len(html)} bytes)")

    tracker_html = build_tracker_html(data)
    with open(tracker_target, "w", encoding="utf-8") as f:
        f.write(tracker_html)
    print(f"Written {tracker_target} ({len(tracker_html)} bytes)")


if __name__ == "__main__":
    main()
