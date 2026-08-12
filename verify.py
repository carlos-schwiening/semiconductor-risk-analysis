"""
verify — Recompute the published figures and report where they no longer hold.
Run with: python verify.py [--full]

A number in a README has no link to the code that made it. This README claimed
51 tests for months after the suite had grown to 85.

A mismatch is a FINDING: either the source moved or the code did. Establish
which before correcting either.

  cheap      Constants, config, structural facts. No cache, no network.
  --full     Re-runs the models over the cached FMP data. Needs FMP_CACHE_DIR.
  by hand    Outside publications (S&P, Damodaran). Printed every run so they
             are not assumed current.

The README has ~290 figures, mostly cells in the three result tables. Those are
outputs of the same runs, so re-running the models is their check. Declared here
is every figure that can drift on its own.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple, cast

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "Merton"),
           os.path.join(PROJECT_ROOT, "DCF"), os.path.join(PROJECT_ROOT, "MCS")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TICKERS = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
README = "README.md"
# endregion


# ----------------------------------------------------------------------------
# region CLAIM DEFINITION
# ----------------------------------------------------------------------------
class Claim(NamedTuple):
    """One published figure, with where it appears and how to recompute it."""
    source: str            # which SOURCES.md entry it comes from
    claim: str             # what is asserted, in words
    document: str          # the file the figure appears in
    expected: Any
    compute: Callable[[], Any]
    expensive: bool = False   # needs the FMP cache; skipped unless --full


class Result(NamedTuple):
    claim: Claim
    actual: Any
    ok: bool
    skipped: bool
# endregion


# ----------------------------------------------------------------------------
# region READING THE DOCUMENTS
# ----------------------------------------------------------------------------
def _readme() -> str:
    with open(os.path.join(PROJECT_ROOT, README), encoding="utf-8") as fh:
        return fh.read()


def _claimed_test_count() -> int:
    """The test count as the README states it."""
    match = re.search(r"\*\*(\d+) tests\*\*", _readme())
    return int(match.group(1)) if match else -1


def _actual_test_count() -> int:
    """What pytest actually collects — the number the README should agree with."""
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "--co"],
                         cwd=PROJECT_ROOT, capture_output=True, text=True)
    match = re.search(r"(\d+) tests? collected", out.stdout)
    return int(match.group(1)) if match else -1


def _readme_headline_table() -> dict[str, dict[str, str]]:
    """
    The Key Results table, parsed back out of the README.

    Reading the published figures from the document rather than restating them
    here is deliberate: a claim that quotes itself proves nothing.

    Anchored to its heading, not matched by shape. Three tables in this README
    have eight columns and start with a ticker, and an unanchored match silently
    returned the last of them — the WACC table, where column 2 is a percentage
    rather than a rating. That is the same failure the filing parser is tested
    against: the right-looking pattern occurring more than once, and the wrong
    occurrence winning quietly.
    """
    rows: dict[str, dict[str, str]] = {}
    inside = False
    for line in _readme().splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Key Results"
            continue
        if not inside:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0] in TICKERS:
            rows[cells[0]] = {"dd": cells[2], "stage": cells[6]}
    return rows


def _readme_model1_table() -> dict[str, dict[str, str]]:
    """
    The Merton table, which is where the DD band is published.

    Anchored to its own heading and stopped at the end of the first table: two
    other tables in this section also start with a ticker, and an unanchored
    match let the wrong one win silently once already.
    """
    rows: dict[str, dict[str, str]] = {}
    inside = False
    for line in _readme().splitlines():
        if line.startswith("#"):
            inside = line.strip() == "## Model 1 — Merton Structural Credit Risk"
            continue
        if not inside:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in TICKERS:
            rows[cells[0]] = {"dd": cells[2], "band": cells[3]}
        elif rows and not line.startswith("|"):
            break
    return rows


def _claimed_dd(ticker: str) -> float:
    row = _readme_headline_table().get(ticker)
    return float(row["dd"]) if row else float("nan")


SP_5Y_RATES = {"AAA": 0.34, "AA": 0.28, "A": 0.39, "BBB": 1.36,
               "BB": 5.75, "B": 15.60, "CCC/C": 46.53}


def _readme_pd_table() -> dict[str, dict[str, str]]:
    """
    The PD comparison table: model PD against the S&P class it lands nearest.

    This table had no claim on it, which is why a stale column survived the
    removal of the rating letters - it still named the class the deleted mapping
    would have assigned. A published figure with nothing pointing at it is a
    figure that drifts unobserved.
    """
    rows: dict[str, dict[str, str]] = {}
    for line in _readme().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] in TICKERS and cells[1].endswith("%"):
            rows[cells[0]] = {"pd5": cells[2].strip("*"), "klass": cells[3]}
    return rows


def _claimed_nearest_class(ticker: str) -> str:
    row = _readme_pd_table().get(ticker)
    return row["klass"] if row else "?"


def _nearest_class_from_published_pd(ticker: str) -> str:
    """Recompute the class from the PD printed beside it, on a log scale."""
    import math
    row = _readme_pd_table().get(ticker)
    if not row:
        raise ValueError(f"{ticker} is not in the PD table - shape changed")
    pd_val = float(row["pd5"].rstrip("%"))
    if pd_val <= 0:
        return "none — below AA"
    return min(SP_5Y_RATES, key=lambda k: abs(math.log(pd_val / SP_5Y_RATES[k])))


def _claimed_band(ticker: str) -> str:
    row = _readme_model1_table().get(ticker)
    return row["band"] if row else "?"


# endregion


# ----------------------------------------------------------------------------
# region CHEAP CLAIMS - CONFIGURATION AND CONSTANTS
# ----------------------------------------------------------------------------
def _risk_free_rates() -> set[float]:
    """Every ticker config should carry the same rate the README quotes."""
    import importlib
    return {getattr(importlib.import_module(f"Config.{t}"), "RISK_FREE_RATE")
            for t in TICKERS}


def _configured_tickers() -> list[str]:
    config_dir = os.path.join(PROJECT_ROOT, "Config")
    return sorted(f[:-3] for f in os.listdir(config_dir)
                  if f.endswith(".py") and not f.startswith("__"))


def _loss_floor() -> float:
    """
    The limited-liability floor. If this ever moves off zero again, the Monte
    Carlo model can report a loss above 100% of capital - which it did, and
    which is why this claim exists.
    """
    from mcs_core import REL_FLOOR   # type: ignore[import-not-found]
    return REL_FLOOR


def _dcf_collapses_to_perpetuity() -> bool:
    """
    A property the README asserts: with zero growth the two-phase DCF must
    collapse to FCF / WACC. Arithmetic, so it is checkable without any data.
    """
    from dcf_core import DcfParams, dcf_full   # type: ignore[import-not-found]
    params: DcfParams = {"fcf_start": 1_000.0, "g1": 0.0, "g2": 0.0, "wacc": 0.10,
                         "years": 5, "net_debt": 0.0, "shares": 1.0}
    return abs(dcf_full(params)["ev"] - 1_000.0 / 0.10) < 1.0


def _band_for_dd(dd: float) -> str:
    from merton_core import dd_band   # type: ignore[import-not-found]
    return str(dd_band(dd))


# endregion


# ----------------------------------------------------------------------------
# region EXPENSIVE CLAIMS - RE-RUNNING THE MODEL
# ----------------------------------------------------------------------------
def _recomputed_merton(ticker: str) -> dict[str, Any]:
    """
    Re-run the Merton model for one ticker off the cached FMP data and return
    the figures the README publishes. Requires FMP_CACHE_DIR.
    """
    import importlib
    import json

    import numpy as np
    import pandas as pd

    from merton_core import merton_model

    cache = os.environ.get("FMP_CACHE_DIR")
    if not cache:
        raise RuntimeError("FMP_CACHE_DIR is not set")

    def load(name: str) -> Any:
        with open(os.path.join(cache, f"{ticker}_{name}.json"), encoding="utf-8") as fh:
            return json.load(fh)

    config = importlib.import_module(f"Config.{ticker}")
    prices = pd.DataFrame(load("historical-price-eod_full"))
    prices["date"] = pd.to_datetime(prices["date"])
    close = prices.sort_values("date").set_index("date")["close"]
    # pandas-stubs types np.log on a Series as an ndarray; at runtime pandas
    # returns a Series, so .dropna() exists. Stating the type beats a blanket
    # suppression that would also hide a real error on this line.
    log_returns = cast(pd.Series, np.log(close / close.shift(1))).dropna()
    sigma_e = float(log_returns.std() * np.sqrt(252))

    balance = load("balance-sheet-statement")[0]
    metrics = load("key-metrics")[0]
    equity = float(metrics.get("marketCap", 0) or 0)
    debt = float(balance.get("totalDebt", 0) or 0)

    # Named on purpose: the signature is (E, D, r, T, sigma_e), and written
    # positionally this passed volatility where the rate belongs.
    result = merton_model(E=equity, D=debt, r=config.RISK_FREE_RATE,
                          T=config.MATURITY, sigma_e=sigma_e)
    return {"dd": round(float(result["dd"]), 2)}


def _recomputed_dd(ticker: str) -> float:
    return float(_recomputed_merton(ticker)["dd"])
# endregion


# ----------------------------------------------------------------------------
# region THE CLAIMS
# ----------------------------------------------------------------------------
def _readme_images_exist() -> list[str]:
    """Every image the README links to, that is actually missing."""
    text = _readme()
    missing = []
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if target.startswith("http"):
            continue
        if not os.path.exists(os.path.join(PROJECT_ROOT, target)):
            missing.append(target)
    return missing


def _images_without_a_producer() -> list[str]:
    """
    Images in images/ that no script writes there.

    INTC_KMV_Textbook.png was copied here by hand and went nearly two months out
    of date, because the script that draws it wrote only to Outputs/. Nothing
    noticed. An image nobody regenerates is a published figure with no source.
    """
    images_dir = os.path.join(PROJECT_ROOT, "images")
    if not os.path.isdir(images_dir):
        return []
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in Path(PROJECT_ROOT).rglob("*.py")
        if ".ipynb_checkpoints" not in path.parts
    )
    return sorted(name for name in os.listdir(images_dir)
                  if name.endswith(".png") and name not in sources)


def _rating_claim(ticker: str) -> Callable[[], str]:
    """Bind one ticker into a checkable claim; a bare lambda with a default
    argument leaves mypy nothing to infer the return type from."""
    return lambda: _band_for_dd(_claimed_dd(ticker))


def _nearest_class_claim(ticker: str) -> Callable[[], str]:
    return lambda: _nearest_class_from_published_pd(ticker)


def _dd_claim(ticker: str) -> Callable[[], float]:
    return lambda: _recomputed_dd(ticker)


def build_claims() -> list[Claim]:
    claims: list[Claim] = [
        Claim(
            source="Repository itself",
            claim="the README's test count matches what pytest collects",
            document=README,
            expected=_actual_test_count(),
            compute=_claimed_test_count,
        ),
        Claim(
            source="7. Treasury rates",
            claim="every ticker config uses the 4.3% risk-free rate the README quotes",
            document="Config/*.py",
            expected={0.043},
            compute=_risk_free_rates,
        ),
        Claim(
            source="Repository itself",
            claim="the five configured tickers are the five the README reports on",
            document=README,
            expected=sorted(TICKERS),
            compute=_configured_tickers,
        ),
        Claim(
            source="Model 3 - Monte Carlo",
            claim="losses are floored at zero (a share cannot lose more than everything)",
            document="MCS/mcs_core.py",
            expected=0.0,
            compute=_loss_floor,
        ),
        Claim(
            source="Model 2 - DCF",
            claim="with zero growth the DCF collapses to FCF / WACC",
            document=README,
            expected=True,
            compute=_dcf_collapses_to_perpetuity,
        ),
        Claim(
            source="Repository itself",
            claim="every image the README links to exists",
            document=README,
            expected=[],
            compute=_readme_images_exist,
        ),
        Claim(
            source="Repository itself",
            claim="every image in images/ is written by a script",
            document="images/",
            expected=[],
            compute=_images_without_a_producer,
        ),
    ]

    for ticker in TICKERS:
        claims.append(Claim(
            source="Model 1 - Merton",
            claim=f"{ticker}: the published DD band follows from the published DD",
            document=README,
            expected=_claimed_band(ticker),
            compute=_rating_claim(ticker),
        ))

    for ticker in TICKERS:
        claims.append(Claim(
            source="5. S&P Global",
            claim=f"{ticker}: the nearest S&P class follows from the published PD",
            document=README,
            expected=_claimed_nearest_class(ticker),
            compute=_nearest_class_claim(ticker),
        ))

    # Expensive: re-run the model and compare against what the README prints.
    for ticker in TICKERS:
        claims.append(Claim(
            source="1-4. FMP",
            claim=f"{ticker}: recomputed Distance to Default matches the README",
            document=README,
            expected=_claimed_dd(ticker),
            compute=_dd_claim(ticker),
            expensive=True,
        ))

    return claims


# Figures no code in this repository can recompute. Listed so they are not
# mistaken for verified just because everything above passed.
BY_HAND = [
    ("5. S&P Global", "observed default rates, 1981-2024 edition, Table 24 p.56",
     "maalot.co.il/Publications/FTS20250331162126.pdf - take all seven from one "
     "edition or none; the previous set was blended across editions"),
    ("6. Damodaran", "the January 2026 sector betas, 1.40 and 1.52",
     "pages.stern.nyu.edu/~adamodar - betas.xls, sheet Industry Averages"),
    ("6. Damodaran", "the multiple bands in the cross-check",
     "vebitda.xls, pedata.xls, psdata.xls - same vintage as the betas or none"),
]
# endregion


# ----------------------------------------------------------------------------
# region RUN
# ----------------------------------------------------------------------------
def run(full: bool = False) -> int:
    results: list[Result] = []
    for claim in build_claims():
        if claim.expensive and not full:
            results.append(Result(claim, None, True, True))
            continue
        try:
            actual = claim.compute()
            ok = actual == claim.expected
        except Exception as exc:                       # a claim that cannot run is a finding
            actual, ok = f"ERROR: {type(exc).__name__}: {exc}", False
        results.append(Result(claim, actual, ok, False))

    width = max(len(r.claim.claim) for r in results)
    print(f"\n{'':6} {'Claim':<{width}}  {'expected':>12}  {'actual':>12}")
    print("-" * (width + 36))
    for r in results:
        if r.skipped:
            print(f"{'[skip]':6} {r.claim.claim:<{width}}  {'--full needed':>12}")
            continue
        mark = "[OK  ]" if r.ok else "[FAIL]"
        print(f"{mark:6} {r.claim.claim:<{width}}  "
              f"{str(r.claim.expected):>12}  {str(r.actual):>12}")

    failures = [r for r in results if not r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    print("-" * (width + 36))
    print(f"{len(results) - len(failures) - len(skipped)} ok, "
          f"{len(failures)} failed, {len(skipped)} skipped")

    if failures:
        print("\nDocuments to correct - but establish WHY the figure moved first.")
        print("A mismatch means the source changed or the code did. Editing the")
        print("document to match the new number without knowing which is how a")
        print("wrong figure becomes a permanent one.\n")
        for r in failures:
            print(f"  {r.claim.document}: {r.claim.claim}")
            print(f"    published {r.claim.expected!r}, recomputed {r.actual!r}")

    print("\nNot checkable by code - verify these by hand against the source:")
    for source, figure, how in BY_HAND:
        print(f"  {source:<16} {figure}")
        print(f"  {'':16} -> {how}")

    if not full:
        print("\nModel re-runs were skipped. Run with --full and FMP_CACHE_DIR set")
        print("to recompute the headline table from the cached data.")

    return 1 if failures else 0
# endregion


if __name__ == "__main__":
    sys.exit(run(full="--full" in sys.argv))
