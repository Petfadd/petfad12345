"""Visual plan: choose, for every line of narration, a picture that shows what is said.

Why this exists
  A production script that gives one source window per narration beat holds the same
  clip for 30-45 seconds while the narrator moves through several subjects, so the
  picture drifts away from the words. This planner works line by line (2-6 s), and it
  can only match what it knows, so it first builds a catalogue of what every shot
  shows, from everything the project already has:

    * an editing guide's cards ("Show: the railroad track seen low" for S49 1:10-1:14)
      and its base-picture table -- descriptions written by someone who looked;
    * a hand-checked b-roll catalogue (data/broll_catalog.json) for the same files;
    * local analysis reports (vision descriptions of sampled frames, and what the
      reporter says over each scene) where "Analyse locally" has been run;
    * the production script's own visual directions for each beat;
    * People-on-screen photos.

How a line is matched
  The line's subjects (who, where, what, when) are scored against every unused shot.
  A shot must score at least MATCH to count. The rules are hard: no suspect picture
  under a victim or family line, no suspect picture before the narration first names
  the suspect, no person, speaker or courtroom picture dated after the events being
  told, no talking head unless that person is the subject, no frame used twice. When
  nothing matches, the fallback order is fixed: a moving base clip of the right kind
  (places, police), the named person's photo, a base still, the script's own choice,
  and only then the best weak option, which is flagged. Stills are capped (10% of
  the film by default). Sound bites are copied from the script unchanged.

The result is a Beat production script (the format the editor already builds and
renders) plus a reason for every choice. Nothing is applied until the user says so,
and nothing here certifies who or what a picture shows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MATCH = 4            # a shot must score this much to count as a real match
MIN_PIECE_MS = 1200  # shorter picture changes read as flashes
MIN_UNIT_MS = 2000   # narration is matched in units of at least this length
MAX_PIECES = 3       # pictures per unit before it is just the best one held
REPEAT_WINDOW_MS = 20000
STILL_CAP = 0.20     # photos (victim, suspect, family) as a share of the film
PHOTO_RUN_MS = 8000  # longest one photo stays up while the narration stays on that person
# Subjects too general to count as a new idea on their own.
WEAK_GROUPS = {'family', 'phone', 'car', 'nature'}
_PRONOUN = re.compile(r"\b(?:she|he|her|his|him|hers|they|their|them)\b", re.I)
HOLD_GAP_MS = 1000

# ---------------------------------------------------------------------- vocabulary
# Subject groups. A line and a shot that share a group are about the same thing.
GROUPS = {
    'track': r'track|tracks|railroad|railway|rail|rails|ballast|train|trains',
    'water': r'bayou|bayous|water|creek|river|stream|lake|pond|canal|drain|culvert|spillway|flood|floated|pool|beach|sea|ocean',
    'police': r'police|officer|officers|cop|cops|patrol|squad|deputy|deputies|detective|detectives|marshal|marshals|'
              r'tpd|hpd|precinct|badge|cruiser|helicopter|sheriff|investigators?|crime ?stoppers',
    'court': r'court|courtroom|courthouse|judge|trial|jury|jurors|bench|lectern|hearing|sentencing|sentenced|sentence|'
             r'verdict|defense|prosecutors?|attorney|plea|pleaded|guilty|testif\w*|bond',
    'custody': r'detention|jail|custody|inmate|escape|escaped|escaping|razor|fence|gate|padlock|transfer\w*|juvenile|'
               r'booking|arrest|arrested|charged|charges',
    'memorial': r'vigil|memorial|balloons?|teddy|candles?|flowers|prayers?|pray\w*|mourn\w*|banners?',
    'search': r'search\w*|volunteers?|k-?9|dog|dogs|missing|amber',
    'home': r'apartment|apartments|complex|playground|home|house|houses|neighbou?rhood|neighbou?rs?|stairs|doorway|door',
    'street': r'street|streets|road|roads|block|boulevard|blvd|avenue|ave|sign|signs|corner|intersection|markers?|dead ?end',
    'news_conf': r'podium|news conference|press conference|microphones?|chief|briefing|announce\w*',
    'family': r'mother|mom|mama|father|dad|grandfather|grandmother|grandma|granddaughter|grandson|family|relatives?|'
              r'son|daughter|aunt|uncle|brother|sister|nana|wife|husband|cousin|niece|nephew|'
              r'step(?:father|mother|dad|mom|son|daughter|brother|sister)|half[- ]?(?:brother|sister)',
    'school': r'school|classmates?|students?|teacher',
    'phone': r'phone|phones|call|called|911|message|messages|text|social media|instagram|facebook|google|search history',
    'weapon': r'gun|guns|weapon|weapons|shot|shooting|shots|bullet|firearm',
    'car': r'car|cars|vehicle|vehicles|suv|van|vans|truck',
    'nature': r'trees?|brush|grass|woods|palmetto|leaves|sky|field',
}
_GROUP_RE = {g: re.compile(r'\b(?:' + p + r')\b', re.I) for g, p in GROUPS.items()}
STOP = set('''a an the and or but if then than that this these those there here is are was were be been being of in on at
to for from by with without into onto over under about after before during while as it its he she they them his her
their him we you your i me my our us not no nor so too very can could would should will shall may might must do does
did done has have had having just also only even still yet again one two three four five six seven eight nine ten
says said say tell tells told asks asked according reports reported report times story video shows show seen see
footage picture pictures photo photos image images clip clips window approximate checked still frames frame later
news pictures event itself station banner reads actual care same another other first last next then'''.split())
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_YEAR = re.compile(r'\b(19[89]\d|20[0-4]\d)\b')
_NO_PEOPLE = re.compile(r'\bno people\b|\bnobody\b|\bno one is shown\b|\bnobody is shown\b|\bpeople only\b', re.I)
_MUGSHOT = re.compile(r'\bmug ?shots?\b|\bbooking photos?\b|\bbooked\b', re.I)
_ARREST = re.compile(r'\barrest(?:ed|s)?\b|\bcharged\b|\bbooked\b|\bin custody\b|\bturned (?:himself|herself) in\b', re.I)
_NAME = re.compile(r'\b([A-Z][a-z]+(?:\s+(?:[A-Z]\.|[A-Z][a-z]+))+)\b')
# Capitalised words that are never somebody's name. No city, state or case-specific
# place is listed: a capitalised run that ends in a place or organisation word ("Sunset
# Crossing Apartments", "Harris County", "Houston Police Department", "Tampa Bay") is
# recognised as a place by _PLACE_END instead, so this works for any production.
_NOT_NAME_WORDS = {'News', 'Police', 'Department', 'County', 'Street', 'Avenue', 'Road', 'Center', 'Centre',
                   'Regional', 'Juvenile', 'Detention', 'Justice', 'State', 'Attorney', 'Office', 'Task', 'Force',
                   'Times', 'Channel', 'Courtesy', 'Crime', 'Stoppers', 'Welcome', 'Chief', 'Deputy', 'Major',
                   'Officer', 'Judge', 'Detective', 'Sergeant', 'Lieutenant', 'Captain', 'Mr', 'Mrs', 'Ms', 'Dr',
                   'Amber', 'Alert', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                   'September', 'October', 'November', 'December', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday', 'Sunday', 'The', 'His', 'Her', 'A', 'North', 'South', 'East', 'West',
                   'Northwest', 'Northeast', 'Southwest', 'Southeast', 'Downtown', 'Breaking', 'Live', 'Update'}
_PLACE_END = {'County', 'Street', 'St', 'Avenue', 'Ave', 'Road', 'Rd', 'Boulevard', 'Blvd', 'Drive', 'Lane', 'Way',
              'Court', 'Place', 'Plaza', 'Square', 'Parkway', 'Highway', 'Freeway', 'Trail', 'Park', 'Bayou', 'River',
              'Creek', 'Lake', 'Bay', 'Beach', 'Island', 'Valley', 'Heights', 'Hills', 'Village', 'Estates', 'City',
              'Town', 'Township', 'Parish', 'Department', 'Office', 'News', 'Times', 'Channel', 'Network', 'Station',
              'University', 'College', 'School', 'Academy', 'Elementary', 'High', 'Hospital', 'Center', 'Centre',
              'Church', 'Apartments', 'Apartment', 'Complex', 'Crossing', 'Mall', 'Bridge', 'Airport', 'Courthouse',
              'Jail', 'Prison', 'Stoppers', 'Force', 'Alert', 'Search', 'Patrol', 'Sheriff', 'Police'}
_TITLES = {'Chief', 'Deputy', 'Major', 'Officer', 'Judge', 'Detective', 'Sergeant', 'Lieutenant', 'Captain',
           'Mr', 'Mrs', 'Ms', 'Dr', 'Attorney', 'Prosecutor', 'Sheriff'}


def _stem(word):
    w = word.lower().strip("'-")
    w = re.sub(r"'s$", '', w)
    for suffix in ('ing', 'ed', 'es', 's'):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def tokens(text):
    return {_stem(w) for w in _WORD.findall(text or '') if w.lower() not in STOP and len(w) > 2}


def narration_tokens(text):
    """Words of a narration line, plus each pair of neighbouring words joined: an SRT
    writes "Beach Nut Street" where the description says "Beechnut"."""
    words = [w for w in _WORD.findall(text or '') if len(w) > 1]
    joined = {_stem(a + b) for a, b in zip(words, words[1:]) if len(a + b) >= 6}
    return tokens(text) | joined


def _near(a, b):
    """Two long words one letter apart (beachnut / beechnut); short words must match exactly."""
    if a == b:
        return True
    if min(len(a), len(b)) < 6 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def shared_words(narration, item_tokens):
    exact = narration & item_tokens
    fuzzy = {t for t in item_tokens - exact if any(_near(t, n) for n in narration)}
    return exact | fuzzy


def groups_in(text):
    return {g for g, rx in _GROUP_RE.items() if rx.search(text or '')}


def years_in(text):
    return [int(y) for y in _YEAR.findall(text or '')]


def surnames(text):
    """Surnames of the people a description names ("Chief Bercaw", "Michael Baldwin Sr.")."""
    found = set()
    for match in _NAME.finditer(text or ''):
        words = [w.rstrip('.') for w in match.group(1).split()]
        if words[-1] in _PLACE_END:
            continue                          # a place or an organisation, not a person
        real = [w for w in words if w not in _NOT_NAME_WORDS and len(w) > 2]
        if not real:
            continue
        if words[0] in _TITLES or len(real) >= 2:
            found.add(real[-1] if real[-1] not in ('Sr', 'Jr') else real[-2] if len(real) > 1 else real[-1])
    return found


def classify(text):
    """What kind of picture a description is: photo, speaker, graphic, people, place or unknown."""
    t = text or ''
    if re.search(r'\b(?:photos?|photographs?|booking photos?|mug ?shots?|selfies?|portraits?)\b', t, re.I):
        return 'photo'
    if re.search(r'\b(?:podium|lectern|speaking|interview|video call|news conference|press conference|on camera|'
                 r'addresses|addressing|statement|testif\w*)\b', t, re.I) and not _NO_PEOPLE.search(t):
        return 'speaker'
    if re.search(r'\b(?:map|graphic|screen that lists|on-screen text|title card)\b', t, re.I):
        return 'graphic'
    people = re.search(r'\b(?:officers?|people|crowd|family|relatives|volunteers|searchers|deputy|deputies|man|woman|'
                       r'boy|girl|walkers?|neighbou?rs|figure|mother|father|grandfather|grandmother|teen|teenagers?)\b', t, re.I)
    if people and not _NO_PEOPLE.search(t):
        return 'people'
    if groups_in(t) & {'track', 'water', 'street', 'home', 'custody', 'court', 'memorial', 'police', 'car', 'nature',
                       'school'} or re.search(r'\b(?:building|wall|car park|parking|sign|flags?|wire)\b', t, re.I):
        return 'place'
    return 'unknown'


def ms(clock):
    h, m, rest = clock.strip().split(':')
    s, frac = re.split(r'[,.]', rest)
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int((frac + '000')[:3])


def clock(value):
    value = max(0, int(round(value)))
    h, rem = divmod(value, 3600000)
    m, rem = divmod(rem, 60000)
    s, f = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{f:03d}'


def _mmss(text):
    """'1:27' or '1:27.5' or '0:08' -> ms."""
    parts = text.strip().split(':')
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return int(round(total * 1000))


# ---------------------------------------------------------------------- card guide

def is_card_guide(text):
    return bool(re.search(r'^###\s+\d+\.\s+Narration beat\s*$', text or '', re.M)) and '**Your timing:**' in (text or '')


def parse_card_guide(text):
    """Read an editing guide written as cards ("### 12. Narration beat")."""
    setup = {}
    for key in ('Victim', 'Suspect', 'Case'):
        m = re.search(r'^-\s*' + key + r':\s*(.+)$', text, re.M)
        if m:
            setup[key.lower()] = m.group(1).strip()
    cards = []
    pattern = re.compile(r'^###\s+(\d+)\.\s+Narration beat\s*$(.*?)(?=^###\s|^##\s|\Z)', re.M | re.S)
    for m in pattern.finditer(text):
        body = m.group(2)

        def field(name):
            f = re.search(r'^\*\*' + re.escape(name) + r':\*\*\s*(.+)$', body, re.M)
            return f.group(1).strip() if f else ''
        timing = re.search(r'`(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})`', field('Your timing'))
        if not timing:
            continue
        card = {'number': int(m.group(1)), 'at': field('At').strip('“”"'), 'show': field('Show'), 'care': field('Care'),
                'label': field('Label'), 'fill': field('Fill'), 'source_id': field('Source ID'),
                'start_ms': ms(timing.group(1)), 'end_ms': ms(timing.group(2)), 'window': None}
        preview = field('Preview')
        win = re.search(r'~\s*(\d+:\d{2}(?:\.\d+)?)\s*[–-]\s*(\d+:\d{2}(?:\.\d+)?)', preview)
        if win and card['source_id']:
            card['window'] = (_mmss(win.group(1)), _mmss(win.group(2)))
        year = years_in(card['label'])
        card['year'] = year[-1] if year else None
        cards.append(card)
    base = []
    table = re.search(r'^##\s+Base clips\s*$(.*?)(?=^##\s|\Z)', text, re.M | re.S)
    if table:
        for row in table.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip('|').split('|')]
            if len(cells) < 4 or not cells[0].startswith('`BASE-'):
                continue
            name = cells[0].strip('`')
            where = cells[2]
            src = re.search(r'`(S\d+)`', where)
            at = re.search(r'(?:frame at|at about)\s*(\d+:\d{2}(?:\.\d+)?)', where)
            cat = re.match(r'BASE-([VSC])--', name)
            if not (src and at and cat):
                continue
            tag = cells[3].strip('`')
            years = [int(y) for y in re.findall(r'20\d\d', tag)]
            base.append({'name': name, 'what': cells[1], 'file': src.group(1) + '.mp4', 'at_ms': _mmss(at.group(1)),
                         'category': cat.group(1), 'tags': set(re.split(r'[+]', tag)) | {tag},
                         'year': years[-1] if years else None, 'approximate': 'about' in where})
    return {'setup': setup, 'cards': cards, 'base': base}


def parse_fill(text):
    """'S / court+2026 / !custody' -> {'category': 'S', 'tags': {'court', '2026'}, 'exclude': {'custody'}}."""
    if not text:
        return None
    parts = [p.strip() for p in text.split('/')]
    cat = parts[0][:1].upper() if parts and parts[0] else None
    tags, exclude = set(), set()
    for p in parts[1:]:
        if p.startswith('!'):
            exclude |= set(p[1:].split('+'))
        elif p:
            tags |= set(p.split('+'))
    return {'category': cat if cat in ('V', 'S', 'C') else None, 'tags': tags, 'exclude': exclude}


# ---------------------------------------------------------------------- people

def people_roles(project, guide=None):
    """Everyone the narration may name, with a role: victim, suspect, family or other."""
    from person_overlays import terms_for, ensure_ids
    people = ensure_ids(list(project.get('people') or []))
    result = []
    setup = (guide or {}).get('setup', {})
    for p in people:
        role_text = (p.get('role') or '').lower()
        role = ('victim' if 'victim' in role_text else
                'suspect' if re.search(r'suspect|accused|defendant|killer|convicted', role_text) else
                'family' if _GROUP_RE['family'].search(role_text) else 'other')   # whole words: not "person"/"Thompson"
        if setup.get('victim', '').casefold() == p.get('name', '').casefold():
            role = 'victim'
        if setup.get('suspect', '').casefold() == p.get('name', '').casefold():
            role = 'suspect'
        result.append({'id': p['id'], 'name': p.get('name', ''), 'role': role, 'terms': terms_for(p, people),
                       'photo': (p.get('photo') or {}).get('path'), 'person': p})
    names = {r['name'].casefold() for r in result}
    for key in ('victim', 'suspect'):
        name = setup.get(key)
        if name and name.casefold() not in names:
            parts = name.split()
            terms = [name] + ([parts[0], parts[-1]] if len(parts) > 1 else [])
            result.append({'id': key, 'name': name, 'role': key, 'terms': terms, 'photo': None, 'person': None})
    for r in result:
        r['regex'] = re.compile(r'(?<![\w])(?:' + '|'.join(r'\s+'.join(map(re.escape, t.split())) for t in r['terms']
                                                          if t) + r")(?![\w])", re.I) if r['terms'] else None
    return result


def people_in(text, roles):
    return {r['id'] for r in roles if r['regex'] and r['regex'].search(text or '')}


# ---------------------------------------------------------------------- shots

def shot_bounds(root, path, at_ms, reach_ms=6000):
    """(start, end) ms of the shot that contains `at_ms`, from the picture itself.

    FFmpeg's scene score finds the cuts in a few seconds either side; the result is
    cached per file. Returns None when the file cannot be read.
    """
    import subprocess, imageio_ffmpeg
    cache_path = Path(root) / 'reviews' / 'shot_bounds.json'
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    stat = Path(path).stat()
    key = f'{Path(path).name}|{stat.st_size}|{int(stat.st_mtime)}|{at_ms}'
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    start = max(0, at_ms - reach_ms)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostats', '-ss', f'{start/1000:.3f}', '-t',
           f'{2*reach_ms/1000:.3f}', '-i', str(path), '-an', '-vf', "scale=160:-2,select='gt(scene,0.30)',showinfo",
           '-f', 'null', '-']
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        cuts = [start + int(float(m) * 1000) for m in re.findall(r'pts_time:([0-9.]+)', run.stderr)]
        before = max([c for c in cuts if c <= at_ms] or [start])
        after = min([c for c in cuts if c > at_ms] or [at_ms + reach_ms])
        result = (before, after) if run.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        result = None
    cache[key] = list(result) if result else None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache), encoding='utf-8')
    return result


# ---------------------------------------------------------------------- catalogue

def _item(file, a, b, text, source, kind=None, verified=False, year=None, extra=None):
    # Stable between builds, so a choice the user made ("use this shot here") still
    # points at the same shot the next time the plan is built.
    import hashlib
    key = f"{source}|{file}|{int(a)}|{int(b)}|{(text or '').strip()[:80]}|{(extra or {}).get('hold_name', '')}"
    item = {'id': hashlib.sha1(key.encode()).hexdigest()[:10], 'file': file, 'in_ms': int(a), 'out_ms': int(b), 'text': text.strip(),
            'source': source, 'kind': kind or classify(text), 'verified': verified, 'year': year, 'moving': True}
    item.update(extra or {})
    return item


def build_catalogue(project, root, guide=None, beats=None, broll_catalog=None):
    """Every described shot this project can use, plus base stills and person photos."""
    root = Path(root)
    assets = {(a.get('original_name') or a.get('name')): a for a in project.get('assets') or []
              if a.get('kind') == 'video' and not a.get('derived_from')}
    roles = people_roles(project, guide)
    items = []
    # 1. The guide's own cards: someone looked at these windows and wrote what they show.
    for card in (guide or {}).get('cards', []):
        if card['window'] and card['source_id']:
            a, b = card['window']
            items.append(_item(card['source_id'] + '.mp4', a, b, card['show'] + ' ' + card['care'], 'guide',
                               verified=True, year=card['year'], extra={'card': card['number']}))
    # 2. A hand-checked catalogue for these very files (matched by name and length).
    #    A production may keep its own catalogue (broll_catalog.json in its project folder).
    #    The bundled one describes one production's files; it is used only when most of
    #    its sources are here with the same lengths, so a new production with a file that
    #    happens to be called S01.mp4 never inherits somebody else's shot descriptions.
    catalog = broll_catalog
    own = root / 'broll_catalog.json'
    bundled = catalog is None and not own.is_file()
    if catalog is None:
        path = own if own.is_file() else Path(__file__).resolve().parent / 'data' / 'broll_catalog.json'
        try:
            catalog = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        except (OSError, ValueError):
            catalog = None
    if catalog:
        sources = catalog.get('sources', {})
        same = {k for k, v in sources.items() if (k + '.mp4') in assets
                and abs(float(assets[k + '.mp4'].get('duration') or 0) - float(v.get('duration') or 0)) < 0.6}
        if bundled and len(same) < max(3, len(sources) // 2):
            same = set()
        for shot in catalog.get('shots', []):
            if shot.get('source') in same and shot.get('verified', True):
                text = shot.get('what', '') + ' ' + ' '.join(shot.get('tags', []))
                kind = {'place': 'place', 'people': 'people', 'speaker': 'speaker', 'graphic': 'graphic'}.get(shot.get('kind'))
                if classify(text) in ('photo', 'people') and kind == 'place':
                    kind = classify(text)          # "a woman and a child at a gate" is people, not a place
                items.append(_item(shot['source'] + '.mp4', shot['in'] * 1000, shot['out'] * 1000, text, 'catalog',
                                   kind=kind, verified=True))
    # 3. Local analysis: what the vision model saw and what the reporter says per scene.
    for name, asset in assets.items():
        report = root / 'reviews' / 'understanding' / (asset['id'] + '.json')
        if not report.is_file():
            continue
        try:
            data = json.loads(report.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        stages = data.get('stages') or data
        visual = (stages.get('visual') or {}).get('observations') or []
        speech = (stages.get('transcript') or {}).get('segments') or []
        scenes = {}
        for obs in visual:
            key = (obs.get('scene_start_s'), obs.get('scene_end_s'))
            if None in key:
                continue
            scenes.setdefault(key, []).append(obs.get('description') or '')
        for (a, b), texts in scenes.items():
            words = ' '.join(s.get('text', '') for s in speech if s.get('start_s', 0) < b and s.get('end_s', 0) > a)
            items.append(_item(name, a * 1000, b * 1000, ' '.join(texts) + ' ' + words, 'analysis'))
    # 4. The script's own visual directions, as a weaker description of each window.
    for beat in beats or []:
        if beat['kind'] == 'narration' and beat.get('direction'):
            # "End on Octavius Bass pre-frame 2 sec silent" describes the NEXT shot (the
            # bite's speaker), not this window, so it is not part of the description.
            direction = re.sub(r'\bEnd on\b[^.]*\.?', '', beat['direction'], flags=re.I)
            items.append(_item(beat['source_file'], beat['source_in_ms'], beat['source_out_ms'], direction,
                               'script', extra={'beat': beat['label']}))
    # 5. Base pictures from the guide's table. The frame sits inside a moving shot, so
    #    the shot around it becomes a moving base clip. Frames are never used as stills.
    for base in (guide or {}).get('base', []):
        asset = assets.get(base['file'])
        bounds = None
        if asset and (root / asset.get('path', '')).is_file():
            bounds = shot_bounds(root, root / asset['path'], base['at_ms'])
        approx = bounds is None
        if approx:
            bounds = (max(0, base['at_ms'] - 1000), base['at_ms'] + 1000)
        if bounds[1] - bounds[0] >= MIN_PIECE_MS:
            kind = {'V': 'photo', 'S': 'photo', 'C': 'place'}[base['category']]
            items.append(_item(base['file'], bounds[0], bounds[1], base['what'] + ' ' + ' '.join(base['tags']), 'base_clip',
                               kind=kind, verified=True, year=base['year'],
                               extra={'category': base['category'], 'tags': base['tags'], 'base': Path(base['name']).stem,
                                      'approximate': approx}))
    # 6a. B-roll and base pictures from the footage sheet, with what the sheet says they
    #     show. A video is moving footage like any other; a picture is a still, used only
    #     when no moving footage fits the line (see the 'base_photo' step in fill).
    for a in project.get('assets') or []:
        pr = a.get('provenance') or {}
        if a.get('derived_from') or not (pr.get('media') == 'broll' or (pr.get('media') == 'photo' and not pr.get('person') and not pr.get('role') and pr.get('description'))):
            continue
        name = a.get('original_name') or a.get('name')
        label = re.sub(r'[_\-]+', ' ', Path(name).stem)
        text = ' '.join(x for x in (pr.get('description') or a.get('notes') or '', label) if x)
        if a.get('kind') == 'video' and a.get('duration'):
            items.append(_item(name, 0, float(a['duration']) * 1000, text, 'sheet_broll', kind='place', verified=True,
                               extra={'broll': True}))
        elif a.get('kind') == 'image' and (root / a.get('path', '')).is_file():
            items.append(_item(None, 0, 0, text, 'sheet_broll', kind='place', verified=True,
                               extra={'moving': False, 'still': {'kind': 'photo', 'path': a['path']},
                                      'hold_name': 'BASE-' + re.sub(r'[^A-Za-z0-9]+', '_', Path(name).stem).strip('_') + '.mp4',
                                      'broll': True}))
    # 6. People-on-screen photos: the only pictures that are not moving footage, and only
    #    of the victim, a suspect or family, shown when the narration names them.
    for r in roles:
        if r['photo'] and (root / r['photo']).is_file() and r['role'] in ('victim', 'suspect', 'family'):
            items.append(_item(None, 0, 0, f"Photo of {r['name']}", 'person_photo', kind='photo', verified=True,
                               extra={'moving': False, 'still': {'kind': 'photo', 'path': r['photo']},
                                      'hold_name': 'PHOTO-' + re.sub(r'[^A-Za-z0-9]+', '_', r['name']).strip('_') + '.mp4',
                                      'people': {r['id']}}))
    # Derived facts used by the matcher.
    role_of = {r['id']: r['role'] for r in roles}
    for item in items:
        item.setdefault('people', set())
        # A name in quotes is a slogan, banner or poster ("Justice for Maliyah Bass" on a
        # shirt), not the person being in the picture.
        unquoted = re.sub(r'["“][^"”]*["”]', ' ', item['text'])
        item['people'] = set(item['people']) | people_in(unquoted, roles)
        item['surnames'] = surnames(item['text'])
        item['groups'] = groups_in(item['text'])
        item['tokens'] = tokens(item['text'])
        item.setdefault('tags', set())
        item['guide_tags'] = set(item['tags'])          # the guide's own tags, exactly as written
        item['tags'] = set(item['tags']) | item['groups']
        if item['kind'] in ('place',) and not item['people']:
            item['tags'].add('location')
        if 'police' in item['groups']:
            item['tags'].add('police')
        roles_here = {role_of.get(p) for p in item['people']}
        item.setdefault('category', 'S' if 'suspect' in roles_here else 'V' if roles_here & {'victim', 'family'} else
                        'C' if item['kind'] == 'place' else None)
        if item['year'] is None:
            ys = years_in(item['text'])
            item['year'] = ys[-1] if ys else None
        item['available'] = item['still'] is not None if 'still' in item else (item['file'] in assets)
        if item.get('still', {}) and item['still'].get('kind') == 'frame':
            item['available'] = item['still']['file'] in assets
        item['duration_ms'] = int(float(assets[item['file']]['duration']) * 1000) if item['file'] in assets else None
        if item['duration_ms'] and item['out_ms'] > item['duration_ms']:
            item['out_ms'] = item['duration_ms']
    return items, roles


# ---------------------------------------------------------------------- narration

def narration_units(spans, blocks):
    """Split each narration span at SRT cue starts into units of at least MIN_UNIT_MS."""
    units = []
    for span in spans:
        a, b = span['start_ms'], span['end_ms']
        cuts = sorted({blk['start_ms'] for blk in blocks if a < blk['start_ms'] < b})
        points = [a] + cuts + [b]
        pieces = [[points[i], points[i + 1]] for i in range(len(points) - 1)]
        merged = []
        for p in pieces:
            if merged and (merged[-1][1] - merged[-1][0] < MIN_UNIT_MS or p[1] - p[0] < MIN_UNIT_MS / 2):
                merged[-1][1] = p[1]
            else:
                merged.append(p)
        if len(merged) > 1 and merged[-1][1] - merged[-1][0] < MIN_UNIT_MS:
            last = merged.pop()
            merged[-1][1] = last[1]
        for x, y in merged:
            text = ' '.join(blk['text'] for blk in blocks if blk['start_ms'] < y and blk['end_ms'] > x)
            units.append({'start_ms': x, 'end_ms': y, 'text': text, 'span': span})
    return units


# ---------------------------------------------------------------------- matcher

class Planner:
    def __init__(self, items, roles, total_ms, still_cap=STILL_CAP, suspect_first_ms=None, arrest_first_ms=None):
        self.items = [i for i in items if i['available']]
        self.unavailable = [i for i in items if not i['available']]
        self.roles = roles
        self.role_of = {r['id']: r['role'] for r in roles}
        self.used = {}          # file -> [(a, b)]
        self.hold = {}          # still item id -> cursor ms in its hold clip
        self.recent = []        # (master_ms, item_id)
        self.still_ms = 0
        self.still_cap_ms = int(total_ms * still_cap)
        self.suspect_first_ms = suspect_first_ms
        self.arrest_first_ms = arrest_first_ms
        self.photo_of = {next(iter(i['people'])): i for i in self.items
                         if i['source'] == 'person_photo' and i['people']}
        self.person_choice = {}
        self.introduced = set()       # people already named once (their first mention shows the photo)
        self.last = None
        self.pauses = set()
        self.root, self.assets = None, {}

    # -- footage bookkeeping
    def reserve(self, file, a, b):
        self.used.setdefault(file, []).append((a, b))

    def free(self, item, need, minimum):
        """Longest unused stretch inside the item's window, up to `need`, at least `minimum`."""
        a, b = item['in_ms'], item['out_ms']
        spans = sorted(x for x in self.used.get(item['file'], []) if x[0] < b and x[1] > a)
        cursor, best = a, None
        for s, e in spans + [(b, b)]:
            if s - cursor >= minimum:
                length = min(need, s - cursor)
                if best is None or length > best[1] - best[0]:
                    best = (cursor, cursor + length)
                if length >= need:
                    return best
            cursor = max(cursor, e)
        return best

    # -- scoring
    def score(self, item, unit, hint, ctx):
        text = unit['text']
        cue_people = ctx['people']
        cue_roles = {self.role_of.get(p) for p in cue_people}
        family_line = bool(ctx['groups'] & {'family'}) or 'victim' in cue_roles or 'family' in cue_roles
        reasons, s = [], 0.0
        if item['kind'] == 'unknown' and item['source'] != 'script':
            return None
        # Who is in the picture.
        shown = item['people']
        shown_roles = {self.role_of.get(p) for p in shown}
        if item.get('category') == 'S' or 'suspect' in shown_roles:
            if family_line and 'suspect' not in cue_roles:
                return None                                   # never a suspect under a victim/family line
            if self.suspect_first_ms is not None and unit['start_ms'] < self.suspect_first_ms:
                return None                                   # not before the narration names him
        if _MUGSHOT.search(item['text']) and (self.arrest_first_ms is None or unit['start_ms'] < self.arrest_first_ms):
            return None                                       # a booking photo before the arrest is told: a spoiler
        if item['kind'] in ('speaker', 'photo') and not (shown & cue_people):
            named_here = {n for n in item['surnames'] if re.search(r'\b' + re.escape(n) + r'\b', text, re.I)}
            if not named_here and not (hint and hint.get('category') and hint['category'] == item.get('category')):
                return None                                   # a face only when that person is the subject
            if named_here:
                s += 5
                reasons.append('shows ' + ', '.join(sorted(named_here)))
        for p in shown & cue_people:
            s += 2 if item['source'] == 'script' else 6
            reasons.append('shows ' + next(r['name'] for r in self.roles if r['id'] == p))
        if item['kind'] == 'people' and shown and not (shown & cue_people):
            s -= 3
        # When the picture was taken.
        story = ctx['year']
        asked = {int(t) for t in (hint or {}).get('tags', set()) if t.isdigit()}
        if item['year'] and story and item['year'] > story and item['kind'] != 'place' and item['year'] not in asked:
            return None                                       # a later picture never covers an earlier event
        # What it is about.
        if hint:
            # "!custody" names the guide's own tag, so it is checked against the guide's tags
            # where the item has them; words in a description are not tags.
            own = item['guide_tags'] or item['tags']
            if hint['exclude'] & (own | ({str(item['year'])} if item['year'] else set())):
                return None
            if hint['category']:
                if item.get('category') == hint['category']:
                    s += 4
                    reasons.append('fits ' + {'V': 'victim', 'S': 'suspect', 'C': 'context'}[hint['category']] + ' fill')
                    if item['kind'] == 'photo':
                        s += 3      # the hint asks for this person: their picture is the point
                elif item.get('category') in ('V', 'S') and hint['category'] != item.get('category'):
                    return None
                else:
                    s -= 2
            year_tags = {t for t in hint['tags'] if t.isdigit()}
            plain = hint['tags'] - year_tags
            if year_tags and item['year'] and str(item['year']) not in year_tags:
                return None
            hit = plain & item['tags']
            if hit:
                s += 3 * len(hit)
                reasons.append('tag ' + ', '.join(sorted(hit)))
        shared = ctx['groups'] & item['groups'] - {'family'}
        if shared:
            s += 3 * len(shared)
            reasons.append('about ' + ', '.join(sorted(shared)))
        carried = (ctx.get('previous') or set()) & item['groups'] - shared - {'family'}
        if carried:
            # The line before set the scene ("...with teddy bears and balloons" then
            # "Grandmother Rosalie Jimerson spoke"): keep with it, at less weight.
            s += 1.5 * len(carried)
            reasons.append('continues ' + ', '.join(sorted(carried)))
        words = shared_words(ctx['tokens'], item['tokens']) - {g for g in GROUPS}
        if item.get('broll') and item.get('best_words', 0) >= 2 and len(words) < item['best_words'] - 1:
            return None              # saved for the line that names what it shows
        if words:
            s += min(3, len(words))
            reasons.append('words ' + ', '.join(sorted(words)[:3]))
        # Preferences.
        if item['moving']:
            s += 1
        if item['verified']:
            s += 1
        if item['source'] == 'script' and item.get('beat') == unit['span'].get('label'):
            s += 2
            reasons.append("the script's own choice for this beat")
        if any(i == item['id'] and unit['start_ms'] - t < REPEAT_WINDOW_MS for t, i in self.recent):
            s -= 3
        return s, reasons

    def candidates(self, unit, hint, ctx, kinds=None, moving=None):
        out = []
        for item in self.items:
            if kinds and item['kind'] not in kinds:
                continue
            if moving is not None and item['moving'] != moving:
                continue
            result = self.score(item, unit, hint, ctx)
            if result:
                out.append((result[0], result[1], item))
        out.sort(key=lambda x: -x[0])
        return out

    def release(self, got, item):
        if item['moving']:
            self.used[got[0]].remove((got[1], got[2]))
        else:
            self.hold[item['id']] = got[1]
            self.still_ms -= got[2] - got[1]

    def shorten(self, got, item, keep):
        if item['moving']:
            spans = self.used[got[0]]
            spans[spans.index((got[1], got[2]))] = (got[1], got[1] + keep)
        else:
            self.hold[item['id']] = got[1] + keep + HOLD_GAP_MS
            self.still_ms -= (got[2] - got[1]) - keep

    def take(self, item, need, minimum):
        """Reserve picture for `need` ms from this item; returns (file, a, b) or None."""
        if not item['moving']:
            if self.still_ms + need > self.still_cap_ms:
                return None
            cursor = self.hold.get(item['id'], 0)
            self.hold[item['id']] = cursor + need + HOLD_GAP_MS
            self.still_ms += need
            return (item['hold_name'], cursor, cursor + need)
        window = self.free(item, need, minimum)
        if not window:
            return None
        self.reserve(item['file'], *window)
        return (item['file'],) + window

    # -- names: the person's photo, or moving footage of them
    def person_options(self, pid, unit, hint, ctx):
        """(moving shots of this person, their photo item or None)."""
        moving = [c for c in self.candidates(unit, hint, ctx, moving=True)
                  if pid in c[2]['people'] and c[0] >= MATCH]
        return moving, self.photo_of.get(pid)

    def person_piece(self, pid, length, unit, hint, ctx):
        """Picture for `length` ms of a line that names this person. None if nothing fits."""
        moving, photo = self.person_options(pid, unit, hint, ctx)
        footage_first = bool(hint and (hint['tags'] - {'portrait'} - {t for t in hint['tags'] if t.isdigit()}))
        name = next((r['name'] for r in self.roles if r['id'] == pid), pid)
        if footage_first:
            # "S / court+2026" asks for footage of them in court; their photo only if none is left.
            for score, reasons, item in moving:
                got = self.take(item, length, length)
                if got:
                    self.person_choice[pid] = 'moving'
                    return got, item, score, [f'names {name}: footage of them ({"; ".join(reasons)})'], 'match'
            moving = []
        # In the opening, and the first time anyone is named, their photo pops up. After
        # that, footage that shows them comes first and the photo only fills in where
        # there is not enough footage of them.
        opening = unit['start_ms'] < getattr(self, 'opening_ms', float('inf')) or pid not in self.introduced
        self.introduced.add(pid)
        if moving and not opening:
            order = [('moving', m) for m in moving] + ([('photo', (0, [], photo))] if photo else [])
        else:
            order = ([('photo', (0, [], photo))] if photo else []) + [('moving', m) for m in moving]
        for how, (score, reasons, item) in order:
            got = self.take(item, length, length)
            if got:
                self.person_choice[pid] = how
                why = (f'names {name}: their photo' if how == 'photo'
                       else f'names {name}: footage of them ({"; ".join(reasons)})')
                return got, item, score, [why], ('photo' if how == 'photo' else 'match')
        return None

    # -- continuity: the same scene keeps running while the narration stays on it
    def continues(self, unit, ctx):
        last = self.last
        if not last or last['end_ms'] != unit['start_ms'] or unit['start_ms'] in self.pauses:
            return False
        if ctx['people'] - last['people']:
            return False                                  # someone new is named
        new = ctx['groups'] - last['groups'] - WEAK_GROUPS
        if new:
            return False                                  # a new subject
        if last['kind'] == 'photo':
            # Keep a photo up for a line that is still about that person ("she knew her
            # ABCs ... her colours, her numbers"), but not for long.
            return bool(_PRONOUN.search(unit['text'])) and last['run_ms'] < PHOTO_RUN_MS
        return True

    def continue_last(self, need, unit):
        """Next frames of the shot that is on screen, up to the shot change."""
        last = self.last
        item = last['item']
        if not item['moving']:
            got = self.take(item, need, min(need, MIN_PIECE_MS))
            return (got, item) if got else None
        a = last['out_ms']
        limit = item['out_ms']
        bound = self.shot_end(item['file'], a)
        if bound:
            limit = max(limit, bound)
        if a >= limit:
            # The described shot is spent: the next described shot in the same report, if
            # it starts right where this one ended, is the same scene going on.
            nxt = [i for i in self.items if i['moving'] and i['file'] == item['file'] and a - 300 <= i['in_ms'] <= a + 1500
                   and i['out_ms'] > a + MIN_PIECE_MS and not (i['people'] - last['people'])]
            if not nxt:
                return None
            item = max(nxt, key=lambda i: len(i['groups'] & last['groups']))
            a, limit = max(a, item['in_ms']), item['out_ms']
        blocked = [x for x in self.used.get(item['file'], []) if x[1] > a and x[0] < limit]
        if blocked:
            limit = min(limit, min(x[0] for x in blocked))
        length = min(need, limit - a)
        if length < min(need, MIN_PIECE_MS) or 0 < need - length < MIN_PIECE_MS:
            return None
        self.reserve(item['file'], a, a + length)
        return (item['file'], a, a + length), item

    def shot_end(self, file, at_ms):
        if not self.root or file not in self.assets:
            return None
        path = self.root / self.assets[file].get('path', '')
        if not path.is_file():
            return None
        bounds = shot_bounds(self.root, path, max(0, at_ms - 200))
        return bounds[1] if bounds else None

    def fill(self, unit, hint, ctx, scripted=None):
        """Pictures for one unit, best first, recorded with the reason for each."""
        need_total = unit['end_ms'] - unit['start_ms']
        pieces, remaining, start = [], need_total, unit['start_ms']

        def add(got, item, score, reasons, label, alternatives):
            nonlocal start, remaining
            if item.get('source') == 'base_clip' and label == 'match':
                label = 'base_clip'          # a moving clip cut around a base picture, not a catalogue match
            length = got[2] - got[1]
            pieces.append({'start_ms': start, 'end_ms': start + length, 'file': got[0], 'in_ms': got[1],
                           'out_ms': got[2], 'kind': label, 'reason': '; '.join(reasons) or label.replace('_', ' '),
                           'score': round(score, 1) if score is not None else None, 'text': item['text'][:200],
                           'item': item['id'], 'source': item['source'], 'moving': item['moving'],
                           'still': item.get('still'), 'alternatives': alternatives,
                           'people': sorted(item.get('people') or [])})
            run = (self.last['run_ms'] + length) if (self.last and label == 'continue' and self.last['kind'] == 'photo') else length
            self.last = {'span': unit['span']['label'], 'item': item, 'file': got[0], 'out_ms': got[2], 'end_ms': start + length, 'kind':
                         'photo' if not item['moving'] else label, 'run_ms': run,
                         'people': set(item.get('people') or set()) | (ctx['people'] if label == 'photo' else set()),
                         'groups': set(item.get('groups') or set()) | ctx['groups']}
            self.recent.append((start, item['id']))
            start += length
            remaining -= length

        forced = ctx.get('force')
        # 1. Names called: the person's photo (victim, suspect, family), or footage of them.
        if not forced:
            named = [(at, pid) for at, pid in ctx.get('named', []) if pid in self.photo_of or self.has_footage(pid)]
            if not named and hint and hint.get('category') in ('V', 'S'):
                want = 'suspect' if hint['category'] == 'S' else ('family' if 'family' in hint['tags'] else 'victim')
                pid = next((r['id'] for r in self.roles if r['role'] == want and (r['id'] in self.photo_of or self.has_footage(r['id']))), None)
                if pid is None and want == 'family':
                    pid = next((r['id'] for r in self.roles if r['role'] == 'victim' and r['id'] in self.photo_of), None)
                if pid:
                    named = [(unit['start_ms'], pid)]
                    ctx['hint_person'] = pid
            segments = []
            for i, (at, pid) in enumerate(named):
                a = unit['start_ms'] if i == 0 else max(unit['start_ms'], at - 150)
                b = unit['end_ms'] if i == len(named) - 1 else max(unit['start_ms'], named[i + 1][0] - 150)
                if segments and segments[-1][2] == pid:
                    segments[-1][1] = b
                elif b - a >= MIN_PIECE_MS:
                    segments.append([a, b, pid])
                elif segments:
                    segments[-1][1] = b
            if segments:
                segments[0][0] = unit['start_ms']
                segments[-1][1] = unit['end_ms']
            for a, b, pid in segments:
                if start != a:
                    break
                found = self.person_piece(pid, b - a, unit, hint, ctx)
                if not found:
                    break
                got, item, score, reasons, label = found
                add(got, item, score, reasons, label, [])
        # 2. The same idea goes on: keep the shot that is on screen running.
        guide_shot = bool(self.last and self.last.get('kind') == 'guide' and self.last.get('span') == unit['span']['label'])
        if remaining > 0 and not forced and (guide_shot or not (hint and hint.get('category'))) and \
                self.continues(dict(unit, start_ms=start), ctx):
            found = self.continue_last(remaining, unit)
            if found:
                got, item = found
                add(got, item, None, [f"the same scene continues (next frames of {got[0]})"], 'continue', [])
        # 3. Match by subject, then moving base clips, the script's own window, the best weak option.
        ladder = [
            ('match', lambda: [c for c in self.candidates(unit, hint, ctx, moving=True) if c[0] >= MATCH]),
            ('base_clip', lambda: [c for c in self.candidates(unit, hint, ctx, kinds={'place'}, moving=True)
                                   if c[0] >= 1 and not c[2].get('broll')
                                   and (not ctx['groups'] & {'police'} or 'police' in c[2]['groups'])]),
            # A base picture from the sheet that shows what the line is about, before a weak guess.
            ('base_photo', lambda: [c for c in self.candidates(unit, hint, ctx, kinds={'place'}, moving=False)
                                    if c[2].get('broll') and c[0] >= MATCH]),
            # Sheet b-roll is kept for the lines it matches; it is not spent as filler.
            ('weak', lambda: [c for c in self.candidates(unit, None, ctx, kinds={'place', 'people'}, moving=True)
                              if not c[2].get('broll')]),
        ]
        for label, make in ladder:
            if remaining <= 0 or len(pieces) >= MAX_PIECES:
                break
            if label == 'base_photo' and scripted:
                # The production script's own window for this beat comes before a base
                # picture or a weak guess.
                got = self.take(scripted, remaining, min(remaining, MIN_PIECE_MS * 2))
                if got and 0 < remaining - (got[2] - got[1]) < MIN_PIECE_MS:
                    self.release(got, scripted)
                    got = self.take(scripted, remaining, remaining)
                if got:
                    add(got, scripted, 0, ["the script's own window (nothing better found)"], 'scripted', [])
                    if remaining <= 0:
                        break
            options = make()
            if forced and any(o[2]['id'] == forced for o in options):
                options = [o for o in options if o[2]['id'] == forced] + [o for o in options if o[2]['id'] != forced]
            free_now = [o for o in options if not o[2]['moving'] or self.free(o[2], remaining, min(remaining, MIN_PIECE_MS))]
            alternatives = [{'file': o[2]['file'] or o[2]['hold_name'], 'text': o[2]['text'][:140], 'score': round(o[0], 1),
                             'item': o[2]['id']} for o in free_now[:4]]
            if options and not (forced and options[0][2]['id'] == forced):
                top = options[0][0]
                for score, reasons, item in options:
                    if score < top - 3:
                        break
                    got = self.take(item, remaining, remaining)
                    if got:
                        add(got, item, score, reasons, label, alternatives)
                        break
            for score, reasons, item in options:
                if remaining <= 0 or len(pieces) >= MAX_PIECES:
                    break
                last = len(pieces) == MAX_PIECES - 1
                minimum = remaining if (last or remaining < 2 * MIN_PIECE_MS) else MIN_PIECE_MS
                if forced and item['id'] == forced and not pieces:
                    minimum = min(remaining, MIN_PIECE_MS)   # the user's pick, for as long as it lasts
                got = self.take(item, remaining, minimum)
                if not got:
                    continue
                length = got[2] - got[1]
                if 0 < remaining - length < MIN_PIECE_MS:
                    keep = remaining - MIN_PIECE_MS
                    if keep < MIN_PIECE_MS:
                        self.release(got, item)
                        continue
                    self.shorten(got, item, keep)
                    got = (got[0], got[1], got[1] + keep)
                add(got, item, score, reasons, label, alternatives)
                break
            # After a cut, let what follows continue it rather than start yet another shot.
            if remaining > 0 and pieces and pieces[-1]['moving'] and self.continues(dict(unit, start_ms=start), ctx):
                found = self.continue_last(remaining, unit)
                if found:
                    got, item = found
                    add(got, item, None, [f"the same scene continues (next frames of {got[0]})"], 'continue', [])
        if remaining > 0:
            # The person this line is about, if footage ran out: their photo for the rest.
            pids = [pid for _, pid in ctx.get('named', [])] or ([ctx['hint_person']] if ctx.get('hint_person') else [])
            for pid in pids:
                photo = self.photo_of.get(pid)
                got = photo and self.take(photo, remaining, remaining)
                if got:
                    name = next((r['name'] for r in self.roles if r['id'] == pid), pid)
                    add(got, photo, 0, [f'names {name}: their photo (no more footage of them)'], 'photo', [])
                    break
        if remaining > 0 and scripted:
            got = self.take(scripted, remaining, remaining) or self.take(dict(scripted, in_ms=0), remaining, remaining)
            if got:
                add(got, scripted, 0, ["the script's own window (nothing better found)"], 'scripted', [])
        if remaining > 0 and pieces and pieces[-1]['moving'] and pieces[-1]['file']:
            # Let the last picture run on, if its file has unused frames right after it.
            last = pieces[-1]
            after = [x for x in self.used.get(last['file'], []) if x != (last['in_ms'], last['out_ms'])]
            end = last['out_ms'] + remaining
            if not any(a < end and b > last['out_ms'] for a, b in after) and (last['file'], last['in_ms'], last['out_ms']) and \
                    (last['in_ms'], last['out_ms']) in self.used.get(last['file'], []):
                spans = self.used[last['file']]
                spans[spans.index((last['in_ms'], last['out_ms']))] = (last['in_ms'], end)
                last['out_ms'] = end
                last['end_ms'] += remaining
                remaining = 0
        return pieces, remaining

    def has_footage(self, pid):
        return any(i['moving'] and pid in i['people'] for i in self.items)


