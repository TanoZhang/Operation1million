"""Shared employer aliases, separate from immutable requisition identity.

Only explicit aliases merge brands. Legal suffix removal is safe for matching;
substring/fuzzy matching would merge staffing firms with their clients.
"""
from functools import lru_cache
import html
import re
import unicodedata


SUFFIXES = {'inc', 'incorporated', 'corp', 'corporation', 'llc', 'ltd',
            'limited', 'co', 'company', 'plc'}
# Catalog names and confirmed brand aliases. Add aliases here, not in callers.
GROUPS = (
    ('Marvell', ('Marvell Technology', 'Marvell Technologies', '31 MSI - (Marvell Semi',
                '31 MSI - (Marvell Semiconductor, Inc.)',
                '31 MSI - (Marvell Semiconductor Inc.) US')),
    ('AMD', ('Advanced Micro Devices',)),
    ('Amazon', ('Amazon.com', 'Amazon.com Services', 'Amazon Web Services (AWS)', 'AWS', 'Annapurna Labs', 'Annapurna Labs (U.S.)')),
    ('Cadence', ('Cadence Design Systems',)),
    ('Cisco', ('Cisco Systems',)),
    ('Micron', ('Micron Technology',)),
    ('Intel', ('100 Intel Corporation', '500 Intel Ireland')), ('NVIDIA', ()), ('Qualcomm', ()), ('Broadcom', ()),
    ('Apple', ()), ('Google', ()), ('Microsoft', ()), ('Synopsys', ()),
    ('Altera', ()), ('Applied Materials', ()), ('KLA', ()),
    ('Lam Research', ()), ('Arm', ()), ('SanDisk', ()), ('SiFive', ()),
    ('Ambarella', ()), ('Anthropic', ()), ('Astera Labs', ('Asteralabs',)),
    ('Cerebras', ('Cerebras Systems',)), ('Credo', ('Credo Technology Group Holding', 'Credo Technology')),
    ('d-Matrix', ()), ('Etched', ('Etched.ai',)), ('GlobalFoundries', ()),
    ('Lattice Semiconductor', ()), ('Lightmatter', ()), ('MatX', ()), ('OpenAI', ()),
    ('NXP', ('NXP USA', 'NXP Semiconductors')), ('Quadric', ('quadric.io', 'quadric.ai')),
    ('Renesas', ('Renesas Electronics', 'Renesas Electronics America')),
    ('Rivos', ()), ('SambaNova', ('SambaNova Systems',)), ('Samsung Semiconductor', ()),
    ('Silicon Labs', ('Silicon Laboratories',)), ('SK hynix', ('SK hynix America',)),
    ('Tenstorrent', ()), ('Teradyne', ()), ('Texas Instruments', ()), ('xAI', ()),
    ('onsemi', ('ON Semiconductor',)), ('HPE', ('Hewlett Packard Enterprise',)),
    ('SpaceX', ('Space Exploration Technologies',)), ('Rocket Lab', ('Rocketlab', 'Rocket Lab USA')),
    ('Meta', ('Meta Careers', 'Meta Platforms')), ('ByteDance', ()), ('Qorvo', ()),
    ('NIKSUN', ()), ('General Motors', ()), ('Astranis', ('Astranis Space Technologies',)),
    ('Two Sigma', ('Two Sigma Investments',)), ('GE HealthCare', ()),
    ('IBM', ('International Business Machines',)),
    ('Skyworks', ('Skyworks Solutions',)), ('Zipline', ()),
    # Japan's chip boards (2026-10-11).
    ('EdgeCortix', ('EdgeCortix Inc.',)), ('Preferred Networks', ('PFN', 'Preferred Networks, Inc.')),
    ('TSMC', ('Taiwan Semiconductor Manufacturing Company', 'Taiwan Semiconductor Manufacturing',
              'TSMC Design Technology Japan')),
    ('Toshiba', ('株式会社東芝', 'Toshiba Electronic Devices & Storage', '東芝デバイス＆ストレージ')),
    ('Kioxia', ('キオクシア', 'KIOXIA Corporation')),
    ('Sony Semiconductor Manufacturing', ('ソニーセミコンダクタマニュファクチャリング',)),
    # Japan's big employers read directly (2026-10-23).
    ('Advantest', ('株式会社アドバンテスト', 'アドバンテスト', 'Advantest Corporation')),
    ('Tokyo Electron', ('東京エレクトロン株式会社', '東京エレクトロン', 'Tokyo Electron Limited')),
    ('Canon', ('キヤノン株式会社', 'キヤノン', 'Canon Inc.')),
    ('Kyocera', ('京セラ株式会社', '京セラ')), ('TDK', ('TDK株式会社',)),
    ('Seiko Epson', ('セイコーエプソン株式会社', 'セイコーエプソン')),
    ('Panasonic', ('パナソニック株式会社', 'パナソニック')),
    ('Sharp', ('シャープ株式会社', 'シャープ')),
    ('Horiba', ('株式会社堀場製作所', '堀場製作所')), ('Nidec', ('ニデック株式会社', 'ニデック')),
    ('Macnica', ('株式会社マクニカ', 'マクニカ')), ('ABLIC', ('エイブリック株式会社', 'エイブリック')),
    ('Konica Minolta', ('コニカミノルタ株式会社', 'コニカミノルタ')), ('Aisin', ('株式会社アイシン', 'アイシン')),
    ('TOPPAN', ('TOPPAN株式会社',)), ('Fuji Electric', ('富士電機株式会社', '富士電機')),
    ('Hitachi', ('株式会社日立製作所', '日立製作所')), ('Subaru', ('株式会社SUBARU',)),
    ('Infineon Technologies', ('Infineon',)), ('Analog Devices', ()),
    ('Microchip Technology', ('Microchip',)),
    # And those needing a reader of their own (2026-10-23).
    ('Mitsubishi Electric', ('三菱電機株式会社', '三菱電機')),
    ('NEC', ('日本電気株式会社', '日本電気', 'NEC Corporation')),
    ('MinebeaMitsumi', ('ミネベアミツミ株式会社', 'ミネベアミツミ')), ('Mazda', ('マツダ株式会社', 'マツダ')),
    ('Murata Manufacturing', ('株式会社村田製作所', '村田製作所', 'Murata')), ('JSR', ('JSR株式会社',)),
    ('ULVAC', ('株式会社アルバック', 'アルバック')), ('IBIDEN', ('イビデン株式会社', 'イビデン')),
    ('Honda', ('本田技研工業株式会社', '株式会社本田技術研究所', '本田技術研究所')),
    ('Denso', ('株式会社デンソー', 'デンソー')), ('Toyota', ('トヨタ自動車株式会社', 'トヨタ自動車')),
    ('Alps Alpine', ('アルプスアルパイン株式会社', 'アルプスアルパイン')),
    ('Nuvoton Technology Japan', ('ヌヴォトン テクノロジージャパン株式会社',)),
    ('NTT', ('日本電信電話株式会社',)), ('Ricoh', ('株式会社リコー', 'リコー')),
    ('KDDI', ('KDDI株式会社',)), ('Nikon', ('株式会社ニコン', 'ニコン')),
    ('Keyence', ('株式会社キーエンス', 'キーエンス')),
    ('Shinko Electric Industries', ('新光電気工業株式会社', '新光電気工業')),
    ('ROHM', ('ローム株式会社',)), ('Shimadzu', ('株式会社島津製作所', '島津製作所')),
    ('Sony Semiconductor Solutions', ('ソニーセミコンダクタソリューションズ株式会社',
                                      'Sony Semiconductor Solutions Corporation')),
    ('Sony Group', ('ソニーグループ株式会社', 'Sony Group Corporation')),
    ('Rapidus', ('Rapidus株式会社', 'ラピダス')),
    ('Astemo', ('Astemo株式会社',)), ('HOYA', ('HOYA株式会社',)),
    ('Omron Corporation', ('オムロン株式会社', 'Omron')), ('Ebara', ('株式会社荏原製作所', '荏原製作所', 'Ebara Corporation')),
    ('Hitachi Systems', ('株式会社日立システムズ', '日立システムズ')),
    ('ArkEdge Space', ('株式会社アークエッジ・スペース', 'アークエッジ・スペース')),
    ('Nintendo Systems', ('ニンテンドーシステムズ株式会社', 'ニンテンドーシステムズ')),
    ('Monolithic Power Systems', ('Monolithic Power Systems, Inc.', 'Monolithic Power')),
    ('Lumentum', ('Lumentum Operations', 'Lumentum Holdings')),
)


