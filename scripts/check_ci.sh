#!/bin/sh
# Linux CI 能跑的測試範圍。
#
# 完整的 `unittest discover` 在 Linux 上會有 54 個紅的，但**沒有一個是程式壞了**：
# 這個 repo 的發布與排程層是 PowerShell（.ps1 / cscript.exe / D:\ 路徑），
# 那些測試會真的去叫 powershell.exe，在 Linux 容器裡必然 FileNotFoundError。
# 另外有兩個模組需要 statsmodels，那不在 requirements.txt 裡（研究用的選用依賴）。
#
# 所以這裡明確排除那些模組，其餘全部要綠。排除清單要寫理由，
# 不寫理由的排除等於把測試偷偷關掉。
#
# 驗證方式：2026-09-12 在 py3.11 上，排除後 discover 的結果是 OK。
set -e

python3 scripts/build_css.py --check

# 需要 Windows（powershell.exe / cscript.exe / D:\ 資料根目錄）
WINDOWS_ONLY="
test_pipeline_scheduler
test_uploader_strictmode
test_observation_release_scripts
test_local_quant_task
test_local_quant
test_tw_observation_recovery
test_hidden_scheduler
test_task_scheduler_restart_probe
test_catch_up_latest_completed_session
test_absorb_config
"

# 需要 statsmodels（不在 requirements.txt）
OPTIONAL_DEPS="
test_regression_adapter
test_regression_builder
test_cold_start_imports
"

# 需要 CJK 字型才能產出可抽取文字的 PDF
NEEDS_FONTS="
test_daily_report_pdf
"

EXCLUDE="$WINDOWS_ONLY $OPTIONAL_DEPS $NEEDS_FONTS"

MODULES=""
for path in tests/test_*.py; do
  name=$(basename "$path" .py)
  skip=""
  for excluded in $EXCLUDE; do
    [ "$name" = "$excluded" ] && skip=1 && break
  done
  [ -n "$skip" ] || MODULES="$MODULES tests.$name"
done

# shellcheck disable=SC2086
python3 -m unittest $MODULES "$@"