# ---------------------------------------------------------------------- plan

def plan(project, root, overrides=None, still_cap=STILL_CAP):
    """Build the visual plan for this project. Returns a dict; never changes the project."""
    from documentary_beats import read_beats
    root = Path(root)
    # Once a plan has been applied the production script IS the plan; planning again
    # starts from the script or guide the user wrote, never from a previous plan.
    text = project.get('visual_plan_source') or (project.get('production_script') or {}).get('text') or ''
    blocks = (project.get('srt') or {}).get('blocks') or []
    if not blocks:
        raise ValueError('Upload the SRT first: the narration lines are what the pictures are matched to.')
    guide, beats, raw_blocks = None, None, []
    guide_text = (project.get('editing_guide') or {}).get('text') or ''
    if is_card_guide(text):
        guide = parse_card_guide(text)
    elif text.strip():
        beats = read_beats(text)
        raw_blocks = re.split(r'(?=^Beat:\s*\d+\s*$)', text, flags=re.M)
        raw_blocks = [b for b in raw_blocks if re.match(r'Beat:\s*\d+', b)]
        if guide_text and is_card_guide(guide_text):
            guide = parse_card_guide(guide_text)
    else:
        raise ValueError('Upload the production script (or a card editing guide) first.')
    items, roles = build_catalogue(project, root, guide, beats)
    from documentary import narration_clock_s
    voice_ms = int(narration_clock_s(project) * 1000) or blocks[-1]['end_ms']
    bite_ms = sum(b['source_out_ms'] - b['source_in_ms'] for b in beats or [] if b['kind'] != 'narration')
    total_ms = voice_ms + bite_ms
    suspect_ids = {r['id'] for r in roles if r['role'] == 'suspect'}
    suspect_first = None
    for blk in blocks:
        if people_in(blk['text'], [r for r in roles if r['id'] in suspect_ids]):
            suspect_first = blk['start_ms']
            break
    arrest_first = next((blk['start_ms'] for blk in blocks if _ARREST.search(blk['text'])), None)
    planner = Planner(items, roles, total_ms, still_cap, suspect_first, arrest_first)
    # Sheet b-roll that names something specific (Sunset Crossing, Beechnut) is saved for
    # the line that names it: its best word match over the whole SRT is noted here.
    line_words = [narration_tokens(blk['text']) | narration_tokens(' '.join(x['text'] for x in blocks[i:i + 2]))
                  for i, blk in enumerate(blocks)]
    group_words = set(GROUPS)
    for item in planner.items:
        if item.get('broll'):
            item['best_words'] = max((len(shared_words(w, item['tokens']) - group_words) for w in line_words), default=0)
    planner.root = root
    planner.assets = {(a.get('original_name') or a.get('name')): a for a in project.get('assets') or [] if a.get('kind') == 'video'}
    planner.pauses = {b['pause_ms'] for b in beats or [] if b['kind'] != 'narration'}
    # Where photos stop popping up for every mention (People on screen setting).
    from person_overlays import settings as _person_settings, opening_end_ms
    _mode = _person_settings(project)['photo_opening']
    _bites = {'bites': [{'pause_s': b['pause_ms'] / 1000} for b in beats or [] if b['kind'] != 'narration']}
    planner.opening_ms = opening_end_ms(_mode, _bites, voice_ms)
    # Spans of narration to picture, and windows that are already spoken for.
    spans = []
    if guide and not beats:
        for card in guide['cards']:
            spans.append({'start_ms': card['start_ms'], 'end_ms': card['end_ms'], 'card': card,
                          'label': f"card {card['number']}", 'caption': ''})
    else:
        for b in beats:
            if b['kind'] != 'narration':
                planner.reserve(b['source_file'], b['source_in_ms'], b['source_out_ms'])
            else:
                spans.append({'start_ms': b['narration_in_ms'], 'end_ms': b['narration_out_ms'], 'beat': b,
                              'label': b['label'], 'caption': b.get('caption', '')})
    # The guide's chosen windows belong to their cards: reserve them before matching.
    fixed = {}
    for span in spans:
        card = span.get('card')
        if card and card['window'] and card['source_id']:
            file = card['source_id'] + '.mp4'
            length = min(card['window'][1] - card['window'][0], span['end_ms'] - span['start_ms'])
            fixed[card['number']] = (file, card['window'][0], card['window'][0] + length)
            planner.reserve(file, card['window'][0], card['window'][0] + length)
    overrides = overrides or {}
    rows, year, previous_groups = [], None, set()
    first_years = [y for blk in blocks for y in years_in(blk['text'])]
    year = first_years[0] if first_years else None
    for span in spans:
        card = span.get('card')
        sub = narration_units([span], blocks) if not card else [{'start_ms': span['start_ms'], 'end_ms': span['end_ms'],
                                                                 'text': ' '.join(b['text'] for b in blocks if b['start_ms'] < span['end_ms'] and b['end_ms'] > span['start_ms']),
                                                                 'span': span}]
        for unit in sub:
            ys = years_in(unit['text'])
            if ys:
                year = ys[-1]
            named = []
            span_ms = max(1, unit['end_ms'] - unit['start_ms'])
            for r in roles:
                if not r['regex']:
                    continue
                hit = r['regex'].search(unit['text'])
                if hit:
                    named.append((unit['start_ms'] + int(span_ms * hit.start() / max(1, len(unit['text']))), r['id']))
            named.sort()
            # "Malia's father Octavius Bass": the first name is only possessive, the line is
            # about the second person.
            text_lower = unit['text']
            keep = []
            for i, (at, pid) in enumerate(named):
                r = next(x for x in roles if x['id'] == pid)
                hit = r['regex'].search(text_lower)
                after = text_lower[hit.end():hit.end() + 30] if hit else ''
                if re.match(r"['’]s\b", after) and i + 1 < len(named):
                    continue
                keep.append((at, pid))
            named = keep
            ctx = {'named': named, 'people': people_in(unit['text'], roles), 'groups': groups_in(unit['text']),
                   'tokens': narration_tokens(unit['text']), 'year': year, 'force': overrides.get(str(unit['start_ms'])),
                   'previous': previous_groups}
            previous_groups = ctx['groups'] or previous_groups
            hint = parse_fill(card['fill']) if card else None
            pieces, start = [], unit['start_ms']
            if card and card['number'] in fixed:
                file, a, b = fixed[card['number']]
                pieces.append({'start_ms': start, 'end_ms': start + (b - a), 'file': file, 'in_ms': a, 'out_ms': b,
                               'kind': 'guide', 'reason': "the guide's own clip for this card", 'score': None,
                               'text': card['show'][:200], 'item': None, 'source': 'guide', 'moving': True, 'still': None,
                               'alternatives': []})
                planner.recent.append((start, None))
                # The rest of the card may carry on in the same shot ("window 2.0 s is shorter
                # than the 3.9 s span"): the shot change in the file decides how far.
                planner.last = {'span': span['label'], 'item': {'id': None, 'file': file, 'in_ms': a, 'out_ms': b, 'moving': True, 'people': set(),
                                         'groups': groups_in(card['show']), 'text': card['show'], 'source': 'guide'},
                                'file': file, 'out_ms': b, 'end_ms': start + (b - a), 'kind': 'guide', 'run_ms': b - a,
                                'people': people_in(card['show'], roles), 'groups': groups_in(card['show'])}
                start += b - a
            remaining = unit['end_ms'] - start
            if remaining > 0:
                rest = dict(unit, start_ms=start)
                scripted = None
                beat = span.get('beat')
                if beat:
                    offset = start - beat['narration_in_ms']
                    scripted = {'id': 'script-' + beat['label'], 'file': beat['source_file'],
                                'in_ms': beat['source_in_ms'] + offset, 'out_ms': beat['source_out_ms'],
                                'text': beat.get('direction') or 'scripted window', 'moving': True, 'source': 'script',
                                'kind': 'scripted'}
                more, left = planner.fill(rest, hint, ctx, scripted)
                if left > 0 and pieces and not more:
                    pass
                pieces += more
                if left > 0:
                    # Nothing at all could be found: say so on the row; the builder's own gap
                    # handling will ask for footage rather than invent any.
                    why = ('No unused moving footage fits, and the photo limit '
                           f'({int(still_cap*100)}% of the film) is used up. Raise the limit, or add footage.'
                           if planner.still_ms >= planner.still_cap_ms - 1000 else
                           'No unused moving footage fits. Add footage that shows this, or choose a picture for the line.')
                    pieces.append({'start_ms': unit['end_ms'] - left, 'end_ms': unit['end_ms'], 'file': None,
                                   'in_ms': None, 'out_ms': None, 'kind': 'uncovered', 'score': None,
                                   'reason': why,
                                   'text': '', 'item': None, 'source': None, 'moving': True, 'still': None,
                                   'alternatives': []})
            rows.append({'start_ms': unit['start_ms'], 'end_ms': unit['end_ms'], 'text': unit['text'],
                         'span': span['label'], 'pieces': pieces, 'hint': card['fill'] if card else ''})
    return finish(project, root, rows, beats, raw_blocks, planner, guide, items)


