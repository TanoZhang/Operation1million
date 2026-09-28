"""Which kept postings to read first.

This module answers a different question from the filter, and deliberately
cannot answer the filter's. `jsearch.rejection_reason` decides whether a posting
is worth keeping at all; everything here runs on what it already kept and only
decides what order to show it in. Nothing is dropped, so a rule that is wrong
here costs a posting its place on the first page, never its place in the store.

The order is a bucket first and a date second. Scoring alone could not do this:
relevance measures how much of the trade's vocabulary a posting uses, which an
`RTL Design Engineer` and a staff-level `SoC Verification Lead` answer the same
way, and which says nothing at all about whether the posting is open to someone
who has not graduated yet. So the bucket asks the two questions the score
cannot -- is this the trade, and is this an opening for the early career -- and
the score is kept to break ties inside a bucket, where it is good at it.

Early career leads both bands it appears in, because an internship is what this
search is actually for. It never rescues a posting from outside the trade and
its neighbourhood, though: `Software Marketing Intern` names neither, so it
sorts below every engineering posting in the queue regardless of the word
"Intern". That ordering is the whole reason relevance is consulted after the
band and not before it.
"""
from datetime import date, datetime
import re


# The trade itself: titles that name the work rather than the neighbourhood.
# Each alternative is a phrase or a proper noun, never a bare English word --
# `digital`, `silicon` and `verification` on their own belong to the adjacent
# bucket below, because an industry that is not this one prints them too.
CORE = re.compile(r"""\b(?:
      rtl | asic | fpga | vlsi | dft | atpg | dv
    | (?<!security\s)(?<!cybersecurity\s) soc(?!\s*(?:analyst|operations?|compliance|audit|\d))
    | (?: design | functional | formal | hardware | rtl | soc | asic | ip | block
        | chip | cpu | gpu | npu | digital | low[-\s]?power
        | pre-?\s?silicon | post-?\s?silicon ) \s+ verification
    | (?: digital | logic | rtl | asic | soc | vlsi | chip | silicon | cpu | gpu
        | npu | memory | sram | standard[-\s]?cell ) \s+ (?:ic\s+)? design(?:er)?
    | digital \s+ ic
    # "Designer" too: "Physical Designer", "Logic Designer" sat in the last
    # band (live queue, 2026-09-27), as did "RTL2GDS" and the timing roles.
    | physical \s+ (?: design(?:er)? | implementation | verification )
    | rtl2gds | timing \s+ methodology | , \s* timing \s* $
    | (?: silicon | soc | chip | hardware | pre-?\s?silicon | post-?\s?silicon )
      \s+ validation
    | design \s+ for \s+ test(?:ability)?
    | (?: static \s+ )? timing \s+ (?: closure | analysis | engineer | design | signoff | sign-off )
    | gate[-\s]?level
    | place \s* (?: and | & ) \s* route
    | synthesis \s+ engineer
    | (?: hardware \s+ )? emulation
    | fpga \s+ prototyping
    | scan \s+ chain | uvm | systemverilog
    # Found in the last band on 2026-09-27: the flow's steps, the languages,
    # library characterization, DFx and the microarchitect.
    | (?-i: STA ) | pnr | clock \s+ tree | cts (?=\s+engineer) | sign-?off
    | floor-?plan\w* | placement (?=\s+engineer) | tape-?out
    | (?: library | lib ) \s+ characteri[sz]ation | standard[-\s]?cell \s+ library
    | verilog | vhdl | dfx | micro-? architect\w*
)\b""", re.I | re.X)


