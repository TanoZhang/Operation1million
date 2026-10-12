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

Japan boards, captured 2026-10-11 UTC (originals ignored in `.local/jp-capture/`):

| Redacted fixture | Captured public request | Preserved observation |
| --- | --- | --- |
| `bamboohr_list_redacted.json` | `https://edgecortix.bamboohr.com/careers/list` | `result[]` with string `id`, `jobOpeningName` prefixed "[Japan]"/"[India]", `location.city/state` and an empty `atsLocation` |
| `bamboohr_detail_redacted.json` | `https://edgecortix.bamboohr.com/careers/<id>/detail` | `result.jobOpening.description` (HTML) and `datePosted` |
| `talentio_home_redacted.html` | `https://open.talentio.com/r/1/c/preferred/homes/4679` | `data-react-props` JSON whose nested postings carry `name` and a `/pages/<id>` `publishedUrl` |
| `talentio_page_redacted.html` | `https://open.talentio.com/r/1/c/preferred/pages/88336` | `recruitmentOpenPage.requisitionDetails[]` of `name`/`value`, required and preferred qualifications under their own names, and a location value written as a bracketed list string |
| `tsmc_sitemap_redacted.xml` | `https://careers.tsmc.com/en_US/careers/sitemap.xml` | Each English JobDetail URL listed twice, beside other locales' copies and non-posting pages |
| `tsmc_detail_redacted.html` | `https://careers.tsmc.com/en_US/careers/JobDetail/Physical-Design-Engineer-Taiwan/248` | No `h1`: the title is in `<title>` and JSON-LD; the place is one `Location` field ("Japan-Yokohama" on Yokohama pages) |
| `hrmos_list_redacted.html` | `https://hrmos.co/pages/toshiba/jobs?page=1` | Each posting an `a` to `/pages/<slug>/jobs/<id>` holding an `h2` title, a `.pg-list-cassette-body` text and `.sg-tags li` tags (function, region, type); `?page=N` pages until one lists none |
| `hrmos_detail_redacted.html` | `https://hrmos.co/pages/toshiba/jobs/300000016` | JSON-LD JobPosting with HTML `description`, `datePosted` and `jobLocation[].address`; its `title` adds "／ <company>" after the `h1` |
| `jposting_list_redacted.json` | `https://jscudp.jcareers.com/kioxia/u/jobs.phtml?job_list=1&job_items[]=location&job_items[]=description` (Referer: the board page) | HAL JSON: `_embedded.job_category.<key>._embedded.job.<key>` with `id`, `name`, multi-line `location`, `description` |
| `jposting_detail_redacted.html` | `https://kioxia.jposting.net/u/job.phtml?job_code=719` | EUC-JP page whose 「応募資格」 holds 【必須要件】 and 【歓迎要件】, absent from the list |
