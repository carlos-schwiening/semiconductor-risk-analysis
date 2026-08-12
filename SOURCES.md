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

**Which figures.** Average cumulative default rates by rating category,
1981–2023, from S&P Global Ratings' annual default and transition study.

**See it yourself.** <https://www.spglobal.com/ratings/en/research-insights/topics/default-transition-and-recovery>
The study is published yearly and free to read, but the site blocks automated
access and may ask you to register. If the link fails, searching for *"S&P
Global annual global corporate default and rating transition study"* finds the
current edition.

**Limits that matter.** These are **realised historical frequencies** for rated
issuers, not forward-looking probabilities, and the rated universe skews larger
and better-capitalised than the market as a whole. They are the right yardstick
for "is this number plausible", and the wrong one for "is this number correct".

---

## 6. Damodaran (NYU Stern) — sector reference values

**What for.** The reference the computed betas and multiples are held against.
The README discloses that the 252-day betas (1.67–2.46) sit above the
semiconductor sector reference (roughly 1.55–1.75), and that this drives much of
the overvaluation result.

**See it yourself.** <https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html>
Free, no registration, updated each January. Look for the industry beta and
multiple tables.

**Covers.** Industry-level betas, costs of capital and multiples, US and global.

**Limits that matter.** Industry averages, not company-specific. They tell you
whether a computed value is in a normal range; they do not tell you the value is
wrong. The README uses them exactly that way — as a disclosed gap, not a
correction applied to the model.

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

## 8. Agency credit ratings

**What for.** The benchmark in *Model against the agencies*. Without it the
Merton letters would only be compared to themselves.

**Where.** Set per ticker in `Config/{TICKER}.py` as `RATING`. `None` means the
issuer has no rated debt — the value is absent because the rating does not
exist, not because it is unknown.

| Ticker | Rating | Agency and date |
|--------|--------|-----------------|
| MCHP | BBB | Fitch, affirmed 2025-03-20; Moody's cut Baa1 → Baa2 on 2025-03-21 |
| INTC | BBB | S&P, cut from BBB+ in Aug 2025 |
| ON | BB+ | S&P; Moody's affirmed Ba1 in Jan 2026 |
| QCOM | A | S&P, affirmed 2024-03-08; Moody's A2 |
| MPWR | *none* | no agency rates it |

**See it yourself.** Two free routes, both without a subscription:
- The company's own 10-K on EDGAR. Intel names its rating outright: *"In August
  2025, a major credit rating agency downgraded our corporate credit rating from
  BBB+ to BBB."* Microchip confirms the March 2025 downgrade but not the letter.
- The agencies publish rating actions as press releases; S&P Global Ratings and
  Moody's both allow free registration.

**Limits that matter.**
- **Only INTC is primary-sourced.** Intel states its rating in a filing it is
  legally responsible for. The other three come from agency press reporting,
  which is one step removed.
- **Ratings move.** Each row carries its date for that reason; QCOM's is from
  2024 and is the oldest here.
- **Split ratings are normal.** MCHP is Baa2 at Moody's and BBB at Fitch — the
  same credit, two scales, and the 10-K's *"downgraded by one rating agency"*
  is only intelligible once you know both.
- **FMP does not supply these.** Its `ratings-snapshot` endpoint returns letters
  that look like agency ratings but are FMP's own metric scoring — it grades
  Intel `D+`. Using it here would have put a junk grade beside an
  investment-grade issuer.

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
