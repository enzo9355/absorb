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
2. **Content-Addressed Input Dataset Lineage**: Define `RegressionInputDataset` (`schema_version = 1`, `kind = "absorb-regression-input-dataset"`) to capture multi-session input lineage (245/252 trading sessions), binding `input_dataset_object`, `input_dataset_sha256`, and `input_dataset_content_sha256` to the regression artifact.
3. **Strict Point-in-Time & Session Calendar Lineage**: Enforce explicit session boundaries (`first_feature_session`, `last_feature_session`, `first_label_end_session`, `last_label_end_session`, `label_horizon_sessions = 5`) where `feature_session_t < label_end_session_t <= source_market_date`, calculated via trading calendar to prevent forward look-ahead label leakage.
4. **Market Benchmark Dependent Variable**: Define dependent variable as `five_session_forward_return` ($Y_t = \frac{P_{t+5}}{P_t} - 1$, where $P_t$ is official TAIEX closing price on session $t$, and $P_{t+5}$ is official TAIEX closing price 5 trading sessions ahead).
5. **Robust Statistical Contract & HAC Covariance**: Enforce automated validation for OLS regression estimates, Newey-West HAC robust standard errors (`hac_max_lags = 4`), sample size policies ($n < 30 \rightarrow \text{unavailable}$, $30 \le n < 60 \rightarrow \text{available\_with\_limited\_sample\_warning}$, $60 \le n \le 252 \rightarrow \text{available}$), non-finite value rejections, confidence interval ordering ($\text{ci\_low} \le \text{coefficient} \le \text{ci\_high}$), and Breusch-Pagan heteroskedasticity diagnostics.
6. **Single Hash Ownership & Canonical Serialization**: Define single responsibility boundaries where `RegressionResearchArtifact` Builder computes `content_sha256`, `serialize_regression_artifact()` produces canonical bytes, and `publisher.py` calculates `object_sha256` once to determine storage path and metadata pointer `sha256`.
7. **Canonical & Metadata Binding without Schema v1 Mutation**: Keep `ProfessionalReportIdentity` (`schema_version = 1`) unchanged. Bind the full content-addressed pointer in `ReportMetadataV2.regression_research` and store a summary reference in `ProfessionalPostCloseReport.quantitative_research.data.regression_reference`.
8. **View Model Overlay Interface & Graceful 200 OK Degradation**: Keep `ProfessionalPostCloseReport` unmutated. Use `build_professional_report_view(report, regression_artifact=None, regression_unavailable_reason=None, pdf_download_url=None)` overlay interface. Ensure missing, corrupted, or statistically invalid regression artifacts set `quantitative_research.status = "unavailable"` in the view model, preserving report **HTTP 200 OK** availability without triggering the global HTTP 503 error handler.
9. **Offline Research Dependency Isolation**: Isolate heavy econometric libraries (`statsmodels`) to offline research/batch modules (`requirements-report.txt`), ensuring `stock_papi.application`, HTTP routes, and Cloud Run cold-start paths NEVER import `statsmodels` at the top level.

---

## 3. Non-Goals

- **No LightGBM / Tree Model Training**: Task C focuses exclusively on linear econometric regression explainers.
- **No SHAP / Tree Explainer Integration**: SHAP value calculation for tree models is out of scope.
- **No Probability Calibration / Model Promotion**: Prediction capability gates remain blocked. No probability or win rate outputs are generated.
- **No Buy / Sell Signals**: No trading recommendations, entry/exit signals, or price targets are generated.
- **No Sample / Mock Data Generation**: If a verified `RegressionInputDataset` is not available in the repository, the artifact builder returns `unavailable` (reason: `"未提供經過 Content-Addressed 驗證之 RegressionInputDataset"`). The system NEVER generates fake or sample coefficients for production reports.
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

---

## 6. Alternatives Considered