# The neighbourhood: hardware work that is not the trade, and the low-level
# software the trade sits under. Wider than CORE on purpose -- this is the
# bucket that says "probably worth a look", not "this is the job".
RELATED = re.compile(r"""\b(?:
      embedded | firmware | bare[-\s]?metal | bootloader | bios | uefi | rtos
    | (?: device | kernel | graphics | display | audio | storage | network )
      \s+ drivers?
    | drivers? \s+ (?: engineer | development | software )
    | hardware | silicon | semiconductor | integrated \s+ circuit | ic | circuit
    | validation | verification
    | (?: computer | hardware | silicon | chip | soc | processor ) \s+ architecture
    | accelerator | pcie | serdes | ddr\d? | lpddr | hbm | sram | dram | memory
    | nand | flash | processor | cpu | gpu | npu | tpu | chip | chiplet
    | signal \s+ integrity | power \s+ integrity | board \s+ bring-? up
    | (?: hardware | silicon | chip | product | board | system | ate | device
        | fpga | asic | soc ) \s+ test
    | electrical \s+ engineer | electronics? \s+ engineer
    # Found on the live queue's Low relevance tab, 2026-09-27: "Electrical
    # Engineering Internship", "Display Electrical Design Engineer", mixed-
    # signal modeling and design, digital / system-level / high-speed I/O
    # test, chipsets and signal processing.
    | electrical \s+ (?: design \s+ )? engineer(?:ing)? | electrical \s+ design
    | mixed[-\s]?signal
    | (?: digital | analog | system[-\s]level | high[-\s]speed \s+ i/?o ) \s+ test
    | chipsets? | dsp | digital \s+ signal \s+ processing
    # The trade's tooling and its neighbours, missing until 2026-09-22, when the
    # queue's "less related" section was read title by title and held "Timing
    # Design Engineer", "CAD Gate-level 3DIC EM/IR Engineer", "Digital Layout
    # Design Engineer" and "PhD Research Intern, Circuits".
    | cad | eda | layout | circuits | em \s* / \s* ir | emir | 3d-?ic | chipdev
    | mask \s+ design | design \s+ automation
    | packag(?:e|ing) \s+ (?: design(?:er)? | engineer | integration ) | advanced \s+ packaging
    | design \s+ engineering
)\b""", re.I | re.X)


# Openings an application without a degree in hand can actually reach.
EARLY_CAREER = re.compile(r"""\b(?:
      interns? | internships? | co[-\s]?ops?
    | (?: new | recent | university | college ) \s+ (?:college \s+)?
      grad(?:uate)?s?
    # "NVIDIA 2027 Internships: ...", "SoC & DFT Engineer - Graduate Training
    # Program", "Graduate Talent (CPU-SoC Silicon Design)" and "Electrical
    # Engineering Graduate" were all read as experienced openings until
    # 2026-09-25, when early career got a review tab of its own.
    | graduate \s+ (?: training \s+ )?
      (?: engineer | program | programme | rotation | scheme | talent )
    | engineering \s+ graduates?
    # "Graduate RTL Engineer", "RTL Design Engineer (Grad)", "Class of 2027"
    # and apprentices, found 2026-09-27.
    | ^ \s* graduate \b | (?<=\() \s* grad(?:uate)? (?=\s*\)) | class \s+ of \s+ \d{4}
    | apprentice(?:ship)?s?
    # Rotational programmes and junior titles (2026-09-27).
    | rotation(?:al)? \s+ program(?:me)?s? | junior | jr
    # Early and emerging talent, freshers, trainees, undergraduates (2026-09-27).
    | early \s+ talent | emerging \s+ talent | freshers? | fresh \s+ graduates?
    | trainees? | undergrad\w*
    # "Campus" as the opening, not the place: "Campus Network Engineer"
    # (2026-09-27).
    | entry[-\s]? level | early[-\s]? career | student
    | campus \s+ (?:hire|hiring|graduate|recruit\w*|program\w*|intern\w*)
    | (?<=\() \s* campus (?=\s*\))
    | \d{4} \s+ grad(?:uate)?s?
    # "NG" is how a board abbreviates new grad: "Physical Design Engineer (NG)".
    # Only in capitals and not hyphenated, so "NG-RAN" stays a radio network.
    # "NCG", new college grad, the same way (2026-09-27).
    | (?-i: (?<![\w-]) N C? G (?![\w-]) )
)\b""", re.I | re.X)

# A senior title names a recruiting or programme role when it also says
# "campus", "student" or "early career": "Senior Manager, Campus Recruiting"
# is not an opening for a student, and was on the Early career tab
# (2026-09-27). An intern, co-op or graduate named outright still is one.
SENIOR = re.compile(r'\b(?:senior|sr\.?|staff|principal|director|head\s+of|vp|manager)\b', re.I)
OPENING = re.compile(r"""\b(?:
      interns? | internships? | co[-\s]?ops? | grad(?:uate)?s?
    | (?-i: (?<![\w-]) N C? G (?![\w-]) )
)\b""", re.I | re.X)


