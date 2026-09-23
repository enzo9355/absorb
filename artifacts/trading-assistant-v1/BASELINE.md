# Task0 baseline

- HEAD b56e9f1850f14c7bedcf663b69ca411188d9fdc6 branch codex/tw-premarket-verified-overlay
- dirty 36 files (see git-status.txt, git-diff-stat.txt), untracked: artifacts/, docs/superpowers/plans/2026-09-24-trading-assistant-v1.md, static/samples/, stock_papi/integrations/line/press_block.py
- must-include dirty: LINE flex/presentation/webhook, conversation policies/web, app_factory, market.py, stock_detail/base/dashboard templates, app.css/js, route_inventory/web_product tests
- baseline tests: 98 tests OK (see baseline-tests.log)
- raw snapshot reader: stock_papi/services/observation_view.py verified-fields reader; trade rule must read raw daily not chart补值
- style source: no scripts/build_css.py, no check_ui.sh, no .github/workflows; source is static/app.css direct edit
- auth: stock_papi/web/routes/auth.py register_auth_routes with server session + CSRF; Store: line_state.py FirestoreStore/SupabaseStore with update() optimistic concurrency
- worktrees: many, no new worktree created (avoid assuming uncommitted LINE styles in new worktree)
- formal site unread: does not block local dev