def finish(project, root, rows, beats, raw_blocks, planner, guide, items):
    """Summaries, the stills that must be made, and the Beat script text."""
    counts = {}
    for row in rows:
        for p in row['pieces']:
            counts[p['kind']] = counts.get(p['kind'], 0) + (p['end_ms'] - p['start_ms'])
    narration_ms = sum(r['end_ms'] - r['start_ms'] for r in rows)
    holds = {}
    for row in rows:
        for p in row['pieces']:
            if p.get('still'):
                h = holds.setdefault(p['file'], {'name': p['file'], 'still': p['still'], 'length_ms': 0})
                h['length_ms'] = max(h['length_ms'], p['out_ms'] + HOLD_GAP_MS)
    script = beat_script(rows, beats, raw_blocks)
    sources = {}
    for i in items:
        sources[i['source']] = sources.get(i['source'], 0) + 1
    return {'version': 1, 'rows': rows, 'counts_ms': counts, 'narration_ms': narration_ms,
            'still_ms': planner.still_ms, 'still_cap_ms': planner.still_cap_ms, 'holds': list(holds.values()),
            'catalogue': {'items': len(items), 'by_source': sources,
                          'unavailable_files': sorted({i['file'] for i in planner.unavailable if i['file']})},
            'input': 'card_guide' if guide and not beats else 'beat_script', 'script': script}


