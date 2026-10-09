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
import unicodedata

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
US_STATE_CODES = frozenset(US_STATES.values())

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
    # Regions the boards name instead of a city (2026-09-27).
    'bay area', 'silicon valley', 'dfw', 'dallas-fort worth', 'dallas fort worth',
    'research triangle', 'twin cities',
    # Semiconductor sites found unplaced on 2026-09-27.
    'boxborough', 'hudson, ma', 'manassas', 'tucson', 'sherman, tx', 'taylor, tx',
    'essex junction', 'bothell', 'everett', 'mesa, az', 'scottsdale', 'san ramon',
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
    # Regions wholly abroad (2026-09-27). Not "Americas", which holds the U.S.
    'apac', 'emea', 'asia pacific', 'europe',
    # Missing until 2026-09-27; "Valletta, Malta" read as Malta, NY. A U.S.
    # town of the same name keeps its state: "Malta, NY", "Panama City, FL".
    'malta', 'ecuador', 'panama', 'nepal', 'cyprus', 'moldova', 'iran', 'albania',
    'azerbaijan', 'uzbekistan', 'myanmar', 'macao', 'bosnia and herzegovina', 'montenegro',
    'north macedonia', 'guatemala', 'venezuela', 'bolivia', 'paraguay', 'dominican republic',
    'cambodia', 'laos', 'mongolia', 'iraq', 'lebanon', 'kuwait', 'bahrain', 'oman', 'ghana',
    'ethiopia', 'rwanda', 'uganda', 'tanzania', 'algeria', 'senegal', 'brunei',
    # "Palestine, Rawabi" (2026-10-02); "Palestine, TX" keeps its state.
    'palestine',
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
    # Semiconductor sites found unplaced on 2026-09-27, and the unaccented
    # forms of the accented names above (places are read without accents).
    'pyeongtaek', 'giheung', 'hwaseong-si', 'taoyuan', 'wuxi', 'xiamen', 'cyberjaya',
    'rousset', 'crolles', 'munchen', 'nurnberg', 'zurich',
    # Unplaced in the live queue on 2026-10-02 (#262).
    'saclay', 'sibiu', 'espoo', 'rawabi',
)
# ISO 3166 codes that lead "IN, KA, Bengaluru"-style strings.
FOREIGN_CODES = {
    'in', 'cn', 'tw', 'jp', 'sg', 'kr', 'de', 'gb', 'uk', 'ie', 'il', 'ca', 'mx', 'my', 'vn',
    'ph', 'th', 'id', 'hk', 'fr', 'nl', 'be', 'ch', 'at', 'it', 'es', 'pt', 'pl', 'cz', 'sk',
    'hu', 'ro', 'bg', 'rs', 'hr', 'si', 'gr', 'tr', 'ua', 'se', 'no', 'fi', 'dk', 'ee', 'lv',
    'lt', 'au', 'nz', 'br', 'ar', 'cl', 'co', 'pe', 'cr', 'eg', 'ma', 'za', 'ae', 'sa', 'pk',
    'am', 'lu', 'is',
}
# Every other ISO 3166 country code, except those that are also a U.S. state
# code: Amazon writes "NG, Lagos", "BH, Manama", "JO, Amman", and those postings
# abroad were unplaced and kept (live index, 2026-09-27). Codes shared with a
# state (GA, PA, MT, AL, ...) stay out, as "Athens, GA" requires.
_ISO_CODES = set('''
    ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br
    bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz
    ec ee eg eh er es et fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw
    gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky
    kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv
    mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py
    qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg
    th tj tk tl tm tn to tr tt tv tw tz ua ug um uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw
'''.split())
FOREIGN_CODES |= _ISO_CODES - US_STATE_CODES - {'us', 'um', 'vi', 'as', 'gu', 'mp', 'pr'}


# Canada's provinces, which a board writes where a U.S. board writes a state.
# Without them "Burlington, ON" was the Vermont Burlington, because the city is
# on the U.S. list and "ON" is no state. Read only after a city, never as the
# first part: "Ontario, CA" is also a city in California.
CANADIAN_PROVINCES = (
    'ontario', 'quebec', 'québec', 'british columbia', 'alberta', 'manitoba',
    'saskatchewan', 'nova scotia', 'new brunswick', 'newfoundland',
    'newfoundland and labrador', 'prince edward island',
)
CANADIAN_PROVINCE_CODES = {'on', 'qc', 'bc', 'ab', 'mb', 'sk', 'ns', 'nb', 'nl', 'pe', 'nt', 'nu', 'yt'}

