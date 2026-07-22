# Design Spec: ABSORB Task C Regression Explainer & Research Presentation Layer

**Date:** 2026-07-22  
**Status:** DRAFT (Pending Independent Diff Review)  
**Target Branch:** `antigravity/task-c-regression-explainer-design`  
**Base SHA:** `39d66adb23d2795143ccac7bf3661db97192e054`  
**Repository:** `enzo9355/absorb`  

---

## 1. Context

ABSORB Task A & B (`PR #5`) established the Institutional Post-close Report architecture, creating structured observation metadata (`ReportMetadataV2`) and canonical professional reports (`ProfessionalPostCloseReport`). Task `PR #6` unified Canonical Object Size Contracts and verified route loading integrity.

Under current model governance, the prediction capability gates (`ranking`, `calibration`, `quality`, `transaction_value`) remain **BLOCKED** or **UNAVAILABLE**. Consequently, the system is strictly prohibited from generating formal probability outputs, win rates, or trading signals.

Task C introduces the **Regression Explainer & Research Presentation Layer**. This layer computes verifiable, econometric regression factor exposures (e.g., OLS linear factor relationships) from historical observation data, packages the results into an immutable research artifact, binds it to the canonical report, and presents it in the `quantitative_research` section of the institutional post-close report under strict statistical and disclosure governance.

---

## 2. Goals

1. **Immutable Research Artifact**: Define a content-addressed `RegressionResearchArtifact` schema (`schema_version = 1`, `kind = "absorb-regression-research-artifact"`) to store deterministic regression estimates, diagnostics, and statistical summaries.
2. **Strict Statistical Contract**: Enforce automated validation for regression inputs, sample size boundaries ($n \ge 30$), non-finite value rejections, confidence interval ordering ($\text{ci\_low} \le \text{coefficient} \le \text{ci\_high}$), and residual diagnostics.
3. **Canonical & Metadata Binding**: Extend `ReportMetadataV2` and `ProfessionalReportIdentity` pointer semantics to bind the regression artifact via `object` path and `content_sha256`.
4. **Fail-Closed Failure Semantics**: Ensure that missing, corrupted, or statistically invalid regression artifacts mark `quantitative_research` section as `status = "unavailable"` with explicit failure reasons, preserving report HTTP 200 availability for critical sections (`market`, `governance`).
5. **Strict Disclosure & Wording Governance**: Enforce mandatory disclosure text and AI labeling while forbidding uncalibrated predictive terminology (`Probability`, `勝率`, `上漲機率`, `下跌機率`, `正式預測`, `買進訊號`, `賣出訊號`).
6. **Cross-Surface Compatibility**: Guarantee HTML view-model safety and design interfaces for future PDF, LINE, and Gemini presentation adapters.

---

## 3. Non-Goals

- **No LightGBM / Tree Model Training**: Task C focuses exclusively on linear/econometric regression explainers.
- **No SHAP / Tree Explainer Integration**: SHAP value calculation for tree models is out of scope.
- **No Probability Calibration / Model Promotion**: Prediction capability gates remain blocked. No probability or win rate outputs are generated.
- **No Buy / Sell Signals**: No trading recommendations, entry/exit signals, or price targets are generated.
- **No Task D Execution**: Task D (Weekly Model / Production Cutover) is strictly prohibited.
- **No Production Deployment / GCS Mutation**: No Cloud Run deployments, GCS updates, backfills, or LINE notifications.

---

## 4. Existing Architecture

The existing report generation and publication flow consists of:
1. `reporting/observation_v2.py`: Aggregates TWSE/TPEx observation data into `ReportMetadataV2`.
2. `reporting/professional_builder.py`: Builds `ProfessionalPostCloseReport` containing 9 standard sections (`market`, `capital_flows`, `industries`, `securities`, `quantitative_research`, `validation`, `next_session`, `governance`, `ai_reference`).
3. `reporting/professional_binding.py`: Cross-checks identity, metadata, pointer SHA, and route parameters.
4. `reporting/publisher.py`: Writes canonical object (`objects/canonical/<sha256>.json`) and metadata (`metadata/v2/<date>.json`) atomically with read-back hash verification.
5. `stock_papi/web/routes/reports.py`: Loads metadata and raw bytes of canonical object, validates binding, and passes Jinja-safe view model to HTML template (`templates/reports/post_close_professional.html`).

Currently, `quantitative_research` section in `professional_builder.py` contains static gate status (`gates.promotion = "BLOCKED"`) and `probability_allowed = False`.