def _early(title):
    if not EARLY_CAREER.search(title):
        return False
    return not SENIOR.search(title) or bool(OPENING.search(title))


# Index into these by bucket number, which is also the order they are read in:
# band 0 comes first. Both early-career bands precede either regular one. An
# adjacent internship is an opening this search can actually take and a
# principal RTL role is not, so the internship is the better thing to put in
# front of someone even though the other is more squarely the trade.
LABELS = ('Intern / New Grad', 'Related · Intern / New Grad', 'Core VLSI',
          'Related Hardware', 'Other')

# What a pass reports, which is coarser than what the queue sorts by: the two
# early-career bands are one number to a reader, though a core opening still
# leads an adjacent one inside them.
SUMMARY = (('intern_ng', (0, 1)), ('core_vlsi', (2,)),
           ('related_hardware', (3,)), ('low_relevance', (4,)))


SECURITY_OPERATIONS = re.compile(r'\bsecurity\s+operations\b|\bSOC\s+analysts?\b|\bcyber\s*security\b', re.I)


def bucket(title):
    """Which band of the queue a title belongs in, 0 (first) to 4 (last).

    Early career is what this search is for, so it outranks seniority across
    the trade and its neighbourhood alike -- but it never rescues a posting
    from outside both. `Software Marketing Intern` names neither, so it stays
    in the last band below every engineering posting in the queue, which is the
    ordering the bands exist to produce.
    """
    title = title or ''
    early = _early(title)
    # A security operations centre's SOC is not a system on chip, however the
    # title spells it: "Security Operations Center (SOC) Engineer" (2026-09-27).
    if CORE.search(title) and not SECURITY_OPERATIONS.search(title):
        return 0 if early else 2
    if RELATED.search(title):
        return 1 if early else 3
    return 4


def early_career(title):
    """Whether the title itself names an early-career opening.

    The review page lists these apart from everything else it has to review,
    asked for on 2026-09-25. "Master's in EE plus 2 years" is not one: it names
    a floor of experience, and stays with the rest.
    """
    return _early(title or '')


def summarize(groups):
    """Count groups per reported band, for a pass or a queue to print."""
    counts = dict.fromkeys((name for name, _ in SUMMARY), 0)
    for group in groups:
        found = bucket(group.get('title') if isinstance(group, dict) else group)
        for name, members in SUMMARY:
            if found in members:
                counts[name] += 1
    return counts


# Every ISO shape the providers send -- with an offset, without one, with
# milliseconds, with `Z`, or a bare date -- agrees about the first ten
# characters, and the day is all this needs. Parsing the rest would only add
# ways to fail over a timezone that cannot move a posting more than one day.
ISO_DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')
ISO_SECONDS = re.compile(r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})')

# Amazon publishes `August 9, 2026`, which no ISO parser accepts.
# More shapes the boards print, found unread on 2026-09-27: "7-Sep-2026",
# "07.09.2026" (day first, as a point-separated date always is), "Sep 7 2026",
# "7 Sep, 2026". A two-digit year and a year-first date are read below.
TEXT_DATES = ('%B %d, %Y', '%b %d, %Y', '%m/%d/%Y', '%d %B %Y', '%d %b %Y', '%d-%b-%Y',
              '%d-%B-%Y', '%d.%m.%Y', '%b %d %Y', '%B %d %Y', '%d %b, %Y', '%d %B, %Y')
WEEKDAY = re.compile(r'^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+', re.I)
ORDINAL = re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)\b', re.I)
YEAR_FIRST = re.compile(r'^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$')
SHORT_YEAR = re.compile(r'^\d{1,2}/\d{1,2}/\d{2}$')


def month_text(text):
    """A month the way `strptime` reads it: "Sept 7, 2026" and "Sep. 7, 2026"
    become "Sep 7, 2026". Both were read as no date at all (2026-09-27)."""
    text = re.sub(r'\bSept\b', 'Sep', text, flags=re.I)
    return re.sub(r'\b([A-Za-z]{3,4})\.(?=\s)', r'\1', text)