# The places abroad above, for the countries whose ISO code is also a U.S.
# state code. "Bengaluru, IN" is India because Bengaluru is; "Dublin, CA" is
# Dublin, California, because Dublin is not in Canada, and "Moscow, ID" is
# Idaho for the same reason. A city not listed here beside such a code is read
# as the state, which keeps the posting -- the side this module errs on.
CODE_CITIES = {
    'in': {'bangalore', 'bengaluru', 'hyderabad', 'chennai', 'pune', 'noida', 'gurgaon',
           'gurugram', 'new delhi', 'delhi', 'mumbai', 'kolkata', 'ahmedabad', 'kochi',
           'madhapur'},
    'ca': {'toronto', 'ottawa', 'vancouver', 'montreal', 'montréal', 'markham', 'waterloo, on',
           'calgary', 'kanata', 'burnaby'},
    'de': {'munich', 'münchen', 'dresden', 'berlin', 'nuremberg', 'nürnberg', 'stuttgart',
           'hamburg', 'frankfurt', 'regensburg', 'erlangen', 'aachen'},
    'il': {'haifa', 'tel aviv', 'jerusalem', 'petah tikva', 'petah-tikva', 'herzliya',
           "ra'anana", 'raanana', 'yokneam', 'kiryat gat'},
    'ar': {'buenos aires'},
}


def _unaccented(text):
    return ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))


# Read the way the place is read, without accents: "DE, München" became
# "Munchen", which the accented entry no longer matched, and read as Delaware
# -- a regression from the accent fix (#88), found on the live queue.
CODE_CITIES = {code: {_unaccented(city) for city in cities} for code, cities in CODE_CITIES.items()}


def _words(options):
    return re.compile(r'(?<![\w])(?:%s)(?![\w])' % '|'.join(
        re.escape(option) for option in sorted(options, key=len, reverse=True)), re.I)


# "US" in capitals, anywhere: "Remote - US" and "Remote (US)" were unplaced, and
# beside a place abroad the posting read as abroad only (2026-09-27). Lower
# case is the pronoun.
_US_WORDS = re.compile(r'\b(?:united\s+states(?:\s+of\s+america)?|usa|u\.s\.a?\.?|(?-i:US))(?![\w])', re.I)
# "Albuquerque, New Mexico 87101": a ZIP code after the state, which made the
# part no state name and left "Mexico" to be read as the country.
_ZIP = re.compile(r'\s+\d{5}(?:-\d{4})?$')
_US_CITIES = _words(US_CITIES)
_FOREIGN_COUNTRIES = _words(FOREIGN_COUNTRIES)
_FOREIGN_CITIES = _words(FOREIGN_CITIES)
_PROVINCES = _words(CANADIAN_PROVINCES)
_LEADING_CODE = re.compile(r'^\s*([a-z]{2})\s*,', re.I)
# A part that is a two-letter code, and a region after a leading country code.
_CODE = re.compile(r'[A-Za-z]{2}')
_REGION = re.compile(r'[A-Za-z]{2,3}')


# Two-letter codes that are a U.S. state and a country at once. After a comma
# they settle nothing on their own: "Carmel, IN" is Indiana, "Bengaluru, IN" is
# India, and the place named beside the code decides. Only the codes this module
# reads as a country: GA, PA, SC, MT and AL were listed too, though no country
# here is written that way, and "Athens, GA" was read as Greece.
AMBIGUOUS_CODES = FOREIGN_CODES & US_STATE_CODES


