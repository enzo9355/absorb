# Design Spec: ABSORB Task C Regression Explainer & Research Presentation Layer

**Date:** 2026-07-22  
**Status:** DRAFT — Pending Independent Review  
**Target Branch:** `antigravity/task-c-regression-explainer-design`  
**Base SHA:** `da25d594d3b76865da22b891285ac0c85e710d86`  
**Repository:** `enzo9355/absorb`  

---

## 1. Context

ABSORB Task A & B (`PR #5`) established the Institutional Post-close Report architecture, creating structured observation metadata (`ReportMetadataV2`) and canonical professional reports (`ProfessionalPostCloseReport`). Task `PR #6` and its restoration (`PR #8`, merged at `da25d594d3b76865da22b891285ac0c85e710d86`) unified Canonical Object Size Contracts (`MAX_CANONICAL_REPORT_BYTES = 5_000_000`) and verified route loading integrity.

Under current model governance, the prediction capability gates (`ranking`, `calibration`, `quality`, `transaction_value`) remain **BLOCKED** or **UNAVAILABLE**. Consequently, the system is strictly prohibited from generating formal probability outputs, win rates, or trading signals.

Task C introduces the **Regression Explainer & Research Presentation Layer**. This layer computes verifiable, econometric regression factor exposures from historical market observation data, packages the results into an immutable research artifact, binds it to report metadata and canonical reports, and presents it in the `quantitative_research` section of the institutional post-close report under strict statistical, point-in-time, and disclosure governance.

---

## 2. Goals

1. **Immutable Research Artifact**: Define a content-addressed `RegressionResearchArtifact` schema (`schema_version = 1`, `kind = "absorb-regression-research-artifact"`) stored at `objects/regression/<object_sha256>.json` to store deterministic OLS regression estimates, HAC robust covariance diagnostics, and statistical summaries.
2. **Strict Point-in-Time & Leakage Prevention**: Enforce explicit temporal boundaries (`feature_start_date`, `feature_end_date`, `label_start_date`, `label_end_date`, `label_horizon_sessions = 5`) where `feature_date < label_end_date <= source_market_date`, calculated via trading calendar to prevent forward look-ahead label leakage.
3. **Robust Statistical Contract & HAC Covariance**: Enforce automated validation for OLS regression estimates, Newey-West HAC robust standard errors (`hac_max_lags = 4`), sample size policies ($n < 30 \rightarrow \text{unavailable}$, $30 \le n < 60 \rightarrow \text{available\_with\_limited\_sample\_warning}$, $60 \le n \le 252 \rightarrow \text{available}$), non-finite value rejections, confidence interval ordering ($\text{ci\_low} \le \text{coefficient} \le \text{ci\_high}$), and Breusch-Pagan heteroskedasticity diagnostics.
4. **Canonical & Metadata Binding without Schema v1 Mutation**: Keep `ProfessionalReportIdentity` (`schema_version = 1`) unchanged. Bind the full content-addressed pointer in `ReportMetadataV2.regression_research` and store a summary reference in `ProfessionalPostCloseReport.quantitative_research.data.regression_reference`.
5. **Dedicated Raw-Bytes Loader & Graceful Failure Semantics**: Add `load_regression_object(object_path, max_bytes=MAX_REGRESSION_ARTIFACT_BYTES)` in `stock_papi/application.py`. Ensure missing, corrupted, or statistically invalid regression artifacts evaluate optional binding `validate_regression_research_binding(...)` to set `quantitative_research.status = "unavailable"`, preserving report **HTTP 200 OK** availability without triggering the global HTTP 503 error handler.
6. **Strict Disclosure & Wording Governance**: Enforce mandatory disclosure text (`"模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"`) and AI labeling (`"AI 模型參考建議"`, `"模型方向參考"`) while forbidding uncalibrated predictive terminology (`Probability`, `勝率`, `上漲機率`, `下跌機率`, `正式預測`, `買進訊號`, `賣出訊號`).
7. **Offline Research Dependency Isolation**: Isolate heavy econometric libraries (`statsmodels`) to offline research/batch modules, ensuring `stock_papi.application`, HTTP routes, and Cloud Run cold-start paths NEVER import `statsmodels` at the top level.

---

## 3. Non-Goals