# Pictures that only stand in for the line: a general place shot, the last-resort
# fallback, or nothing at all. These are the lines the footage does not yet show.
WEAK_KINDS = ('base_clip', 'weak', 'uncovered')


def missing_footage(data, title=''):
    """The narration lines still without a picture of what they say, as a markdown list.

    Written to be pasted into the Footage Gap Fill prompt: each line's narration time,
    how long a picture it needs, its exact words and what stands in for it now.
    Consecutive weak lines of the same beat are joined into one request.
    """
    wanted = []
    for row in data.get('rows') or []:
        for piece in row.get('pieces') or []:
            if piece.get('kind') not in WEAK_KINDS:
                continue
            now = ('nothing' if piece['kind'] == 'uncovered'
                   else f"{piece.get('file') or '?'} ({'general place shot' if piece['kind'] == 'base_clip' else 'last-resort fallback'})")
            last = wanted[-1] if wanted else None
            if last and last['span'] == row.get('span') and abs(last['end_ms'] - piece['start_ms']) < 50:
                last['end_ms'] = piece['end_ms']
                if row.get('text') and row['text'] not in last['words']:
                    last['words'].append(row['text'])
                continue
            wanted.append({'span': row.get('span'), 'start_ms': piece['start_ms'], 'end_ms': piece['end_ms'],
                           'words': [row.get('text') or ''], 'now': now})
    total = int(data.get('narration_ms') or 0)
    weak_ms = sum(w['end_ms'] - w['start_ms'] for w in wanted)
    out = [f"# Missing footage{(' — ' + title) if title else ''}", '',
           f"{len(wanted)} narration passage(s), {weak_ms / 1000:.1f}s of {total / 1000:.1f}s narration "
           f"({100 * weak_ms / total if total else 0:.0f}%), show a stand-in rather than what the narrator says.",
           'Times are on the narration clock (the voice-over file).', '',
           '| # | Narration time | Picture needed | Narration words | Showing now |', '|---|---|---|---|---|']
    for n, w in enumerate(wanted, 1):
        words = ' '.join(w['words']).replace('|', '/').strip()
        out.append(f"| G{n:02d} | {clock(w['start_ms'])} → {clock(w['end_ms'])} | {(w['end_ms'] - w['start_ms']) / 1000:.1f}s "
                   f"| {words} | {w['now']} |")
    if not wanted:
        out.append('| — | — | — | Every narration line has a matching picture. | — |')
    return '\n'.join(out) + '\n'


