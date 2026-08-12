# Sources

Where every number in this repository comes from, and what each source can and
cannot support. The README says what the models do and what came out; this file
says where the inputs came from, so any figure can be traced back without
reading the code.

Each source has the same fields, so you can skim to the one you need.

---

## 1. Financial Modeling Prep — daily price history

**What for.** Equity volatility and the 252-day OLS beta (both models), market
capitalisation as the equity value in the Merton model, and the current price
every valuation is compared against.

**Endpoint.** `/stable/historical-price-eod/full?symbol={TICKER}`
Cached as `{TICKER}_historical-price-eod_full.json`.

**See it yourself.** The endpoint needs an API key, so there is no link that
works in a plain browser. What *is* checkable without one: any of these five
prices against a public quote page for the same date. A price series that agrees
with a public source on a handful of dates is not proof of the whole history,
but a series that disagrees is disqualified immediately.

**Covers.** MCHP, INTC, ON, QCOM, MPWR, plus the S&P 500 series used as the beta
benchmark (`SP500_historical-price-eod_full.json`). Daily closes.

**Cost.** Paid API. The endpoint returns at most 5,000 rows per request — about
19.8 trading years — and **truncates silently** beyond that rather than paging or
erroring, which is why the workspace client fetches long histories in chunks.

**Limits that matter.**
- These are **not** dividend-adjusted closes. For a beta and a volatility that is
  the right choice; for a total-return series it would not be.
- Vendor data. It must not be committed to this repository, which is why the
  cache lives outside it and `.gitignore` excludes the data directory.
- A one-year daily beta is a noisy estimator. The README says so explicitly and
  quantifies the gap against the sector reference below — that disclosure exists
  because of this source's properties, not despite them.

---

## 2. Financial Modeling Prep — balance sheet

**What for.** Total debt, which is the default barrier in the Merton model, and
net debt in the DCF bridge from enterprise value to equity value.

**Endpoint.** `/stable/balance-sheet-statement?symbol={TICKER}`
Cached as `{TICKER}_balance-sheet-statement.json`.

**See it yourself.** The same figures are in the company's own 10-K on SEC
EDGAR, which needs no key. For example, Microchip Technology:
<https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=MCHP&type=10-K>
Comparing one year of total debt against the filing is the single most useful
check on this whole pipeline: it is the input the Merton model is most sensitive
to.

**Covers.** Annual statements per ticker.

**Cost.** Paid API. The free plan caps fundamentals at five years.

**Limits that matter.** The barrier is **interest-bearing debt** here — which is
the textbook choice, and the reason the Distance to Default figures in this
project are **not** comparable to `credit-risk-validation`, where the barrier is
total liabilities because debt tags are sparsely populated in XBRL.

---

## 3. Financial Modeling Prep — income statement and cash flow

**What for.** Revenue and EBIT for growth and margin inputs; free cash flow as
the DCF's starting figure, normalised to the five-year median.

**Endpoints.** `/stable/income-statement`, `/stable/cash-flow-statement`
Cached as `{TICKER}_income-statement.json`, `{TICKER}_cash-flow-statement.json`.

**See it yourself.** Same 10-K link as above.

**Covers.** Annual statements per ticker.

**Limits that matter.** The five-year median smooths the semiconductor cycle,
and for four of the five names it works. It does not rescue INTC, whose median
across the window is itself negative (−$9.62 Bn). The DCF is reported as **not
applicable** for INTC rather than normalised into a positive number — a model
limit stated rather than smoothed away.

---

## 4. Financial Modeling Prep — key metrics and TTM ratios

**What for.** WACC inputs: interest expense over total debt for the cost of
debt, and the market-value capital structure weighting.

**Endpoints.** `/stable/key-metrics`, `/stable/key-metrics-ttm`, `/stable/ratios-ttm`

**Covers.** Per ticker, most recent fiscal year and trailing twelve months.