### Approach A: Direct Embedding into Professional Canonical Report
- *Description*: Store full regression matrices, t-stats, and residual statistics directly inside `document["quantitative_research"]["data"]`.
- *Drawbacks*: Bloats canonical report JSON; couples statistical spec changes directly to `PROFESSIONAL_REPORT_SCHEMA_VERSION`; complicates schema validation for optional regression runs.

### Approach C: View-Model-Only On-The-Fly Computation
- *Description*: Calculate regression on demand when serving HTTP route requests.
- *Drawbacks*: Violates zero-runtime-computation invariant; non-deterministic HTML renders; loses content-addressed auditability; risks route timeouts.

---

## 7. Artifact Schema (`RegressionResearchArtifact`)

Path: `reporting/regression_schema.py`

```python
REGRESSION_ARTIFACT_SCHEMA_VERSION = 1
REGRESSION_ARTIFACT_KIND = "absorb-regression-research-artifact"
MAX_REGRESSION_ARTIFACT_BYTES: int = 2_000_000  # 2MB strict size limit
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
    "input_dataset_object": "publish/research/v1/datasets/e5f6a7b8...json.gz",
    "input_dataset_sha256": "e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6",
    "input_dataset_content_sha256": "f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1",
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
    "dependent_variable": "five_session_forward_return",
    "dependent_variable_definition": "5-session forward return over official TAIEX daily closing prices",
    "independent_variables": [
      "volume_surge_ratio",
      "foreign_net_flow_ratio",
      "industry_momentum_score",
      "volatility_20d"
    ],
    "intercept": true,
    "frequency": "daily",
    "first_feature_session": "2025-07-10",
    "last_feature_session": "2026-07-10",
    "first_label_end_session": "2025-07-17",
    "last_label_end_session": "2026-07-17",
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
    "summary": "在控制 20 日波動度與產業動能後，外資買賣超比率與成交量放大比率對大盤 5 日未來報酬展現正向係數關係 (p < 0.01)。",
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

## 8. Content-Addressed Input Dataset Lineage Contract (`RegressionInputDataset`)

Multi-session regression estimation requires a content-addressed input dataset artifact storing the exact 245/252 trading session observations used for regression fitting.

### JSON Structure (`RegressionInputDataset`):
```json
{
  "schema_version": 1,
  "kind": "absorb-regression-input-dataset",
  "identity": {
    "dataset_id": "TW-20260717-input-dataset-v1",
    "market": "TW",
    "analysis_scope": "market_level_daily",
    "generated_at": "2026-07-17T10:25:00Z",
    "source_market_date": "2026-07-17",
    "feature_start_session": "2025-07-10",
    "feature_end_session": "2026-07-10",
    "first_label_end_session": "2025-07-17",
    "last_label_end_session": "2026-07-17",
    "row_count": 245,
    "calendar_id": "TWSE_TRADING_CALENDAR",
    "calendar_version": "2026.1",
    "calendar_sha256": "c1a2l3e4n5d6a7r8...64hex",
    "canonical_rows_sha256": "r1o2w3s4...64hex",
    "code_commit_sha": "da25d594d3b76865da22b891285ac0c85e710d86",
    "content_sha256": "f0a1b2c3...64hex"
  },
  "source_objects": [
    {
      "object": "publish/quant/v1/objects/a1b2c3d4...json.gz",
      "sha256": "a1b2c3d4...64hex"
    }
  ],
  "input_columns": [
    "feature_session",
    "label_end_session",
    "close_t",
    "close_t_plus_5",
    "five_session_forward_return",
    "volume_surge_ratio",
    "foreign_net_flow_ratio",
    "industry_momentum_score",
    "volatility_20d"
  ],
  "factor_definitions": {
    "volume_surge_ratio": "Session t volume divided by 20-session moving average volume",
    "foreign_net_flow_ratio": "Session t foreign net buy value divided by total session turnover"
  },
  "dependent_variable_definition": "five_session_forward_return = (close_t_plus_5 / close_t) - 1",
  "preprocessing_policy": {
    "missing_value_policy": "listwise_deletion",
    "winsorization_policy": "1st_99th_percentile_linear_interpolation",
    "standardization_policy": "z_score_sample_std_ddof_1"
  }
}
```

### Strict Dataset Lineage Rules:
1. **Forbidden Network & Sample Data**:
   - Runtime network fallback (e.g., `requests.get` to remote APIs) is strictly prohibited during artifact building.
   - `yfinance` live downloads during report building are strictly prohibited.
   - Sample or mock fixture datasets are strictly prohibited in production.
   - Retrospective current constituent filtering or unhashed local CSV files are prohibited.
2. **Missing Input Dataset Readiness Policy**:
   - If a verified `RegressionInputDataset` is NOT available in repository storage, `build_regression_research_artifact()` MUST return `None`.
   - The publisher and route handler MUST evaluate `quantitative_research.status = "unavailable"` with reason `"未提供經過 Content-Addressed 驗證之 RegressionInputDataset"`.
   - The system NEVER generates fake coefficients or mock regression outputs.

---

## 9. Point-in-Time & Session Calendar Lineage Rules

### Per-Row Session Temporal Contract:
For each observation row $t$ in the regression estimation matrix:
- `feature_session_t`: The trading session date where independent factor features $X_t$ are observed.
- `label_start_session_t = feature_session_t`: Session $t$ closing price $P_t$.
- `label_end_session_t = calendar.shift(feature_session_t, +5)`: Official session closing price $P_{t+5}$ five trading calendar sessions ahead.
- Dependent Variable:
  $$Y_t = \frac{P_{\text{label\_end\_session\_t}}}{P_{\text{label\_start\_session\_t}}} - 1$$

### Strict Calendar Temporal Constraint:
1. **Per-Row Constraint**:
   $$\text{feature\_session\_t} < \text{label\_end\_session\_t} \le \text{source\_market\_date}$$
2. **Latest Eligible Feature Session**:
   $$\text{latest\_eligible\_feature\_session} = \text{calendar.shift}(\text{source\_market\_date}, -5)$$
3. **Aggregate Lineage Fields**:
   - `first_feature_session` & `last_feature_session`
   - `first_label_end_session` & `last_label_end_session`
   - `label_horizon_sessions = 5`

---

## 10. Factor Preprocessing Rules

For each independent factor $X_j$:
1. **Selection**: Select the last 252 mature trading sessions where `label_end_session <= source_market_date`.
2. **Listwise Deletion**: Drop any session row containing missing (`None`/`NaN`) factor or dependent return values. If $n < 30$ after listwise deletion, return Hard Failure.
3. **Winsorization**: Trim extreme outliers at the 1st and 99th percentiles estimated in-sample over the 252-session estimation window using `linear` quantile interpolation.
4. **Z-Score Standardization**: Standardize features using in-sample mean $\mu$ and sample standard deviation $\sigma$ with $\text{ddof} = 1$:
   $$Z_{j, t} = \frac{X_{j, t} - \mu_j}{\sigma_j}$$
5. **Zero Variance Check**: Any factor with $\sigma_j = 0$ (constant factor) triggers immediate Hard Failure.
6. **Duplicate Session Check**: Duplicate session dates trigger immediate Hard Failure.

---

## 11. Statistical Contract & Diagnostic Governance

### Covariance & Estimator Selection:
- **Model Framework**: Ordinary Least Squares (OLS) with Newey-West HAC robust standard errors (`covariance_estimator = "newey_west_hac"`, `hac_max_lags = 4`). Overlapping 5-session forward returns induce moving-average error autocorrelation up to lag 4; Newey-West HAC adjusts standard errors and t-statistics accordingly. `hc3_robust` is NOT used for overlapping returns.

### Diagnostic Thresholds & Hard Failures vs Warnings:

| Diagnostic / Gate | Metric / Test | Threshold | Action |
|---|---|---|---|
| **Sample Count** | $n$ | $n < 30$ | **Hard Failure** (Section `unavailable`) |
| **Matrix Rank** | $\text{rank}(X)$ | Rank deficient ($\text{rank} < k + 1$) | **Hard Failure** (Section `unavailable`) |
| **Numeric Integrity** | Non-finite check | Any `NaN`/`Inf`/`bool` | **Hard Failure** (Section `unavailable`) |
| **Temporal Alignment** | `last_label_end_session` | $> \text{source\_market\_date}$ | **Hard Failure** (Section `unavailable`) |
| **CI Consistency** | $\text{ci\_low} \le \beta \le \text{ci\_high}$ | Unordered | **Hard Failure** (Section `unavailable`) |
| **Multicollinearity** | Max VIF (Excluding Intercept) | $< 5.0$ (Passed)<br>$5.0 \le \text{VIF} < 10.0$ (Warning badge)<br>$\ge 10.0$ (Severe warning badge) | Diagnostic Warning (Does not fail report) |
| **Heteroskedasticity** | Breusch-Pagan Test | $p < 0.05$ | Diagnostic Warning badge |
| **Autocorrelation** | Durbin-Watson | $DW < 1.5$ or $DW > 2.5$ | Diagnostic Warning badge |
| **Normality** | Jarque-Bera Test | $p < 0.05$ | Diagnostic Warning badge |

---

## 12. Single Hash Ownership Responsibility

1. **Schema & Builder Responsibility**:
   - `build_regression_research_artifact()` constructs document dict.
   - Computes `identity.content_sha256` (semantic content hash with `identity.content_sha256 = ""`).
   - Does NOT store `object_sha256` inside `identity` dict.
   - Does NOT determine file storage paths.
2. **Canonical Serializer Responsibility (`reporting/regression_schema.py`)**:
   - `serialize_regression_artifact(artifact: dict) -> bytes`
   - Fixed serialization format:
     ```python
     json.dumps(
         document,
         ensure_ascii=False,
         sort_keys=True,
         separators=(",", ":"),
         allow_nan=False,
     ).encode("utf-8")
     ```
3. **Publisher Responsibility (`reporting/publisher.py`)**:
   - Calls `serialize_regression_artifact(artifact)` ONCE to get `serialized_bytes`.
   - Computes `object_sha256 = hashlib.sha256(serialized_bytes).hexdigest()`.
   - Sets storage path `object_path = f"objects/regression/{object_sha256}.json"`.
   - Sets pointer `sha256 = object_sha256`.

---

## 13. Publication Flow & Exact Ordering

The publisher (`reporting/publisher.py`) executes the exact 10-step atomic sequence:

```
Step 1: Save previous_index_bytes and previous_latest_bytes in memory
Step 2: Pre-validate Regression Artifact document in memory
Step 3: Serialize Regression Artifact canonical UTF-8 JSON bytes via serialize_regression_artifact()
Step 4: Validate size (<= MAX_REGRESSION_ARTIFACT_BYTES) and compute object_sha256
Step 5: Write immutable Regression Object to `objects/regression/<object_sha256>.json`
Step 6: Perform post-write atomic read-back size and hash verification
Step 7: Build Professional Canonical Report summary reference block
Step 8: Write & verify Professional Canonical Object (`objects/canonical/<canonical_sha256>.json`)
Step 9: Write & verify Metadata (`metadata/<metadata_sha256>.json`) with exact whitelist pointer
Step 10: Commit Index (`index-TW.json`) and Latest (`latest-TW-post_close.json`) last
```

---

## 14. Canonical & Metadata Binding Rules

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

## 15. Route Loading & Application Loader

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

## 16. View Model Overlay Interface & Graceful Degradation

Path: `reporting/professional_html.py` & `stock_papi/web/routes/reports.py`

`ProfessionalPostCloseReport` is an immutable canonical object. HTTP route loading MUST NOT mutate `report.quantitative_research.status`.

### View Model Overlay Signature:
```python
def build_professional_report_view(
    report: ProfessionalPostCloseReport,
    *,
    regression_artifact: RegressionResearchArtifact | None = None,
    regression_unavailable_reason: str | None = None,
    pdf_download_url: str | None = None,
) -> dict[str, Any]:
```

### Route Data Flow & Degradation:
1. Load metadata & canonical professional report object.
2. If `metadata.regression_research` pointer is present:
   - Call `load_regression_object` ONCE to get raw bytes.
   - Verify size and SHA-256 hash using `hmac.compare_digest`.
   - Parse JSON and validate `RegressionResearchArtifact.from_document()`.
   - Execute `validate_regression_research_binding()`.
   - Pass valid `regression_artifact` to `build_professional_report_view`.
3. If pointer absent or any validation fails:
   - Pass `regression_artifact = None` and `regression_unavailable_reason = "..."` to `build_professional_report_view`.
   - View model sets `quantitative_research.status = "unavailable"`, `reason = "..."`.
   - Report page **remains HTTP 200 OK**. (HTTP 503 handler is NOT invoked).

---

## 17. Offline Research Dependency Installation Boundary

1. **Dependency File Update**:
   - `requirements-report.txt` is updated with `statsmodels>=0.14.0,<0.15.0`.
   - Web application runtime `requirements.txt` remains UNCHANGED (does NOT include `statsmodels`).
2. **Import Isolation Contract**:
   - Heavy econometric libraries (`statsmodels`) MUST NOT be imported at the top level of `stock_papi.application`, HTTP routes, or Cloud Run cold-start paths.
   - `stock_papi/research/regression_deps.py` provides lazy function-scoped imports.
3. **Cold-Start Guard Test**:
   - `tests/test_cold_start_imports.py` verifies that `import stock_papi.application` does NOT load `statsmodels` into `sys.modules`.

---

## 18. Future Adapters

1. **PDF Generator**: `reporting/pdf_generator.py` renders a 1-page compact factor matrix table when `status == "available"`.
2. **LINE Flex Message**: `stock_papi/integrations/line/` renders a 2-line summary card under `"模型方向參考"`.
3. **Gemini Prompt**: `stock_papi/services/papi_service.py` formats regression coefficients into context prompts strictly wrapped with mandatory disclaimers.

---

## 19. Failure Semantics & Graceful Degradation Summary

| Scenario | Handling Level | HTTP Response | Log Level |
|---|---|---|---|
| Missing `RegressionInputDataset` | Builder returns `None` | 200 OK (`unavailable`) | WARNING |
| Missing / Corrupted Regression Object | Route catches error, sets view overlay `unavailable` | 200 OK (`unavailable`) | ERROR |
| Regression SHA / Binding Mismatch | Route catches error, sets view overlay `unavailable` | 200 OK (`unavailable`) | ERROR |
| Critical Section (`market`/`governance`) Corrupted | Schema validator raises `ValueError` | 503 Service Unavailable | CRITICAL |

---

## 20. Rollback Mechanism

If metadata, index, or latest write fails during publishing:
- Rollback deletes ONLY newly created objects (`objects/regression/<object_sha256>.json`, `objects/canonical/<canonical_sha256>.json`, `metadata/<metadata_sha256>.json`).
- Pre-existing identical immutable objects are NOT deleted.
- Previous `index-TW.json` and `latest-TW-post_close.json` states are restored from in-memory byte backups (`previous_index_bytes`, `previous_latest_bytes`).

---

## 21. Production Safety Declarations

- **No Cloud Run Deployment**: Code and design changes remain strictly in repository docs/branches.
- **No Production Traffic Change**: No route rules or DNS modified.
- **No Production GCS Mutation**: No uploads or pointer updates executed against live production GCS buckets.
- **No LINE Notification Triggered**: No push or broadcast notifications sent.
- **No Task D Execution**: Task D remains strictly uninitiated.
