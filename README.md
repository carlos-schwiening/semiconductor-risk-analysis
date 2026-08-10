# Semiconductor Risk Analysis

[![CI](https://github.com/carlos-schwiening/semiconductor-risk-analysis/actions/workflows/ci.yml/badge.svg)](https://github.com/carlos-schwiening/semiconductor-risk-analysis/actions/workflows/ci.yml)

This repository contains quantitative risk models I developed during my Master's in Accounting, Finance & Controlling. I am publishing it as one of several projects in my public portfolio, showcasing applied financial modelling skills in Python for job applications.

The project applies three quantitative risk models to a portfolio of five U.S. semiconductor companies — MCHP, INTC, ON, QCOM, MPWR — covering structural credit risk, DCF equity valuation, and Monte Carlo portfolio simulation. Each model is self-contained, reads from a local FMP data cache, and produces terminal output, Plotly charts, and multi-sheet Excel workbooks. Together they answer the questions: *How likely is each company to default? What is the equity fairly worth? And what is the tail risk of holding all five?* All models are calibrated on five years of historical price and fundamental data (June 2021 – June 2026), sourced from the FMP API.

I chose the semiconductor sector because it sits at the intersection of cyclical earnings pressure, high capital intensity, and geopolitical risk — making it an ideal stress-test environment for structural credit risk models. The five tickers span the full credit spectrum: MPWR (near-zero debt, DD = 13.9σ) at one extreme and INTC (elevated leverage, DD = 3.7σ, IFRS 9 Stage 2) at the other, with MCHP, ON, and QCOM in between — giving the models meaningful differentiation to work with.

---

## Key Results

| Ticker | Company | Model Rating | Distance to Default | DCF Value/Share | Market Price | Upside | IFRS 9 Stage |
|--------|---------|--------------|--------------------:|----------------:|-------------:|-------:|:-------------|
| MCHP | Microchip Technology | BBB | 5.14 | $61.03 | $87.91 | −30.6% | Stage 1 |
| INTC | Intel Corporation | BB | 3.65 | not applicable ¹ | $107.04 | — | Stage 2 |
| ON | ON Semiconductor | BBB | 4.17 | $56.56 | $110.17 | −48.7% | Stage 1 |
| QCOM | Qualcomm | A | 6.52 | $100.25 | $191.20 | −47.6% | Stage 1 |
| MPWR | Monolithic Power Systems | AAA/AA | 13.88 | $235.54 | $1,473.04 | −84.0% | Stage 1 |

¹ INTC's normalized free cash flow is −$9.62 Bn. A DCF discounts the cash a company is expected to generate, so a negative starting point yields the present value of continued cash burn — arithmetically −$70.11 per share, or −165.5% "upside" — rather than an intrinsic value. Reporting that number as a valuation would be a category error, so the model states the limitation instead and points to the two measures that do carry information for INTC: the Merton credit model (Stage 2, `DD` = 3.65) and the multiples cross-check.

The Monte Carlo simulation (10,000 runs, $\rho$ = 60% sector correlation, three macro regimes) yields a portfolio `VaR` 99% of 84.57% (normalized to 100) across the four tickers whose DCF applies, reflecting that they all trade at significant premiums to their base-case DCF fair values. The Tornado Chart identifies `FCF` as the largest uncertainty driver, moving `VaR` 99% by 21.3 percentage points across its P10–P90 range.

---

## Model 1 — Merton Structural Credit Risk

The Merton (1974) model treats a firm's equity as a call option on its assets with the face value of debt as the strike price. Given observed equity market cap and equity volatility, the model iteratively solves for implied asset value and asset volatility using a Black-Scholes framework. The key output is the Distance to Default ($DD$) — the number of standard deviations separating current asset value from the default boundary — which maps directly to a risk-neutral Probability of Default ($PD$) and a credit spread.

$$DD = \frac{\ln(V/D) + (r - \frac{1}{2}\sigma_V^2)T}{\sigma_V\sqrt{T}}$$

The drift term is the risk-free rate $r$, not an estimated real-world asset drift $\mu$. That makes the resulting $PD$ a risk-neutral one, consistent with the credit spread derived from it further below; a real-world $PD$ would need an expected asset return the model does not estimate.

IFRS 9 `ECL` integration classifies each borrower into Stage 1 ($DD$ > 4, 12-month `ECL`), Stage 2 ($DD$ 2–4, lifetime `ECL`), or Stage 3 ($DD$ < 2, `LGD` × `EAD`). This is a deliberate simplification and departs from the standard in one respect worth stating: IFRS 9 triggers Stage 2 on a *significant increase in credit risk since initial recognition* — a relative test against the exposure's own starting point — whereas absolute `DD` thresholds are used here. That trade is made knowingly: a relative test needs an origination date and a credit-risk history per exposure, which a market-data model of listed equity does not have. The staging should therefore be read as a credit-quality bucket, not as an audit-ready IFRS 9 classification. The model also produces a quarterly Rating Migration Matrix showing transition probabilities between rating buckets, an `LGD` sensitivity analysis across Bear/Base/Bull scenarios, and a five-ticker summary Excel workbook.

| Ticker | Company | Distance to Default | Model Rating | Agency Rating | IFRS 9 Stage | Model Spread (bps) | Market Benchmark (bps) |
|--------|---------|--------------------:|--------------|---------------|:-------------|-------------------:|:----------------------|
| MCHP | Microchip Technology | 5.14 | BBB | BB+ | Stage 1 | 0.0 | 120–180 |
| INTC | Intel Corporation | 3.65 | BB | BBB | Stage 2 | 0.6 | 250–400 |
| ON | ON Semiconductor | 4.17 | BBB | BBB− | Stage 1 | 0.1 | 120–180 |
| QCOM | Qualcomm | 6.52 | A | A− | Stage 1 | 0.0 | 60–90 |
| MPWR | Monolithic Power Systems | 13.88 | AAA/AA | A | Stage 1 | 0.0 | 30–50 |

**The rating letters are model-internal, not agency ratings.** They are a mapping of the `DD` bucket onto familiar labels, derived from equity volatility and leverage alone. Placing the agency rating beside them shows the model does not simply run more conservatively: it is *more optimistic* for four of the five and harsher only for INTC. The divergence has a structural cause — the model rewards a clean balance sheet almost mechanically, which is why MPWR's near-zero debt lands it at AAA/AA, while an agency also weighs scale, competitive position, and business risk that no equity-volatility model can observe.

**Where the model earns its keep: the five-year horizon.** The one-year `PD` is near zero for every investment-grade issuer here, which says more about the horizon than about the companies. The five-year `PD` — the same model, run at $T=5$, and the figure already driving the lifetime `ECL` — lands close to observed cumulative default rates:

| Ticker | Model Rating | $PD$ 1Y (model) | $PD$ 1Y (observed) | $PD$ 5Y (model) | $PD$ 5Y (observed) |
|--------|--------------|----------------:|-------------------:|----------------:|-------------------:|
| MCHP | BBB | 0.0000% | 0.16% | **1.95%** | 1.55% |
| QCOM | A | 0.0000% | 0.05% | **0.33%** | 0.55% |
| INTC | BB | 0.0131% | 0.63% | **9.82%** | 5.60% |
| ON | BBB | 0.0015% | 0.16% | **6.40%** | 1.55% |
| MPWR | AAA/AA | 0.0000% | 0.02% | 0.00% | 0.30% |

*Observed = S&P Global average cumulative default rates by rating category, 1981–2023.*

Three of the five land in the right neighbourhood at five years, which is the more meaningful validation of a structural model than any one-year figure. ON is the exception and worth naming: its five-year `PD` of 6.40% is four times the BBB benchmark, so the model's own outputs disagree with each other — the rating bucket derives from the one-year `DD`, the lifetime `ECL` from the five-year `PD`, and for ON those two tell different stories. MPWR's 0.00% reflects a firm with almost no debt, where the structural model has nothing to price.

**The model spread sits far below the market benchmark for every ticker — that gap is a result, not an error.** The theoretical spread follows from the risk-neutral $PD$ via $s = -\ln(1 - PD \cdot LGD)\,/\,T$, and at a one-year horizon the Merton $PD$ for an investment-grade issuer is vanishingly small: a $DD$ of 5.14 corresponds to a $PD$ of roughly $10^{-7}$. The structural model therefore prices almost no credit risk, while observed market spreads compensate for liquidity, recovery uncertainty, and the jump-to-default risk that a diffusion process cannot represent. This is the well-documented credit spread puzzle of structural models at short horizons. The script reports the comparison explicitly for the active ticker (`Model UNDER market range`), which is why the benchmark band is shown alongside rather than in place of the model output — the informative content of the Merton model here lies in the $DD$ ranking and the IFRS 9 staging, not in the absolute spread level.

![KMV Asset Value Simulation](images/INTC_KMV_Textbook.png)

![Distance to Default — 5 Tickers](images/DD_TimeSeries.png)

---

## Model 2 — DCF Valuation & Scenario Analysis

The DCF model values equity using a two-phase discounted cash flow approach: an explicit five-year forecast phase (Phase 1, growth rate $g_1$) and a terminal value (Phase 2, perpetuity at $g_2$). The `WACC` is computed via `CAPM` using a 252-day OLS beta against the S&P 500, with debt cost derived from the ratio of interest expense to total debt and a market-value capital structure weighting. Free cash flow is normalized to the five-year median to smooth cyclical distortions. That works for the four cyclical names; it does not rescue INTC, whose median across the five years is itself negative (−$9.62 Bn), which is why the DCF is reported as not applicable there rather than normalized into a positive figure.

$$WACC = \frac{E}{V} \cdot K_e + \frac{D}{V} \cdot K_d \cdot (1-t)$$

**The resulting discount rates sit above sector norms, and that drives much of the result.** The 252-day betas come out between 1.67 and 2.46, against a semiconductor sector reference of roughly 1.55–1.75 (Damodaran). With a 4.3% risk-free rate and a 5.5% equity risk premium that yields a cost of equity of 13.5%–17.8%, where the sector reference is closer to 11%–12%. A discount rate two to six points above the reference is a large part of why all five names come out overvalued — a one-year daily beta is a noisy estimator, and the 2025/26 window contains unusually large idiosyncratic moves for these stocks. The scenario analysis below varies `WACC` by ±1.0–1.5 percentage points, which brackets part but not all of that gap.

$$EV_{DCF} = \sum_{t=1}^{5} \frac{FCF_t}{(1+WACC)^t} + \frac{FCF_5 \cdot (1+g_2)}{(WACC - g_2) \cdot (1+WACC)^5}$$

Scenario analysis stresses the Base Case along three paths: Bear (`WACC` +1.5%, $g_1$ −2%, `FCF` ×0.85), Base (unchanged), and Bull (`WACC` −1%, $g_1$ +2%, `FCF` ×1.15). A full Peer Group loop computes `WACC`, DCF value, and upside for all five tickers independently, and a Multiples Cross-Check benchmarks EV/EBITDA, P/E, and EV/Sales against semiconductor sector norms (Damodaran, Jan 2025). The two methods deliberately use different bases and should not be read as directly comparable: the DCF normalizes free cash flow over five years to smooth the cycle, while the multiples are computed on the most recent fiscal year. In a trough year that inflates them sharply — MCHP's P/E of 173x reflects collapsed trailing earnings, not a 173-year payback expectation. The cross-check is therefore a sanity check on current market pricing, not a second valuation.

Across the four tickers with a positive Base Case valuation, the present value of the terminal value (Phase 2) makes up 57%–65% of total EV_DCF — MPWR 56.9%, ON 60.1%, QCOM 61.3%, MCHP 65.4% (INTC's Base Case EV is structurally negative, so a terminal value share is not meaningful there). Varying the terminal growth rate $g_2$ by ±1% around the Base Case (2.5%) shifts implied value per share by roughly ±3–4% for MPWR up to ±8–10% for MCHP across the five tickers. This sensitivity is inversely related to each ticker's WACC-g₂ spread: MPWR's high 17.2% WACC creates a wide buffer against terminal growth assumptions, while MCHP's lower 12.0% WACC leaves less room, amplifying the impact of any change in g₂. Because more than half of every ticker's enterprise value rests on a single long-run growth assumption — one that by construction cannot be observed or back-tested over a short horizon — these DCF valuations are structurally dependent on a parameter with limited empirical anchoring, and should be read as scenario-sensitive estimates rather than precise point values.

| Ticker | Company | `WACC` | Beta | `FCF` Normalized (Bn) | DCF Value/Share | Market Price | Upside |
|--------|---------|-----:|-----:|--------------------:|----------------:|-------------:|-------:|
| MCHP | Microchip Technology | 12.0% | 1.67 | $2.47 | $61.03 | $87.91 | −30.6% |
| QCOM | Qualcomm | 13.7% | 1.88 | $9.85 | $100.25 | $191.20 | −47.6% |
| ON | ON Semiconductor | 14.0% | 2.10 | $1.29 | $56.56 | $110.17 | −48.7% |
| MPWR | Monolithic Power Systems | 17.2% | 2.35 | $0.58 | $235.54 | $1,473.04 | −84.0% |
| INTC | Intel Corporation | 14.3% | 2.46 | −$9.62 | not applicable | $107.04 | — |

**MCHP Scenario Analysis:**

| Scenario | `WACC` | Growth $g_1$ | Value/Share | Upside vs. Price |
|----------|-----:|----------:|------------:|----------------:|
| Bear | 13.5% | 3.0% | $36.95 | −58.0% |
| Base | 12.0% | 5.0% | $61.03 | −30.6% |
| Bull | 11.0% | 7.0% | $90.58 | +3.0% |

**Scenario Assumptions — Sector Context**

The scenario framework reflects three concrete, dated industry developments rather than abstract macro adjustments.

<table>
<tr>
<th>Bear Case</th>
<th>Base Case</th>
<th>Bull Case</th>
</tr>
<tr>
<td valign="top">

**WACC +1.5%** — PC/smartphone demand softens as memory chip costs rise (IDC); AI capex monetization risk could delay data center buildouts (Deloitte); CHIPS Act Section 48D credit expires Dec 2026 with extension unresolved

</td>
<td valign="top">

**WACC unchanged** — Reflects normal semiconductor cycle, deliberately excluding the AI-specific super-cycle since none of the five tickers are primary AI accelerator suppliers

</td>
<td valign="top">

**WACC −1.0%** — Indirect AI infrastructure spillover into power management, RF/connectivity, and mixed-signal components; Senate draft proposes raising Section 48D credit from 25% to 30%

</td>
</tr>
<tr>
<td valign="top">

**Growth g₁ −2%** — Consumer and industrial end-market exposure (MCHP, ON, QCOM) is more vulnerable to a pricing-driven demand pullback than AI infrastructure suppliers

</td>
<td valign="top">

**Growth g₁ unchanged** — WSTS projects $1.5T industry-wide sales for 2026, but Deloitte estimates AI chips alone account for ~$500B of that — the Base Case does not import this AI-specific growth rate

</td>
<td valign="top">

**Growth g₁ +2%** — Data center buildouts require power management, connectivity, and mixed-signal components even though none of the five tickers are core AI silicon vendors

</td>
</tr>
<tr>
<td valign="top">

**FCF ×0.85** — Operating deleverage as utilization rates fall in a cyclical downturn

</td>
<td valign="top">

**FCF unchanged** — Based on 5-year median, smoothing cyclical distortion without scenario adjustment

</td>
<td valign="top">

**FCF ×1.15** — Operating leverage as utilization rises, reinforced by potential capital cost relief from an extended/expanded investment tax credit

</td>
</tr>
</table>

INTC is a partial exception: its negative normalized FCF reflects company-specific balance sheet issues rather than sector cyclicality, so scenario deltas move INTC's outputs but cannot resolve its structurally negative base valuation.

*Sources: Semiconductor Industry Association / WSTS Spring 2026 Forecast; Deloitte 2026 Semiconductor Industry Outlook; IDC (Jan 2026, via The Straits Times); Semiconductor Industry Association, "Chip Incentives & Investments"; Pillsbury Law, "Senate Draft Tax Bill Expands CHIPS Act Investment Tax Credit" (June 2025).*

---

## Model 3 — Monte Carlo Simulation

The Monte Carlo engine runs 10,000 simulations of DCF equity values across all five tickers simultaneously, using configurable parametric distributions for each input. A Gaussian copula with Cholesky decomposition imposes $\rho$ = 60% pairwise correlation across tickers, reflecting the high systematic co-movement of semiconductor stocks. A macro regime overlay (Recession 25% / Base 50% / Boom 25%) shifts `WACC`, $g_1$, and `FCF` before each simulation run. All five tickers are simulated; the reported portfolio holds the four with an applicable DCF at equal weights (25% each), normalized to 100, and `VaR`/`CVaR` are computed on the resulting loss distribution. The equal-weighted five-ticker variant is shown alongside it for reference — see the footnotes to the per-ticker table.

The Convergence Test confirms `VaR` 99% stabilizes beyond 5,000 simulations: the step from 7,500 to 10,000 moves it by 0.005 pp, against 0.4–0.6 pp between the smallest sample sizes. The Tornado Chart isolates the contribution of each parameter by varying it from P10 to P90 while holding all others at their mean:

| Parameter | `VaR` 99% @ P10 | `VaR` 99% @ P90 | Swing |
|---|---:|---:|---:|
| `FCF` | 82.2% | 60.9% | 21.3 pp |
| `WACC` | 62.0% | 78.4% | 16.4 pp |
| $g_1$ | 74.0% | 67.4% | 6.6 pp |
| $g_2$ | 73.7% | 69.6% | 4.2 pp |

`FCF` uncertainty dominates, followed by `WACC`. The tornado runs without the macro regime overlay in order to isolate the four input parameters, so its base `VaR` 99% of 72.2% differs from the 84.6% reported above — read the swings as relative contributions, not as deltas on the headline figure.

Each parameter's distribution shape reflects a specific assumption about its empirical behavior rather than a default choice. `WACC` uses a Normal distribution because its underlying components (cost of equity, cost of debt) are approximately symmetric around their expected value with no known skew — the standard approach in practice. $g_1$ uses a Triangular distribution, deliberately chosen because the available information is a plausible range (0% floor, no negative growth assumed) and a most-likely value rather than a fully estimated distribution shape — the 12% ceiling reflects historical semiconductor sector growth rates. `FCF` uses a Log-Normal distribution to capture the right-skew typical of cash flow shocks, where large positive surprises are more likely than symmetric extremes in either direction. $g_2$ uses a Uniform distribution between a plausible floor and ceiling close to long-run GDP growth, deliberately encoding maximum uncertainty without favoring any value within that range — the most conservative assumption available when only the bounds, not the shape, are known.

**Parameter Distributions:**

| Parameter | Distribution | E[X] | P10 | P90 |
|-----------|-------------|-----:|----:|----:|
| `WACC` | Normal ($\sigma$ = 1.5%) | 12.0% | 10.1% | 13.9% |
| $g_1$ (Phase 1 growth) | Triangular (0%, mode, 12%) | 5.0% | 2.4% | 9.0% |
| `FCF` | Log-Normal ($\sigma$ = 25%) | $2.47 Bn | $1.75 Bn | $3.34 Bn |
| $g_2$ (Terminal growth) | Uniform (1.5%–3.5%) | 2.5% | 1.7% | 3.3% |

**Portfolio Risk (MCHP/ON/QCOM/MPWR, equal weight, normalized to 100):**

| Metric | Value |
|--------|------:|
| Portfolio Median | 46.05 |
| `VaR` 95% | 80.44% loss |
| `VaR` 99% | 84.57% loss |
| `CVaR` 99% (Expected Shortfall) | 85.77% loss |
| Diversification Effect vs. Single Names | 6.3% Std reduction |
| Largest Uncertainty Driver | `FCF` (21.3 pp swing in `VaR` 99%) |

**Limited liability caps the loss at 100%.** A simulated equity value is floored at zero before it enters the loss distribution, because a shareholder can lose the capital invested but no more. This is the same assumption Model 1 rests on, where equity is priced as a call option with payoff $\max(V-D,\,0)$ — the three models share it rather than each making its own.

![QCOM Monte Carlo Dashboard](images/QCOM_MCS_Dashboard.png)

The table below translates each ticker's simulated loss distribution into VaR/CVaR terms relative to its current market price (100% = no loss, 100% = total loss).

| Ticker | VaR 95% | VaR 99% | CVaR 99% |
|---|---|---|---|
| MCHP | 76.6% | 83.0% | 84.2% |
| INTC | — ¹ | — ¹ | — ¹ |
| ON | 79.0% | 84.0% | 85.1% |
| QCOM | 78.7% | 83.4% | 84.4% |
| MPWR | 92.2% | 93.4% | 93.7% |
| **Portfolio** (4 tickers, 25% each) | **80.4%** | **84.6%** | **85.8%** |
| *All five, for reference* ² | *84.4%* | *87.7%* | *88.6%* |

¹ **No DCF-based risk measure is reported for INTC, because the model that would produce it does not apply.** Its normalized `FCF` is −$9.62 Bn, so every simulated equity value comes out negative and the floor sends all 10,000 draws to a total loss. Printing the resulting 100% would state something the model cannot support and would read as a certain default — while the Merton model in this same repository puts INTC's one-year `PD` at 0.0131%. Model 1 is the applicable tool here, and it does rank INTC as the weakest of the five (`DD` = 3.65, IFRS 9 Stage 2) without needing a cash flow forecast at all. Where one model reaches its limit, another still answers, which is the reason for running all three. (On the sampling: Log-Normal draws require a positive mean, so `FCF` falls back to a Normal distribution centred on the negative mean with its standard deviation scaled to the same magnitude, |mean| × 25% — the intended relative uncertainty is preserved without a sign change.)

² Kept visible rather than dropped: including INTC pins a fifth of the portfolio at total loss by construction, which is why the four-ticker figure is the one reported. INTC is excluded from this measure only — it remains fully part of the study in Models 1 and 2.

**The diversification effect is small — 6.3% standard deviation reduction — and that is the expected outcome.** All five companies come from one sector, and the model itself imposes 60% pairwise correlation between them. Diversification arises from combining assets that move independently, which is precisely what this portfolio does not do. The number is consistent with the deliberate design of the study: the semiconductor sector was chosen for its concentration and cyclicality in order to stress-test the credit models, not to build a diversified portfolio. Computing the same measure over only the four tickers with an applicable DCF yields 6.3% as well, so the result does not hinge on how INTC is handled.

---

## Tech Stack

Python 3.12+ (CI runs 3.12 and 3.13) · pandas · numpy · scipy · plotly · openpyxl

```bash
git clone https://github.com/carlos-schwiening/semiconductor-risk-analysis
cd semiconductor-risk-analysis
pip install -e .
python Merton/Merton_Model.py --ticker MCHP
python DCF/DCF_Valuation.py --ticker MCHP
python MCS/Monte_Carlo_Sim.py --ticker MCHP
```

This installs the project as a package (see `pyproject.toml`), so `Merton`,
`DCF`, `MCS`, and `Config` can be imported cleanly without path hacks.

**Data cache location.** Every model reads its input from a local folder of
cached FMP JSON files. By default the scripts look in `data/FMP_Cache/` inside
the project. If your cache lives elsewhere, point the `FMP_CACHE_DIR`
environment variable at it:

```bash
export FMP_CACHE_DIR=/path/to/FMP_Cache          # macOS / Linux
setx FMP_CACHE_DIR "D:\path\to\FMP_Cache"        # Windows, once
```

All generated artefacts are written to `Outputs/` inside the project and are
excluded from version control.

Each script is self-contained and runs against a local FMP cache. Switch the
active ticker via `--ticker` (`MCHP` | `INTC` | `ON` | `QCOM` | `MPWR`,
defaults to `MCHP`) — no code editing needed. `Merton_Report.py` and the
other multi-ticker scripts process all five tickers regardless of `--ticker`;
`DCF_Valuation.py`'s peer-group comparison block and `Monte_Carlo_Sim.py`'s
correlated portfolio simulation likewise always include all five tickers
alongside the `--ticker`-selected one.

---

## Code Structure

Each model is split into a pure calculation module and a script that orchestrates it. The calculation modules take numbers and return numbers — no file access, no API calls, no charts — which is what makes them unit-testable and keeps a single formula from drifting apart across scripts.

```
Merton/merton_core.py   Merton model, rating table, credit spread
DCF/dcf_core.py         Two-phase DCF, CAPM, sensitivities, Monte Carlo, classifiers
DCF/fmp_extract.py      Cache access and FMP field mapping
```

`fmp_extract.py` is the only module that knows FMP field names. The calculation modules never see them, so replacing the data provider means changing that one file. The remaining scripts (`Merton_Model.py`, `DCF_Valuation.py`, `DCF_Report.py`, `Monte_Carlo_Sim.py`) load data, call the core modules, and handle output.

## Tests & Continuous Integration

[GitHub Actions](.github/workflows/ci.yml) runs on every push to `main`:

- **85 tests** (`python -m pytest`) over the calculation modules. Deterministic functions are checked against closed-form results — with zero growth the DCF must collapse to `FCF / WACC`, and enterprise value must not depend on how the cash flows are split between forecast and terminal phase. Stochastic functions are tested on properties instead of fixed values: reproducibility under a fixed seed, correct ordering of the output range, wider dispersion under wider inputs. The Monte Carlo tests assert impossibilities rather than values — a loss above 100% of the invested amount, a conditional VaR below its own VaR, a scenario the model could not evaluate counted as a total loss.
- **mypy** across all three model entry points and their core modules. `mypy.ini` sets `disallow_untyped_defs`, because mypy otherwise skips the bodies of unannotated functions — a green run without that flag says considerably less than it appears to.

Both run in a clean environment on Ubuntu with Python 3.12, so a dependency that happens to be installed locally cannot mask a missing entry in `pyproject.toml`.

---

## Data

Price history, balance sheet, income statement, cash flow, and key metrics are sourced from the Financial Modeling Prep (FMP) API (`/stable/` endpoints) and cached locally as JSON files before processing. No API key is stored in this repository — the key is read from a local `Config/Api_keys.py` file excluded via `.gitignore`. The S&P 500 price series used for beta estimation is cached as `SP500_historical-price-eod_full.json`.

---

## Author

**Carlos Schwiening** — MSc Accounting, Finance & Controlling  
GitHub: [carlos-schwiening](https://github.com/carlos-schwiening)

---

## References

Bolder, David Jamieson (2018): Credit-Risk Modelling. Theoretical Foundations, Diagnostic Tools, Practical Examples, and Numerical Recipes in Python. 1st ed. Cham: Springer International Publishing.

Desmettre, Sascha; Korn, Ralf (2018): Erweiterungen des Black-Scholes-Modells, Zins, Kreditrisiko und Statistik. Wiesbaden: Springer Spektrum (Studienbücher Wirtschaftsmathematik, Band 2).

Gleißner, Werner (2019): Risikoaggregation und Monte-Carlo-Simulation: Schlüsseltechnologie für Risikomanagement und Controlling. 1. Auflage. Wiesbaden: Springer Verlag.

IDW – Institut der Wirtschaftsprüfer in Deutschland e. V. (2017): Grundsätze zur Durchführung von Unternehmensbewertungen (IDW S 1 i.d.F. 2008). Düsseldorf.

Merton, Robert C. (1974): On the Pricing of Corporate Debt: The Risk Structure of Interest Rates. In: The Journal of Finance, Vol. 29, No. 2, pp. 449-470.

Witzany, Jiří (2017): Credit Risk Management. Pricing, Measurement, and Modeling. 1st ed. Cham: Springer International Publishing.

Zieliński, Tomasz: Merton's and KMV Models in Credit Risk Management. University of Economics in Katowice.
