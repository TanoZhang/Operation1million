from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from .local_config import load_credentials

try:
    from scripts.build_company_seed_csv import normalize_company_name
except ModuleNotFoundError:
    try:
        from build_company_seed_csv import normalize_company_name
    except ModuleNotFoundError:
        # Standalone fallback so this file runs without the seed-builder module.
        def normalize_company_name(name: str) -> str:
            return re.sub(r"\s+", " ", (name or "").replace("﻿", "").strip())


DEFAULT_MODEL = "gpt-5.4"
RESPONSES_API_URL = "https://api.openai.com/v1/responses"

# Bump when the system prompt, schema, or any semantics change. resume-existing
# only reuses rows whose prompt_version matches the selected mode, so a schema
# change forces re-classification instead of silently inheriting stale rows.
BASE_PROMPT_VERSION = "v3-precision-step2"
ATS_STRICT_PROMPT_VERSION = "v4-ats-sql-target"

TARGET_CATEGORIES = [
    # --- original 15 ---
    "VLSI",
    "ASIC",
    "SoC",
    "semiconductor design",
    "EDA",
    "semiconductor IP",
    "RTL",
    "design verification",
    "FPGA",
    "analog or digital design",
    "firmware",
    "embedded systems",
    "computer/server/datacenter/networking hardware",
    "EV or automotive electronics",
    "hardware validation or electronics test",
    # --- added: user-requested ---
    "AI accelerator or ML hardware",
    "CPU or GPU architecture or HPC",
    # --- added: VLSI-adjacent hiring buckets ---
    "physical design or place and route",
    "design for test (DFT)",
    "static timing analysis or timing closure",
    "post-silicon validation or silicon bring-up",
    "SerDes or high-speed I/O",
    "memory design (DRAM/SRAM/NAND/flash controller)",
    "power management IC or PMIC",
    "RF or mmWave or wireless baseband chipset",
    "semiconductor foundry or manufacturing process",
]

OUTPUT_FIELDS = [
    "company_name",              # raw input string as it appeared in the seed CSV
    "input_entity_type",         # company | product_line | merged_or_renamed | defunct | not_a_company | unclear
    "canonical_company_name",    # brand/parent/successor (Xilinx -> AMD; Dell XPS -> Dell Technologies)
    "na_entity_name",            # NA hiring subsidiary (Renesas -> Renesas Electronics America); empty when canonical is already US/CA-HQ
    "step1_active",              # canonical resolution IS an active hireable entity
    "step2_north_america",       # canonical entity has NA presence / hiring
    "step3_relevant",            # canonical entity does target EE work
    "step4_ats_sql_fit",         # strict mode: medium/large, likely real careers/ATS volume, not low-signal
    "gpt_decision",              # yes only when all three steps are yes
    "categories",
    "confidence",
    "rationale",
    "prompt_version",            # PROMPT_VERSION at classification time -- see apply_existing_results
    "model",
    "checked_at",
]

REDIRECTED_OUTPUT_PATHS: dict[Path, Path] = {}


def read_company_names(input_path: Path) -> list[str]:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "company_name" not in reader.fieldnames:
            raise ValueError(f"{input_path} must contain a company_name column")
        names = [normalize_company_name(row["company_name"]) for row in reader if row.get("company_name")]
    return sorted({name for name in names if name}, key=str.casefold)


def read_company_names_many(input_paths: Sequence[Path]) -> list[str]:
    names: list[str] = []
    for input_path in input_paths:
        names.extend(read_company_names(input_path))
    return sorted({name for name in names if name}, key=str.casefold)


def prompt_version(ats_strict: bool) -> str:
    return ATS_STRICT_PROMPT_VERSION if ats_strict else BASE_PROMPT_VERSION