---

## 5. Selected Architecture: Approach B (Independent Content-Addressed Regression Research Artifact)

We select **Approach B**, which creates a separate, content-addressed `RegressionResearchArtifact` stored under `objects/regression/<content_sha256>.json` (or relative path in GCS/archive), bound via a pointer in `ReportMetadataV2` and `ProfessionalReportIdentity`.

```
+-----------------------------------------------------------------------------------+
|                            Observation Pipeline                                   |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
                    +------------------------------------------+
                    |   Regression Explainer Adapter/Builder   |
                    +------------------------------------------+
                                          |
                                          v
              +------------------------------------------------------+
              |  RegressionResearchArtifact (Content-Addressed)     |
              |  Path: objects/regression/<content_sha256>.json      |
              +------------------------------------------------------+
                                          |
                   +----------------------+----------------------+
                   | Pointer & SHA                               | SHA & Summary
                   v                                             v
+------------------------------------+        +------------------------------------+
|         ReportMetadataV2           |        |    ProfessionalPostCloseReport     |
| pointer.regression_research = {    |        | quantitative_research.data = {     |
|   "object": "objects/...",         |        |   "artifact_sha256": "...",        |
|   "content_sha256": "..."          |        |   "summary": { ... }               |
| }                                  |        | }                                  |
+------------------------------------+        +------------------------------------+
```

### Rationale for Selecting Approach B:
1. **Content-Addressed Storage & Immutability**: Regression computations are deterministic and bound to the source observation snapshot. Hash-addressing guarantees zero tampering.
2. **Schema Decoupling**: The regression schema (`regression_spec_version = 1`) can evolve independently without bloating `ProfessionalPostCloseReport` core schema.
3. **Failure Isolation**: If regression computation fails or artifact is missing, `quantitative_research` section status evaluates to `"unavailable"` gracefully. The primary post-close report remains valid (200 OK).
4. **Pre-market Lineage Protection**: Pre-market pipeline reads raw observation core without depending on regression artifacts.

---

## 6. Alternatives Considered

### Approach A: Direct Embedding into Professional Canonical Report
- *Description*: Store full regression matrices, t-stats, and residual statistics directly inside `document["quantitative_research"]["data"]`.
- *Drawbacks*: Bloats the canonical report JSON beyond target size; couples statistical spec changes directly to `PROFESSIONAL_REPORT_SCHEMA_VERSION`; complicates schema validation for optional regression runs.

### Approach C: View-Model-Only On-The-Fly Computation
- *Description*: Calculate regression on demand when serving HTTP route requests.
- *Drawbacks*: Violates zero-runtime-computation invariant for report routes; causes non-deterministic HTML renders; loses content-addressed auditability; risks route timeouts (503).

---

## 7. Artifact Schema (`RegressionResearchArtifact`)

Path: `reporting/regression_schema.py`

```python
REGRESSION_ARTIFACT_SCHEMA_VERSION = 1
REGRESSION_ARTIFACT_KIND = "absorb-regression-research-artifact"
```

