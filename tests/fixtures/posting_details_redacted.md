# Detail fixture provenance

Captured 2026-10-07 through the existing paced Collector transport under the
production collection lock; no paid calls. Original captures remain ignored in
`.local/apple-jd-audit/` and must not be committed to this public repository.

`workday_detail_redacted.json` retains the observed CXS `jobPostingInfo` nesting
and selected keys from an Altera posting. `posting_detail_redacted.html` retains
the JSON-LD script wrapper and selected JobPosting keys from a Lam Research
Eightfold page. Values identifying a posting, and all description content, are
replaced with synthetic test content. Unused fields are omitted.

`eightfold_detail_redacted.json` retains `data.id` and `data.jobDescription`
from Microsoft's public `pcsx/position_details` endpoint, discovered in its
public JavaScript bundle. The HTML required/preferred section boundaries are
preserved in a synthetic degree-alternative example. Its JSON-LD description
omitted these headings; using that flattened value incorrectly rejected the
real posting. `smartrecruiters_detail_redacted.json` retains the posting id and
`jobAd.sections.*.text` shape captured from Sandisk's public posting API.