- **No LightGBM / Tree Model Training**: Task C focuses exclusively on linear econometric regression explainers.
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
3. `reporting/professional_binding.py`: Cross-checks identity, metadata, pointer SHA, and route parameters for critical canonical reports via `validate_professional_report_binding()`.
4. `reporting/publisher.py`: Writes canonical object (`objects/canonical/<canonical_sha256>.json`) and metadata (`metadata/<metadata_sha256>.json`) atomically with read-back hash verification.
5. `stock_papi/web/routes/reports.py`: Loads metadata and raw bytes of canonical object via `load_canonical_object`, validates binding, and passes Jinja-safe view model to HTML template (`templates/reports/post_close_professional.html`).

Currently, `quantitative_research` section in `professional_builder.py` contains static gate status (`gates.promotion = "BLOCKED"`) and `probability_allowed = False`.

---

## 5. Selected Architecture: Approach B (Independent Content-Addressed Regression Research Artifact)

We select **Approach B**, which creates a separate, content-addressed `RegressionResearchArtifact` stored under `objects/regression/<object_sha256>.json`, bound via an exact whitelist pointer in `ReportMetadataV2` and a summary reference in `ProfessionalPostCloseReport`.

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
              |  Path: objects/regression/<object_sha256>.json       |
              +------------------------------------------------------+
                                          |
                   +----------------------+----------------------+
                   | Pointer                              | Summary Reference
                   v                                      v
