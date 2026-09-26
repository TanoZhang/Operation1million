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
    | soc(?!\s*(?:analyst|operations?|compliance|audit|\d))
    | (?: design | functional | formal | hardware | rtl | soc | asic | ip | block
        | chip | cpu | gpu | npu | digital | low[-\s]?power
        | pre-?\s?silicon | post-?\s?silicon ) \s+ verification
    | (?: digital | logic | rtl | asic | soc | vlsi | chip | silicon | cpu | gpu
        | npu | memory | sram | standard[-\s]?cell ) \s+ (?:ic\s+)? design
    | digital \s+ ic
    | physical \s+ (?: design | implementation | verification )
    | (?: silicon | soc | chip | hardware | pre-?\s?silicon | post-?\s?silicon )
      \s+ validation
    | design \s+ for \s+ test(?:ability)?
    | micro-? architecture
    | (?: static \s+ )? timing \s+ (?: closure | analysis | engineer | design | signoff | sign-off )
    | gate[-\s]?level
    | place \s* (?: and | & ) \s* route
    | synthesis \s+ engineer
    | (?: hardware \s+ )? emulation
    | fpga \s+ prototyping
    | scan \s+ chain | uvm | systemverilog
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
    # The trade's tooling and its neighbours, missing until 2026-09-22, when the
    # queue's "less related" section was read title by title and held "Timing
    # Design Engineer", "CAD Gate-level 3DIC EM/IR Engineer", "Digital Layout
    # Design Engineer" and "PhD Research Intern, Circuits".
    | cad | eda | layout | circuits | em \s* / \s* ir | emir | 3d-?ic | chipdev
    | packag(?:e|ing) \s+ (?: design | engineer | integration ) | advanced \s+ packaging
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
    | entry[-\s]? level | early[-\s]? career | campus | student
    | \d{4} \s+ grad(?:uate)?s?
    # "NG" is how a board abbreviates new grad: "Physical Design Engineer (NG)".
    # Only in capitals and not hyphenated, so "NG-RAN" stays a radio network.
    | (?-i: (?<![\w-]) NG (?![\w-]) )
)\b""", re.I | re.X)


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


def bucket(title):
    """Which band of the queue a title belongs in, 0 (first) to 4 (last).

    Early career is what this search is for, so it outranks seniority across
    the trade and its neighbourhood alike -- but it never rescues a posting
    from outside both. `Software Marketing Intern` names neither, so it stays
    in the last band below every engineering posting in the queue, which is the
    ordering the bands exist to produce.
    """
    title = title or ''
    early = bool(EARLY_CAREER.search(title))
    if CORE.search(title):
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
    return bool(EARLY_CAREER.search(title or ''))


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
TEXT_DATES = ('%B %d, %Y', '%b %d, %Y', '%m/%d/%Y', '%d %B %Y')


def posted_day(value):
    """The calendar day a stamp names, or None if it names nothing usable."""
    text = ' '.join(str(value or '').split())
    if not text:
        return None
    found = ISO_DAY.match(text)
    if found:
        try:
            return date(*(int(part) for part in found.groups()))
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
RELATIVE_DAY = re.compile(
    r'^\s*posted\s+(?:(?P<today>today|just\s+now)|(?P<yesterday>yesterday)|'
    r'(?P<days>\d{1,2})\s+days?\s+ago)\s*$', re.I)


def relative_day(text, as_of):
    """The ISO day a board's relative age names, read against when it said it.

    `as_of` is the stamp of the pass that read the text; the store updates the
    two together. None when either is missing or the text is not an exact age.
    """
    found = RELATIVE_DAY.match(str(text or ''))
    seen = posted_day(as_of)
    if not found or seen is None:
        return None
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