def _place(text):
    """One place, in the order the plainer statement wins.

    A country written out beats a city name: "Burlington, Canada" is the
    Canadian one, however many Burlingtons the U.S. has.
    """
    parts = [_ZIP.sub('', part.strip()) for part in text.split(',') if part.strip()]
    codes = [part.lower() for part in parts if _CODE.fullmatch(part)]
    state_codes = [code for code in codes if code in US_STATE_CODES]
    if (_US_WORDS.search(text) or re.match(r'^\s*US\b', text) or 'us' in codes
            or any(part.lower() in US_STATES for part in parts)):
        return 'us'
    # The country written first, then a region: "IN, TN, Chennai", "IT, MI,
    # Milan". The region is often also a state code (Tamil Nadu, Milano), and
    # 52 queued postings in Chennai read as Tennessee (live queue, 2026-09-27).
    # A U.S. place never opens with two codes in a row.
    if (len(parts) >= 3 and _CODE.fullmatch(parts[0]) and _REGION.fullmatch(parts[1])
            and parts[0].lower() in FOREIGN_CODES):
        return 'foreign'
    countries = list(_FOREIGN_COUNTRIES.finditer(text))
    # A country's name inside the town, with a state after it, is the town:
    # "West Jordan, UT", "Poland, OH", "Mexico, MO", "Peru, IN" (2026-09-27).
    # Written after the city it is the country: "Perth, WA, Australia".
    town = len(parts) > 1 and state_codes and all(
        found.end() <= text.index(',') for found in countries)
    # A bare name that is also a U.S. site is that site: "Malta" is
    # GlobalFoundries' Malta, NY, and #119 had read it as the country.
    if countries and not town and not (len(parts) == 1 and _US_CITIES.fullmatch(parts[0])):
        return 'foreign'
    # A state code that is not also a country code settles it: "Paris, TX" and
    # "London, KY" are in the U.S. whatever the city is called.
    if any(code not in AMBIGUOUS_CODES for code in state_codes):
        return 'us'
    region = parts[1:]
    if (any(part.lower() in CANADIAN_PROVINCE_CODES for part in region)
            or any(_PROVINCES.fullmatch(part) for part in region)):
        return 'foreign'
    if _US_CITIES.search(text):
        return 'us'
    city = _FOREIGN_CITIES.search(text)
    if (city and state_codes
            and not any(code in FOREIGN_CODES and code not in AMBIGUOUS_CODES for code in codes)
            and not any(city.group(0).lower() in CODE_CITIES.get(code, ()) for code in state_codes)):
        # A city abroad beside a code that is also a state, in a country the
        # code does not name: the code is the state.
        return 'us'
    if city or any(
            code in FOREIGN_CODES and code not in AMBIGUOUS_CODES for code in codes):
        return 'foreign'
    # "IN, KA, Bengaluru": a leading ambiguous code followed by a region code is
    # a country, not a state -- a state is never written first.
    lead = _LEADING_CODE.match(text)
    if lead and lead.group(1).lower() in FOREIGN_CODES and len(parts) >= 2:
        return 'foreign'
    if state_codes:
        return 'us'
    return None


def country(location):
    """'us', 'foreign', or None when the string does not say.

    A posting may list several places, and the separator between them is a
    semicolon while the separator inside one is a comma. Reading the whole
    string at once made the answer depend on their order: "Salem, Oregon;
    Toronto, Canada" read as abroad because "Oregon; Toronto" is no state,
    while the same two places the other way round read as U.S. Each place is
    now read on its own, and one U.S. place keeps the posting.
    """
    text = re.sub(r'^\s*locations?\s+', '', str(location or ''), flags=re.I).strip()
    # Without accents: "Gdańsk", "Timișoara" and "Iași" did not match the
    # names listed without them (2026-09-27).
    text = _unaccented(text)
    if not text:
        return None
    # "Austin, TX & Toronto, ON" as well (2026-09-27), but only between places
    # that each have their own comma: "Toronto and Ottawa, Canada" is one.
    parts = re.split(r'\s*[;|\u2022]\s*|\s+/\s+', text)
    parts = [piece for part in parts
             for piece in (re.split(r'\s+(?:&|and)\s+(?=[^,]+,)', part) if part.count(',') >= 2 else [part])]
    found = [_place(part) for part in parts if part.strip()]
    if 'us' in found:
        return 'us'
    return 'foreign' if 'foreign' in found else None


def outside_us(location):
    """Only a location this can place abroad, and nowhere in the U.S."""
    return country(location) == 'foreign'


# Abroad but wanted (the user, 2026-10-08): Japan, China with Hong Kong and
# Macau, and Taiwan. The cities are the ones FOREIGN_CITIES lists there.
ALLOWED_ABROAD = (
    'japan', 'china', "people's republic of china", 'taiwan', 'hong kong', 'macau', 'macao',
    'tokyo', 'osaka', 'yokohama', 'hiroshima', 'kyoto', 'nagoya', 'kumamoto',
    'shanghai', 'beijing', 'shenzhen', 'suzhou', 'nanjing', 'hangzhou', 'chengdu', 'wuhan',
    "xi'an", 'xian', 'guangzhou', 'dalian', 'hefei', 'tianjin', 'chongqing', 'wuxi', 'xiamen',
    'taipei', 'new taipei', 'hsinchu', 'taichung', 'tainan', 'kaohsiung', 'zhubei', 'jubei', 'taoyuan',
)
# Not "mo" for Macau: it is Missouri.
ALLOWED_CODES = {'jp', 'cn', 'tw', 'hk'}
_ALLOWED = _words(ALLOWED_ABROAD)


def _allowed_part(text):
    return bool(_ALLOWED.search(text)) or any(
        part.strip().lower() in ALLOWED_CODES for part in text.split(','))


def outside_allowed(location):
    """Placed abroad, and in none of the U.S., Japan, China or Taiwan.

    Asked for on 2026-10-08; before it, everything abroad left the queue
    (`outside_us`, 2026-09-22). One allowed place keeps a posting, as one U.S.
    place does, and a place this cannot read is kept.
    """
    if not outside_us(location):
        return False
    text = _unaccented(str(location or ''))
    return not any(_allowed_part(part) for part in re.split(r'\s*[;|•]\s*|\s+/\s+', text) if part.strip())