**Limits that matter.** The multiples cross-check uses **the most recent fiscal
year**, while the DCF normalises over five. In a trough year that inflates the
multiples sharply — MCHP's P/E of 173x reflects collapsed trailing earnings, not
a 173-year payback. The two are deliberately on different bases and the README
says so; they are not two valuations to be averaged.

---

## 5. S&P Global — observed corporate default rates

**What for.** The plausibility check on the model's output. The README puts the
Merton five-year PD next to S&P's observed cumulative default rate for the same
rating category — the test of whether a modelled probability is in the right
order of magnitude at all.

**Which figures.** One edition, named exactly, because the previous entry was not:

> S&P Global Ratings, *Default, Transition, and Recovery: 2024 Annual Global
> Corporate Default And Rating Transition Study*, published 27 March 2025,
> **Table 24**, page 56 — "Global corporate average cumulative default rates,
> 1981-2024". Underlying data: S&P Global Market Intelligence's CreditPro.

| Rating | Y1 | Y5 |
|--------|---:|---:|
| AAA | 0.00% | 0.34% |
| AA | 0.02% | 0.28% |
| A | 0.05% | 0.39% |
| BBB | 0.14% | 1.36% |
| BB | 0.56% | 5.75% |
| B | 2.93% | 15.60% |
| CCC/C | 26.12% | 46.53% |

**See it yourself.** <https://maalot.co.il/Publications/FTS20250331162126.pdf> —
the full text mirrored by Maalot, S&P's Israeli affiliate, free and without a
login. Table 24 begins on page 55 and continues on 56. The same document behind
<https://www.spglobal.com/ratings/en/research-insights/topics/default-transition-and-recovery>
requires registration.

**Limits that matter.**
- **The previous figures matched no edition.** They read AAA/AA 0.30, A 0.55,
  BBB 1.55, BB 5.60 at five years. Checked against three editions, A 0.55 fits an
  older one while BB 5.60 is below even the newest — mutually exclusive, and all
  four ended in a round 0 or 5, which S&P's figures effectively never do. They
  were smoothed by hand somewhere along the way. Every figure now comes from the
  single edition named above.
- **A newer edition exists** (1981–2025, published 18 March 2026) but only its
  teaser is free; the tables sit behind registration. Moving to it means moving
  all seven values at once, not just the reachable ones.
- **AAA looks worse than AA at five years** (0.34% vs 0.28%). That is in the
  source, not a transcription error — the AAA cohort is small enough that its
  rates are noisy. It is also why MPWR's combined AAA/AA bucket is shown as a
  range rather than one number.
- **Realised historical frequencies**, not forward-looking probabilities, and the
  rated universe skews larger and better-capitalised than the market as a whole.
  The right yardstick for "is this plausible", the wrong one for "is this right".

---

## 6. Damodaran (NYU Stern) — sector reference values

**What for.** The reference the computed betas and multiples are held against,
and the anchor for the equity risk premium.

**Which vintage.** **January 2026** — the whole dataset carries one date, and
mixing vintages is how the S&P figures above went wrong. From `betas.xls`,
sheet *Industry Averages*, dated 2026-01-05:

| Industry | Firms | Beta | EV/EBITDA | Trailing P/E | EV/Sales |
|----------|------:|-----:|----------:|-------------:|---------:|
| Semiconductor | 66 | 1.52 | 34.8 | 100.2 | 15.7 |
| Semiconductor Equipment | 31 | 1.40 | 24.7 | 46.8 | 7.6 |

The multiples cross-check uses the two rows as the low and high of its band.
Files: `betas.xls`, `vebitda.xls`, `pedata.xls`, `psdata.xls`, all sheet
*Industry Averages*.

**See it yourself.** <https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html>
Free, no registration, updated each January. The raw files sit under
`pages.stern.nyu.edu/~adamodar/pc/datasets/` — `betas.xls` for the table above,
`histimpl.xls` for the implied premium below.

**Covers.** Industry-level betas, costs of capital and multiples, US and global.

