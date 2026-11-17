"""Person photo overlays: when the narrator says a name, that person's photo appears.

The photo is laid OVER the picture that is already playing: full screen by default
(the photo fitted to the frame over a blurred copy of itself), or as a corner card. Nothing on the
storyboard changes: no Beat is split, no cut moves, no frame is added or removed, and
the narration is untouched. The card is composited in the final render pass (and drawn
over the monitor in the preview), so turning overlays off gives back exactly the film
that was there before.

Rules
  * Timing `cue` (default): the photo is up for the whole SRT line that names the
    person, and through following lines that name them again. When one line names two
    people, the first holds until the second name is spoken, then the second takes over.
    Timing `fixed`: the photo arrives a moment before the word and stays for `hold_ms`.
  * Saying the same name again while the card is up keeps it up instead of flashing it
    off and on, up to `max_ms` in one stretch.
  * Only one card is on screen at a time. When the narrator moves on to another person
    the first card gives way to the second.
  * A card never crosses into a sound bite: sound bites show their speaker. A card that
    would have less than `min_ms` before a bite starts is left out and reported.
  * A person with no uploaded photo, or switched off, is reported and never shown.

Where a name falls inside an SRT cue is estimated from its position in the cue text.
SRT cues are a few seconds long, so this lands within a fraction of a second; the
preview shows the result so it can be checked by eye.

This module decides timing and draws the card. It does not verify who is in a photo,
where the photo came from or whether it may be published -- that is the uploader's
own responsibility and is recorded as such.
"""
from pathlib import Path
import hashlib
import re
import uuid


DEFAULTS = {
    'enabled': True,
    'style': 'full',          # full (photo fills the screen) | card (corner card)
    'timing': 'cue',          # cue (whole SRT line) | fixed (hold_ms after the name)
    'position': 'right',      # right | left | center
    'size': 'medium',         # small | medium | large
    'show_label': True,       # name and role under the photo
    'hold_ms': 3500,          # how long one mention keeps the card up
    'max_ms': 8000,           # longest one card stays up in one stretch
    'merge_gap_ms': 1500,     # same name again within this keeps the card up
    'lead_ms': 150,           # card arrives this long before the word
    'min_ms': 1500,           # shorter than this reads as a flash, so it is left out
    'fade_ms': 0,             # 0 = a clean cut on the frame (the photo pops); a dissolve if set
    'with_visual_plan': False,  # also show cards when an applied visual plan already shows the photos
    # When photos pop up. In the opening every mention shows the photo; after it, footage
    # that shows the person is left playing and the photo is used only where there is
    # none. A person's first mention always shows their photo, wherever it falls.
    'photo_opening': 'scene2',  # scene1 | scene2 | half | always
    # Slow camera move on a full-screen photo while it is up. The name label stays
    # still; only the photo moves. 'none' keeps the photo static, as before.
    'photo_motion': 'none',     # none | zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down
    'photo_motion_intensity': 'subtle',   # subtle | medium | strong
}
MOTIONS = ('none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down')
MOTION_INTENSITIES = ('subtle', 'medium', 'strong')
OPENINGS = ('scene1', 'scene2', 'half', 'always')
POSITIONS = ('right', 'left', 'center')
STYLES = ('full', 'card')
TIMINGS = ('cue', 'fixed')
# Between two photos of different people, footage showing for less than this would
# read as a flash, so the first photo is held until the second arrives.
BRIDGE_MS = 800
SIZES = {'small': 0.36, 'medium': 0.46, 'large': 0.58}   # photo height / frame height
LIMITS = {'hold_ms': (1000, 15000), 'max_ms': (2000, 30000), 'merge_gap_ms': (0, 10000),
          'lead_ms': (0, 1000), 'min_ms': (300, 5000), 'fade_ms': (0, 1000)}
# Short words that are names in nobody's case but often begin or end a full name.
_NOT_A_NAME = {'the', 'and', 'van', 'von', 'der', 'jr', 'sr', 'iii', 'mr', 'mrs', 'ms', 'dr'}
# A lone first name or surname followed by one of these is a place or an organisation
# ("Harris County", "Thompson Street"), not the person.
_PLACE_WORDS = ('County', 'Street', 'St', 'Avenue', 'Ave', 'Road', 'Rd', 'Boulevard', 'Blvd', 'Drive', 'Lane',
                'Park', 'Bayou', 'River', 'Creek', 'Lake', 'City', 'Town', 'Township', 'Parish', 'Department',
                'University', 'College', 'School', 'Elementary', 'High', 'Hospital', 'Center', 'Centre', 'Church',
                'Apartments', 'Mall', 'Bridge', 'Highway', 'Freeway', 'Station', 'Airport', 'Courthouse')


# ----------------------------------------------------------------------------- settings

def settings(project):
    """The project's overlay settings with defaults filled in and values bounded."""
    saved = project.get('person_overlay_settings') or {}
    result = dict(DEFAULTS)
    for key, value in saved.items():
        if key not in DEFAULTS:
            continue
        if key in ('enabled', 'show_label', 'with_visual_plan'):
            result[key] = bool(value)
        elif key == 'position':
            result[key] = value if value in POSITIONS else DEFAULTS['position']
        elif key == 'size':
            result[key] = value if value in SIZES else DEFAULTS['size']
        elif key == 'style':
            result[key] = value if value in STYLES else DEFAULTS['style']
        elif key == 'timing':
            result[key] = value if value in TIMINGS else DEFAULTS['timing']
        elif key == 'photo_opening':
            result[key] = value if value in OPENINGS else DEFAULTS['photo_opening']
        elif key == 'photo_motion':
            result[key] = value if value in MOTIONS else DEFAULTS['photo_motion']
        elif key == 'photo_motion_intensity':
            result[key] = value if value in MOTION_INTENSITIES else DEFAULTS['photo_motion_intensity']
        else:
            try:
                low, high = LIMITS[key]
                result[key] = int(min(high, max(low, int(value))))
            except (TypeError, ValueError):
                pass
    return result


