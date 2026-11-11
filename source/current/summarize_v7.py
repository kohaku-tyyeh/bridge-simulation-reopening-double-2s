#!/usr/bin/env python3
"""Rebuild machine-readable summaries from merged saved results.

This script never generates deals or calls DDS/Par.  The three policy scenarios
are paired on the same boards; the retained preview and final sample overlap.
"""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from math import isclose
from pathlib import Path
import platform

from analyze_dk_contracts import component, stats as component_stats
from dds_backend import pbn
from run_experiment import statistics, imps
from run_dk_no_double_policy import bootstrap, mask_for, paired, stats


MODELS = ("baseline", "protect_32", "protect_32_41")
FILES = {"baseline": "results.jsonl", "protect_32": "no_double_policy/protect_32.jsonl",
         "protect_32_41": "no_double_policy/protect_32_41.jsonl"}
SX = dict(level=2, strain="S", declarer="E", doubled=1)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if rows:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def ordered(rows, n, name):
    by_id = {r["number"]: r for r in rows}
    if len(rows) != n or len(by_id) != n or set(by_id) != set(range(1, n + 1)):
        raise ValueError(f"{name}: expected unique consecutive board numbers 1..{n}")
    return [by_id[i] for i in range(1, n + 1)]


def verify_inputs(dataset, tables, models, n):
    deals = ordered(dataset["deals"], n, "deals")
    seen = set()
    for i, (deal, dd) in enumerate(zip(deals, tables)):
        text = pbn(deal)
        if text in seen or text != dd["pbn"]:
            raise ValueError(f"Duplicate/mismatched deal at board {i + 1}")
        seen.add(text)
        if deal["hands"]["S"]["suits"] != dict(S="3", H="9754", D="AKT8", C="A764"):
            raise ValueError("Expected original DK South hand")
        previous_score = None
        for model in MODELS:
            row = models[model][i]
            if row["pbn"] != text or row["handviewer_url"] != deal["handviewer_url"]:
                raise ValueError(f"{model}: identity mismatch at board {i + 1}")
            if row["east_2S_tricks"] != dd["dd_table_CDHSN_NESW"][3][1]:
                raise ValueError(f"{model}: East spade tricks mismatch")
            if row["pass_score_ns"] != models["baseline"][i]["pass_score_ns"]:
                raise ValueError("Policies must share the same Pass score")
            delta = row["double_par_score_ns"] - row["pass_score_ns"]
            if row["delta_ns"] != delta or row["delta_imp"] != imps(delta):
                raise ValueError(f"{model}: inconsistent score/IMP difference")
            if row["bam_points"] != (1 if delta > 0 else 0 if delta < 0 else .5):
                raise ValueError(f"{model}: inconsistent BAM score")
            if not row["optimal_contracts"]:
                raise ValueError("Empty co-optimal contract set")
            if previous_score is not None and row["double_par_score_ns"] < previous_score:
                raise ValueError("Protection policy worsened the NS Par score")
            previous_score = row["double_par_score_ns"]
            if model != "baseline":
                mask = mask_for(deal, model == "protect_32_41")
                if row["blocked_ns_level3_strains"] != mask:
                    raise ValueError(f"{model}: protection mask mismatch")
    return deals


def verify_supplement(run, retained, models, tables):
    """Compare immutable saved payloads by PBN; supplement numbering may differ."""
    supplement = run / "supplement"
    checked = {}
    for name, rel in {"dds": "dds.jsonl", **FILES}.items():
        path = supplement / rel
        if not path.exists():
            continue
        new_rows = read_rows(path)
        combined = tables[retained:] if name == "dds" else models[name][retained:]
        by_pbn = {r["pbn"]: r for r in combined}
        if len(new_rows) != len(combined) or len(by_pbn) != len(combined):
            raise ValueError(f"Supplement count mismatch: {path}")
        if {r["pbn"] for r in new_rows} != set(by_pbn):
            raise ValueError(f"Supplement PBN set mismatch: {path}")
        for row in new_rows:
            merged = by_pbn[row["pbn"]]
            for key, value in row.items():
                if key != "number" and merged.get(key) != value:
                    raise ValueError(f"Supplement payload changed: {name}/{row['number']}/{key}")
        checked[name] = len(new_rows)
    return checked


