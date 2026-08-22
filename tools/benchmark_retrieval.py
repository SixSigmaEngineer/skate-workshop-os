"""SKATE retrieval benchmark — the harness behind the numbers in
Why-SKATE-AI-Memory.docx.

Run from the repository root:

    python tools/benchmark_retrieval.py            # per-query metrics + baselines
    python tools/benchmark_retrieval.py --scale    # payload-vs-vault-size sweep

Measures SKATE's real MCP retrieval path (mcp_server.service.search_memory)
against the committed demo vault, over a fixed query set with hand-labelled
ground truth, and reports:

  * precision@k / recall@k / hit@1 / MRR at several k
  * the same metrics EXPECTED UNDER CHANCE (uniform random ordering of the
    session), computed analytically from the hypergeometric distribution —
    so every headline number ships with its null baseline
  * an exact Clopper-Pearson 95% confidence interval for hit@1
  * mean/median/max payload tokens per query (SKATE's chars/4 estimator)

Methodology limitations, stated up front because they are real:
  * n = 10 queries, ground truth labelled by the tool's author. No public
    benchmark exists for workshop-note retrieval; building a neutral one is
    open work. The chance baselines and CI are the honesty mechanism.
  * Lexical mode only (deterministic — identical output on every run;
    there is no run-to-run variance to average over).
  * The --scale sweep replicates sessions, so it bounds PAYLOAD only;
    it says nothing about ranking quality at scale.
  * Token counts use SKATE's own estimator: ceil(chars / 4).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ.setdefault("SKATE_ROOT", str(REPO / "demo-vault"))
os.environ.setdefault("SKATE_EMBED_BACKEND", "off")
sys.path.insert(0, str(REPO / "ui"))
sys.path.insert(0, str(REPO / "mcp_server"))

import service  # noqa: E402

S1 = "harborlight-service-access-2026"
S2 = "harborlight-volunteer-readiness-2026"

# (query, session, ground-truth filename fragments)
QUERIES = [
    ("why do families repeat their story at every handoff", S1,
     ["stated-problem", "intake-across", "community-quot", "referral-statu"]),
    ("privacy risk of sharing sensitive family information", S1,
     ["risk-sensitive", "opportunity-co", "hmw-one-story"]),
    ("what did we decide about buying a platform", S1,
     ["decision-pilot", "recommendation", "action-two-wee"]),
    ("experienced staff keep private resource lists", S1,
     ["shadow-resourc", "changing-eligi"]),
    ("partner eligibility rules and referral visibility", S1,
     ["changing-eligi", "referral-statu", "bridge-coordin"]),
    ("how long until volunteers feel ready", S2,
     ["stated-si", "bridge-co", "volunteer-quote"]),
    ("the volunteer directory is out of date", S2,
     ["outdated-", "opportuni", "decision-"]),
    ("risk that a playbook overstandardizes human judgement", S2,
     ["risk-over"]),
    ("shadowing quality is inconsistent", S2,
     ["shadowing", "expert-st"]),
    ("what actions did we commit to in the readiness sprint", S2,
     ["action-la", "recommend", "decision-"]),
]


def tok(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def chance_hit1(n: int, m: int) -> float:
    """P(first item of a uniform random ordering is relevant)."""
    return m / n


def chance_mrr(n: int, m: int) -> float:
    """E[1 / rank of first relevant item] under uniform random ordering."""
    return sum(
        (comb(n - m, i - 1) / comb(n, i - 1)) * (m / (n - i + 1)) * (1 / i)
        for i in range(1, n - m + 2)
    )


def chance_precision_at_k(n: int, m: int, k: int) -> float:
    """E[precision@k] under uniform random ordering = m/n (linearity)."""
    return m / n


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact binomial CI via bisection on the regularised incomplete beta."""

    def beta_cdf(a: float, b: float, x: float, steps: int = 100_000) -> float:
        from math import exp, lgamma, log
        ln_c = lgamma(a + b) - lgamma(a) - lgamma(b)
        total = prev = 0.0
        for i in range(1, steps + 1):
            t = x * i / steps
            f = exp(ln_c + (a - 1) * log(t + 1e-300) + (b - 1) * log(1 - t + 1e-300))
            total += (f + prev) / 2 * (x / steps)
            prev = f
        return total

    def solve(a: float, b: float, target: float) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if beta_cdf(a, b, mid) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower = solve(k, n - k + 1, alpha / 2) if k > 0 else 0.0
    upper = solve(k + 1, n - k, 1 - alpha / 2) if k < n else 1.0
    return lower, upper


def resolve_ground_truth():
    governed, _ = service._active_entries()
    by_id = {e.file_id: e for e in governed}

    def fid(session, stub):
        matches = [k for k in by_id if k.startswith(session) and stub in k]
        if len(matches) != 1:
            raise SystemExit(f"ground-truth fragment {stub!r} matched {matches}")
        return matches[0]

    resolved = []
    for query, session, stubs in QUERIES:
        n_session = len([e for e in governed if e.session_key == session])
        resolved.append((query, session, {fid(session, s) for s in stubs}, n_session))
    return governed, resolved


