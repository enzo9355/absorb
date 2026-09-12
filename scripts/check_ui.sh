#!/bin/sh
# ORDER 4：介面層每次交付要跑的測試集合。
# M-7 只指名 tests.test_web_product，但 ORDER 3 新增 /_catalog 路由時
# tests.test_route_inventory 就紅了而沒人發現 —— 單一模組的檢查太窄。
set -e
python3 scripts/build_css.py --check
python3 -m unittest \
  tests.test_web_product \
  tests.test_absorb_brand \
  tests.test_us_presentation_regression \
  tests.test_observation_public_surfaces \
  tests.test_report_web \
  tests.test_reports_template \
  tests.test_professional_report_html \
  tests.test_route_inventory \
  "$@"
