# Apple detail fixture provenance

Minimized from an HTTP 200 response captured from jobs.apple.com on 2026-10-07
UTC using the existing Collector transport and production collection lock.
The original capture is private in `.local/apple-jd-audit/`.

Preserved: the actual `window.__staticRouterHydrationData = JSON.parse(...)`
double JSON encoding and loaderData/jobDetails/jobsData field paths.
Removed: unrelated page chrome, translations and metadata.
Redacted: requisition, employer prose and qualifications; replacement values
are policy examples, not statements about a real posting. This public file
contains no real job record or application data.

`apple_detail_legacy_redacted.html` keeps the same hydration path for Apple's
older layout (shape of 200355493-0836, captured 2026-10-09): `keyQualifications`
and `educationAndExperience` in place of minimum/preferred qualifications. All
values are synthetic.
