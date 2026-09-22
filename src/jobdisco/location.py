"""Whether a posting's stated location is in the United States.

Asked for on 2026-09-22: a posting located only outside the U.S. is not worth
reviewing, but one that is also offered in the U.S. is. So this answers three
ways, and only a confident "outside" removes anything: a blank location, "2
Locations", "Remote" or a place this does not recognise is unknown and kept.

Locations arrive in every format the boards use -- "US, WA, Seattle" and "IN,
KA, Bengaluru" (country code first), "Bangalore, India", "San Diego,
California, United States of America", Apple's "Location Cupertino", a bare
"Austin, Texas". A U.S. sign anywhere wins, so a multi-city string naming one
U.S. city is kept.
"""
import re

US_STATES = {
    'alabama': 'al', 'alaska': 'ak', 'arizona': 'az', 'arkansas': 'ar', 'california': 'ca',
    'colorado': 'co', 'connecticut': 'ct', 'delaware': 'de', 'florida': 'fl', 'georgia': 'ga',
    'hawaii': 'hi', 'idaho': 'id', 'illinois': 'il', 'indiana': 'in', 'iowa': 'ia',
    'kansas': 'ks', 'kentucky': 'ky', 'louisiana': 'la', 'maine': 'me', 'maryland': 'md',
    'massachusetts': 'ma', 'michigan': 'mi', 'minnesota': 'mn', 'mississippi': 'ms',
    'missouri': 'mo', 'montana': 'mt', 'nebraska': 'ne', 'nevada': 'nv', 'new hampshire': 'nh',
    'new jersey': 'nj', 'new mexico': 'nm', 'new york': 'ny', 'north carolina': 'nc',
    'north dakota': 'nd', 'ohio': 'oh', 'oklahoma': 'ok', 'oregon': 'or', 'pennsylvania': 'pa',
    'rhode island': 'ri', 'south carolina': 'sc', 'south dakota': 'sd', 'tennessee': 'tn',
    'texas': 'tx', 'utah': 'ut', 'vermont': 'vt', 'virginia': 'va', 'washington': 'wa',
    'west virginia': 'wv', 'wisconsin': 'wi', 'wyoming': 'wy', 'district of columbia': 'dc',
    'puerto rico': 'pr',
}

# Cities the boards name without a state -- Apple's "Location Cupertino" above
# all. Only places that are unambiguous; a name shared with somewhere abroad
# (Cambridge, Richmond) is left to the rest of the string.
US_CITIES = (
    'cupertino', 'sunnyvale', 'santa clara', 'san jose', 'san diego', 'san francisco',
    'san francisco bay area', 'mountain view', 'palo alto', 'milpitas', 'fremont', 'irvine',
    'los angeles', 'culver city', 'austin', 'dallas', 'houston', 'plano', 'richardson',
    'seattle', 'redmond', 'bellevue', 'kirkland', 'beaverton', 'hillsboro', 'portland',
    'boise', 'chandler', 'phoenix', 'tempe', 'folsom', 'rocklin', 'roseville', 'boston',
    'burlington', 'andover', 'westford', 'marlborough', 'new york city', 'nyc', 'boulder',
    'fort collins', 'colorado springs', 'denver', 'salt lake city', 'lehi', 'raleigh',
    'durham', 'research triangle park', 'morrisville', 'atlanta', 'chicago', 'minneapolis',
    'pittsburgh', 'ann arbor', 'detroit', 'albany', 'malta', 'east fishkill', 'poughkeepsie',
    'yorktown heights', 'huntsville', 'orlando', 'tampa', 'melbourne, fl', 'rochester, mn',
    'endicott', 'lexington', 'allentown', 'santa barbara', 'goleta', 'sacramento',
    'san mateo', 'redwood city', 'menlo park', 'los gatos', 'campbell', 'pleasanton',
    'livermore', 'hopkinton', 'nashua', 'manchester, nh', 'washington dc', 'washington, dc',
)