**Limits that matter.**
- **The 5.5% equity risk premium is not a Damodaran figure.** His implied ERP was
  **4.18%** at end-2025 and his 2006–2025 average **5.16%**. The 5.5% in
  `dcf_core.py` is a rounded assumption sitting above both, and it feeds every
  WACC in the project. It is left unchanged so the published DCF table stays
  reproducible, and it is named here rather than passed off as sourced.
- **The reference betas moved.** This entry previously said "roughly 1.55–1.75"
  with no vintage; the January 2026 figures are 1.40–1.52. The gap between the
  model's 252-day betas and the reference is therefore wider than the README
  used to claim, not narrower.
- **The multiple bands were badly stale.** They read 15–25 / 20–35 / 3–8 under a
  "Jan 2025" label, against actual figures of 24.7–34.8 / 46.8–100.2 / 7.6–15.7.
  The sector re-rated far above the old bands, so nearly everything was marked
  expensive by construction. Correcting them moved MCHP's EV/Sales from
  *expensive* to *fair* — no README figure depended on them, which is the only
  reason this was a small fix rather than a large one.
- **Industry averages, not company-specific.** They say whether a computed value
  is in a normal range, not that it is wrong. The README uses them that way — as
  a disclosed gap, not a correction applied to the model.

---

## 7. Treasury rates

**What for.** The risk-free rate in CAPM and in the Merton model.

**Where.** Set per ticker in `Config/{TICKER}.py` as `RISK_FREE_RATE`, currently
4.3%. The workspace FMP client can fetch `/stable/treasury-rates`, but the value
used here is a configured constant, not a live pull.

**See it yourself.** <https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve>
Free, no key, updated daily.

**Limits that matter.** A constant, not a curve. Every discounted cash flow in
the project uses the same rate at every maturity. That is a simplification worth
knowing about before comparing these figures to anything term-structured.

---

## 8. Industry outlooks — the scenario assumptions

**What for.** The Bear/Base/Bull cases in Model 2. They are not abstract
±1.5 percentage-point nudges; each leg names a dated industry development.

**Which sources.**

| Source | Used for |
|--------|----------|
| Semiconductor Industry Association / WSTS Spring 2026 Forecast | the $1.5T 2026 industry sales figure in the Base Case |
| Deloitte 2026 Semiconductor Industry Outlook | AI capex monetization risk (Bear), the ~$500B AI-chip share (Base) |
| IDC, January 2026 (via The Straits Times) | memory cost pressure on PC/smartphone demand (Bear) |
| SIA, "Chip Incentives & Investments" | CHIPS Act Section 48D credit expiring Dec 2026 (Bear) |
| Pillsbury Law, June 2025 | Senate draft raising Section 48D from 25% to 30% (Bull) |

**See it yourself.** All five are free to read online; the README footnote under
the scenario table names each one in full.

**Limits that matter.**
- **Forecasts, not data.** WSTS and Deloitte publish expectations that later turn
  out right or wrong. Nothing here re-checks them, and the scenario table would
  not change if they did.
- **They justify direction, not magnitude.** Why the Bear case lowers growth is
  sourced; that it lowers it by exactly 2 points is not — that is a model
  parameter, chosen to bracket a plausible downturn.
- **Dated to 2025/26.** A scenario framework built on a specific policy debate
  ages faster than the model around it.

---

## Checking the numbers: `python verify.py`

Run it from the project root. Without arguments it checks constants,
configuration and structural facts; with `--full` (and `FMP_CACHE_DIR` set) it
re-runs the Merton model per ticker and compares the Distance to Default figures
against what the README publishes.

The README carries roughly **290** numeric figures — my earlier estimate of forty
was badly low — but most are cells in the three models' result tables and are
outputs of the same runs. Re-running the models *is* the check for those. What
`verify.py` covers individually is every figure that can drift on its own.

Three figures cannot be recomputed by any code here and are printed at the end
of every run so they are not mistaken for verified: the S&P observed default
rates and the two Damodaran sector references. Those need a human and the
current publication. A `verify` command here would be worth
building, and it is not built yet.
