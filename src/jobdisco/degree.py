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

from .experience import OPTIONAL, REQUIRED

PHD = r'(?:ph\.?\s?d\.?s?|doctora(?:l|te)(?:\s+degree)?)'
_PHD = re.compile(r'(?<![\w])' + PHD + r'(?![\w])', re.I)
# Another degree, or another way in. Words in any case; the short forms only
# as a degree is written -- "BS", "M.S.", "BSEE" -- because read without case
# "B.E." is the word "be" and "M.E." the word "me", in every description.
_OTHER_WORDS = re.compile(
    r"\b(?:bachelor\w*|master'?s|masters|master\s+(?:degree|of|in)|undergrad\w*|"
    r"associate'?s\s+degree|or\s+(?:an?\s+)?equivalent|"
    r"equivalent\s+(?:practical\s+|work\s+|industry\s+)?experience)(?![\w])", re.I)
_OTHER_SHORT = re.compile(
    r"(?<![\w.])(?:BS|MS|B\.\s?S\.?|M\.\s?S\.?|BSc|MSc|B\.\s?Sc\.?|M\.\s?Sc\.?|B\.\s?E\.|M\.\s?E\.|"
    r"BE|ME|B\.?\s?Tech|M\.?\s?Tech|BTech|MTech|BSEE|MSEE|BSCS|MSCS|BSCE|MSCE|MBA|MEng|BEng)(?![\w])")


class _Other:
    @staticmethod
    def search(text):
        return _OTHER_WORDS.search(text) or _OTHER_SHORT.search(text)


OTHER_DEGREE = _Other()
STATED = re.compile(
    r'\b(?:(?:currently\s+)?(?:pursuing|enrolled\s+in|working\s+(?:towards?|on)|studying\s+for|'
    r'candidates?\s+for|completing)\s+(?:a\s+|an\s+|your\s+)?' + PHD +
    r'|' + PHD + r'\s+(?:degree\s+)?(?:is\s+)?(?:required|mandatory|needed)'
    r'|(?:must|shall|will)\s+(?:have|hold|possess|be\s+(?:pursuing|enrolled\s+in))\s+(?:a\s+|an\s+)?' + PHD +
    r'|' + PHD + r'\s+(?:students?|candidates?)\s+only)', re.I)
DEGREE_LINE = re.compile(r'^\s*(?:a\s+)?' + PHD + r'\s+(?:degree\s+)?(?:in|from)\b', re.I)


def title_only(title):
    """The title names a PhD and no other degree."""
    title = title or ''
    return bool(_PHD.search(title)) and not OTHER_DEGREE.search(title)


def description_only(text):
    """The description states a PhD requirement and offers no other way in."""
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]*>', '\n', text)
    optional_section = required_section = False
    stated, other = False, False
    for block in re.split(r'[\n;\x1e]|(?<=[.!?])\s+(?=[A-Z])', text):
        block = block.strip(' \t-*•·')
        if not block:
            continue
        words = len(block.split())
        if words <= 7 and not _PHD.search(block):
            if OPTIONAL.search(block):
                optional_section, required_section = True, False
                continue
            if REQUIRED.search(block):
                optional_section, required_section = False, True
                continue
            if re.match(r'^(?:responsibilities|about\b|benefits\b|what you)', block, re.I):
                optional_section = required_section = False
        optional = optional_section or bool(OPTIONAL.search(block))
        if OTHER_DEGREE.search(block) and not optional:
            other = True
        if not _PHD.search(block) or optional or OTHER_DEGREE.search(block):
            continue
        if STATED.search(block) or (required_section and DEGREE_LINE.search(block)):
            stated = True
    return stated and not other


def phd_only(title, text):
    """Only a PhD will do, by the title or, failing that, the description."""
    if title_only(title):
        return True
    if _PHD.search(title or '') or OTHER_DEGREE.search(title or ''):
        # The title names degrees and a PhD is not the only one: it decides.
        return False
    return description_only(text)