def beat_script(rows, beats, raw_blocks):
    """The plan written as a Beat production script; sound bites are copied verbatim."""
    out, number = [], 0
    by_label = {}
    for row in rows:
        by_label.setdefault(row['span'], []).append(row)

    def narration_block(piece, row, caption):
        nonlocal number
        number += 1
        span = piece['end_ms'] - piece['start_ms']
        return '\n'.join([
            f'Beat: {number:03d}', '', 'Type: VOICE OVER', '',
            f"Narration clock: RESUMES at {clock(piece['start_ms'])} --> {clock(piece['end_ms'])}", '',
            'Narration state: RESUMING', '',
            f"Spoken narration: \"{row['text']}\"", '',
            f"Full source: {piece['file'] or 'MISSING.mp4'}", '',
            f"Source in: {clock(piece['in_ms'] or 0)}", '',
            f"Source out: {clock((piece['in_ms'] or 0) + span)}", '',
            'Footage audio: MUTED (0%)', '', 'Cut action: CUT TO B-ROLL', '',
            f"Visual direction: {piece['text'] or 'No matching picture'} [{piece['kind']}: {piece['reason']}]", '',
            f"On-screen caption: {caption or 'None'}", '',
            f"Continuity note: Visual plan ({piece['kind']}).", '',
            '-' * 80, ''])

    def narration_for(label, caption):
        parts, first = [], True
        for row in by_label.get(label, []):
            for piece in row['pieces']:
                parts.append(narration_block(piece, row, caption if first else ''))
                first = False
        return parts

    if beats:
        for beat, raw in zip(beats, raw_blocks):
            if beat['kind'] == 'narration':
                out += narration_for(beat['label'], beat.get('caption', ''))
            else:
                number += 1
                body = re.sub(r'^Beat:\s*\d+\s*$', f'Beat: {number:03d}', raw.strip(), count=1, flags=re.M)
                out.append(body.rstrip('-\n ') + '\n\n' + '-' * 80 + '\n')
    else:
        seen = []
        for row in rows:
            if row['span'] not in seen:
                seen.append(row['span'])
        for label in seen:
            out += narration_for(label, '')
    return '\n'.join(out)