# Japanese legal designators, the 株式会社 of "Inc.", written before or after
# the name, joined to it or not: 「株式会社 アドバンテスト」 and 「株式会社アドバンテスト」
# were two employers (2026-10-23). NFKD has already made ㈱ and （株） "(株)".
JAPANESE_LEGAL = re.compile(r'株式会社|有限会社|合同会社|\((?:株|有)\)')


def _plain(value):
    text = unicodedata.normalize('NFKD', html.unescape(str(value or '')))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = JAPANESE_LEGAL.sub(' ', text)
    words = re.sub(r'[\W_]+', ' ', text.casefold()).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    return ' '.join(words)


def build_aliases(groups):
    result = {}
    for name, aliases in groups:
        for alias in (name, *aliases):
            key = _plain(alias)
            if key in result and result[key] != name:
                raise ValueError(f'Conflicting company alias: {alias}')
            result[key] = name
    return result


ALIASES = build_aliases(GROUPS)


@lru_cache(maxsize=4096)
def identity(name):
    plain = _plain(name)
    return _plain(ALIASES.get(plain, plain))


@lru_cache(maxsize=4096)
def display(name):
    """Stable public label; the original provider value remains in raw/ledger."""
    plain = _plain(name)
    if plain in ALIASES:
        return ALIASES[plain]
    # Preserve spelling and punctuation for unconfirmed brands.
    text = ' '.join(html.unescape(str(name or '')).split())
    suffix = r'[,\s]+(?:' + '|'.join(sorted(SUFFIXES)) + r')\.?\s*$'
    while True:
        shortened = re.sub(suffix, '', text, flags=re.I).rstrip(', ')
        if shortened == text:
            return text
        text = shortened


def label_group(group):
    """Normalize an in-memory group without mutating its stored job snapshots."""
    group['company'] = display(group.get('company'))
    group['jobs'] = [dict(job, company=display(job.get('company') or group['company']))
                     for job in group['jobs']]
    return group


def display_names(names):
    """One deterministic label per identity, including employers outside the catalog."""
    choices = {}
    for name in names:
        label = display(name)
        choices.setdefault(identity(name), set()).add(label)
    return {key: min(labels, key=lambda label: (
        label.isupper() or label.islower(), len(label), label.casefold(), label))
        for key, labels in choices.items()}


def label_queue(state):
    groups = [group for section in ('pending', 'backlog', 'applied', 'skipped')
              for group in state.get(section, ())]
    names = [group.get('company') for group in groups]
    names.extend(job.get('company') for group in groups for job in group['jobs']
                 if job.get('company'))
    labels = display_names(names)
    for group in groups:
        group['company'] = labels[identity(group.get('company'))]
        group['jobs'] = [dict(job, company=labels[identity(job.get('company') or group['company'])])
                         for job in group['jobs']]
    return state