def build_prefilter_rows(company_names: Sequence[str]) -> list[dict[str, str]]:
    """Every non-empty input is a candidate. All judgment (active vs product-
    line vs defunct, NA, relevance) is deferred to the LLM. No hardcoded
    allow/deny lists or regex rules -- those turn into an ever-growing
    maintenance disaster the moment new brands or product lines show up."""
    rows: list[dict[str, str]] = []
    checked_at = utc_now()
    for name in company_names:
        rows.append(
            {
                "company_name": normalize_company_name(name),
                "input_entity_type": "",
                "canonical_company_name": "",
                "na_entity_name": "",
                "step1_active": "",
                "step2_north_america": "",
                "step3_relevant": "",
                "step4_ats_sql_fit": "",
                "gpt_decision": "not_run",
                "categories": "",
                "confidence": "",
                "rationale": "",
                "prompt_version": "",
                "model": "",
                "checked_at": checked_at,
            }
        )
    return rows


def apply_existing_results(
    rows: list[dict[str, str]],
    existing_output: Path,
    *,
    current_prompt_version: str,
    ats_strict: bool,
) -> list[dict[str, str]]:
    """Resume mode: reuse yes/no rows from a previous run so we don't re-spend
    API $$ on names already decided.

    A prior row is only inherited when ALL of these hold:
      * its prompt_version matches the current selected mode -- otherwise the
        prompt/schema drifted and the old decision no longer matches what a
        fresh run would produce;
      * gpt_decision is 'yes' or 'no' -- 'not_run' or blank must be re-tried;
      * the three step fields are all populated -- otherwise we would inherit
        a half-written row from a crashed run.
    Anything failing these checks is re-classified this run."""
    if not existing_output.exists():
        return rows
    existing_by_name: dict[str, dict[str, str]] = {}
    stale_count = 0
    incomplete_count = 0
    with existing_output.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "company_name" not in reader.fieldnames:
            return rows
        for row in reader:
            name = normalize_company_name(row.get("company_name", ""))
            if not name:
                continue
            existing_by_name[name] = {field: row.get(field, "") for field in OUTPUT_FIELDS}

    merged_rows: list[dict[str, str]] = []
    reused = 0
    for row in rows:
        existing = existing_by_name.get(row["company_name"])
        if not existing:
            merged_rows.append(row)
            continue
        if existing.get("gpt_decision") not in {"yes", "no"}:
            merged_rows.append(row)
            continue
        if existing.get("prompt_version") != current_prompt_version:
            stale_count += 1
            merged_rows.append(row)
            continue
        # Step fields must be populated. A crashed writer can leave these
        # blank while gpt_decision is already 'no' (the default), which would
        # look reusable but is not a real result.
        if not (existing.get("step1_active")
                and existing.get("step2_north_america")
                and existing.get("step3_relevant")):
            incomplete_count += 1
            merged_rows.append(row)
            continue
        if ats_strict and not existing.get("step4_ats_sql_fit"):
            incomplete_count += 1
            merged_rows.append(row)
            continue
        merged = dict(row)
        merged.update(existing)
        merged["company_name"] = row["company_name"]
        merged_rows.append(merged)
        reused += 1
    print(
        f"RESUME reused={reused} stale_prompt_version={stale_count} "
        f"incomplete_rows={incomplete_count} (all re-classified this run)",
        file=sys.stderr,
    )
    return merged_rows