def clean_settings(data):
    """Validate a settings update from the client. Raises ValueError with a reason."""
    if not isinstance(data, dict):
        raise ValueError('Overlay settings must be an object.')
    out = {}
    for key, value in data.items():
        if key not in DEFAULTS:
            raise ValueError(f'Unknown overlay setting: {key}.')
        if key in ('enabled', 'show_label', 'with_visual_plan'):
            out[key] = bool(value)
        elif key == 'position':
            if value not in POSITIONS:
                raise ValueError('Card position must be right, left or center.')
            out[key] = value
        elif key == 'size':
            if value not in SIZES:
                raise ValueError('Card size must be small, medium or large.')
            out[key] = value
        elif key == 'style':
            if value not in STYLES:
                raise ValueError('Photo style must be full or card.')
            out[key] = value
        elif key == 'timing':
            if value not in TIMINGS:
                raise ValueError('Photo timing must be cue (whole SRT line) or fixed.')
            out[key] = value
        elif key == 'photo_opening':
            if value not in OPENINGS:
                raise ValueError('Photos first must be scene1, scene2, half or always.')
            out[key] = value
        elif key == 'photo_motion':
            if value not in MOTIONS:
                raise ValueError('Photo motion must be one of: ' + ', '.join(MOTIONS) + '.')
            out[key] = value
        elif key == 'photo_motion_intensity':
            if value not in MOTION_INTENSITIES:
                raise ValueError('Photo motion strength must be subtle, medium or strong.')
            out[key] = value
        else:
            low, high = LIMITS[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high} milliseconds.')
            out[key] = int(value)
    return out


# ----------------------------------------------------------------------------- people

def new_person_id():
    return uuid.uuid4().hex[:12]


def ensure_ids(people):
    """Give every person a stable id (older projects stored only name/role/aliases)."""
    for person in people:
        if not person.get('id'):
            person['id'] = new_person_id()
    return people


_MUGSHOT = re.compile(r'\bmug ?shots?\b|\bbooking (?:photo|picture|image)s?\b', re.I)
_ARREST = re.compile(r'\barrest(?:ed|s)?\b|\bcharged\b|\bbooked\b|\bin custody\b|\bturned (?:himself|herself) in\b', re.I)


def is_mugshot(text):
    """True when a photo's own description calls it a mugshot or booking photo."""
    return bool(_MUGSHOT.search(text or ''))


def arrest_ms(blocks):
    """Narration time of the first SRT line that speaks of an arrest or charge, or None."""
    return next((b['start_ms'] for b in blocks if _ARREST.search(b.get('text') or '')), None)


def has_photo(person, root):
    photo = person.get('photo') or {}
    return bool(photo.get('path')) and (Path(root) / photo['path']).is_file()


_HASHES = {}


def _photo_hash(path):
    """A 256-bit difference hash of a photo (same picture = near-identical hash), or None."""
    try:
        st = path.stat(); key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _HASHES:
            from PIL import Image
            with Image.open(path) as im:
                g = im.convert('L').resize((17, 16))
                px = list(g.getdata())
            _HASHES[key] = tuple(px[r * 17 + c] > px[r * 17 + c + 1] for r in range(16) for c in range(16))
        return _HASHES[key]
    except Exception:
        return None


