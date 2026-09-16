# Job Source Collection Results - 2026-09-15

Collected 33,113 records from 52 source companies. 41 companies returned jobs.

This is a historical snapshot from before Advantest, MaxLinear, and OMNIVISION
were removed from the active catalog. Its counts and company table are retained
as evidence and are not the current active-company count.

Direct status: {'complete': 37, 'fallback': 9, 'partial': 4, 'failed': 2}. JSearch requests: 0 (API key unavailable).

Results combine an all-source run with targeted reruns after extractor corrections. Input manifests and live terminal-page checks are retained in `runs/20260915T190602Z/manifest.json`.

Ten offline regression tests passed. JSONL/CSV record counts, required fields, per-company counts, URL uniqueness, and the absence of the five deleted companies were checked.

## Company Results

| Company | Jobs | Direct status | Failure reason / next step |
|---|---:|---|---|
| Achronix Semiconductor Corporation | 7 | complete | None |
| Advantest Corporation | 0 | fallback | ADP shell downloaded but exposed no job list without client-side app execution.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Akeana Inc. | 6 | complete | None |
| Altera Corporation | 234 | complete | None |
| Amazon.com, Inc. | 10000 | partial | Amazon search returned its 10,000-result ceiling; partition searches to establish full coverage; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Ambarella, Inc. | 38 | complete | None |
| Advanced Micro Devices, Inc. | 0 | fallback | iCIMS returned 405 Human Verification for search and sitemap paths.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Analog Devices, Inc. | 801 | complete | None |
| Apple Inc. | 4488 | complete | None |
| Arm, Inc. | 375 | complete | None |
| Astera Labs, Inc. | 168 | complete | None |
| Broadcom Inc. | 372 | complete | None |
| Cadence Design Systems, Inc. | 603 | partial | 1 malformed records rejected. ; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Celestica Inc. | 1104 | complete | None |
| Cerebras Systems Inc. | 111 | complete | None |
| Cisco Systems, Inc. | 1302 | complete | None |
| Credo Technology Group Holding Ltd | 44 | complete | None |
| Etched.ai, Inc. | 105 | complete | None |
| Google LLC | 3360 | complete | None |
| Infineon Technologies Americas Corp. | 0 | fallback | Eightfold app shell downloads but exposes no structured job list; public apply-v2 guesses returned 404/403.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Intel Corporation | 592 | complete | None |
| Lattice Semiconductor Corporation | 148 | complete | None |
| Lightmatter, Inc. | 65 | complete | None |
| Marvell Technology, Inc. | 188 | complete | None |
| MATX | 44 | complete | None |
| MaxLinear, Inc. | 0 | fallback | iCIMS returned 405 Human Verification for search and sitemap paths.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Microchip Technology Incorporated | 493 | complete | None |
| Micron Technology, Inc. | 0 | fallback | Eightfold app shell downloads but exposes no structured job list; public apply-v2 guesses returned 404/403.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Microsoft Corporation | 0 | fallback | Careers site redirects to an Eightfold-style app with reCAPTCHA; public GCS API guesses returned 404.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Nexperia USA Inc. | 233 | complete | None |
| Nokia of America Corporation | 589 | complete | None |
| NVIDIA | 2000 | complete | None |
| NXP USA, Inc. | 768 | complete | None |
| OMNIVISION Technologies, Inc. | 0 | fallback | Direct page is unstable under bot checks and public sitemap exposes only careers/job-openings pages, not job detail URLs.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| onsemi | 705 | complete | None |
| PsiQuantum Corp. | 74 | complete | None |
| QUALCOMM Incorporated | 0 | fallback | Eightfold app shell downloads but exposes no structured job list; public apply-v2 guesses returned 404/403.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Rambus Inc. | 0 | fallback | iCIMS returned 405 Human Verification for search and sitemap paths.; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Renesas Electronics America, Inc. | 910 | complete | None |
| Rivos Inc. | 15 | partial | No next-page link; board completeness unverified; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Samsung Semiconductor, Inc. | 695 | partial | 1 malformed records rejected. ; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| SanDisk | 310 | complete | None |
| Semtech Corporation | 103 | complete | None |
| SiFive, Inc. | 121 | complete | None |
| Silicon Laboratories Inc. | 83 | complete | None |
| SK hynix America Inc. | 46 | complete | None |
| Synopsys, Inc. | 461 | complete | None |
| Tenstorrent Inc. | 127 | complete | None |
| Teradyne, Inc. | 512 | complete | None |
| Texas Instruments Incorporated | 713 | complete | None |
| Taiwan Semiconductor Manufacturing Company Limited | 0 | failed | ValueError: No structured job records; extractor or public endpoint required; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |
| Ventana Micro Systems Inc. | 0 | failed | ValueError: No structured job records; extractor or public endpoint required; Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback |

## Remaining Work

- Configure JSearch credentials and validate a paid response with the strict employer filter. The nine configured fallback companies remain uncollected.
- Amazon exposes a 10,000-result search ceiling. Partition searches by location or job category and deduplicate before claiming full-board coverage.
- Cadence and Samsung each returned one malformed record. Valid records were collected; rejected records are retained for review.
- Rivos yielded 15 public Uplers job cards; pagination completeness is unverified.
- TSMC returned HTTP 403. Ventana redirected to a Jobvite product site, with no job records. Both attempt JSearch when credentials are available.
- Add a shared daily JSearch quota ledger before scheduling repeated automated runs. No scheduled task or startup entry was installed.

## Source Changes

- MatX migrated from Greenhouse to Ashby, verified against [the company careers page](https://matx.com/jobs). SQL and SQLite were updated together.
- Renesas returned 403 during the validator run but succeeded through the collector using its standard identifying User-Agent; 910 public detail pages were collected without challenge bypass.
- Four missing tuple-opening parentheses in schema.sql were repaired. The source catalog rebuild and idempotent rerun passed SQLite foreign-key checks.

The schema and JSONL preserve provider data. Most boards are worldwide; Apple and JSearch use their configured US scope. Counts are source records, not deduplicated real-world requisitions across locations.