def run_openai_filter(
    rows: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    ats_strict: bool,
    current_prompt_version: str,
    batch_size: int,
    limit: int | None,
    sleep_seconds: float,
    api_timeout: float,
    max_retries: int,
    checkpoint_output: Path | None,
    kept_output: Path | None,
) -> list[dict[str, str]]:
    candidates = [row for row in rows if row["gpt_decision"] in {"", "not_run"}]
    if limit is not None:
        candidates = candidates[:limit]

    processed = 0
    for batch in chunks(candidates, batch_size):
        # Join by a stable integer id, never by the model's echoed name. This is
        # what makes silent drops impossible: a missing/renamed item shows up as
        # a missing id, which we detect and retry, instead of vanishing.
        id_to_row = {index: row for index, row in enumerate(batch)}
        companies = [{"id": index, "name": row["company_name"]} for index, row in id_to_row.items()]

        results = classify_batch_with_retries(
            companies, api_key=api_key, model=model,
            ats_strict=ats_strict,
            api_timeout=api_timeout, max_retries=max_retries,
        )
        by_id = _index_results(results, id_to_row)

        missing_ids = [i for i in id_to_row if i not in by_id]
        if missing_ids:
            retry_companies = [{"id": i, "name": id_to_row[i]["company_name"]} for i in missing_ids]
            try:
                retry_results = classify_batch_with_retries(
                    retry_companies, api_key=api_key, model=model,
                    ats_strict=ats_strict,
                    api_timeout=api_timeout, max_retries=max_retries,
                )
                by_id.update(_index_results(retry_results, id_to_row))
            except OSError:
                pass

        checked_at = utc_now()
        for index, row in id_to_row.items():
            item = by_id.get(index)
            if item is None:
                # Explicit, visible, and re-runnable -- not a silent delete.
                row.update(
                    {
                        "gpt_decision": "not_run",
                        "input_entity_type": "",
                        "canonical_company_name": "",
                        "na_entity_name": "",
                        "step1_active": "",
                        "step2_north_america": "",
                        "step3_relevant": "",
                        "step4_ats_sql_fit": "",
                        "categories": "",
                        "confidence": "",
                        "rationale": "model omitted row; retry pending",
                        "prompt_version": "",
                        "model": "",
                        "checked_at": checked_at,
                    }
                )
                continue

            categories = item.get("categories") or []
            canonical = str(item.get("canonical_company_name") or "").strip()
            na_entity = str(item.get("na_entity_name") or "").strip()
            input_type = str(item.get("input_entity_type") or "").strip()
            s1 = clean_choice(item.get("step1_active"), {"yes", "no"})
            s2 = clean_choice(item.get("step2_north_america"), {"yes", "no"})
            s3 = clean_choice(item.get("step3_relevant"), {"yes", "no"})
            s4 = clean_choice(item.get("step4_ats_sql_fit"), {"yes", "no"})
            # Hard rule enforced in code, not just the prompt: keep only when
            # required steps are yes. The model cannot short-circuit or
            # override this by fluffing rationale.
            decision = "yes" if (
                s1 == "yes"
                and s2 == "yes"
                and s3 == "yes"
                and (not ats_strict or s4 == "yes")
            ) else "no"
            row.update(
                {
                    "input_entity_type": input_type,
                    # If the model returned nothing usable, fall back to the
                    # input so this row stays diagnosable (never blank a key).
                    "canonical_company_name": canonical or row["company_name"],
                    "na_entity_name": na_entity,
                    "step1_active": s1,
                    "step2_north_america": s2,
                    "step3_relevant": s3,
                    "step4_ats_sql_fit": s4,
                    "gpt_decision": decision,
                    "categories": ";".join(str(category) for category in categories),
                    "confidence": str(item.get("confidence", "")),
                    "rationale": str(item.get("rationale", ""))[:240],
                    "prompt_version": current_prompt_version,
                    "model": model,
                    "checked_at": checked_at,
                }
            )
        processed += len(batch)
        omitted = sum(1 for r in id_to_row.values() if r["gpt_decision"] == "not_run")
        print(f"GPT_FILTER processed={processed} omitted_this_batch={omitted} model={model}", file=sys.stderr)
        if checkpoint_output is not None:
            write_rows(rows, checkpoint_output)
        if kept_output is not None:
            write_kept_company_names(rows, kept_output)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return rows


def _index_results(results: Sequence[dict[str, Any]], id_to_row: dict[int, dict[str, str]]) -> dict[int, dict[str, Any]]:
    """Map model results back to rows by their integer id, ignoring anything
    with a missing/out-of-range/duplicate id."""
    by_id: dict[int, dict[str, Any]] = {}
    for item in results:
        raw = item.get("id")
        try:
            iid = int(raw)
        except (TypeError, ValueError):
            continue
        if iid in id_to_row and iid not in by_id:
            by_id[iid] = item
    return by_id