def posted_day(value):
    """The calendar day a stamp names, or None if it names nothing usable."""
    text = month_text(' '.join(str(value or '').split()))
    text = ORDINAL.sub(r'\1', WEEKDAY.sub('', text))
    if not text:
        return None
    found = ISO_DAY.match(text) or YEAR_FIRST.match(text)
    if found:
        try:
            return date(*(int(part) for part in found.groups()))
        except ValueError:
            return None
    if SHORT_YEAR.match(text):
        try:
            return datetime.strptime(text, '%m/%d/%y').date()
        except ValueError:
            return None
    for shape in TEXT_DATES:
        try:
            return datetime.strptime(text, shape).date()
        except ValueError:
            continue
    return None


# Workday prints a posting's age, never its date: "Posted Today", "Posted 6
# Days Ago". Its postings were all shown as having no date and ranked on the
# day we first saw them, though the board had said how old each was. "30+
# Days Ago" is only a lower bound, and is left unread.
# Hours and minutes are today, "a day" is one, and a week is seven days: the
# same ages `job_text.POSTED_SUFFIX` strips from titles, which this read as no
# date at all (2026-09-27). Months stay unread; their length is a guess.
# "Posted: 3 days ago", "Reposted 3 days ago" and a bare "3 days ago" too.
RELATIVE_DAY = re.compile(
    # Abbreviated too: "1 hr ago", "5 mins ago", "2h ago", "3d ago", "1w ago".
    r'^\s*(?:(?:re)?posted\s*:?\s+)?(?:(?P<today>today|just\s+now|'
    r'(?:an?|one|\d{1,2})\s*(?:minutes?|mins?|m|hours?|hrs?|h)\s+ago)'
    r'|(?P<yesterday>yesterday|(?:a|one)\s+day\s+ago)|'
    r'(?P<days>\d{1,2})\s*(?:days?|d)\s+ago|(?P<weeks>\d{1,2}|a|one)\s*(?:weeks?|wks?|w)\s+ago)\s*$', re.I)


def relative_day(text, as_of):
    """The ISO day a board's relative age names, read against when it said it.

    `as_of` is the stamp of the pass that read the text; the store updates the
    two together. None when either is missing or the text is not an exact age.
    """
    found = RELATIVE_DAY.match(str(text or ''))
    seen = posted_day(as_of)
    if not found or seen is None:
        return None
    if found['weeks']:
        back = 7 * (int(found['weeks']) if found['weeks'].isdigit() else 1)
    else:
        back = 0 if found['today'] else 1 if found['yesterday'] else int(found['days'])
    return date.fromordinal(seen.toordinal() - back).isoformat()


def _seconds(value):
    """A monotone number for an ISO stamp, so it can be sorted descending."""
    found = ISO_SECONDS.match(' '.join(str(value or '').split()))
    if not found:
        day = posted_day(value)
        return day.toordinal() * 86400 if day else 0
    year, month, day, hour, minute, second = (int(p) for p in found.groups())
    try:
        return date(year, month, day).toordinal() * 86400 + hour * 3600 + minute * 60 + second
    except ValueError:
        return 0


def rank(group):
    """Sort key for one group: bucket, then newest, then the score, then stable.

    A posting's date and the day we first saw it are not the same fact and are
    not mixed. `first_seen` is only consulted when the employer published no
    date at all, and a group standing on that fallback sorts behind a group of
    the same day that published one, because its date is an inference and the
    other's is a statement. Everything the first pass collected shares one
    `first_seen`, so treating the two as interchangeable would have read a
    two-month-old posting as today's news.
    """
    jobs = group.get('jobs') or ()
    published = [day for day in (posted_day(job.get('posted_at')) for job in jobs)
                 if day is not None]
    if published:
        day, stated = max(published), True
    else:
        seen = [day for day in (posted_day(job.get('first_seen')) for job in jobs)
                if day is not None]
        day, stated = (max(seen) if seen else date.min), False
    return (bucket(group.get('title')),
            -day.toordinal(),
            0 if stated else 1,
            -int(group.get('confidence') or 0),
            -max((_seconds(job.get('first_seen')) for job in jobs), default=0),
            group.get('id') or '')


def order(groups):
    """The queue, best first. A stable sort, so equal keys keep their order."""
    return sorted(groups, key=rank)
