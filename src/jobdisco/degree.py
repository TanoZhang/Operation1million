"""Whether a posting accepts only a PhD.

Asked for on 2026-09-22: a posting open only to PhDs is not worth reviewing,
but one a PhD is merely allowed or preferred for is -- and nothing is to be
removed by mistake. So this answers "only a PhD" and nothing broader, and every
doubt keeps the posting:

- The title decides when it names a PhD and no other degree: "Software
  Engineer, PhD, Early Career", "Ph.D. Intern - Analog". "Intern, MS/PhD" and
  "BS/MS/PhD" name another path and are kept.
- Otherwise the description decides, and only on an explicit statement --
  "currently pursuing a PhD", "PhD required", "must have a PhD", or a "PhD in
  ..." line under a required heading -- with no other degree and no "or
  equivalent" beside it, and not under a preferred heading. A bachelor's or
  master's named anywhere else in the posting outside a preferred section
  keeps it: that is another way in.
"""
import html
import re

from .experience import OPTIONAL, REQUIRED, SECTION_END

# A PhD that is welcome rather than demanded. The experience gate's OPTIONAL
# words alone read "PhD is highly desirable", "pursuing a PhD is an
# advantage", "PhD students are encouraged to apply" and "the ideal candidate
# will have a PhD" as requirements, and removed postings a PhD is only
# preferred for. Kept local: widening OPTIONAL would also change experience.
PREFERENCE = re.compile(
    OPTIONAL.pattern + r'|\b(?:prefer(?:ence|ab(?:ly|le))?|desirable|advantage(?:ous)?|'
    r'beneficial|helpful|welcomed?|encouraged|ideal|nice[-\s]to[-\s]have|pluses|'
    r'(?:big|huge|strong|major|definite|great|added)\s+plus|extra\s+credit|'
    r'sets?\s+you\s+apart|stand\s+out)\b', re.I)
# A sentence that only qualifies the one before it: "Currently pursuing a
# PhD. Strongly preferred." The sentence split had left the requirement alone.
_TRAILING_PREFERENCE = re.compile(
    r'^\(?(?:(?:is|are|strongly|highly|very|much|but|not|required|preferred|preferably|'
    r'desired|desirable|a|plus|nice|to|have|optional|ideally)[\s,.!)]*)+$', re.I)
# A heading that neither requires nor prefers, and belongs to the section it
# sits in: "Education:" under "Minimum qualifications:".
_NEUTRAL_HEADING = re.compile(r'^(?:education|degrees?|qualifications?|skills)\b', re.I)

PHD = r'(?:ph\.?\s?d\.?s?|doctora(?:l|te)(?:\s+degree)?)'
_PHD = re.compile(r'(?<![\w])' + PHD + r'(?![\w])', re.I)
# Another degree, or another way in. Words in any case; the short forms only
# as a degree is written -- "BS", "M.S.", "BSEE" -- because read without case
# "B.E." is the word "be" and "M.E." the word "me", in every description.
_OTHER_WORDS = re.compile(
    r"\b(?:bachelor\w*|master'?s|masters|master\s+(?:degree|of|in)|undergrad\w*|"
    r"associate'?s\s+degree|or\s+(?:an?\s+)?equivalent|"
    r"(?:equivalent|or\s+(?:comparable|relevant))\s+"
    r"(?:practical\s+|work\s+|industry\s+)?experience)(?![\w])", re.I)
_OTHER_SHORT = re.compile(
    r"(?<![\w.])(?:BS|MS|B\.\s?S\.?|M\.\s?S\.?|BSc|MSc|B\.\s?Sc\.?|M\.\s?Sc\.?|B\.\s?E\.|M\.\s?E\.|"
    r"BE|ME|B\.?\s?Tech|M\.?\s?Tech|BTech|MTech|BSEE|MSEE|BSCS|MSCS|BSCE|MSCE|MBA|MEng|BEng)(?![\w])")


STATED = re.compile(
    r'\b(?:(?:currently\s+)?(?:pursuing|enrolled\s+in|working\s+(?:towards?|on)|studying\s+for|'
    r'candidates?\s+for|completing)\s+(?:a\s+|an\s+|your\s+)?' + PHD +
    r'|' + PHD + r'\s+(?:degree\s+)?(?:is\s+)?(?:required|mandatory|needed)'
    r'|(?:must|shall|will)\s+(?:have|hold|possess|be\s+(?:pursuing|enrolled\s+in))\s+(?:a\s+|an\s+)?' + PHD +
    r'|' + PHD + r'\s+(?:students?|candidates?)\s+only)', re.I)