def classify_batch_with_retries(
    companies: Sequence[dict[str, Any]],
    *,
    api_key: str,
    model: str,
    ats_strict: bool,
    api_timeout: float,
    max_retries: int,
) -> list[dict[str, Any]]:
    for attempt in range(max_retries + 1):
        try:
            return classify_batch_with_openai(
                companies,
                api_key=api_key,
                model=model,
                ats_strict=ats_strict,
                api_timeout=api_timeout,
            )
        except OSError:
            if attempt >= max_retries:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable retry state")


def classify_batch_with_openai(
    companies: Sequence[dict[str, Any]],
    *,
    api_key: str,
    model: str,
    ats_strict: bool,
    api_timeout: float,
) -> list[dict[str, Any]]:
    strict_gate_text = (
        "STEP 4 -- step4_ats_sql_fit: yes ONLY if the canonical company is a "
        "good seed for an ATS SQL table: a medium/large employer (roughly 200+ "
        "employees, public company, well-known large private company, or clearly "
        "substantial North-America hiring presence), likely to have a real "
        "careers site / ATS / many jobs, and directly useful for VLSI, ASIC, "
        "SoC, semiconductor design, EDA/IP, RTL/DV, FPGA, analog/digital design, "
        "firmware, embedded systems, networking/datacenter hardware, EV or "
        "automotive electronics, or hardware validation/test.\n"
        "Say NO for aviation, aerospace, defense/military contractors, finance, "
        "insurance, asset management, banking, sales-only distributors/reps, "
        "staffing/recruiting/consulting, tiny private companies, local service "
        "shops, companies with no obvious careers/ATS footprint, and companies "
        "whose relevance is only weak/adjacent. For department/location/product "
        "strings, first resolve to the parent, then judge the parent; do not "
        "keep a location as a separate company, but answer yes if the resolved "
        "parent itself passes this ATS SQL fit gate. Do not keep a company "
        "merely because it is public/SEC-listed; SEC is only a size signal, not "
        "a relevance signal. If you are unsure on size or ATS usefulness, answer "
        "no.\n\n"
    )
    base_gate_text = (
        "STEP 4 -- step4_ats_sql_fit: return yes in normal mode. This field is "
        "reserved for the stricter ATS SQL target mode and does not affect the "
        "normal broad EE company filter.\n\n"
    )
    step4_text = strict_gate_text if ats_strict else base_gate_text
    step4_bias_text = (
        "  * step 4 -> err toward NO. This is a PRECISION gate for building an "
        "ATS SQL table, not a broad company encyclopedia. Drop weakly related, "
        "small, sales-only, aviation/aerospace/defense, finance, and no-obvious-"
        "ATS employers.\n"
        if ats_strict
        else "  * step 4 -> answer YES in normal mode.\n"
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You classify company-name strings for a North-America EE/VLSI "
                    "job-search database. The user is building a SQL job-board and "
                    "needs a list of companies they can realistically apply to. "
                    "Each input has an integer id and a name. Return EXACTLY ONE "
                    "result per input id, echoing that id.\n\n"

                    "IMPORTANT: The gates below are evaluated on the CANONICAL "
                    "COMPANY you resolve the input to -- not on the raw input "
                    "string. Resolution comes FIRST; gates come second.\n\n"

                    "========== PHASE A: RESOLUTION ==========\n\n"

                    "A.1 -- input_entity_type: pick exactly one:\n"
                    "  * company           : input names a company as-is\n"
                    "  * product_line      : input names a product / model / "
                    "sub-brand / individual factory owned by a parent company "
                    "(e.g. 'Dell XPS', 'Lenovo Yoga', 'Acer Nitro', "
                    "'Compaq Presario', 'MSI Wind Netbook', 'Gigafactory Nevada')\n"
                    "  * merged_or_renamed : input names a former company that "
                    "was acquired, merged, renamed, or spun in, and whose "
                    "engineering org now lives inside a current parent "
                    "(e.g. 'Xilinx' -> AMD; 'Altera' -> Intel then Altera Corp; "
                    "'Mentor Graphics' -> Siemens EDA; 'Freescale' -> NXP)\n"
                    "  * defunct           : dissolved, bankrupt, liquidated, "
                    "no surviving successor (e.g. 'Cyrix', 'Transmeta', 'DEC' "
                    "if you cannot identify a still-hiring successor)\n"
                    "  * not_a_company     : article title, concept, technical "
                    "term, verb, event, list (e.g. 'High Bandwidth Memory', "
                    "'Connected car', 'Debugging', 'AI-driven design automation')\n"
                    "  * unclear           : you cannot tell\n\n"

                    "A.2 -- canonical_company_name: the CURRENT legal/brand name "
                    "the input resolves to. This is what will be stored as the "
                    "'company' primary key.\n"
                    "  * company            -> its current legal name "
                    "(e.g. 'Nvidia' -> 'NVIDIA Corporation')\n"
                    "  * product_line       -> the current parent "
                    "(e.g. 'Dell XPS' -> 'Dell Technologies Inc.'; "
                    "'MSI Wind Netbook' -> 'Micro-Star International Co., Ltd.')\n"
                    "  * merged_or_renamed  -> the current surviving parent/"
                    "successor (e.g. 'Xilinx' -> 'Advanced Micro Devices, Inc.'; "
                    "'Altera' -> 'Altera Corporation' (now an Intel subsidiary "
                    "again); 'Mentor Graphics' -> 'Siemens AG')\n"
                    "  * defunct            -> the last legal name of the "
                    "defunct entity (audit trail only)\n"
                    "  * not_a_company / unclear -> empty string\n\n"

                    "A.3 -- na_entity_name: the North-America LEGAL SUBSIDIARY "
                    "that actually hires, and ONLY when the canonical company's "
                    "HQ is outside the US/Canada. Prefer the umbrella NA entity "
                    "over a specific city/site.\n"
                    "  Examples:\n"
                    "    Samsung / Samsung Austin -> 'Samsung Semiconductor Inc.'\n"
                    "    Renesas                  -> 'Renesas Electronics America, Inc.'\n"
                    "    Bosch                    -> 'Robert Bosch LLC'\n"
                    "    Infineon                 -> 'Infineon Technologies Americas Corp.'\n"
                    "    ASML                     -> 'ASML US, LLC'\n"
                    "  Only fall back to a specific site when there is NO "
                    "umbrella NA subsidiary (e.g. 'TSMC' -> 'TSMC Arizona').\n"
                    "  Leave this field EMPTY STRING when the canonical company "
                    "is already headquartered in the US or Canada, or when the "
                    "input is not_a_company / defunct / unclear.\n\n"

                    "========== PHASE B: GATES ==========\n\n"

                    "All three gates below are evaluated on canonical_company_name "
                    "(the resolved entity), not on the raw input.\n\n"

                    "STEP 1 -- step1_active: yes if canonical_company_name refers "
                    "to a currently operating entity that a job-seeker could "
                    "apply to. Consequences of Phase A:\n"
                    "  * input_entity_type == 'company'           -> yes if that "
                    "company is currently operating\n"
                    "  * input_entity_type == 'product_line'      -> yes if the "
                    "parent is currently operating (product lines with live "
                    "parents ARE keepable -- they get canonicalized upward, "
                    "they do NOT get dropped)\n"
                    "  * input_entity_type == 'merged_or_renamed' -> yes if the "
                    "successor is currently operating (Xilinx -> AMD => yes)\n"
                    "  * input_entity_type == 'defunct'           -> no\n"
                    "  * input_entity_type == 'not_a_company'     -> no\n"
                    "  * input_entity_type == 'unclear'           -> no\n\n"

                    "STEP 2 -- step2_north_america: yes if the canonical company "
                    "has meaningful US/Canada presence a job-seeker could apply to "
                    "(US/Canada HQ, US/Canada subsidiary or design center, or a "
                    "publicly known US/Canada office that hires). Foreign HQ alone "
                    "is NOT a reason to say no -- what matters is whether they hire "
                    "in NA. Say NO for companies with no known NA operations (e.g. "
                    "small European GmbH/AG with only European offices, small "
                    "Chinese/Japanese firms with domestic-only presence).\n\n"

                    "STEP 3 -- step3_relevant: yes if the canonical company's "
                    "business includes at least one of the target categories in "
                    "the user message. Populate `categories` with the ones that "
                    "apply. Say NO for pure software/SaaS/cloud, finance, "
                    "consulting, retail, hospitality, food, staffing, marketing, "
                    "logistics, general utilities, generic energy, or optics/"
                    "photonics/laser-only businesses.\n\n"
                    + step4_text +

                    "Return step1_active / step2_north_america / step3_relevant "
                    "/ step4_ats_sql_fit as 'yes' or 'no'. Do NOT return "
                    "'unknown'. Bias rules when "
                    "you are genuinely unsure:\n"
                    "  * step 1 -> err toward NO for anything that clearly looks "
                    "like a concept, verb, or article title (pure noise for a "
                    "job-board).\n"
                    "  * step 2 -> err toward NO. This is a PRECISION gate. If "
                    "you have no specific knowledge of a US or Canada office, "
                    "subsidiary, design center, or NA hiring presence, answer "
                    "no. A 'they probably have a distributor / rep / maybe an "
                    "office somewhere' guess is NOT enough -- that guess is the "
                    "leak that lets small foreign firms (e.g. random European "
                    "GmbHs, Hangzhou / Shenzhen firms with domestic-only sales) "
                    "contaminate the kept list. Only answer yes when you can "
                    "point to a concrete NA presence.\n"
                    "  * step 3 -> err toward YES. This is a RECALL gate. If a "
                    "company is plausibly in an EE / hardware / chips / test / "
                    "automotive-electronics area, keep it; missing a real "
                    "employer costs more than adding a marginal one.\n\n"
                    + step4_bias_text +

                    "confidence is your overall 0-1 confidence in the final "
                    "decision; rationale is one short sentence explaining the "
                    "combined judgment, mentioning what the input resolved to."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_categories": TARGET_CATEGORIES,
                        "companies": list(companies),
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "company_relevance_batch",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "integer"},
                                    "input_entity_type": {
                                        "type": "string",
                                        "enum": [
                                            "company",
                                            "product_line",
                                            "merged_or_renamed",
                                            "defunct",
                                            "not_a_company",
                                            "unclear",
                                        ],
                                    },
                                    "canonical_company_name": {"type": "string"},
                                    "na_entity_name": {"type": "string"},
                                    "step1_active": {"type": "string", "enum": ["yes", "no"]},
                                    "step2_north_america": {"type": "string", "enum": ["yes", "no"]},
                                    "step3_relevant": {"type": "string", "enum": ["yes", "no"]},
                                    "step4_ats_sql_fit": {"type": "string", "enum": ["yes", "no"]},
                                    "categories": {
                                        "type": "array",
                                        "items": {"type": "string", "enum": TARGET_CATEGORIES},
                                    },
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                    "rationale": {"type": "string"},
                                },
                                "required": [
                                    "id",
                                    "input_entity_type",
                                    "canonical_company_name",
                                    "na_entity_name",
                                    "step1_active",
                                    "step2_north_america",
                                    "step3_relevant",
                                    "step4_ats_sql_fit",
                                    "categories",
                                    "confidence",
                                    "rationale",
                                ],
                            },
                        }
                    },
                    "required": ["results"],
                },
            }
        },
    }
    request = urllib.request.Request(
        RESPONSES_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=api_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc
    parsed = json.loads(extract_response_text(data))
    return list(parsed["results"])


def extract_response_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    text_parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and "text" in content:
                text_parts.append(str(content["text"]))
    if not text_parts:
        raise ValueError("OpenAI response did not contain output text")
    return "".join(text_parts)


def write_rows(rows: Sequence[dict[str, str]], output_path: Path) -> None:
    actual_output_path = effective_output_path(output_path)
    actual_output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = actual_output_path.with_name(f"{actual_output_path.name}.tmp")
    with temp_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["company_name"].casefold()):
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})
    replace_with_retry(temp_path, output_path, actual_output_path)