def run_benchmark():
    governed, resolved = resolve_ground_truth()
    print(f"vault: {os.environ['SKATE_ROOT']}")
    print(f"active notes: {len(governed)}   queries: {len(resolved)}   mode: lexical (deterministic)\n")

    print(f"{'query':<46}{'n':>3}{'|GT|':>5}{'rank of 1st':>12}{'RR':>6}")
    print("-" * 74)
    hits, rrs, ch_h, ch_m, payloads = [], [], [], [], []
    per_k = {k: {"p": [], "r": []} for k in (1, 3, 5, 8)}
    for query, session, gt, n_session in resolved:
        result = service.search_memory(query=query, session=session, top_k=20)
        got = [r["memory_id"] for r in result["results"]]
        rank = next((i + 1 for i, x in enumerate(got) if x in gt), None)
        hits.append(1 if rank == 1 else 0)
        rrs.append(1 / rank if rank else 0.0)
        ch_h.append(chance_hit1(n_session, len(gt)))
        ch_m.append(chance_mrr(n_session, len(gt)))
        for k in per_k:
            top = got[:k]
            found = [x for x in top if x in gt]
            per_k[k]["p"].append(len(found) / len(top) if top else 0.0)
            per_k[k]["r"].append(len(found) / len(gt))
        five = service.search_memory(query=query, session=session, top_k=5)
        payloads.append(tok(json.dumps(five, ensure_ascii=False)))
        print(f"{query[:45]:<46}{n_session:>3}{len(gt):>5}{rank:>12}{rrs[-1]:>6.2f}")

    n = len(resolved)
    obs_h, obs_m = sum(hits) / n, sum(rrs) / n
    exp_h, exp_m = sum(ch_h) / n, sum(ch_m) / n
    lo, hi = clopper_pearson(sum(hits), n)

    print("\n" + "=" * 74)
    print(f"{'metric':<26}{'observed':>10}{'chance':>10}{'lift':>8}")
    print("-" * 74)
    print(f"{'hit@1':<26}{obs_h:>10.2f}{exp_h:>10.3f}{obs_h / exp_h:>7.1f}x")
    print(f"{'MRR':<26}{obs_m:>10.3f}{exp_m:>10.3f}{obs_m / exp_m:>7.1f}x")
    for k in (1, 3, 5, 8):
        p = statistics.mean(per_k[k]["p"])
        r = statistics.mean(per_k[k]["r"])
        cp = statistics.mean(chance_precision_at_k(ns, len(gt), k)
                             for _, _, gt, ns in resolved)
        print(f"{f'precision@{k} / recall@{k}':<26}{p:>6.2f} /{r:>5.2f}{cp:>8.3f}{p / cp:>7.1f}x")
    print("-" * 74)
    print(f"hit@1 exact 95% CI (Clopper-Pearson, {sum(hits)}/{n}): [{lo:.3f}, {hi:.3f}]")
    print(f"payload tokens at top_k=5: mean {statistics.mean(payloads):,.0f}, "
          f"median {statistics.median(payloads):,.0f}, max {max(payloads):,}")
    print("\nLimitations: n=10 author-labelled queries; lexical mode; chars/4 token estimate.")


def run_scale():
    src = Path(os.environ["SKATE_ROOT"])
    queries = [q for q, s, _ in QUERIES if s == S1][:5]
    print(f"{'copies':>7}{'notes':>7}{'vault tok':>12}{'payload tok (mean)':>20}{'avoided':>9}")
    print("-" * 58)
    for copies in (1, 2, 4, 8, 16, 32):
        dest = Path(tempfile.mkdtemp())
        try:
            (dest / "conversations").mkdir()
            (dest / "sessions").mkdir()
            for i in range(copies):
                for sess_dir in sorted((src / "conversations").iterdir()):
                    if not sess_dir.is_dir():
                        continue
                    new = f"{sess_dir.name}-r{i:02d}"
                    out = dest / "conversations" / new
                    out.mkdir()
                    for md in sorted(sess_dir.glob("*.md")):
                        out.joinpath(md.name).write_text(
                            md.read_text(encoding="utf-8").replace(sess_dir.name, new),
                            encoding="utf-8")
            import importlib
            os.environ["SKATE_ROOT"] = str(dest)
            import skate_lib
            importlib.reload(skate_lib)
            importlib.reload(service)
            governed, _ = service._active_entries()
            raw = "".join(e.path.read_text(encoding="utf-8") for e in governed)
            key = sorted({e.session_key for e in governed})[0]
            toks = [tok(json.dumps(service.search_memory(query=q, session=key, top_k=5),
                                   ensure_ascii=False)) for q in queries]
            mean_t = statistics.mean(toks)
            print(f"{copies * 2:>7}{len(governed):>7}{tok(raw):>12,}{mean_t:>20,.0f}"
                  f"{100 * (1 - mean_t / tok(raw)):>8.1f}%")
        finally:
            shutil.rmtree(dest, ignore_errors=True)
    print("\nNote: replicas bound PAYLOAD only; ranking quality at scale is untested.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", action="store_true",
                        help="run the payload-vs-vault-size sweep instead")
    args = parser.parse_args()
    (run_scale if args.scale else run_benchmark)()