DEGREE_LINE = re.compile(r'^\s*(?:a\s+)?' + PHD + r'\s+(?:degree\s+)?(?:in|from)\b', re.I)
# Explicitly saying the PhD is absent or optional defeats a nearby word such as
# "required". Without this guard, STATED read the substring in "No PhD
# required" as a requirement. The same wording can occur in a title.
NOT_EXCLUSIVE = re.compile(
    r'(?:\b(?:no|without)\s+(?:a\s+)?' + PHD +
    r'|' + PHD + r'\s+(?:degree\s+)?(?:is\s+)?(?:not\s+(?:required|needed|necessary|mandatory)|optional)\b)',
    re.I)


def _has_other_degree(text: str) -> bool:
    """Recognize a second degree or an explicit experience alternative."""
    return bool(_OTHER_WORDS.search(text) or _OTHER_SHORT.search(text))


def _description_blocks(text):
    """Yield prose blocks and field-end markers without losing section scope."""
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]*>', '\n', text)
    # "Ph.D. Preferred" ends a sentence at the abbreviation for the split
    # below, which left "Ph.D." read apart from its own preference.
    text = re.sub(r'\bPh\.\s?D\.', 'PhD', text, flags=re.I)
    # Keep structured field boundaries visible to the qualification policy.
    text = text.replace(SECTION_END, '\n' + SECTION_END + '\n')
    for block in re.split(r'[\n;]|(?<=[.!?])\s+(?=[A-Z])', text):
        block = block.strip(' \t-*•·')
        if block:
            yield block


def title_only(title):
    """The title names a PhD and no other degree."""
    title = title or ''
    # A title can state the preference itself. It is still not an exclusive
    # PhD opening, and this filter deliberately keeps every doubtful case.
    return (bool(_PHD.search(title)) and not _has_other_degree(title)
            and not PREFERENCE.search(title) and not NOT_EXCLUSIVE.search(title))


# A heading opens a section; a short sentence does not. "Python preferred."
# is two words and names a preference, and was read as a Preferred heading --
# which then suppressed the "PhD required." on the line after it. A heading is
# written as one: it ends in a colon, or it is the name of a qualification
# section.
_HEADING_WORDS = re.compile(
    r'^(?:minimum|basic|preferred|desired|required|requirements?|qualifications?|'
    r'nice[-\s]to[-\s]have|education|additional|responsibilities|about|benefits|what\s+you|'
    r'desirable|bonus|pluses|ideal(?:ly)?|extra\s+credit)\b',
    re.I)


def _is_heading(block):
    return block.rstrip().endswith(':') or bool(_HEADING_WORDS.match(block))


def description_only(text):
    """The description states a PhD requirement and offers no other way in."""
    optional_section = required_section = False
    stated, other = False, False
    blocks = list(_description_blocks(text))
    for index, block in enumerate(blocks):
        if block == SECTION_END:
            optional_section = required_section = False
            continue
        has_phd = bool(_PHD.search(block))
        has_other = _has_other_degree(block)
        following = blocks[index + 1] if index + 1 < len(blocks) else ''
        optional = (optional_section or bool(PREFERENCE.search(block))
                    or bool(PREFERENCE.search(following) and _TRAILING_PREFERENCE.match(following)))
        # What a block states about degrees is read before it can be taken for
        # a heading. "Or Master's degree required." is four words and matches
        # REQUIRED, and was read as a heading and skipped -- losing the very
        # alternative that keeps the posting.
        if has_other and not optional:
            other = True
        if len(block.split()) <= 7 and not has_phd and not has_other and _is_heading(block):
            if PREFERENCE.search(block):
                optional_section, required_section = True, False
                continue
            if REQUIRED.search(block):
                optional_section, required_section = False, True
                continue
            if re.match(r'^(?:responsibilities|about\b|benefits\b|what you)', block, re.I):
                optional_section = required_section = False
            elif not _NEUTRAL_HEADING.match(block):
                # "What sets you apart:" or any heading this list does not
                # know ends the required section: a doubt keeps the posting.
                required_section = False
        if (not has_phd or optional or has_other
                or NOT_EXCLUSIVE.search(block)):
            continue
        # A requirement may sit behind its own heading on one line:
        # "Required: PhD in EE". The heading names the section, the rest states
        # the degree, and neither half is read alone.
        body = block.split(':', 1)[1].strip(' \t-*•·') if ':' in block else block
        under_heading = required_section or bool(
            REQUIRED.search(block[:block.index(':')]) if ':' in block else False)
        if STATED.search(block) or (under_heading and DEGREE_LINE.search(body)):
            stated = True
    return stated and not other


def phd_only(title, text):
    """Only a PhD will do, by the title or, failing that, the description."""
    if title_only(title):
        return True
    if _PHD.search(title or '') or _has_other_degree(title or ''):
        # The title names degrees and a PhD is not the only one: it decides.
        return False
    return description_only(text)