def write_kept_company_names(rows: Sequence[dict[str, str]], output_path: Path) -> None:
    """Kept, de-duplicated, single column -- the actual 'apply-here' name that
    goes into the job-board.

    Name-preference order:
      1. na_entity_name        (foreign-HQ with US sub, e.g. 'Renesas Electronics America')
      2. canonical_company_name (US-HQ or after canonicalization, e.g. 'Dell Technologies Inc.')
      3. company_name           (raw input, last resort)
    So 'Dell XPS' + 'Dell Inc' + 'Dell Technologies' all collapse to one row,
    and 'Xilinx' + 'AMD' collapse to 'Advanced Micro Devices, Inc.'."""
    actual_output_path = effective_output_path(output_path)
    actual_output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = actual_output_path.with_name(f"{actual_output_path.name}.tmp")
    seen: set[str] = set()
    names: list[str] = []
    for row in rows:
        if row.get("gpt_decision") != "yes":
            continue
        name = (row.get("na_entity_name") or "").strip()
        if not name:
            name = (row.get("canonical_company_name") or "").strip()
        if not name:
            name = row["company_name"]
        name = normalize_company_name(name)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    names.sort(key=str.casefold)
    with temp_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company_name"])
        writer.writeheader()
        for name in names:
            writer.writerow({"company_name": name})
    replace_with_retry(temp_path, output_path, actual_output_path)


