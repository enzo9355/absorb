# Migration

- Data-root migration: [`migrate_stock_papi_data_to_absorb.ps1`](../../scripts/migrate_stock_papi_data_to_absorb.ps1)
- Scheduler migration: [`migrate_stock_papi_tasks_to_absorb.ps1`](../../scripts/migrate_stock_papi_tasks_to_absorb.ps1)
- Cutover and rollback: [`absorb-cutover-checklist.md`](../absorb-cutover-checklist.md)

Both migrations preserve the old data and tasks until a separately approved cutover succeeds.