### JSON Structure:
```json
{
  "schema_version": 1,
  "kind": "absorb-regression-research-artifact",
  "identity": {
    "artifact_id": "TW-20260717-regression-ols-v1",
    "market": "TW",
    "source_market_date": "2026-07-17",
    "applicable_trading_date": "2026-07-20",
    "generated_at": "2026-07-17T10:30:00Z",
    "source_manifest": "quant/v1/manifests/TW-20260717T103000Z-a1b2c3d4e5f6.json",
    "source_manifest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "source_observation_content_sha256": "f4c1b2a3890e...64hex",
    "code_commit_sha": "39d66adb23d2795143ccac7bf3661db97192e054",
    "generator_version": "1.0.0",
    "content_sha256": "a1b2c3d4...64hex",
    "regression_spec_version": "1.0"
  },
  "regression_spec": {
    "model_family": "ols_linear_factor",
    "dependent_variable": "five_day_relative_return",
    "independent_variables": [
      "volume_surge_ratio",
      "foreign_net_flow_ratio",
      "industry_momentum_score",
      "volatility_20d"
    ],
    "intercept": true,
    "frequency": "daily",
    "observation_start_date": "2025-07-17",
    "observation_end_date": "2026-07-17",
    "sample_count": 245,
    "missing_value_policy": "listwise_deletion",
    "standardization_policy": "z_score",
    "outlier_policy": "winsorize_1_99",
    "covariance_estimator": "hc3_robust",
    "confidence_level": 0.95
  },
  "results": [
    {
      "factor_name": "volume_surge_ratio",
      "display_label": "成交量異常放大比率",
      "coefficient": 0.0425,
      "standard_error": 0.0112,
      "t_statistic": 3.7946,
      "p_value": 0.0002,
      "confidence_interval_low": 0.0205,
      "confidence_interval_high": 0.0645,
      "direction": "positive",
      "economic_magnitude": "moderate",
      "display_status": "statistically_significant"
    },
    {
      "factor_name": "foreign_net_flow_ratio",
      "display_label": "外資買賣超占成交量比率",
      "coefficient": 0.0812,
      "standard_error": 0.0195,
      "t_statistic": 4.1641,
      "p_value": 0.0001,
      "confidence_interval_low": 0.0428,
      "confidence_interval_high": 0.1196,
      "direction": "positive",
      "economic_magnitude": "strong",
      "display_status": "statistically_significant"
    }
  ],
  "fit_statistics": {
    "r_squared": 0.2845,
    "adjusted_r_squared": 0.2726,
    "residual_standard_error": 0.0312,
    "degrees_of_freedom": 240,
    "f_statistic": 23.84,
    "f_p_value": 0.000001
  },
  "diagnostics": {
    "multicollinearity": {
      "status": "passed",
      "max_vif": 2.14,
      "vif_details": {
        "volume_surge_ratio": 1.42,
        "foreign_net_flow_ratio": 1.85,
        "industry_momentum_score": 2.14,
        "volatility_20d": 1.31
      }
    },
    "heteroskedasticity": {
      "status": "passed",
      "test_name": "white_test",
      "p_value": 0.184
    },
    "autocorrelation": {
      "status": "passed",
      "durbin_watson": 1.94
    },
    "residual_normality": {
      "status": "passed",
      "jarque_bera_p_value": 0.125
    },
    "data_quality": {
      "missing_rate": 0.0,
      "outlier_count": 3
    },
    "warnings": []
  },
  "presentation": {
    "headline": "近 245 個交易日因子迴歸分析顯示外資動向與成交量異常具有統計顯著相關性",
    "summary": "在控制 20 日波動度與產業動能後，外資買賣超比率與成交量放大比率對個股 5 日相對報酬展現正向係數關係 (p < 0.01)。",
    "key_exposures": [
      "外資買賣超比率: 係數 +0.0812 (t=4.16, p < 0.001)",
      "成交量放大比率: 係數 +0.0425 (t=3.79, p < 0.001)"
    ],
    "limitations": "本分析為歷史 OLS 迴歸結果，反映過去 245 個交易日之統計相關性，不代表未來因果關係。",
    "disclosure": "模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"
  }
}
```

---

## 8. Data Lineage & Point-In-Time Rules

1. **Strict Window Bound**: `observation_end_date` MUST satisfy `observation_end_date <= source_market_date`.
2. **No Future Data**: `observation_start_date` and `observation_end_date` cannot utilize market data or observations after `source_market_date`.
3. **Manifest Lineage**: Artifact identity must include `source_manifest` and `source_manifest_sha256`.
4. **Code Lineage**: Artifact identity must record `code_commit_sha` (40-hex Git commit) and `generator_version`.
5. **Content Lineage**: `content_sha256` is computed over canonical sorted JSON bytes of the document excluding self-referential hash fields during calculation.

---

## 9. Statistical Contract

1. **Sample Count Minimum**: $n \ge 30$. If $n < 30$, the builder MUST NOT publish the artifact and marks the section `status = "unavailable"`, `reason = "迴歸樣本數不足 (n < 30)"`.
2. **Confidence Intervals**: Must strictly enforce $\text{ci\_low} \le \text{coefficient} \le \text{ci\_high}$.
3. **Standard Errors**: Must satisfy $\text{standard\_error} \ge 0.0$.
4. **Goodness of Fit**: $0.0 \le R^2 \le 1.0$ and Adjusted $R^2 \le R^2$.
5. **Numeric Finite Check**: All floating point numbers must be finite numbers. Any `NaN`, `Infinity`, `-Infinity`, or `bool` values passed as numbers cause immediate validation failure.
6. **p-Value Interpretation**:
   - $p < 0.05$: Marked as `display_status = "statistically_significant"`.
   - $p \ge 0.05$: Marked as `display_status = "statistically_insignificant"`. Insignificant factors must be rendered with neutral styling in HTML and excluded from executive summary key exposures.
   - p-value does NOT imply economic causality or predictive probability.