def shared_photos(people, root):
    """{person id: [names of the other people whose photo is the same picture]}.

    Five people filed with one family graphic all pop up with the same face: each
    person needs their own photo, so the editor says so instead of letting it pass."""
    hashes = {}
    for p in people:
        if has_photo(p, root):
            h = _photo_hash(Path(root) / p['photo']['path'])
            if h: hashes[p['id']] = h
    out = {}
    ids = list(hashes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if sum(x != y for x, y in zip(hashes[a], hashes[b])) <= 20:
                name = {p['id']: p.get('name', '') for p in people}
                out.setdefault(a, []).append(name[b]); out.setdefault(b, []).append(name[a])
    return out


def _tokens(name):
    return [t for t in re.findall(r"[A-Za-z][A-Za-z'\-]*", name or '')]


def _terms(person, people):
    """(term, short) pairs. `short` marks a lone first name or surname added automatically."""
    terms = [(person.get('name', ''), False)] + [(a, False) for a in person.get('aliases') or []]
    if person.get('short_names', True):
        others = set()
        for other in people:
            if other is person:
                continue
            for word in _tokens(other.get('name', '')) + [w for a in other.get('aliases') or [] for w in _tokens(a)]:
                others.add(word.casefold())
        words = _tokens(person.get('name', ''))
        if len(words) > 1:
            for word in (words[0], words[-1]):
                if len(word) >= 3 and word.casefold() not in _NOT_A_NAME and word.casefold() not in others:
                    terms.append((word, True))
    seen, result = set(), []
    for term, short in terms:
        term = ' '.join(term.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            result.append((term, short))
    return result


def terms_for(person, people):
    """Every spelling that counts as saying this person's name.

    The full name and the aliases always count, in any letter case. With
    `short_names` on (the default) the first name and the surname count too, but
    only when written as a name (capital first letter), not followed by a place word
    ("Harris County"), and only when no other person in this production shares that
    word -- so "Bass" never decides between Maliyah Bass and Octavius Bass. Add the
    misspellings the SRT uses ("Malia", "Irvin") as aliases, and phrases that are not
    this person ("Harris County") under `exclude`.
    """
    return [term for term, _ in _terms(person, people)]


def _matcher(people):
    """One regex for every term of every person, longest first, plus a lookup."""
    lookup, short, parts = {}, set(), []
    for person in people:
        for term, is_short in _terms(person, people):
            key = ' '.join(term.casefold().split())
            # A term two people claim (both list "Bass" as an alias) names neither.
            if key in lookup and lookup[key] is not person:
                lookup[key] = None
                continue
            lookup[key] = person
            if is_short:
                short.add(key)
            parts.append(term)
    parts = sorted(set(parts), key=lambda t: (-len(t), t))
    if not parts:
        return None, lookup, short
    body = '|'.join(r'\s+'.join(re.escape(w) for w in term.split()) for term in parts)
    return re.compile(r"(?<![\w])(?:" + body + r")(?![\w])", re.I), lookup, short


_PLACE_AFTER = re.compile(r"\s+(?:" + '|'.join(_PLACE_WORDS) + r")\b")


def _excluded(person, text, start, end):
    """True when the match sits inside a phrase the user said is not this person."""
    for phrase in person.get('exclude') or []:
        phrase = ' '.join(str(phrase).split())
        if not phrase:
            continue
        pattern = r'\s+'.join(re.escape(w) for w in phrase.split())
        for hit in re.finditer(pattern, text, re.I):
            if hit.start() <= start and end <= hit.end():
                return True
    return False


# "Maliyah's mother", "Sahara Irvin's boyfriend": the line is about somebody else.
_RELATIONS = {
    'mother': r'mother|mom|mum|mama|mommy', 'father': r'father|dad|daddy|papa', 'brother': r'brother',
    'sister': r'sister', 'son': r'son', 'daughter': r'daughter', 'grandmother': r'grandmother|grandma|nana',
    'grandfather': r'grandfather|grandpa', 'aunt': r'aunt', 'uncle': r'uncle', 'cousin': r'cousin',
    'wife': r'wife', 'husband': r'husband', 'boyfriend': r'boyfriend', 'girlfriend': r'girlfriend',
    'stepfather': r'stepfather|stepdad', 'stepmother': r'stepmother|stepmom', 'family': r'family|relatives',
    'friend': r'friend|friends', 'lawyer': r'lawyer|attorney', 'neighbor': r'neighbou?rs?',
}
_POSSESSIVE = re.compile(r"\s*(?:'|\u2019)s?\s+(?:own\s+|two[- ]year[- ]old\s+|\w+[- ]year[- ]old\s+)?(" +
                         '|'.join(f'(?:{v})' for v in _RELATIONS.values()) + r")\b", re.I)


def _relation_of(word):
    for key, pattern in _RELATIONS.items():
        if re.fullmatch(pattern, word, re.I):
            return key
    return None


def _person_with_role(people, relation, owner):
    """The one person who is `owner`'s relative of this kind, or None.

    Roles in the People list are the victim's family by default: "Mother" is the
    victim's mother. So "Maliyah's mother" finds the person whose role is Mother, but
    "Thompson's mother" does not: that needs a role naming whose mother it is
    ("Suspect's mother", "Mother of Travion Thompson").
    """
    rel = r'\b(?:' + _RELATIONS.get(relation, relation) + r')\b'
    owner_role = (owner.get('role') or '').lower()
    owner_words = [w for w in (owner.get('name') or '').split() if len(w) > 2]
    owner_words += [w for w in re.findall(r'[a-z]+', owner_role) if w in ('victim', 'suspect', 'accused', 'defendant')]
    hits = []
    for p in people:
        if p is owner:
            continue
        role = p.get('role') or ''
        if not re.search(rel, role, re.I):
            continue
        names_owner = any(re.search(r'\b' + re.escape(w) + r'\b', role, re.I) for w in owner_words)
        names_someone = bool(re.search(r"\bof\b|'s\b|\u2019s\b", role))
        if names_owner or ('victim' in owner_role and not names_someone):
            hits.append(p)
    return hits[0] if len(hits) == 1 else None


def find_mentions(blocks, people, keep_blocked=False):
    """Each time a person's name is spoken, on the narration clock (ms).

    A name followed by "'s mother" (or father, boyfriend ...) is about that relative, not
    the person named: the relative's photo is used when their role is in the People
    list, and otherwise nobody's. With keep_blocked, mentions that are not shown are
    returned too, with `blocked` saying why, so the People list can show every moment.
    """
    regex, lookup, short = _matcher(people)
    found = []
    if regex is None:
        return found
    for block in blocks:
        text = block.get('text') or ''
        if not text:
            continue
        start, end = int(block['start_ms']), int(block['end_ms'])
        for match in regex.finditer(text):
            key = ' '.join(match.group(0).casefold().split())
            person = lookup.get(key)
            if person is None:
                continue
            if key in short and (not match.group(0)[0].isupper() or _PLACE_AFTER.match(text, match.end())):
                continue
            # Place the word by its position in the cue: the cue's words are spread
            # over its duration, so a name halfway through is said about halfway in.
            at = start + round((end - start) * match.start() / max(1, len(text)))
            item = {'person_id': person['id'], 'name': person.get('name', ''), 'cue': block.get('number'),
                    'narration_ms': at, 'said': match.group(0), 'text': text,
                    'short': key in short or len(key.split()) == 1}      # one word: worth a look
            if _excluded(person, text, match.start(), match.end()):
                if keep_blocked:
                    found.append(dict(item, blocked='inside a phrase you marked "not this person"'))
                continue
            rel = _POSSESSIVE.match(text, match.end())
            if rel:
                relation = _relation_of(rel.group(1))
                other = _person_with_role(people, relation, person) if relation else None
                said = text[match.start():rel.end()]
                if other is None:
                    if keep_blocked:
                        owner = person.get('name', '')
                        word = (relation or rel.group(1)).lower()
                        role = word.title() if 'victim' in (person.get('role') or '').lower() else f"{owner.split()[0]}'s {word}"
                        found.append(dict(item, said=said, blocked=f"about {owner}'s {rel.group(1).lower()}, not {owner}; "
                                                                 f"add that person with the role \"{role}\" to show their photo"))
                    continue
                item = dict(item, person_id=other['id'], name=other.get('name', ''), said=said,
                            via=person.get('name', ''), short=False)
                person = other
            skip = {int(x) for x in person.get('skip_cues') or [] if str(x).lstrip('-').isdigit()}
            if block.get('number') in skip:
                if keep_blocked:
                    found.append(dict(item, blocked='turned off for this line'))
                continue
            found.append(item)
    found.sort(key=lambda m: m['narration_ms'])
    return found


# ----------------------------------------------------------------------------- clocks

def narration_segments(project, sound_plan):
    """Narration segments on both clocks, in ms. Bites sit in the gaps between them."""
    from documentary import build_timeline
    timeline = build_timeline(project, sound_plan or {'version': 1, 'revision': 0, 'bites': []})
    result = []
    for seg in timeline['segments']:
        if seg['kind'] != 'narration':
            continue
        result.append({'narration_in': round(seg['source_in_s'] * 1000), 'narration_out': round(seg['source_out_s'] * 1000),
                       'master_in': round(seg['timeline_in_s'] * 1000), 'master_out': round(seg['timeline_out_s'] * 1000)})
    return result, round(timeline['duration_s'] * 1000)


def to_master(segments, narration_ms):
    """(master ms, segment) for a narration moment, or (None, None) outside narration."""
    for seg in segments:
        if seg['narration_in'] <= narration_ms < seg['narration_out']:
            return seg['master_in'] + (narration_ms - seg['narration_in']), seg
    return None, None


# ----------------------------------------------------------------------------- plan

def _cue_windows(mentions, blocks, segments, conf, notes):
    """Whole-SRT-line timing: each line that names someone shows them for the whole line.

    Works on the narration clock first (lines, and where inside a line a second name
    starts), then moves every piece onto the master clock, splitting it at a sound
    bite so a photo never covers one.
    """
    cues = {b['number']: b for b in blocks}
    by_cue = {}
    for m in mentions:
        by_cue.setdefault(m['cue'], []).append(m)
    pieces = []
    for number in sorted(by_cue, key=lambda n: cues[n]['start_ms']):
        block = cues[number]
        order = []
        for m in sorted(by_cue[number], key=lambda m: m['narration_ms']):
            if order and order[-1]['person_id'] == m['person_id']:
                order[-1]['mentions'] += 1
                continue
            order.append(dict(m, mentions=1))
        line = []
        for i, m in enumerate(order):
            # The first person named holds the line from its start; anyone named later
            # in the same line takes over a moment before their name.
            start = block['start_ms'] if i == 0 else max(block['start_ms'], m['narration_ms'] - conf['lead_ms'])
            end = block['end_ms'] if i == len(order) - 1 else max(block['start_ms'], order[i+1]['narration_ms'] - conf['lead_ms'])
            line.append({'person_id': m['person_id'], 'name': m['name'], 'a': start, 'z': end,
                         'cue': number, 'said': m['said'], 'mentions': m['mentions']})
        # Someone named only in passing ("Malia's father Octavius Bass") would flash.
        # Their share of the line goes to the person next to them in the same line.
        while len(line) > 1:
            short = [i for i, piece in enumerate(line) if piece['z'] - piece['a'] < conf['min_ms']]
            if not short:
                break
            i = short[0]
            piece = line.pop(i)
            other = line[i] if i < len(line) else line[i-1]
            if i < len(line):
                other['a'] = piece['a']
            else:
                other['z'] = piece['z']
            notes.append(f"{piece['name']} (cue {number}, \"{piece['said']}\"): named only in passing, so this line "
                         f"shows {other['name']} throughout.")
        pieces.extend(line)
    windows = []
    for piece in pieces:
        for seg in segments:
            a, z = max(piece['a'], seg['narration_in']), min(piece['z'], seg['narration_out'])
            if z <= a:
                continue
            window = {'person_id': piece['person_id'], 'name': piece['name'],
                      'start_ms': seg['master_in'] + a - seg['narration_in'], 'end_ms': seg['master_in'] + z - seg['narration_in'],
                      'cues': [piece['cue']], 'said': piece['said'], 'mentions': piece['mentions'],
                      'narration_ms': a, 'seg_out': seg['master_out']}
            previous = windows[-1] if windows else None
            if previous and previous['seg_out'] == window['seg_out']:
                gap = window['start_ms'] - previous['end_ms']
                if previous['person_id'] == window['person_id'] and gap <= conf['merge_gap_ms']:
                    # The same person named again in the next line: one continuous photo.
                    previous['end_ms'] = max(previous['end_ms'], window['end_ms'])
                    previous['mentions'] += window['mentions']
                    if piece['cue'] not in previous['cues']:
                        previous['cues'].append(piece['cue'])
                    continue
                if 0 <= gap < BRIDGE_MS:
                    previous['end_ms'] = window['start_ms']
            windows.append(window)
    kept = []
    for i, window in enumerate(windows):
        following = windows[i+1] if i + 1 < len(windows) else None
        if window['end_ms'] - window['start_ms'] < conf['min_ms']:
            # A very short line ("Sahara Irvin,") followed by narration that names no
            # one: let the photo run on into it, long enough to be seen.
            limit = min(window['seg_out'], following['start_ms'] if following else window['seg_out'])
            window['end_ms'] = max(window['end_ms'], min(window['start_ms'] + conf['min_ms'], limit))
        length = window['end_ms'] - window['start_ms']
        if length < conf['min_ms']:
            why = ('the next photo' if following and following['start_ms'] <= window['end_ms']
                   else 'a sound bite' if window['end_ms'] == window['seg_out'] else 'footage returns')
            notes.append(f"{window['name']} (cue {window['cues'][0]}, \"{window['said']}\"): left out, the line gives "
                         f"only {length/1000:.1f}s before {why}.")
            continue
        kept.append(window)
    return kept



def opening_end_ms(mode, sound_plan, narration_ms):
    """End of the opening on the narration clock: where photos always pop up.

    A scene is a stretch of narration between sound bites. With no bites, the first
    scene is the first quarter and two scenes the first half.
    """
    if mode == 'always':
        return float('inf')
    if mode == 'half' or not narration_ms:
        return narration_ms / 2
    pauses = sorted({round(float(b['pause_s']) * 1000) for b in (sound_plan or {}).get('bites') or []
                     if float(b.get('pause_s') or 0) * 1000 > 500})
    want = 1 if mode == 'scene1' else 2
    if len(pauses) >= want:
        return pauses[want - 1]
    return narration_ms * (0.25 if want == 1 else 0.5)


def footage_of_people(project, root, roles=None):
    """Windows of known footage that show a person: [(file, in_ms, out_ms, {person ids})].

    Taken from what the editor knows each shot shows: the b-roll catalogue, local
    analysis, the script's visual directions and the footage sheet's descriptions.
    """
    try:
        import visual_plan as vp
        from documentary_beats import read_beats
        try:
            beats = read_beats((project.get('production_script') or {}).get('text', ''))
        except ValueError:
            beats = None
        items, _roles = vp.build_catalogue(project, root, None, beats)
    except Exception:
        return []
    return [(i['file'], i['in_ms'], i['out_ms'], set(i['people'])) for i in items
            if i.get('moving') and i.get('file') and i.get('people')]


def _on_screen(project, master_ms):
    """(file, source ms) of the picture playing at a master-clock moment, or None."""
    assets = {a['id']: a for a in project.get('assets') or []}
    for scene in project.get('scenes') or []:
        row = scene.get('plan_row') or {}
        a0 = row.get('timeline_in_ms', scene.get('frame_in', 0) * 1000 / 30)
        a1 = row.get('timeline_out_ms', scene.get('frame_out', 0) * 1000 / 30)
        if a0 <= master_ms < a1:
            asset = assets.get(scene.get('asset_id')) or {}
            name = row.get('source_file') or asset.get('original_name') or asset.get('name')
            source = row.get('source_in_ms', float(scene.get('in_s') or 0) * 1000) + (master_ms - a0)
            return name, source
    return None


def plan(project, root, sound_plan=None):
    """Every card window on the final timeline, plus what was left out and why."""
    conf = settings(project)
    people = ensure_ids(list(project.get('people') or []))
    blocks = (project.get('srt') or {}).get('blocks') or []
    summary = {p['id']: {'id': p['id'], 'name': p.get('name', ''), 'role': p.get('role', ''),
                         'terms': terms_for(p, people), 'has_photo': has_photo(p, root),
                         'show': p.get('show', True) is not False, 'mentions': 0, 'windows': 0, 'on_screen_ms': 0}
               for p in people}
    result = {'settings': conf, 'windows': [], 'notes': [], 'people': list(summary.values()),
              'mentions': 0, 'on_screen_ms': 0, 'duration_ms': 0}
    for pid, others in shared_photos(people, root).items():
        summary[pid]['same_photo_as'] = others
    groups = {}
    for info in summary.values():
        if info.get('same_photo_as'):
            groups.setdefault(frozenset([info['name'], *info['same_photo_as']]), None)
    for g in groups:
        result['notes'].append(f"{', '.join(sorted(g))} all have the same photo. Each person needs their own picture: "
                               f"replace it, or untick Show photo for the ones without one.")
    if not people or not blocks:
        return result
    if project.get('visual_plan_applied') and not conf['with_visual_plan']:
        # The applied visual plan already puts each named person's photo (or footage of
        # them) on screen; a card on top would show the same face twice.
        result['notes'].append('A visual plan is in use and already shows the photos, so name cards are off. '
                               'Tick "Also show name cards with the visual plan" to show them as well.')
        result['visual_plan'] = True
        return result
    if not (project.get('voiceover') or {}).get('duration'):
        result['notes'].append('Upload the narration so name mentions can be placed on the timeline.')
        return result
    if sound_plan is None:
        from documentary import load_plan
        sound_plan = load_plan(root)
    segments, duration = narration_segments(project, sound_plan)
    result['duration_ms'] = duration
    mentions = find_mentions(blocks, people)
    result['mentions'] = len(mentions)
    # Footage first after the opening: a mention whose picture already shows the person
    # keeps the footage; their photo fills in where no footage of them is playing.
    from documentary import narration_clock_s
    narration_total = round(narration_clock_s(project) * 1000)
    opening = opening_end_ms(conf['photo_opening'], sound_plan, narration_total)
    result['opening_ms'] = None if opening == float('inf') else int(opening)
    known = footage_of_people(project, root) if conf['photo_opening'] != 'always' else []
    introduced, kept, result['footage_lines'] = set(), [], []
    for m in mentions:
        first = m['person_id'] not in introduced
        introduced.add(m['person_id'])
        if first or m['narration_ms'] < opening or not known:
            kept.append(m)
            continue
        master, _seg = to_master(segments, m['narration_ms'])
        here = _on_screen(project, master) if master is not None else None
        if here and any(f == here[0] and a <= here[1] < b and m['person_id'] in who for f, a, b, who in known):
            result['footage_lines'].append({'person_id': m['person_id'], 'cue': m['cue']})
            continue
        kept.append(m)
    if result['footage_lines']:
        result['notes'].append(f"{len(result['footage_lines'])} later line(s) keep footage that already shows the person "
                               f"instead of covering it with their photo.")
    mentions = kept
    shown, windows, eligible = [], [], []
    arrested = arrest_ms(blocks)
    held_back = {}
    by_id = {p['id']: p for p in people}
    for m in mentions:
        info = summary[m['person_id']]
        info['mentions'] += 1
        if not info['has_photo'] or not info['show']:
            continue
        if (by_id[m['person_id']].get('photo') or {}).get('mugshot') and (arrested is None or m['narration_ms'] < arrested):
            # Their only photo is a mugshot: it never appears before the arrest is narrated.
            held_back[m['person_id']] = held_back.get(m['person_id'], 0) + 1
            continue
        eligible.append(m)
        master, seg = to_master(segments, m['narration_ms'])
        if master is None:
            continue
        shown.append(dict(m, master_ms=master, seg_in=seg['master_in'], seg_out=seg['master_out']))
    if conf['timing'] == 'cue':
        windows = _cue_windows(eligible, blocks, segments, conf, result['notes'])
        shown = []
    current = None

    def close(window, reason=None):
        if window['end_ms'] - window['start_ms'] < conf['min_ms']:
            windows.remove(window)
            result['notes'].append(
                f"{window['name']} (cue {window['cues'][0]}, \"{window['said']}\"): left out, only "
                f"{(window['end_ms']-window['start_ms'])/1000:.1f}s before {reason or 'the next card'}.")

    for m in shown:
        start = max(m['seg_in'], m['master_ms'] - conf['lead_ms'])
        end = min(m['seg_out'], m['master_ms'] + conf['hold_ms'])
        if current and current['person_id'] == m['person_id'] and current['seg_out'] == m['seg_out'] \
                and start <= current['end_ms'] + conf['merge_gap_ms']:
            # Same person again, close by: keep the card up rather than flash it.
            current['end_ms'] = min(max(current['end_ms'], end), current['start_ms'] + conf['max_ms'], m['seg_out'])
            current['mentions'] += 1
            if m['cue'] not in current['cues']:
                current['cues'].append(m['cue'])
            continue
        if current and start < current['end_ms']:
            # Someone else is named while a card is up: the new name takes over.
            current['end_ms'] = start
            close(current, f"{m['name']} is named")
        current = {'person_id': m['person_id'], 'name': m['name'], 'start_ms': start, 'end_ms': end,
                   'cues': [m['cue']], 'said': m['said'], 'mentions': 1, 'seg_out': m['seg_out'],
                   'narration_ms': m['narration_ms']}
        windows.append(current)
        if end - start < conf['min_ms']:
            close(current, 'a sound bite starts' if end == m['seg_out'] else None)
            current = None
    for pid_, count in held_back.items():
        result['notes'].append(f"{summary[pid_]['name']}'s photo is a mugshot, so {count} mention(s) before the arrest is "
                               f"narrated show no photo. Add a non-booking photo of them to show one in the opening.")
    for w in windows:
        w.pop('seg_out', None)
        info = summary[w['person_id']]
        info['windows'] += 1
        info['on_screen_ms'] += w['end_ms'] - w['start_ms']
    result['windows'] = windows
    result['on_screen_ms'] = sum(w['end_ms'] - w['start_ms'] for w in windows)
    for info in summary.values():
        if info['mentions'] and not info['has_photo']:
            result['notes'].append(f"{info['name']} is named {info['mentions']} time(s) but has no photo yet.")
        elif info['mentions'] and not info['show']:
            result['notes'].append(f"{info['name']} is switched off, so {info['mentions']} mention(s) show no card.")
        elif not info['mentions']:
            result['notes'].append(f"{info['name']} is never named in the SRT. Add the spelling the SRT uses as an alias "
                                   f"(it currently matches: {', '.join(info['terms']) or 'nothing'}).")
    return result


# ----------------------------------------------------------------------------- card

def _font(size, bold):
    from PIL import ImageFont
    names = (['DejaVuSans-Bold.ttf', 'arialbd.ttf', 'Arial Bold.ttf', 'LiberationSans-Bold.ttf'] if bold
             else ['DejaVuSans.ttf', 'arial.ttf', 'Arial.ttf', 'LiberationSans-Regular.ttf'])
    bundled = str(Path(__file__).resolve().parent / 'static' / 'fonts') + '/'
    folders = [bundled, '', '/usr/share/fonts/truetype/dejavu/', '/usr/share/fonts/truetype/liberation/',
               'C:/Windows/Fonts/', '/Library/Fonts/', '/System/Library/Fonts/Supplemental/']
    for folder in folders:
        for name in names:
            try:
                return ImageFont.truetype(folder + name, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def geometry(width, height, conf):
    """Card size and position on a width x height frame, in pixels."""
    if conf.get('style') == 'full':
        return {'card_w': width, 'card_h': height, 'canvas_w': width, 'canvas_h': height, 'x': 0, 'y': 0,
                'label_h': 0, 'shadow': 0, 'border': 0, 'photo_w': width, 'photo_h': height}
    photo_h = SIZES[conf['size']] * height
    photo_w = photo_h * 0.8
    if photo_w > 0.42 * width:            # tall frames: bound by width instead
        photo_w = 0.42 * width
        photo_h = photo_w / 0.8
    photo_w, photo_h = round(photo_w), round(photo_h)
    border = max(3, round(photo_h * 0.012))
    label_h = round(photo_h * 0.19) if conf['show_label'] else 0
    shadow = max(6, round(photo_h * 0.035))
    card_w = photo_w + 2 * border
    card_h = photo_h + 2 * border + label_h
    canvas_w, canvas_h = card_w + 2 * shadow, card_h + 2 * shadow
    margin = round(0.05 * width)
    if conf['position'] == 'left':
        x = margin
    elif conf['position'] == 'center':
        x = (width - card_w) // 2
    else:
        x = width - margin - card_w
    # Vertically a little above centre: clear of top captions and bottom subtitles.
    y = max(round(0.06 * height), round((height - card_h) / 2 - 0.03 * height))
    return {'photo_w': photo_w, 'photo_h': photo_h, 'border': border, 'label_h': label_h, 'shadow': shadow,
            'card_w': card_w, 'card_h': card_h, 'canvas_w': canvas_w, 'canvas_h': canvas_h,
            # Where the canvas (card plus its shadow) goes on the frame.
            'x': x - shadow, 'y': y - shadow}


def _label_lines(draw, name, role, room, height_px):
    lines = [(name.upper(), True, 0.36, (255, 255, 255, 255))]
    if role:
        lines.append((role, False, 0.25, (235, 190, 70, 255)))
    sized = []
    for text, bold, share, colour in lines:
        size = max(8, round(height_px * share))
        font = _font(size, bold)
        while size > 8 and draw.textlength(text, font=font) > room:
            size -= 1
            font = _font(size, bold)
        sized.append((text, font, colour, draw.textbbox((0, 0), text, font=font)))
    return sized


def draw_full(photo_path, name, role, width, height, conf, focus_y=0.3):
    """The photo filling the frame: fitted whole over a blurred copy of itself.

    A photo the shape of the frame simply fills it. Any other shape is shown whole,
    never stretched or cropped, with a soft blurred fill behind it -- the way news
    graphics show a portrait in a wide frame.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    with Image.open(photo_path) as source:
        photo = ImageOps.exif_transpose(source).convert('RGB')
    w, h = photo.size
    frame = Image.new('RGB', (width, height), (0, 0, 0))
    if abs((w / h) / (width / height) - 1) <= 0.03:
        frame = photo.resize((width, height), Image.LANCZOS)
    else:
        cover = max(width / w, height / h)
        back = photo.resize((max(1, round(w * cover)), max(1, round(h * cover))), Image.LANCZOS)
        left, top = (back.width - width) // 2, round((back.height - height) * max(0.0, min(1.0, focus_y)))
        back = back.crop((left, top, left + width, top + height))
        back = back.filter(ImageFilter.GaussianBlur(max(8, width // 60)))
        frame = ImageEnhance.Brightness(back).enhance(0.55)
        fit = min(width / w, height / h)
        front = photo.resize((max(1, round(w * fit)), max(1, round(h * fit))), Image.LANCZOS)
        frame.paste(front, ((width - front.width) // 2, (height - front.height) // 2))
    frame = frame.convert('RGBA')
    if conf.get('show_label', True) and name:
        _lower_third(frame, name, role, width, height)
    return frame, geometry(width, height, conf)


def _lower_third(frame, name, role, width, height):
    """Draw the name/role lower third onto an RGBA frame, in place."""
    from PIL import ImageDraw
    # A lower third, kept above where SRT subtitles sit.
    draw = ImageDraw.Draw(frame, 'RGBA')
    bar_h = round(height * 0.11)
    pad = round(min(width, height) * 0.03)
    sized = _label_lines(draw, name, role, round(width * 0.5), bar_h)
    text_w = max(draw.textlength(t, font=f) for t, f, _, _ in sized)
    top = round(height * 0.70)
    left = round(width * 0.05)
    draw.rectangle((left, top, left + text_w + 2 * pad, top + bar_h), fill=(14, 14, 16, 215))
    draw.rectangle((left, top, left + max(4, pad // 4), top + bar_h), fill=(235, 190, 70, 255))
    gap = round(bar_h * 0.06)
    total = sum(b[3] - b[1] for *_, b in sized) + gap * (len(sized) - 1)
    y = top + (bar_h - total) // 2
    for text, font, colour, box in sized:
        draw.text((left + pad + pad // 3, y - box[1]), text, font=font, fill=colour)
        y += box[3] - box[1] + gap


def draw_card(photo_path, name, role, width, height, conf, focus_y=0.3):
    """The card as an RGBA image sized for a width x height frame."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    if conf.get('style') == 'full':
        return draw_full(photo_path, name, role, width, height, conf, focus_y)
    g = geometry(width, height, conf)
    with Image.open(photo_path) as source:
        photo = ImageOps.exif_transpose(source).convert('RGB')
    # Fill a 4:5 portrait. Faces sit in the upper part of most photos, so a tall photo
    # is cropped toward its top rather than its middle.
    target = g['photo_w'] / g['photo_h']
    w, h = photo.size
    if w / h > target:
        new_w = round(h * target)
        left = (w - new_w) // 2
        photo = photo.crop((left, 0, left + new_w, h))
    else:
        new_h = round(w / target)
        top = round((h - new_h) * max(0.0, min(1.0, focus_y)))
        photo = photo.crop((0, top, w, top + new_h))
    photo = photo.resize((g['photo_w'], g['photo_h']), Image.LANCZOS)
    canvas = Image.new('RGBA', (g['canvas_w'], g['canvas_h']), (0, 0, 0, 0))
    s = g['shadow']
    shade = Image.new('L', canvas.size, 0)
    ImageDraw.Draw(shade).rectangle((s, s + s // 3, s + g['card_w'], s + g['card_h'] + s // 3), fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(s / 2))
    canvas.paste((0, 0, 0, 255), (0, 0), shade)
    card = Image.new('RGBA', (g['card_w'], g['card_h']), (255, 255, 255, 255))
    card.paste(photo, (g['border'], g['border']))
    if g['label_h']:
        draw = ImageDraw.Draw(card)
        top = g['photo_h'] + 2 * g['border']
        draw.rectangle((0, top, g['card_w'], g['card_h']), fill=(18, 18, 20, 255))
        pad = round(g['card_w'] * 0.06)
        room = g['card_w'] - 2 * pad
        sized = _label_lines(draw, name, role, room, g['label_h'])
        gap = round(g['label_h'] * 0.06)
        total = sum(b[3] - b[1] for *_, b in sized) + gap * (len(sized) - 1)
        y = top + (g['label_h'] - total) // 2
        for text, font, colour, box in sized:
            draw.text((pad, y - box[1]), text, font=font, fill=colour)
            y += box[3] - box[1] + gap
    canvas.alpha_composite(card, (s, s))
    return canvas, g


def card_key(person, root, width, height, conf):
    photo = Path(root) / (person.get('photo') or {}).get('path', '')
    stat = photo.stat()
    fields = [person.get('name', ''), person.get('role', ''), str(person.get('focus_y', 0.3)), str(stat.st_size),
              str(stat.st_mtime_ns), str(width), str(height), conf['size'], conf['position'], str(conf['show_label']), conf['style'], 'v2']
    return hashlib.sha256('|'.join(fields).encode()).hexdigest()[:24]


def motion_camera(person, conf):
    """The camera move for this person's full-screen photo, or None when it stays still.

    A person's own saved `camera` wins; otherwise the overlay setting's move is aimed at
    the person's focus point (the height of the face in the photo, `focus_y`).
    """
    if conf.get('style') != 'full':
        return None
    from cinematic import normalise, preset, is_active
    try:
        own = normalise(person.get('camera')) if person.get('camera') else None
    except ValueError:
        own = None
    if own is not None:
        return own if is_active(own) else None
    move = conf.get('photo_motion', 'none')
    if move == 'none':
        return None
    # The photo is fitted whole and centred, so its focus sits a little nearer the
    # frame's middle than it does in the photo itself.
    fy = 0.5 + (float(person.get('focus_y', 0.3)) - 0.5) * 0.9
    cam = normalise(preset(move, conf.get('photo_motion_intensity', 'subtle'), (0.5, fy)))
    return cam if is_active(cam) else None


def layer_files(person, root, width, height, conf, folder=None):
    """(photo layer JPEG, label layer PNG or None) for a moving full-screen photo.

    The photo moves and the label must not, so they are drawn apart: the photo with no
    label, and the label alone on a transparent frame.
    """
    folder = Path(folder or Path(root) / '.cache' / 'person-cards')
    folder.mkdir(parents=True, exist_ok=True)
    key = card_key(person, root, width, height, dict(conf, show_label=False))
    photo = folder / (key + '-photo.jpg')
    if not photo.is_file():
        image, _ = draw_full(Path(root) / person['photo']['path'], '', '', width, height,
                             dict(conf, show_label=False), float(person.get('focus_y', 0.3)))
        temp = photo.with_name(photo.stem + '.' + uuid.uuid4().hex[:8] + photo.suffix)
        image.convert('RGB').save(temp, quality=93); temp.replace(photo)
    if not (conf.get('show_label', True) and person.get('name')):
        return photo, None
    label = folder / (card_key(person, root, width, height, conf) + '-label.png')
    if not label.is_file():
        from PIL import Image
        frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        _lower_third(frame, person.get('name', ''), person.get('role', ''), width, height)
        temp = label.with_name(label.stem + '.' + uuid.uuid4().hex[:8] + label.suffix)
        frame.save(temp); temp.replace(label)
    return photo, label


def card_file(person, root, width, height, conf, folder=None):
    """Render (or reuse) the card PNG for this person at this frame size."""
    folder = Path(folder or Path(root) / '.cache' / 'person-cards')
    folder.mkdir(parents=True, exist_ok=True)
    # A full-screen photo is opaque, so it is stored as a JPEG: a fraction of the size
    # of a PNG, and much quicker for the export to read once per frame.
    full = conf.get('style') == 'full'
    out = folder / (card_key(person, root, width, height, conf) + ('.jpg' if full else '.png'))
    if not out.is_file():
        image, _ = draw_card(Path(root) / person['photo']['path'], person.get('name', ''), person.get('role', ''),
                             width, height, conf, float(person.get('focus_y', 0.3)))
        temp = out.with_name(out.stem + '.' + uuid.uuid4().hex[:8] + out.suffix)
        if full:
            image.convert('RGB').save(temp, quality=93)
        else:
            image.save(temp)
        temp.replace(out)
    return out


# ----------------------------------------------------------------------------- render

def covered_spans(project, root, sound_plan):
    """(start_s, end_s) on the final timeline where a full-screen photo hides the footage.

    The script's on-screen captions describe the footage ("Sunset Crossing
    Apartments"), so they are held back while a full-screen photo covers it.
    """
    conf = settings(project)
    if not conf['enabled'] or conf['style'] != 'full':
        return []
    return [(w['start_ms'] / 1000, w['end_ms'] / 1000) for w in plan(project, root, sound_plan)['windows']]


def frame_of(seconds, fps):
    """The output frame a moment falls on: the same rounding the picture cuts use."""
    from fractions import Fraction
    return int((Fraction(str(seconds)) * Fraction(str(fps)) + Fraction(1, 2)).__floor__())


def _frames_on(f0, f1, fps):
    """ffmpeg expression true for output frames f0 .. f1-1 exactly."""
    from fractions import Fraction
    fps = Fraction(str(fps))
    return f'gte(t,{float((f0 - Fraction(1, 2)) / fps):.6f})*lt(t,{float((f1 - Fraction(1, 2)) / fps):.6f})'


def caption_enable(start_s, end_s, spans, fps=None):
    """ffmpeg `enable` expression: on from start to end, except under a full-screen photo.

    With `fps`, it is written in frame numbers on the picture's own cut grid, so a
    caption comes on and goes off on exactly the frame where the shot cuts.
    """
    if fps:
        expr = _frames_on(frame_of(start_s, fps), frame_of(end_s, fps), fps)
        inside = [_frames_on(frame_of(x, fps), frame_of(y, fps), fps) for x, y in spans if x < end_s and y > start_s]
        return expr + (f"*not({'+'.join(inside)})" if inside else '')
    expr = f'gte(t,{start_s:.3f})*lt(t,{end_s:.3f})'
    inside = [f'between(t,{a:.3f},{b:.3f})' for a, b in spans if a < end_s and b > start_s]
    return expr + (f"*not({'+'.join(inside)})" if inside else '')



def render_filters(project, root, sound_plan, width, height, rate, work, first_input, between=None, cache=None):
    """ffmpeg inputs and filter chain that put the cards over the finished picture.

    Returns (input_args, filter_steps, count). `filter_steps` are filtergraph pieces
    that read [base] and leave [cards]; with no cards there are none. Every card input
    lasts exactly its window, so the frame count and timing of the film are unchanged.

    `between=(first_frame, end_frame)` keeps only the cards on screen in those frames
    (one piece of the film; its picture must already be on the film's clock).
    `cache` (a dict) keeps the plan and card files between calls for the same render.
    """
    conf = settings(project)
    if not conf['enabled']:
        return [], [], 0
    if cache is not None and 'plan' in cache:
        data = cache['plan']
    else:
        data = plan(project, root, sound_plan)
        if cache is not None:
            cache['plan'] = data
    people = {p['id']: p for p in project.get('people') or []}
    windows = [w for w in data['windows'] if w['person_id'] in people]
    if not windows:
        return [], [], 0
    inputs, steps, label = [], [], 'base'
    cards = cache.setdefault('cards', {}) if cache is not None else {}
    starts = {w['start_ms'] for w in windows}
    ends = {w['end_ms'] for w in windows}
    from fractions import Fraction
    fr = Fraction(str(rate))
    used = 0
    next_input = first_input
    for w in windows:
        # Snapped to the picture's frame grid (the rounding every cut uses): the photo
        # appears on the exact frame its line starts and is gone on the frame it ends.
        f0, f1 = frame_of(w['start_ms'] / 1000, fr), frame_of(w['end_ms'] / 1000, fr)
        if f1 <= f0:
            continue
        if between is not None and not (f0 < between[1] and f1 > between[0]):
            continue
        person = people[w['person_id']]
        camera = motion_camera(person, conf)
        if w['person_id'] not in cards:
            if camera:
                layers = layer_files(person, root, width, height, conf, Path(work) / 'person-cards')
                cards[w['person_id']] = (layers, geometry(width, height, conf))
            else:
                path = card_file(person, root, width, height, conf, Path(work) / 'person-cards')
                cards[w['person_id']] = (path, geometry(width, height, conf))
        path, g = cards[w['person_id']]
        k = used; used += 1
        start = float(f0 / fr)
        length = (f1 - f0) / fr
        fade = min(conf['fade_ms'] / 1000, length / 3)
        loop = ['-loop', '1', '-framerate', rate, '-t', f'{float(length):.6f}', '-i']
        if camera:
            # The photo moves over the card's own time; the label rides on top, still.
            from cinematic import ffmpeg_filter
            photo_layer, label_layer = path
            inputs += loop + [str(photo_layer)]
            moved = f'[{next_input}:v]format=rgba,{ffmpeg_filter(camera, width, height, 0, int(f1 - f0))}'
            next_input += 1
            if label_layer:
                inputs += loop + [str(label_layer)]
                steps.append(f'{moved}[ph{k}]')
                steps.append(f'[{next_input}:v]format=rgba[lb{k}]')
                steps.append(f'[ph{k}][lb{k}]overlay=0:0:format=auto,format=rgba[pc{k}]')
                next_input += 1
            else:
                steps.append(f'{moved},format=rgba[pc{k}]')
            index = None
        else:
            inputs += loop + [str(path)]
            index = next_input; next_input += 1
        # Fade only where a photo meets footage. Where one photo hands straight over
        # to the next, a fade would dip to the footage underneath for a few frames.
        fades = ''
        if fade > 0 and w['start_ms'] not in ends:
            fades += f'fade=t=in:st=0:d={fade:.3f}:alpha=1,'
        if fade > 0 and w['end_ms'] not in starts:
            fades += f'fade=t=out:st={float(length)-fade:.6f}:d={fade:.3f}:alpha=1,'
        source = f'[{index}:v]format=rgba,' if index is not None else f'[pc{k}]'
        steps.append(f'{source}{fades}setpts=PTS-STARTPTS+{start:.6f}/TB[card{k}]')
        nxt = f'over{k}'
        # On from frame f0 up to (not including) frame f1. Written as times half a frame
        # before each cut, so exactly those frames are chosen: never one frame early,
        # never one frame into the next shot.
        steps.append(f"[{label}][card{k}]overlay=x={g['x']}:y={g['y']}:eof_action=pass:"
                     f"enable='{_frames_on(f0, f1, fr)}'[{nxt}]")
        label = nxt
    if steps:
        # The last overlay is the graph's output.
        steps[-1] = steps[-1][:steps[-1].rindex('[')] + '[cards]'
    return inputs, steps, (len(windows) if between is None else used)