# ---------------------------------------------------------------------- stills -> hold clips

def make_hold(root, still, length_ms, out, assets_by_name):
    """A silent clip holding one picture, long enough for every use the plan made of it.

    A frame is taken from the downloaded file at the guide's second; a person photo is
    used as uploaded. Either is fitted to 1920x1080 over a blurred copy of itself, the
    same treatment tools/photo_to_clip.py gives photographs.
    """
    import subprocess, sys as _sys, tempfile, imageio_ffmpeg
    from PIL import Image
    tools = Path(__file__).resolve().parent / 'tools'
    if str(tools) not in _sys.path:
        _sys.path.insert(0, str(tools))
    from photo_to_clip import background_graph, output_size
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    root = Path(root)
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        if still['kind'] == 'frame':
            asset = assets_by_name.get(still['file'])
            if not asset:
                raise ValueError(f"{still['file']} is not in this production, so its frame cannot be cut.")
            picture = work / 'frame.png'
            run = subprocess.run([ff, '-v', 'error', '-y', '-ss', f"{still['at_ms']/1000:.3f}", '-i', str(root / asset['path']),
                                  '-frames:v', '1', str(picture)], capture_output=True, text=True)
            if run.returncode or not picture.is_file():
                raise ValueError(f"Could not cut the frame at {still['at_ms']/1000:.1f}s from {still['file']}.")
        else:
            picture = root / still['path']
        with Image.open(picture) as im:
            target = output_size(*im.size)
        frame = work / 'composite.png'
        run = subprocess.run([ff, '-v', 'error', '-y', '-i', str(picture), '-filter_complex', background_graph(target, 'blur'),
                              '-map', '[out]', '-frames:v', '1', str(frame)], capture_output=True, text=True)
        if run.returncode:
            raise ValueError('Could not prepare the still: ' + run.stderr[-300:])
        seconds = length_ms / 1000 + 1.0
        run = subprocess.run([ff, '-v', 'error', '-y', '-loop', '1', '-i', str(frame), '-f', 'lavfi', '-i',
                              'anullsrc=channel_layout=stereo:sample_rate=48000', '-t', f'{seconds:.3f}', '-r', '30000/1001',
                              '-c:v', 'libx264', '-crf', '20', '-preset', 'ultrafast', '-tune', 'stillimage', '-pix_fmt', 'yuv420p',
                              '-c:a', 'aac', '-b:a', '96k', '-shortest', '-movflags', '+faststart', str(out)],
                             capture_output=True, text=True)
        if run.returncode or not Path(out).is_file():
            raise ValueError('Could not make the hold clip: ' + run.stderr[-300:])
    return seconds