+------------------------------------+        +------------------------------------+
|         ReportMetadataV2           |        |    ProfessionalPostCloseReport     |
| regression_research = {            |        | quantitative_research.data = {     |
|   "object": "objects/regression/..",|        |   "regression_reference": {        |
|   "sha256": "<object_sha256>",     |        |     "object_sha256": "...",        |
|   "content_sha256": "<content_sha>",|        |     "content_sha256": "...",       |
|   "schema_version": 1,             |        |     "summary_status": "available"  |
|   "generator_version": "1.0.0",    |        |   }                                |
|   "code_commit_sha": "<40hex>"     |        | }                                  |
| }                                  |        |                                    |
+------------------------------------+        +------------------------------------+
```

### Rationale for Selecting Approach B:
1. **Content-Addressed Storage & Immutability**: Regression computations are deterministic and bound to source observation snapshots. Hash-addressing at `objects/regression/<object_sha256>.json` guarantees zero tampering.
2. **Schema Decoupling**: The regression schema (`schema_version = 1`) can evolve independently without bloating `ProfessionalPostCloseReport` core schema or mutating `ProfessionalReportIdentity` (`schema_version = 1`).
3. **Failure Isolation**: If regression computation fails or artifact is missing, optional binding validation evaluates `quantitative_research` status to `"unavailable"` gracefully. The primary post-close report remains valid (**HTTP 200 OK**).
4. **Pre-market Lineage Protection**: Pre-market pipeline reads raw observation core without depending on regression artifacts.

---

## 6. Alternatives Considered

### Approach A: Direct Embedding into Professional Canonical Report
- *Description*: Store full regression matrices, t-stats, and residual statistics directly inside `document["quantitative_research"]["data"]`.
- *Drawbacks*: Bloats the canonical report JSON beyond target size; couples statistical spec changes directly to `PROFESSIONAL_REPORT_SCHEMA_VERSION`; complicates schema validation for optional regression runs.

### Approach C: View-Model-Only On-The-Fly Computation
- *Description*: Calculate regression on demand when serving HTTP route requests.
- *Drawbacks*: Violates zero-runtime-computation invariant for report routes; causes non-deterministic HTML renders; loses content-addressed auditability; risks route timeouts.

---

## 7. Artifact Schema (`RegressionResearchArtifact`)

Path: `reporting/regression_schema.py`

```python
REGRESSION_ARTIFACT_SCHEMA_VERSION = 1
REGRESSION_ARTIFACT_KIND = "absorb-regression-research-artifact"
MAX_REGRESSION_ARTIFACT_BYTES: int = 2_000_000  # 2MB strict size limit
```

### Hash Definitions:
- `object_sha256`: SHA-256 hex digest computed over the exact canonical UTF-8 JSON bytes written to storage (`json.dumps(..., sort_keys=True, separators=(',', ':'))`). `object_sha256` serves as the content-addressed file key `objects/regression/<object_sha256>.json` and metadata pointer attribute `sha256`. It is NOT embedded inside `identity` to prevent circular hash dependencies.
- `content_sha256`: Semantic content SHA-256 hex digest stored in `identity.content_sha256`. Computed over canonical JSON bytes with `identity.content_sha256` set to `""`.

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
    "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86",
    "generator_version": "1.0.0",
    "content_sha256": "a1b2c3d4...64hex",
    "regression_spec_version": "1.0"
  },
  "regression_spec": {
    "analysis_scope": "market_level_daily",
    "entity_type": "market_index",
    "universe_definition": "TWSE_TAIEX",
    "observation_unit": "daily_session",
    "model_family": "ols_linear_factor",
    "dependent_variable": "five_day_forward_relative_return",
    "dependent_variable_definition": "5-day session forward relative return over TAIEX benchmark",
    "independent_variables": [
      "volume_surge_ratio",
      "foreign_net_flow_ratio",
      "industry_momentum_score",
      "volatility_20d"
    ],
    "intercept": true,
    "frequency": "daily",
    "feature_start_date": "2025-07-10",
    "feature_end_date": "2026-07-10",
    "label_start_date": "2025-07-17",
    "label_end_date": "2026-07-17",
    "label_horizon_sessions": 5,
    "sample_count": 245,
    "missing_value_policy": "listwise_deletion",
    "standardization_policy": "z_score",
    "outlier_policy": "winsorize_1_99",
    "covariance_estimator": "newey_west_hac",
    "hac_max_lags": 4,
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
      "note": "VIF calculated exclusively over independent factor columns excluding constant intercept",
      "vif_details": {
        "volume_surge_ratio": 1.42,
        "foreign_net_flow_ratio": 1.85,
        "industry_momentum_score": 2.14,
        "volatility_20d": 1.31
      }
    },
    "heteroskedasticity": {
      "status": "passed",
      "test_name": "breusch_pagan",
      "test_statistic": 3.38,
      "p_value": 0.184,
      "threshold": 0.05
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
    "summary": "在控制 20 日波動度與產業動能後，外資買賣超比率與成交量放大比率對市場 5 日相對報酬展現正向係數關係 (p < 0.01)。",
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

### Analysis Unit Scope (v1):
- **Scope A: Market-level daily time series**.
- Observation Unit: 1 row = 1 trading day session ($t$).
- Dependent Variable: `five_day_forward_relative_return` (5-day forward return of market benchmark index).
- Sample Size $n$: Total number of daily sessions in rolling estimation window.

### Point-in-Time & Forward Label Leakage Prevention Rules:
1. **Explicit Window Timestamps**:
   - `feature_start_date` and `feature_end_date`: Date range of independent variables $X_t$.
   - `label_start_date` and `label_end_date`: Date range of forward dependent returns $Y_t$.
   - `label_horizon_sessions = 5`.
2. **Strict Calendar Temporal Bound**:
   - `feature_date < label_end_date`
   - `label_end_date <= source_market_date`
   - `label_end_date` must be calculated using trading calendar sessions (skipping weekends and market holidays), NOT plain calendar subtraction (-5 days).
   - If `label_end_date > source_market_date`, validation fails closed immediately.
3. **Manifest Lineage**: Artifact identity must include `source_manifest` and `source_manifest_sha256`.
4. **Code Lineage**: Artifact identity must record `code_commit_sha` (40-hex Git commit) and `generator_version`.

---

## 9. Statistical Contract

1. **Sample Count Policy**:
   - $n < 30$: Hard Failure $\rightarrow$ Artifact BLOCKED / `quantitative_research.status = "unavailable"` (reason: `"迴歸樣本數不足 (n < 30)"`).
   - $30 \le n < 60$: Available with `limited_sample_warning` badge in presentation.
   - $60 \le n \le 252$: Standard research window `available`.
   - $n > 252$: Truncated to 252-session rolling estimation window.
2. **Degrees of Freedom & Matrix Rank**:
   - $\text{degrees\_of\_freedom} = n - \text{parameter\_count} > 0$.
   - Design matrix $X$ must be full rank ($\text{rank}(X) = \text{parameter\_count}$). If matrix is singular or rank deficient, Hard Failure.
3. **Statistical Field Bounds**:
   - $0 \le R^2 \le 1$.
   - Adjusted $R^2 \le 1$ (Adjusted $R^2$ may be negative for poor models; negative values are valid and preserved).
   - $0 \le p\text{-value} \le 1$.
   - Standard errors $\text{SE} \ge 0.0$.
   - $0 < \text{confidence\_level} < 1$ (default $0.95$).
   - Confidence interval order: $\text{ci\_low}_j \le \beta_j \le \text{ci\_high}_j$.
4. **Numeric Finite Check**: All numbers must be finite floats/ints. Any `NaN`, `Infinity`, `-Infinity`, or `bool` passed as numeric values causes immediate Hard Failure.

---

## 10. Validation Rules & Diagnostic Governance

### Covariance & Estimator Selection:
- **Covariance Estimator**: `covariance_estimator = "newey_west_hac"`, `hac_max_lags = 4`. Overlapping 5-day forward returns induce moving average error autocorrelation up to lag 4; Newey-West HAC adjusts standard errors and t-statistics accordingly. `hc3_robust` is NOT used for overlapping returns.

### Diagnostic Thresholds & Hard Failures vs Warnings:

| Diagnostic / Gate | Metric / Test | Threshold | Action |
|---|---|---|---|
| **Sample Count** | $n$ | $n < 30$ | **Hard Failure** (Section `unavailable`) |
| **Matrix Rank** | $\text{rank}(X)$ | Rank deficient | **Hard Failure** (Section `unavailable`) |
| **Numeric Integrity** | Non-finite check | Any `NaN`/`Inf`/`bool` | **Hard Failure** (Section `unavailable`) |
| **Temporal Alignment** | `label_end_date` | $> \text{source\_market\_date}$ | **Hard Failure** (Section `unavailable`) |
| **CI Consistency** | $\text{ci\_low} \le \beta \le \text{ci\_high}$ | Unordered | **Hard Failure** (Section `unavailable`) |
| **Multicollinearity** | Max VIF | $< 5.0$ (Passed)<br>$5.0 \le \text{VIF} < 10.0$ (Warning badge)<br>$\ge 10.0$ (Severe warning badge) | Diagnostic Warning (Does not fail report) |
| **Heteroskedasticity** | Breusch-Pagan Test | $p < 0.05$ | Diagnostic Warning badge |
| **Autocorrelation** | Durbin-Watson | $DW < 1.5$ or $DW > 2.5$ | Diagnostic Warning badge (HAC handles inference) |
| **Normality** | Jarque-Bera Test | $p < 0.05$ | Diagnostic Warning badge |

---

## 11. Publication Flow & Exact Ordering

The publisher (`reporting/publisher.py`) executes the exact 10-step atomic sequence:

```
Step 1: Pre-validate Regression Artifact document in memory
Step 2: Serialize Regression Artifact canonical UTF-8 JSON bytes
Step 3: Validate size (<= MAX_REGRESSION_ARTIFACT_BYTES), object_sha256, content_sha256
Step 4: Write immutable Regression Object to `objects/regression/<object_sha256>.json`
Step 5: Perform post-write atomic read-back hash & schema verification
Step 6: Build Professional Canonical Report summary reference block
Step 7: Write & verify Professional Canonical Object (`objects/canonical/<canonical_sha256>.json`)
Step 8: Write & verify Metadata (`metadata/<metadata_sha256>.json`) with regression pointer
Step 9: Write Index (`index-TW.json`)
Step 10: Write Latest (`latest-TW-post_close.json`) last
```

---

## 12. Canonical & Metadata Binding Rules

### Exact Metadata Pointer Whitelist (`ReportMetadataV2.regression_research`):
```json
{
  "object": "objects/regression/<object_sha256>.json",
  "sha256": "<object_sha256>",
  "content_sha256": "<semantic_content_sha256>",
  "schema_version": 1,
  "generator_version": "1.0.0",
  "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86"
}
```
*Rule*: `pointer.object == f"objects/regression/{pointer.sha256}.json"`.

### Canonical Report Summary Reference (`ProfessionalPostCloseReport`):
`ProfessionalReportIdentity` (`schema_version = 1`) remains **UNMUTATED**.

In `ProfessionalPostCloseReport.quantitative_research.data`:
```json
{
  "regression_reference": {
    "object_sha256": "<object_sha256>",
    "content_sha256": "<semantic_content_sha256>",
    "schema_version": 1,
    "summary_status": "available"
  }
}
```

---

## 13. Route Loading & Application Loader

Path: `stock_papi/application.py`

```python
def load_regression_object(
    object_path: str,
    max_bytes: int = MAX_REGRESSION_ARTIFACT_BYTES,
) -> bytes | None:
    """Load raw bytes for a regression research object with strict safety checks."""
    if not isinstance(object_path, str) or not _REGRESSION_OBJECT_PATH_RE.fullmatch(object_path):
        return None
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not (1 <= max_bytes <= MAX_REGRESSION_ARTIFACT_BYTES):
        return None
    full_object_name = f"reports/v2/{object_path}"
    raw_bytes = _gcs_get_report_v2_object(full_object_name, max_bytes=max_bytes)
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) == 0 or len(raw_bytes) > max_bytes:
        return None
    return raw_bytes