def effective_output_path(output_path: Path) -> Path:
    return REDIRECTED_OUTPUT_PATHS.get(absolute_path(output_path), output_path)


def absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def replace_with_retry(
    temp_path: Path,
    original_output_path: Path,
    actual_output_path: Path,
    attempts: int = 5,
) -> None:
    """Replace checkpoint files robustly on Windows.

    Antivirus, indexers, and file-preview tools can briefly hold a CSV handle even
    when the user did not open the file. If the requested output stays locked,
    redirect the rest of this run to a stable .active.csv file instead of losing
    progress or crashing a long GPT run after a successful batch.
    """
    delay_seconds = 0.25
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            temp_path.replace(actual_output_path)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32}:
                raise
            last_error = exc

        if attempt < attempts:
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 3.0)

    redirected_path = write_to_redirected_output(temp_path, original_output_path)
    print(
        f"WARNING output locked: {actual_output_path}. "
        f"Continuing this run at {redirected_path}. "
        f"Use that path with --output/--kept-output if you resume later.",
        file=sys.stderr,
    )


def write_to_redirected_output(temp_path: Path, original_output_path: Path) -> Path:
    original = absolute_path(original_output_path)
    for redirect_path in redirected_output_candidates(original):
        try:
            redirect_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(redirect_path)
            REDIRECTED_OUTPUT_PATHS[original] = redirect_path
            return redirect_path
        except PermissionError:
            continue
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32}:
                raise
            continue
    raise RuntimeError(
        f"Could not replace {original_output_path} and could not write a redirected CSV. "
        "Pick a fresh --output path and rerun with --resume-existing."
    )