# Countries and the cities the boards name without a country. A name here only
# ever means the place abroad.
FOREIGN_COUNTRIES = (
    'india', 'china', 'taiwan', 'japan', 'singapore', 'korea', 'south korea', 'republic of korea',
    'germany', 'united kingdom', 'uk', 'england', 'scotland', 'wales', 'northern ireland',
    'ireland', 'israel', 'canada', 'mexico', 'malaysia', 'vietnam', 'viet nam', 'philippines',
    'thailand', 'indonesia', 'hong kong', 'macau', 'france', 'netherlands', 'the netherlands',
    'belgium', 'luxembourg', 'switzerland', 'austria', 'italy', 'spain', 'portugal', 'poland',
    'czech republic', 'czechia', 'slovakia', 'hungary', 'romania', 'bulgaria', 'serbia',
    'croatia', 'slovenia', 'greece', 'turkey', 'türkiye', 'ukraine', 'sweden', 'norway',
    'finland', 'denmark', 'iceland', 'estonia', 'latvia', 'lithuania', 'australia',
    'new zealand', 'brazil', 'argentina', 'chile', 'colombia', 'peru', 'costa rica',
    'uruguay', 'egypt', 'morocco', 'south africa', 'nigeria', 'kenya', 'united arab emirates',
    'uae', 'saudi arabia', 'qatar', 'pakistan', 'bangladesh', 'sri lanka', 'armenia',
    'belarus', 'russia', 'kazakhstan', 'jordan', 'tunisia',
)
FOREIGN_CITIES = (
    'bangalore', 'bengaluru', 'hyderabad', 'chennai', 'pune', 'noida', 'gurgaon', 'gurugram',
    'new delhi', 'delhi', 'mumbai', 'kolkata', 'ahmedabad', 'kochi', 'shanghai', 'beijing',
    'shenzhen', 'suzhou', 'nanjing', 'hangzhou', 'chengdu', 'wuhan', "xi'an", 'xian',
    'guangzhou', 'dalian', 'hefei', 'taipei', 'new taipei', 'hsinchu', 'taichung', 'tainan',
    'kaohsiung', 'zhubei', 'tokyo', 'osaka', 'yokohama', 'hiroshima', 'kyoto', 'nagoya',
    'kumamoto', 'seoul', 'suwon', 'hwaseong', 'pangyo', 'seongnam', 'icheon', 'munich',
    'münchen', 'dresden', 'berlin', 'nuremberg', 'nürnberg', 'stuttgart', 'hamburg',
    'frankfurt', 'regensburg', 'erlangen', 'aachen', 'london', 'cambridge, uk', 'bristol',
    'edinburgh', 'glasgow', 'reading, uk', 'manchester, uk', 'haifa', 'tel aviv', 'jerusalem',
    "petah tikva", 'herzliya', "ra'anana", 'raanana', 'yokneam', 'kiryat gat', 'toronto',
    'ottawa', 'vancouver', 'montreal', 'montréal', 'markham', 'waterloo, on', 'calgary',
    'guadalajara', 'penang', 'kuala lumpur', 'kulim', 'ho chi minh', 'hanoi', 'da nang',
    'manila', 'bangkok', 'paris', 'grenoble', 'sophia antipolis', 'eindhoven', 'nijmegen',
    'amsterdam', 'leuven', 'zurich', 'zürich', 'geneva', 'lausanne', 'villach', 'graz',
    'linz', 'vienna', 'milan', 'turin', 'catania', 'madrid', 'barcelona', 'krakow', 'kraków',
    'warsaw', 'gdansk', 'wroclaw', 'bucharest', 'iasi', 'timisoara', 'cluj', 'sofia',
    'belgrade', 'athens', 'istanbul', 'ankara', 'kyiv', 'stockholm', 'lund', 'gothenburg',
    'oslo', 'trondheim', 'helsinki', 'oulu', 'tampere', 'copenhagen', 'sydney', 'melbourne, australia',
    'dublin', 'cork', 'limerick', 'shannon', 'sao paulo', 'são paulo', 'campinas',
    'buenos aires', 'cairo', 'dubai', 'abu dhabi', 'yerevan', 'minsk', 'moscow',
    # Seen unplaced in the live queue on 2026-09-22.
    'gratkorn', 'caen', 'toulouse', 'belo horizonte', 'tianjin', 'chongqing', 'budapest',
    'brno', 'kanata', 'petah-tikva', 'burnaby', 'galway', 'madhapur', 'valbonne',
    'sophia-antipolis', 'lapu-lapu', 'cebu', 'alajuela', 'heredia', 'bayan lepas',
    'chachoengsao', 'jubei', 'turkiye',
)
# ISO 3166 codes that lead "IN, KA, Bengaluru"-style strings.
FOREIGN_CODES = {
    'in', 'cn', 'tw', 'jp', 'sg', 'kr', 'de', 'gb', 'uk', 'ie', 'il', 'ca', 'mx', 'my', 'vn',
    'ph', 'th', 'id', 'hk', 'fr', 'nl', 'be', 'ch', 'at', 'it', 'es', 'pt', 'pl', 'cz', 'sk',
    'hu', 'ro', 'bg', 'rs', 'hr', 'si', 'gr', 'tr', 'ua', 'se', 'no', 'fi', 'dk', 'ee', 'lv',
    'lt', 'au', 'nz', 'br', 'ar', 'cl', 'co', 'pe', 'cr', 'eg', 'ma', 'za', 'ae', 'sa', 'pk',
    'am', 'lu', 'is',
}


