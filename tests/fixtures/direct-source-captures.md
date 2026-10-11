# Direct-source fixture provenance

The original HTTP 200 response bodies were captured from public employer
endpoints on 2026-10-11 UTC with `JobSourceCollector/1.0`. They remain in the
ignored `.local/direct-source-captures/` directory and must not be committed to
this public repository. The committed fixtures retain observed response paths,
field names, value types and boundary counts, with job identifiers, links,
locations and descriptions replaced by synthetic test values. The tests run
offline and do not call an employer or paid API.

| Redacted fixture | Captured public request | Preserved observation |
| --- | --- | --- |
| `sandisk_sitemap_redacted.xml` | `https://avature.sandisk.com/Careers/sitemap.xml` | Namespaced URL set, 310 numbered `JobDetail` URLs, and a non-job portal URL |
| `sandisk_detail_redacted.html` | A numbered `https://avature.sandisk.com/Careers/JobDetail/` page | JSON-LD names the job and date but omits description and location; visible `h1`, `main` and labeled fields supply them |
| `amazon_base_redacted.json` | `https://www.amazon.jobs/en/search.json?offset=0&result_limit=100&sort=recent` | `hits=10000` global ceiling and string `business_category` on jobs |
| `amazon_advertising_redacted.json` | The same search with `business_category[]=advertising` | `hits=525` and the same job/category field paths |

The Amazon boundary test lowers the source-local ceiling to one synthetic job
so it crosses from the captured global response shape to the captured category
response shape in two offline requests. Production uses the observed 10,000
result ceiling.

`amazon_facets_redacted.json` keeps the shape of the same global search with
`facets[]=business_category`, captured 2026-10-11 UTC: `facets.business_category_facet`
is a list of one-key objects, category to count, across the whole board (62
categories summing to 22,338 while `hits` stayed 10,000). Jobs without a
category are filed under `no-business-category`, and their own
`business_category` field carries that string. Counts and job values are
synthetic.