```

*Regex*: `_REGRESSION_OBJECT_PATH_RE = re.compile(r"^objects/regression/[0-9a-f]{64}\.json$")`.

Route registration accepts `load_regression_object=None` optional dependency.

---

## 14. HTML Presentation & View Model Rules

### View Model Mapping:
`build_professional_report_view(report)` populates `quantitative_research`:
- Section Title: `"量化與迴歸因子研究"`
- AI Label: `"AI 模型參考建議"`
- Model Output Label: `"模型方向參考"`
- Mandatory Disclaimer: `"模型尚未通過 Ranking、Calibration、Quality 與 Transaction Value，因此不提供正式預測機率。"`

### HTML Rendering Behavior:
- **If Available**: Render factor exposure table, t-stats, p-values, 95% CIs, diagnostic badges, and limitations card.
- **If Unavailable**: Render graceful alert card: *"量化迴歸研究暫不提供：[reason]"*. Report page returns **HTTP 200 OK**.

---

## 15. PDF / LINE / Gemini Future Compatibility

1. **PDF Generator**: `reporting/pdf_generator.py` will render a 1-page compact factor matrix table when `status == "available"`.
2. **LINE Flex Message**: `stock_papi/integrations/line/` will render a 2-line summary card under `"模型方向參考"`.
3. **Gemini Prompt**: `stock_papi/services/papi_service.py` will format regression coefficients into context prompts strictly wrapped with mandatory disclaimers.

---

## 16. Failure Semantics & Graceful Degradation

### Separate Critical vs Optional Binding:
1. `validate_professional_report_binding()`: Critical Canonical Contract $\rightarrow$ Failures trigger HTTP 503.
2. `validate_regression_research_binding()`: Optional Research Contract $\rightarrow$ Any optional regression failure (missing object, SHA mismatch, bad JSON, date mismatch, manifest mismatch, code SHA mismatch) gracefully sets `quantitative_research.status = "unavailable"` with reason `"迴歸解釋分析組件未就緒或資料驗證失敗"`. The report page **remains HTTP 200 OK**.

---

## 17. Security & Leakage Prevention

1. **Path Traversal Protection**: Regex `^objects/regression/[0-9a-f]{64}\.json$`.
2. **Error Message Redaction**: No file paths, bucket names, or stack traces exposed.
3. **Offline Dependency Isolation**: Heavy econometric libraries (`statsmodels`) MUST NOT be imported at the top level of `stock_papi.application`, HTTP routes, or Cloud Run cold-start paths.

---

## 18. Testing Strategy

1. **Schema & Contract Tests** (`tests/test_regression_schema.py`).
2. **Point-in-Time & Leakage Tests** (`tests/test_regression_pit.py`).
3. **Adapter & Validation Tests** (`tests/test_regression_adapter.py`).
4. **Publisher & Rollback Failure Injection Tests** (`tests/test_regression_publisher.py`).
5. **Application Loader Tests** (`tests/test_regression_loader.py`).
6. **Route Graceful Degradation Tests** (`tests/test_regression_route.py`).
7. **Cold-Start Import Isolation Test** (`tests/test_cold_start_imports.py`).

---

## 19. Migration & Backward Compatibility

Older metadata documents lacking `regression_research` remain 100% valid and default to `quantitative_research.status = "unavailable"`. `PROFESSIONAL_REPORT_SCHEMA_VERSION = 1` remains unmutated.

---

## 20. Rollback Mechanism

If metadata, index, or latest write fails during publishing:
- Rollback deletes ONLY newly created objects (`objects/regression/<sha256>.json`, `objects/canonical/<sha256>.json`, `metadata/<sha256>.json`).
- Pre-existing identical immutable objects are NOT deleted.
- Previous `index-TW.json` state is restored.

---

## 21. Production Safety Declarations

- **No Cloud Run Deployment**: Code and design changes remain strictly in repository docs/branches.
- **No Production Traffic Change**: No route rules or DNS modified.
- **No Production GCS Mutation**: No uploads or pointer updates executed against live production GCS buckets.
- **No LINE Notification Triggered**: No push or broadcast notifications sent.
- **No Task D Execution**: Task D remains strictly uninitiated.