def redirected_output_candidates(original: Path) -> Iterable[Path]:
    yield original.with_name(f"{original.stem}.active{original.suffix}")
    for index in range(2, 21):
        yield original.with_name(f"{original.stem}.active-{index}{original.suffix}")


def current_output_display(path: Path | None) -> str:
    if path is None:
        return ""
    return str(effective_output_path(path))


def clean_choice(value: object, allowed: set[str]) -> str:
    text = str(value or "no").casefold()
    return text if text in allowed else "no"


def chunks(items: Sequence[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(items), size):
        yield list(items[index : index + size])


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter company names for likely North America EE/hardware relevance."
    )
    parser.add_argument("--input", required=True, type=Path, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--kept-output",
        type=Path,
        help="Write final kept company_name-only CSV. Only GPT yes rows are kept.",
    )
    parser.add_argument("--use-openai", action="store_true")
    parser.add_argument(
        "--ats-strict",
        action="store_true",
        help="Use a narrower ATS SQL target filter: medium/large, clear NA hiring/ATS footprint, no weak-adjacent industries.",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Reuse yes/no rows from an existing output CSV. Rows still 'not_run' get re-tried.",
    )
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=positive_int, default=40)
    parser.add_argument("--limit", type=positive_int)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--api-timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser


def _refuse_input_overwrite(input_paths: Sequence[Path], *output_paths: Path | None) -> None:
    """Refuse to write to the same file we read the seed from. Compares by
    resolved absolute path so relative vs absolute and '.', '..' can't sneak
    a collision past us. strict=False so we do not require the output to
    already exist -- only the input must exist and it does, since
    read_company_names just opened it."""
    seeds = {input_path.resolve(strict=True) for input_path in input_paths}
    for out in output_paths:
        if out is None:
            continue
        try:
            candidate = out.resolve(strict=False)
        except OSError:
            candidate = Path(os.path.abspath(str(out)))
        if candidate in seeds:
            raise ValueError(
                f"refusing to write to {out!s}: it resolves to the same file as "
                "--input. Pick a different output path so the "
                f"seed CSV is not clobbered."
            )