---

## 10. Fail-Closed Validation Rules

The module `reporting/regression_schema.py` will implement `RegressionResearchArtifact.from_document(doc)` with fail-closed rules:

1. **Type Checks**: Reject non-dict root, wrong `schema_version` != 1, wrong `kind` != `"absorb-regression-research-artifact"`.
2. **Identity Checks**: Validate SHA hex formats (64-hex SHA-256, 40-hex commit SHA), ISO dates (`observation_start_date <= observation_end_date <= source_market_date`).
3. **Numeric Checks**: Check `sample_count` is `int` (reject `bool`), `sample_count >= 30`. Check $R^2$ and Adjusted $R^2$ within $[0.0, 1.0]$.
4. **Result Array Checks**: Each result item must contain `factor_name`, `display_label`, `coefficient`, `standard_error`, `t_statistic`, `p_value`, `confidence_interval_low`, `confidence_interval_high`. Reject if `confidence_interval_low > coefficient` or `coefficient > confidence_interval_high`.

---

## 11. Publication Flow

```
[Observation Data & Manifest Verified]
                    │
                    ▼
[Run Regression Builder & Statistical Validation]
                    │
           ┌────────┴────────┐
        Valid?             Invalid / n < 30?
           │                         │
           ▼                         ▼
[Write objects/regression/   [Set quantitative_research]
   <sha256>.json]            [status = "unavailable"   ]
           │                         │
           ▼                         │
[Bind Pointer in Report]             │
[Metadata & Canonical  ]             │
[Post-Close Report     ]             │
           │                         │
           └────────┬────────────────┘
                    │
                    ▼
[Write Canonical Object & Metadata Atomically]
```

1. **Step 1**: `build_regression_research_artifact(...)` executes regression estimation.
2. **Step 2**: Validate artifact document via `RegressionResearchArtifact.from_document(...)`.
3. **Step 3**: If valid, `publisher.py` writes `objects/regression/<sha256>.json` atomically, performs post-write read-back verification of `content_sha256`.
4. **Step 4**: Update `ReportMetadataV2` with `regression_research` pointer block:
   ```json
   "regression_research": {
     "object": "objects/regression/a1b2c3d4...json",
     "sha256": "a1b2c3d4...json_file_sha256",
     "content_sha256": "a1b2c3d4...content_sha256",
     "schema_version": 1,
     "generator_version": "1.0.0",
     "code_commit_sha": "39d66adb23d2795143ccac7bf3661db97192e054"
   }
   ```
5. **Step 5**: Update `ProfessionalPostCloseReport`'s `quantitative_research` section data with summary and pointer SHA.
6. **Step 6**: Complete atomic publish of canonical post-close report and metadata.

---

## 12. Canonical & Metadata Binding Rules

Path: `reporting/professional_binding.py`

When `validate_professional_report_binding(...)` executes:
1. If `metadata.regression_research` pointer is present:
   - Check `pointer.object` strictly matches regex `^objects/regression/[0-9a-f]{64}\.json$`.
   - Check `pointer.content_sha256` matches artifact identity `content_sha256`.
   - Check `pointer.code_commit_sha` matches report identity `code_commit_sha`.
2. If `metadata.regression_research` is `None`:
   - Verify `report.quantitative_research.status` is `"unavailable"`.

---

## 13. HTML Presentation & View Model Rules

Path: `reporting/professional_html.py` & `templates/reports/post_close_professional.html`

### View Model Mapping:
`build_professional_report_view(report)` populates `quantitative_research`:
- Status: `report.quantitative_research.status` (`"available"` or `"unavailable"`).
- Section Title: `"量化與迴歸因子研究"`
- AI Label: `"AI 模型參考建議"`
- Model Output Label: `"模型方向參考"`
- Fixed Disclaimer: `"模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"`

### HTML Rendering Behavior:
- **If Available**:
  - Displays summary headline & key factor exposures table (`Factor Name`, `Coefficient`, `t-Stat`, `p-Value`, `95% CI`, `Status`).
  - Statistically significant factors ($p < 0.05$) highlighted in navy/mint; insignificant factors ($p \ge 0.05$) styled in muted gray with label `統計未達顯著`.
  - Displays model fit stats ($R^2$, Adjusted $R^2$, Sample Count $n$) and diagnostic status badges.
  - Displays explicit limitations box: *"本分析為歷史 OLS 迴歸結果，反映過去 245 個交易日之統計相關性，不代表未來因果關係。"*