def _words(options):
    return re.compile(r'(?<![\w])(?:%s)(?![\w])' % '|'.join(
        re.escape(option) for option in sorted(options, key=len, reverse=True)), re.I)


_US_WORDS = re.compile(r'\b(?:united\s+states(?:\s+of\s+america)?|usa|u\.s\.a?\.?)(?![\w])', re.I)
_US_CITIES = _words(US_CITIES)
_FOREIGN = _words(FOREIGN_COUNTRIES + FOREIGN_CITIES)
_LEADING_CODE = re.compile(r'^\s*([a-z]{2})\s*,', re.I)


# Two-letter codes that are a U.S. state and a country at once. After a comma
# they settle nothing on their own: "Carmel, IN" is Indiana, "Bengaluru, IN" is
# India, and the place named beside the code decides.
AMBIGUOUS_CODES = {'in', 'ca', 'co', 'de', 'id', 'il', 'ma', 'ar', 'ga', 'pa', 'sc', 'mt', 'al'}


def country(location):
    """'us', 'foreign', or None when the string does not say."""
    text = re.sub(r'^\s*locations?\s+', '', str(location or ''), flags=re.I).strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(',') if part.strip()]
    codes = [part.lower() for part in parts if re.fullmatch(r'[A-Za-z]{2}', part)]
    foreign = bool(_FOREIGN.search(text))
    # The plain statements of a U.S. place win outright: the country, a state
    # written out, a U.S. city. "Dublin, California" is not Ireland.
    if (_US_WORDS.search(text) or re.match(r'^\s*US\b', text) or 'us' in codes
            or any(part.lower() in US_STATES for part in parts) or _US_CITIES.search(text)):
        return 'us'
    state_codes = [code for code in codes if code in US_STATES.values()]
    # A state code that is not also a country code settles it: "Paris, TX" and
    # "London, KY" are in the U.S. whatever the city is called.
    if any(code not in AMBIGUOUS_CODES for code in state_codes):
        return 'us'
    if foreign or any(code in FOREIGN_CODES and code not in AMBIGUOUS_CODES for code in codes):
        return 'foreign'
    # "IN, KA, Bengaluru": a leading ambiguous code followed by a region code is
    # a country, not a state -- a state is never written first.
    lead = _LEADING_CODE.match(text)
    if lead and lead.group(1).lower() in FOREIGN_CODES and len(parts) >= 2:
        return 'foreign'
    if state_codes:
        return 'us'
    return None


def outside_us(location):
    """Only a location this can place abroad, and nowhere in the U.S."""
    return country(location) == 'foreign'
