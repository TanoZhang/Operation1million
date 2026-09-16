# Job Discovery

This context describes a job discovery system for finding and storing relevant hardware engineering roles from configurable, compliant sources.

## Language

**Job Discovery System**:
A system that finds job postings from configured sources and records normalized job leads for later filtering.
_Avoid_: crawler, scraper

**Source**:
A configured place to discover job postings from, with an explicit allowed access method.
_Avoid_: target, scrape site

**Platform Source**:
A source that represents a reusable platform-level connector, such as an official API, public ATS endpoint, or search API.
_Avoid_: generic crawler

**Company Source**:
A source that represents one company-specific career surface or ATS board.
_Avoid_: company scraper

**ATS Provider**:
A recruiting platform used by companies to publish their complete public job boards, such as Greenhouse, Lever, Ashby, or Workday.
_Avoid_: job board search engine

**Search Provider**:
A cross-company service that requires discovery queries to return job opportunities from many employers.
_Avoid_: ATS provider

**Public Feed**:
A public endpoint that returns a broad current collection of opportunities in one request without requiring discovery queries.
_Avoid_: company career site

**Company Career Site**:
A company-owned public careers surface that is not yet mapped to a supported ATS provider or public feed.
_Avoid_: public feed

**Discovery Query**:
A broad search expression used only by search providers to discover opportunities; it is not a final relevance filter.
_Avoid_: filter rule

**Risk Tier**:
A scheduling and automation safety classification for a source, based on whether the access path is official, verified, sensitive, or permissioned.
_Avoid_: trust score

**Job Record**:
The normalized discovery output for one opportunity, with stable identity fields reserved for storage and dedupe.
_Avoid_: raw posting

**Source Health Record**:
A log row for one fetch attempt, recording success, HTTP status, returned job count, and basic failure information.
_Avoid_: alert

**Company Watchlist**:
A non-executable list of target companies to research and map into real sources later.
_Avoid_: source config

**Company Catalog**:
A minimal maintained list of large-enough companies and how their public application surface can be reached.
_Avoid_: company ranking table, import batch log

**Application Surface**:
The current known way to apply to a company: a supported ATS board, a direct company career page, or unknown.
_Avoid_: website domain

**Job Lead**:
A discovered job posting represented by its title, link, source, and discovery time.
_Avoid_: raw job, listing blob

**Discovery Run**:
One scheduled execution that checks every configured source according to its own access and quota rules.
_Avoid_: request, crawl

**Provider Limit Scope**:
The boundary to which a provider quota applies: one board instance, one provider account, the provider integration globally, or one query.
_Avoid_: global limit

**Experience Opportunity**:
A legitimate paid, low-paid, unpaid, internship, volunteer, contract, or entry-level role that can provide relevant industry experience.
_Avoid_: job only