def main(argv: Sequence[str] | None = None) -> int:
    load_credentials()
    args = build_parser().parse_args(argv)
    try:
        current_prompt_version = prompt_version(args.ats_strict)
        _refuse_input_overwrite(args.input, args.output, args.kept_output)
        names = read_company_names_many(args.input)
        rows = build_prefilter_rows(names)
        if args.resume_existing:
            rows = apply_existing_results(
                rows,
                args.output,
                current_prompt_version=current_prompt_version,
                ats_strict=args.ats_strict,
            )
        if args.use_openai:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print("ERROR OPENAI_API_KEY is not set", file=sys.stderr)
                return 2
            rows = run_openai_filter(
                rows,
                api_key=api_key,
                model=args.model,
                ats_strict=args.ats_strict,
                current_prompt_version=current_prompt_version,
                batch_size=args.batch_size,
                limit=args.limit,
                sleep_seconds=args.sleep_seconds,
                api_timeout=args.api_timeout,
                max_retries=args.max_retries,
                checkpoint_output=args.output,
                kept_output=args.kept_output,
            )
        write_rows(rows, args.output)
        if args.kept_output:
            write_kept_company_names(rows, args.kept_output)
        kept_count = sum(1 for row in rows if row["gpt_decision"] == "yes")
        not_run_count = sum(1 for row in rows if row["gpt_decision"] == "not_run")
        # Step-level counts help you audit WHERE things got dropped:
        # too many step1=no -> lots of product-line noise in the input;
        # step2=no dominant -> a lot of foreign-only firms;
        # step3=no dominant -> your input list has non-EE companies.
        s1_no = sum(1 for row in rows if row.get("step1_active") == "no")
        s2_no = sum(1 for row in rows if row.get("step2_north_america") == "no")
        s3_no = sum(1 for row in rows if row.get("step3_relevant") == "no")
        s4_no = sum(1 for row in rows if row.get("step4_ats_sql_fit") == "no")
        print(
            f"WROTE rows={len(rows)} kept={kept_count} not_run={not_run_count} "
            f"step1_no={s1_no} step2_no={s2_no} step3_no={s3_no} "
            f"step4_no={s4_no} prompt_version={current_prompt_version} "
            f"csv={current_output_display(args.output)}"
        )
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