- **If Unavailable**:
  - Displays structured alert card: *"量化迴歸研究暫不提供：[reason]"*.
  - **Does NOT crash or return HTTP 503.**

---

## 14. PDF / LINE / Gemini Future Compatibility

1. **PDF Generator Adapter**: `reporting/pdf_generator.py` will read `report_view["quantitative_research"]` and render a dedicated 1-page compact factor matrix table when `status == "available"`.
2. **LINE Flex Message Adapter**: `stock_papi/integrations/line/` will render a compact 2-line summary card under `"模型方向參考"` showing top positive/negative factor exposures.
3. **Gemini Prompt Adapter**: `stock_papi/services/papi_service.py` will format regression coefficients into context prompts strictly wrapped with mandatory disclaimers and forbidden wording filters.

---

## 15. Failure Semantics & Fail-Closed Hierarchy

| Failure Scenario | Behavior | HTTP Status | Log Level |
|---|---|---|---|
| Regression calculation error ($n < 30$, matrix singular) | Section status set to `"unavailable"`, report published normally | 200 OK | WARNING |
| Regression artifact JSON corrupt / read error | Section status evaluated as `"unavailable"` in view model | 200 OK | ERROR |
| Canonical Post-Close Report object corrupted | Route catches `ReportWebError` | 503 Service Unavailable | ERROR |
| Critical section (`market`, `governance`) missing | Schema validation fails | 503 Service Unavailable | CRITICAL |

*Key Principle*: Quantitative research regression failures are non-fatal to the broader post-close report availability.

---

## 16. Security & Leakage Prevention

1. **Path Traversal Protection**: Regression object paths strictly enforced via regex `^objects/regression/[0-9a-f]{64}\.json$`.
2. **Error Message Redaction**: Exception messages caught during route loading must NOT leak absolute file paths, bucket names, or stack trace snippets.
3. **XSS & Injection Protection**: Factor labels and text summaries HTML-escaped via Jinja2 auto-escaping.
4. **Data Isolation**: Research data and regression artifacts strictly isolated from pre-market raw core lineage.

---

## 17. Testing Strategy

1. **Unit Tests for Schema (`tests/test_regression_schema.py`)**:
   - Round-trip serialization/deserialization.
   - Rejection of invalid dates, non-finite values, $n < 30$, unordered CIs ($\text{ci\_low} > \text{ci\_high}$).
   - Rejection of forbidden wording (`Probability`, `勝率`, etc.).
2. **Unit Tests for Builder & Validation (`tests/test_regression_builder.py`)**:
   - Verified regression fitting on synthetic datasets.
   - Diagnostic checks (VIF, Durbin-Watson, Jarque-Bera).
   - Insufficient sample fallback ($n < 30 \rightarrow \text{unavailable}$).
3. **Unit Tests for Binding & Publisher (`tests/test_regression_publisher.py`)**:
   - Content SHA hash verification.
   - Atomic write and read-back hash comparison.
   - Metadata pointer cross-validation.
4. **Unit Tests for HTML View & Routes (`tests/test_regression_route.py`)**:
   - HTML view model structure validation.
   - Availability fallback: verified rendering of 200 OK with `"unavailable"` card when artifact is missing.
   - Forbidden wording scan across HTML renders.
5. **Full Regression Suite**: Ensure all 717 existing tests continue to pass without regression.

---

## 18. Migration & Compatibility

- **Backward Compatibility**: `ReportMetadataV2` field `regression_research` is optional (`dict | None = None`). Older metadata documents lacking `regression_research` remain 100% valid and default to `quantitative_research.status = "unavailable"`.
- **Schema Versioning**: `PROFESSIONAL_REPORT_SCHEMA_VERSION = 1` remains unchanged; `quantitative_research` data schema extended gracefully.

---

## 19. Rollback Plan

If regression explainer components need to be rolled back:
1. Revert `regression_research` pointer generation in `reporting/observation_v2.py`.
2. `professional_builder.py` will omit regression artifact references and output `quantitative_research.status = "unavailable"`.
3. Reports rendered prior to rollback remain intact due to immutable content-addressed storage.

---

## 20. Production Safety Declarations

- **No Cloud Run Deployment**: Code and design changes remain strictly in repository docs/branches.
- **No Production Traffic Change**: No route rules or DNS modified.
- **No Production GCS Mutation**: No uploads or pointer updates executed against live production GCS buckets.
- **No LINE Notification Triggered**: No push or broadcast notifications sent.
- **No Task D Execution**: Task D remains strictly uninitiated.
