"""Acceptance benchmark test — evaluates rules-first engine against annotated samples.

Checks:
  - false_pass rate < 5%
  - deterministic rules work without LLM
  - benchmark.json annotations match check_evidence output
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import acceptance

BENCH_PATH = os.path.join(os.path.dirname(__file__), "data", "acceptance_bench.json")


def load_bench():
    with open(BENCH_PATH, encoding="utf-8") as f:
        return json.load(f)


def _param_ids():
    return [b["id"] + ": " + b["desc"][:40] for b in load_bench()]


@pytest.mark.parametrize("sample", load_bench(), ids=_param_ids())
def test_bench_sample(sample):
    """Run a single benchmark sample through check_evidence."""
    verdict = acceptance.check_evidence(sample["task"], sample["details"])

    assert verdict.pass_ == sample["expected_pass"], (
        f"Expected pass={sample['expected_pass']}, got pass={verdict.pass_}. "
        f"Reason: {verdict.reason}"
    )
    assert verdict.needs_llm == sample["should_need_llm"], (
        f"Expected needs_llm={sample['should_need_llm']}, "
        f"got needs_llm={verdict.needs_llm}"
    )


def test_bench_false_pass_rate():
    """Safety check: false_pass rate must be < 5%."""
    samples = load_bench()
    false_pass = 0
    false_fail = 0
    total = len(samples)

    for sample in samples:
        verdict = acceptance.check_evidence(sample["task"], sample["details"])
        if verdict.pass_ and not sample["expected_pass"]:
            false_pass += 1
        if not verdict.pass_ and sample["expected_pass"]:
            false_fail += 1

    fp_rate = false_pass / total * 100 if total else 0
    ff_rate = false_fail / total * 100 if total else 0

    print(f"\nBenchmark: {total} samples, {false_pass} false_pass ({fp_rate:.1f}%), {false_fail} false_fail ({ff_rate:.1f}%)")

    assert fp_rate < 5.0, f"false_pass rate {fp_rate:.1f}% exceeds 5% threshold"
    # false_fail is less critical — just report it
    if ff_rate > 20:
        print(f"WARNING: false_fail rate {ff_rate:.1f}% is above 20%")