def component_rows(rows, tables, cohort, model):
    groups = defaultdict(list)
    for row, dd in zip(rows, tables):
        groups[component(row, dd["dd_table_CDHSN_NESW"])].append(row)
    result = [dict(cohort=cohort, model=model, component=key,
                   **component_stats(members, len(rows))) for key, members in sorted(groups.items())]
    if sum(r["n"] for r in result) != len(rows) or sum(r["sum_imp"] for r in result) != sum(r["delta_imp"] for r in rows):
        raise ValueError("Component partition mismatch")
    return result


def cohort_summary(rows):
    result = stats(rows)
    available = [r for r in rows if SX in r["optimal_contracts"]]
    unique = sum({(c["level"], c["strain"], c["declarer"], c["doubled"])
                  for c in r["optimal_contracts"]} == {(2, "S", "E", 1)} for r in available)
    result.update(two_sx_available=len(available), two_sx_unique=unique,
                  two_sx_cooptimal=len(available) - unique,
                  two_sx_frequency=len(available) / len(rows),
                  two_sx_sum_imp=sum(r["delta_imp"] for r in available),
                  two_sx_contribution=sum(r["delta_imp"] for r in available) / len(rows))
    return result


def policy_summary(run, deals, models, tables, bootstrap_count, bootstrap_seed, root):
    original = models["baseline"]
    n = len(original)
    summary = dict(
        dataset=str(run), n=n, fixed_south="S3 H9754 DAKT8 CA764",
        vulnerability="NS nonvulnerable; EW vulnerable",
        definitions={
            "protect_32": "Prohibit EW double of NS level-three suit contracts with exactly 8-card NS fit and EW 3-2 split.",
            "protect_32_41": "Additionally protect EW 4-1 splits; EW 5-0 remains unprotected.",
            "scope": "Both NS declarers, all four suit strains, throughout the continuation auction; other levels and NT unchanged.",
            "method": "Aggregate saved continuation-Par outcomes; retained outcomes reused and supplement outcomes solved separately.",
            "impact": "Mean of per-board IMP(Double Par minus Pass), not IMP conversion of the mean raw-score difference.",
        }, original=stats(original),
        scenarios={m: stats(models[m]) for m in MODELS[1:]},
        comparisons={m + "_minus_original": paired(original, models[m]) for m in MODELS[1:]},
        summary_stage_no_deals_or_dds_or_par_recomputed=True)
    summary["comparisons"]["protect_32_41_minus_protect_32"] = paired(models["protect_32"], models["protect_32_41"])
    summary["bootstrap"] = bootstrap([models[m] for m in MODELS], bootstrap_count, bootstrap_seed)
    summary["mask_counts"] = {}
    summary["suit_coverage"] = {}
    for model in MODELS[1:]:
        masks = [mask_for(d, model == "protect_32_41") for d in deals]
        summary["mask_counts"][model] = dict(Counter(masks))
        summary["suit_coverage"][model] = {s: sum(bool(mask & (1 << i)) for mask in masks)
                                           for i, s in enumerate("CDHS")}
    grouped = defaultdict(list)
    for i, row in enumerate(original):
        grouped[component(row, tables[i]["dd_table_CDHSN_NESW"])].append(i)
    contributions = []
    for category, indices in sorted(grouped.items()):
        values = {m: sum(models[m][i]["delta_imp"] for i in indices) / n for m in MODELS}
        contributions.append(dict(original_component=category, n=len(indices),
            original_mean_contribution=values["baseline"],
            protect_32_mean_contribution=values["protect_32"],
            protect_32_41_mean_contribution=values["protect_32_41"],
            protect_32_increase=values["protect_32"] - values["baseline"],
            protect_32_41_increase=values["protect_32_41"] - values["baseline"]))
    summary["contributions_by_original_component"] = contributions
    summary["source_code_sha256"] = {name: digest(root / name) for name in
        ("summarize_v7.py", "run_dk_no_double_policy.py", "continuation_par_policy.cpp", "continuation_par_policy.py")}
    return summary


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, nargs="?", default=root.parent)
    parser.add_argument("--retained-count", type=int, default=9128)
    parser.add_argument("--expected-count", type=int, default=10000)
    parser.add_argument("--bootstrap-count", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=2026111117)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    n, retained = args.expected_count, args.retained_count
    if not 0 < retained < n or args.bootstrap_count < 1:
        parser.error("Require 0 < retained-count < expected-count and positive bootstrap-count")
    input_names = ["deals.json", "dds.jsonl", *FILES.values()]
    hashes = {name: digest(run / name) for name in input_names}
    dataset = read_json(run / "deals.json")
    tables = ordered(read_rows(run / "dds.jsonl"), n, "DDS")
    models = {m: ordered(read_rows(run / path), n, m) for m, path in FILES.items()}
    deals = verify_inputs(dataset, tables, models, n)
    supplement_checks = verify_supplement(run, retained, models, tables)
    cohorts, components, comparison = {}, [], []
    for cohort, start, end in (("retained", 0, retained), ("supplement", retained, n), ("combined", 0, n)):
        cohorts[cohort] = {}
        for model in MODELS:
            rows = models[model][start:end]
            value = cohort_summary(rows)
            cohorts[cohort][model] = value
            comparison.append(dict(cohort=cohort, model=model, n=value["n"], mean_imp=value["mean_imp"],
                                   bam_mean_points=value["bam_mean_points"], sum_imp=value["sum_imp"],
                                   loss8=value["loss8"], loss10=value["loss10"], gain8=value["gain8"],
                                   two_sx_available=value["two_sx_available"], two_sx_unique=value["two_sx_unique"]))
            components.extend(component_rows(rows, tables[start:end], cohort, model))
    for model in MODELS:
        if cohorts["retained"][model]["sum_imp"] + cohorts["supplement"][model]["sum_imp"] != cohorts["combined"][model]["sum_imp"]:
            raise ValueError("Cohort IMP sums do not reconstruct the combined result")
    base = statistics(models["baseline"], args.bootstrap_count, args.bootstrap_seed)
    source_names = ("filter_deals.py", "nt_choice.py", "knr_suit.py", "rules.json", "dds_backend.py", "continuation_par.cpp",
                    "continuation_par.py", "run_experiment.py", "summarize_v7.py")
    base.update(seed=dataset.get("seed"), generated_deals=dataset.get("attempts"), rules=dataset["rules"],
                vulnerability="NS nonvulnerable, EW vulnerable", fixed_auction_before_action=dataset["auction"],
                double_branch_initial_state="South X, then West to act; all four seats unrestricted",
                python_version=platform.python_version(), sampling=dataset.get("sampling"),
                retained_outcomes=retained, supplementary_outcomes=n-retained,
                source_sha256={name: digest(root / name) for name in source_names})
    policy = policy_summary(run, deals, models, tables, args.bootstrap_count, args.bootstrap_seed + 1, root)
    for model in MODELS:
        s = base if model == "baseline" else policy["scenarios"][model]
        if not isclose(s["mean_imp"], cohorts["combined"][model]["mean_imp"], abs_tol=1e-12):
            raise ValueError("Summary mean mismatch")
    for name, expected in hashes.items():
        if digest(run / name) != expected:
            raise ValueError(f"Input changed during aggregation: {name}")
    write_json(run / "summary.json", base)
    policy["source_sha256"] = {name: digest(run / name) for name in ("deals.json", "results.jsonl", "dds.jsonl", "summary.json")}
    write_json(run / "no_double_policy" / "summary.json", policy)
    write_csv(run / "no_double_policy" / "contributions_by_original_component.csv", policy["contributions_by_original_component"])
    write_json(run / "analysis.json", dict(n=n, retained=retained, supplement=n-retained,
        attempts=dataset.get("attempts"), sampling=dataset.get("sampling"), cohorts=cohorts,
        components=components, input_sha256=hashes, supplement_payload_checks=supplement_checks,
        component_note="Mutually exclusive and exhaustive within each cohort/model; contributions use the cohort denominator.",
        inference_note="The retained preview is a subset of the final sample; these are not independent experiments.",
        no_solver_calls=True))
    write_csv(run / "components.csv", components)
    write_csv(run / "cohort_comparison.csv", comparison)
    print(json.dumps(dict(output=str(run / "summary.json"), n=n,
                         metrics={m: {k: cohorts["combined"][m][k] for k in ("mean_imp", "bam_mean_points", "loss8", "loss10")}
                                  for m in MODELS}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
