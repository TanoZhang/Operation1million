# Evidence-backed recruitment domain exclusions

Reviewed 2026-09-22 UTC. The user requested exclusions backed by reliable
fraud evidence, not a blanket ban on third-party job boards.

## Added: 13 domains seized in a fake recruitment investigation

Source: [DOJ announcement, June 10, 2026](https://www.justice.gov/opa/pr/justice-department-fbi-disable-13-websites-backed-suspected-chinese-agents-sought-sensitive).
The announcement identifies fake consulting websites and confirms seizure of
all 13 domains below. The underlying criminal allegations are allegations;
seizure is not a conviction. This documented enforcement action meets the
project's exclusion threshold. It does not prove current ownership or that
every domain still hosts active content. We did not visit these domains.

| Domain | Evidence |
| --- | --- |
| centrikglobalconsulting.com | DOJ seizure announcement |
| rightinfoconsult.com | DOJ seizure announcement |
| finnaclevesperconsulting.com | DOJ seizure announcement |
| cydfconsulting.com | DOJ seizure announcement |
| pulsewaveglobal.com | DOJ seizure announcement |
| catalystglobalsolutions.com | DOJ seizure announcement |
| thehorizzen.com | DOJ seizure announcement |
| geoindopacific.com | DOJ seizure announcement |
| gpf-ina.org | DOJ seizure announcement |
| safesec-group.com | DOJ seizure announcement |
| thetruthinfo.com | DOJ seizure announcement |
| vandercons.com | DOJ seizure announcement |
| gulfpeace.org | DOJ seizure announcement |

`filter.exclude_publisher_domains` in `data/config/jsearch_queries.toml` matches
the posting URL host or a domain-form publisher, including subdomains. It
returns the existing `excluded_publisher` hard rejection before keep/score
rules and also hides previously indexed postings at Review read time. It does
not match a domain merely mentioned in a path/query, map an arbitrary display
name to a domain, follow redirects, or discover future replacement domains.
No application decisions, raw provider records or historical logs are deleted.

## Existing preference blocks

Trabajo.org, Advies Van Spijk and Experteer retain their previously requested
text exclusions. This research did not establish authoritative fraud findings
against them. They must not be described as proven scams merely because they
are blocked or have negative reviews.

## Research considered but not imported

[FTC's July 2023 Fluent enforcement announcement](https://www.ftc.gov/news-events/news/press-releases/2023/07/ftc-law-enforcers-nationwide-announce-enforcement-sweep-stem-tide-illegal-telemarketing-calls-us)
describes deceptive job-opportunity lead generation associated with
FindDreamJobs, StartACareerToday and JobsOnDemand. This is relevant enforcement
evidence, but does not establish that every current site or similarly named
business is entirely fraudulent. No guessed domains or broad brand patterns
were imported under the user's narrower request.

General scam advice, review-site scores and isolated complaints are not a
domain list. Legitimate platforms mentioned as distribution channels in an
enforcement announcement are not implicated as fraudulent platforms.

## Verification and limits

Offline regressions cover all 13 domains, subdomains, mixed case, trailing DNS
dots, rejection before keeps, existing Review rows, publisher domains, URL
userinfo, misleading suffixes, path/query mentions and malformed URLs. This
is an evidence-backed starter list, not a complete global scam registry.
No paid collection, live prevalence measurement or deployment was performed.
