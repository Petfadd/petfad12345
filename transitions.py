"""A curated transition library, and the rule that picks one for each cut.

The catalogue is deliberately short. FFmpeg's xfade filter offers 57 transitions,
and a library that long stops being a choice and becomes a menu nobody reads. These
are the ones that survive being used in a documentary: they read as edits rather than
as effects, and every one of them is symmetric enough not to look broken on a cut
between two wildly different scenes.

Nothing here changes timing. A transition overlaps the outgoing and incoming picture
inside the handles the timeline already reserves, so narration, SRT cues, duration
and audio sync are untouched -- which is the same contract `dissolve` already had.
"""
from __future__ import annotations

# name -> (ffmpeg xfade name, label, one-line description)
#
# `cut` is a real member of the library, not a fallback: on a hard news cut it is the
# most professional choice available, and auto-suggest picks it more often than any
# effect. The descriptions are short because they are shown in a grid of cards.
LIBRARY = {
    'cut': ('', 'Cut', 'Hard cut. No overlap.'),
    'fade': ('fade', 'Cross Fade', 'One scene dissolves into the next.'),
    'fadeblack': ('fadeblack', 'Black Fade', 'Dips through black between scenes.'),
    'fadewhite': ('fadewhite', 'White Fade', 'Flashes through white. Use sparingly.'),
    'dissolve': ('dissolve', 'Dissolve', 'Soft grain blend between pictures.'),
    'distance': ('distance', 'Distance', 'Next scene pushes in through depth.'),
    'pixelize': ('pixelize', 'Pixelate', 'Breaks into blocks, then resolves.'),
    'circleopen': ('circleopen', 'Circle Open', 'Reveal opens from the centre.'),
    'slideleft': ('slideleft', 'Slide', 'Next scene slides in from the right.'),
    'whip': ('slideleft', 'Whip Pan', 'A very fast sideways push into the next scene.'),
    'smoothup': ('smoothup', 'Smooth Rise', 'Picture lifts upward into the next.'),
    'zoomin': ('zoomin', 'Zoom Through', 'Camera pushes through into the next scene.'),
    'fadefast': ('fadefast', 'Quick Fade', 'A short, energetic cross fade.'),
    'fadeslow': ('fadeslow', 'Long Fade', 'A slow blend for reflective beats.'),
    'fadegrays': ('fadegrays', 'Grey Fade', 'Drains to grey, then into the next scene.'),
    'hblur': ('hblur', 'Blur Blend', 'Smears softly from one scene into the next.'),
    'wipeleft': ('wipeleft', 'Wipe', 'A clean edge wipes the next scene across.'),
    'slideright': ('slideright', 'Slide Right', 'Next scene slides in from the left.'),
    'slideup': ('slideup', 'Slide Up', 'Next scene slides up from below.'),
    'smoothleft': ('smoothleft', 'Smooth Pan', 'A soft panning blend to the next scene.'),
    'circleclose': ('circleclose', 'Circle Close', 'The picture closes to a point, then opens.'),
    'radial': ('radial', 'Clock Wipe', 'Sweeps round like a clock hand.'),
    'squeezeh': ('squeezeh', 'Squeeze', 'Squeezes away to reveal the next scene.'),
    'horzopen': ('horzopen', 'Split Open', 'Opens from the middle like a door.'),
    'diagtl': ('diagtl', 'Diagonal', 'A diagonal edge reveals the next scene.'),
}


# What the export page offers in its "Intensity" control. A stronger setting is
# allowed to choose a more visible transition; subtle stays close to a cut.
INTENSITY = {
    'subtle': ('Subtle', ['cut', 'fade', 'dissolve', 'fadefast']),
    'balanced': ('Balanced', ['cut', 'fade', 'dissolve', 'fadefast', 'fadeslow', 'fadeblack']),
    'expressive': ('Expressive', list(LIBRARY)),
}

# Durations in frames at 30fps. The renderer rounds to the nearest whole frame, so
# these are expressed in frames directly rather than seconds that drift.
DURATION = {
    'quick': ('Quick · 0.33 s', 10),
    'standard': ('Standard · 0.50 s', 15),
    'slow': ('Slow · 1.00 s', 30),
}

DEFAULT_DURATION = 'standard'
DEFAULT_INTENSITY = 'balanced'
DURATION_FRAMES = {k: v[1] for k, v in DURATION.items()}


def label(key):
    return LIBRARY.get(key, LIBRARY['cut'])[1]


def is_transition(key):
    return key in LIBRARY and key != 'cut'


def catalogue():
    """Everything the library dialog needs, in one payload."""
    return {'transitions': [{'key': k, 'label': v[1], 'detail': v[2], 'ffmpeg': v[0],
                             'overlaps': bool(v[0])} for k, v in LIBRARY.items()],
            'intensity': [{'key': k, 'label': v[0]} for k, v in INTENSITY.items()],
            'durations': [{'key': k, 'label': v[0], 'frames': v[1]} for k, v in DURATION.items()],
            'defaults': {'intensity': DEFAULT_INTENSITY, 'duration': DEFAULT_DURATION}}


def _pool(intensity):
    return INTENSITY.get(intensity, INTENSITY[DEFAULT_INTENSITY])[1]


# Which transitions suit which feeling. The list is ordered: the first entry that is
# allowed by the current intensity wins, so raising intensity enriches the result
# without ever changing the fact that a reflective beat gets a soft transition.
AFFINITY = {
    'grief': ['fadeslow', 'fade', 'dissolve'],
    'mourning': ['fadeslow', 'fade', 'dissolve'],
    'remembrance': ['fadeslow', 'fade', 'dissolve'],
    'loss': ['fadeslow', 'fade', 'dissolve'],
    'orientation': ['fade', 'smoothup', 'slideleft'],
    'place': ['fade', 'smoothup', 'slideleft'],
    'location': ['fade', 'smoothup', 'slideleft'],
    'scrutiny': ['cut', 'fadefast', 'distance'],
    'investigation': ['fadefast', 'distance', 'cut'],
    'uncertainty': ['dissolve', 'fade', 'cut'],
    'legal': ['cut', 'fade', 'fadeblack'],
    'accountability': ['cut', 'fadeblack', 'fadefast'],
    'clarity': ['cut', 'fade', 'dissolve'],
    'attention / restraint': ['cut', 'fade', 'dissolve'],
}
DEFAULT_AFFINITY = ['cut', 'fade', 'dissolve']


def transition_prev_handle(key, scene):
    """Frames the blend INTO this scene's successor would consume from this scene."""
    return 0 if key == 'cut' else max(1, DURATION_FRAMES.get(key, 15))


def _inside_one_take(scenes, i):
    """True when scene i continues the previous take rather than cutting to a new shot.

    The test is the source interval, not the filename: consecutive beats whose intervals
    touch or overlap are the same continuous run, and blending inside one run is what
    looks like a fault. Beats pulled from different parts of the same clip are separate
    shots and take a transition like any other.
    """
    if i == 0:
        return False
    prev, cur = scenes[i - 1], scenes[i]
    if prev.get('asset_id') != cur.get('asset_id'):
        return False
    if prev.get('in_s') is None or cur.get('in_s') is None:
        # Without source clocks, touching timeline frames mean one continuous segment.
        return prev.get('frame_out') == cur.get('frame_in')
    return abs(float(prev['in_s']) - float(cur['in_s'])) < 0.002


def suggest(scene, previous=None, intensity=DEFAULT_INTENSITY, is_last=False,
            same_source=False, duration_frames=None):
    """Pick a transition for ONE boundary, from that scene's own content.

    The rules, in order:

    1. The last scene never carries a transition -- there is nothing to blend into.
    2. A cut that stays inside one continuous take stays a cut. Blending across a jump
       cut inside a single shot looks like a mistake, not a stylistic choice. Two beats
       taken from the same FILE are not that: a documentary draws many beats from one
       interview clip, and those are ordinary cuts between separate shots.
    3. A very short beat (under half a second) gets a fade at most: any transition
       long enough to see would eat the whole shot.
    4. Otherwise the scene's emotion decides, via AFFINITY.
    5. Two consecutive scenes never receive the same transition unless both resolved
       to a cut. Repeating an effect on every boundary is what makes auto-generated
       edits feel mechanical. Adjacent blends are allowed, but they must leave a whole
       scene between them: a blend may not be longer than the scene it leads into, so
       when two would overlap the incoming scene the second falls back to a cut.
    """
    if is_last:
        return 'cut'
    if same_source:
        return 'cut'
    allowed = _pool(intensity)
    tone = f"{scene.get('emotion', '')} {scene.get('purpose', '')}".lower()

    candidates = []
    for key in AFFINITY:
        if key in tone:
            candidates = AFFINITY[key]
            break
    if not candidates:
        candidates = DEFAULT_AFFINITY
    # Intensity gates the list without discarding its order: Subtle keeps whatever in
    # the affinity list is allowed, falling back to a cut rather than to a loud effect.
    usable = [c for c in candidates if c in allowed]
    if not usable:
        usable = ['cut']

    choice = usable[0]
    if duration_frames is not None and duration_frames < 15 and choice != 'cut':
        # Under half a second there is no room for anything but the briefest blend.
        choice = 'fadefast' if 'fadefast' in allowed else 'cut'
    if previous is not None and choice == previous and choice != 'cut':
        # Step to the next acceptable option so no two boundaries repeat an effect.
        # The wider pool is consulted before falling back to a cut, because "the same
        # effect twice" is a worse outcome than "a slightly less apt effect once".
        rest = [c for c in usable if c != choice] or \
               [c for c in allowed if c != choice and c != 'cut']
        choice = rest[0] if rest else 'cut'
    # A run of cuts is not a problem; a run of the SAME effect is. But an entirely
    # cut-only result on a film whose beats are all investigative would still fail the
    # brief of "make it more engaging", so every other boundary is asked to carry a
    # transition when the intensity allows one at all.
    return choice


def suggest_all(scenes, intensity=DEFAULT_INTENSITY, enrich=True):
    """A transition per scene, each chosen against its own content and its neighbour.

    With `enrich`, a timeline where the affinity rules produced nothing but cuts gets
    alternating transitions on every other boundary. This is the difference between
    "the rules were applied" and "the film has rhythm": a documentary entirely of hard
    cuts is correct but flat, and the request was for something more engaging. Beats
    that genuinely must stay cuts -- the last scene, and runs inside one continuous
    take -- are never touched.
    """
    out = []
    previous = None
    for i, scene in enumerate(scenes):
        same = _inside_one_take(scenes, i)
        length = scene.get('frame_out', 0) - scene.get('frame_in', 0)
        key = suggest(scene, previous=previous, intensity=intensity,
                      is_last=i == len(scenes) - 1,
                      same_source=same, duration_frames=length)
        # A blend needs a handle longer than nothing but shorter than the scene it
        # leads into. If this scene is too short to carry the previous blend as well,
        # it must not open on one.
        if i and transition_prev_handle(out[-1], scenes[i - 1]) >= length:
            key = 'cut'
        out.append(key)
        previous = key
    if enrich:
        allowed = [c for c in _pool(intensity) if c != 'cut']
        if allowed:
            soft = [c for c in ('fade', 'dissolve', 'fadefast', 'fadeslow') if c in allowed]
            last = len(scenes) - 1
            # Two boundaries in a row must never both be cuts on a film that has room
            # for a transition: a run of hard cuts is what makes an automatic pass look
            # like it did nothing. Only a take, or a beat too short to carry a blend,
            # is allowed to interrupt that rhythm.
            for i, scene in enumerate(scenes):
                # `out[i]` is the transition on the boundary AFTER scene i, chosen from
                # scene i's own content. Whether the previous boundary already carries
                # a transition therefore depends on out[i-1], and whether this one must
                # stay a cut depends on the take scene i continues.
                if i == last or out[i] != 'cut':
                    continue
                same = _inside_one_take(scenes, i)
                short = (scene.get('frame_out', 0) - scene.get('frame_in', 0)) < 15
                if same or short:
                    continue
                if i > 0 and out[i - 1] != 'cut':
                    continue          # one transition already separates these beats
                # Avoid repeating whichever effect the previous boundary used.
                choice = next((c for c in soft if c != (out[i - 1] if i else None)), None)
                out[i] = choice or 'cut'
    return out


# ---------------------------------------------------------------------------------
# Documentary (Beat-built) timelines
#
# A Beat timeline is cut at every subtitle line, so most scene boundaries are not
# picture cuts at all: the same footage simply carries on. A transition only means
# something where the picture really changes -- a different file, a jump within one
# file, or a sound bite starting or ending. These helpers find those boundaries the
# same way the renderer merges continuous footage, so what you set is what renders.

# How long each transition runs by default, in frames at 30 fps.
DEFAULT_FRAMES = {'fadefast': 8, 'fadeslow': 30, 'fadeblack': 20, 'fadewhite': 12, 'fadegrays': 20, 'whip': 6}

# The production script's "Cut action" line, read as the transition INTO that Beat.
# Matched in order, longest phrases first; anything that just says CUT stays a cut.
CUT_ACTION_WORDS = [
    ('whip pan', 'whip'), ('whip', 'whip'), ('dip to black', 'fadeblack'), ('fade through black', 'fadeblack'), ('fade to black', 'fadeblack'),
    ('black fade', 'fadeblack'), ('dip to white', 'fadewhite'), ('white flash', 'fadewhite'),
    ('flash', 'fadewhite'), ('quick fade', 'fadefast'), ('fast fade', 'fadefast'),
    ('slow fade', 'fadeslow'), ('long fade', 'fadeslow'), ('grey fade', 'fadegrays'), ('gray fade', 'fadegrays'),
    ('cross fade', 'fade'), ('crossfade', 'fade'), ('cross-fade', 'fade'), ('dissolve', 'dissolve'),
    ('blur', 'hblur'), ('wipe', 'wipeleft'), ('slide up', 'slideup'), ('slide right', 'slideright'),
    ('slide', 'slideleft'), ('push', 'slideleft'), ('pan', 'smoothleft'), ('rise', 'smoothup'),
    ('zoom', 'zoomin'), ('distance', 'distance'), ('circle close', 'circleclose'), ('iris', 'circleopen'),
    ('circle', 'circleopen'), ('clock', 'radial'), ('squeeze', 'squeezeh'), ('split', 'horzopen'),
    ('diagonal', 'diagtl'), ('pixel', 'pixelize'), ('pixelate', 'pixelize'), ('clock wipe', 'radial'),
    ('zoom through', 'zoomin'), ('fade', 'fade'),
]


def from_cut_action(text):
    """The library key a script's Cut action asks for, 'auto', or None for a plain cut.

    `FADE IN FROM BLACK` on the opening Beat is the film's fade-in, handled separately,
    so it is not read as a transition.
    """
    t = ' '.join(str(text or '').lower().replace('_', ' ').split())
    if not t or 'fade in from black' in t:
        return None
    if t in LIBRARY:
        return t if t != 'cut' else None
    for key, (_, name, _) in LIBRARY.items():
        if t == name.lower():
            return key if key != 'cut' else None
    if 'auto' in t:
        return 'auto'
    import re
    # Whole words, longest phrase first: "CLOCK WIPE" is not a plain wipe, and "PAN"
    # must not fire inside "PANORAMA".
    for phrase, key in sorted(CUT_ACTION_WORDS, key=lambda x: -len(x[0])):
        if re.search(r'(?<![a-z])' + re.escape(phrase) + r'(?![a-z])', t):
            return key
    return None


def scene_kind(scene):
    row = scene.get('plan_row') or {}
    return 'sound_bite' if row.get('bite_id') or 'sound-bite' in str(row.get('continuity') or '') else 'narration'


def is_picture_cut(previous, scene):
    """True when the picture really changes between two consecutive scenes."""
    if previous.get('asset_id') != scene.get('asset_id'):
        return True
    if scene_kind(previous) != 'narration' or scene_kind(scene) != 'narration':
        return True
    if (previous.get('picture_scale') or 100) != (scene.get('picture_scale') or 100):
        return True
    a, b = previous.get('plan_row') or {}, scene.get('plan_row') or {}
    if a.get('source_out_ms') is None or b.get('source_in_ms') is None:
        return True
    return abs(float(a['source_out_ms']) - float(b['source_in_ms'])) > 40


def documentary_cuts(scenes):
    """Indexes i where the boundary AFTER scene i is a real picture cut."""
    return [i for i in range(len(scenes) - 1) if is_picture_cut(scenes[i], scenes[i + 1])]


def shot_frames(scenes, cuts):
    """Frame length of the shot that runs up to each cut, and of the shot after it."""
    out = {}
    starts = [0] + [c + 1 for c in cuts]
    ends = [c + 1 for c in cuts] + [len(scenes)]
    lengths = [scenes[e - 1]['frame_out'] - scenes[s]['frame_in'] for s, e in zip(starts, ends)]
    for n, c in enumerate(cuts):
        out[c] = (lengths[n], lengths[n + 1])
    return out


def frames_for(key, duration=None):
    if key == 'cut':
        return 0
    if duration in DURATION:
        base = DURATION[duration][1]
        if key == 'fadefast':
            return max(6, base * 2 // 3)
        if key == 'fadeslow':
            return base * 2
        return base
    return DEFAULT_FRAMES.get(key, 15)


def fit_frames(key, frames, before, after):
    """Shorten a transition so it never eats a whole shot. Too short a shot gets a cut."""
    if key == 'cut' or not frames:
        return 'cut', 0
    room = min(after - 1, before)
    if room < 6:
        return 'cut', 0
    return key, max(4, min(frames, room // 2 if room < 24 else room))


# What "Auto" may use, from gentle to lively. Every pool is ordered so that a run of
# cuts moves through it, giving each cut a different transition from its neighbours.
AUTO_STYLES = {
    'subtle': ('Subtle', ['fade', 'dissolve', 'fadefast', 'fadeslow']),
    'balanced': ('Balanced', ['fade', 'dissolve', 'fadeblack', 'fadefast', 'smoothup', 'hblur',
                              'fadeslow', 'distance', 'fadegrays']),
    'expressive': ('Expressive · every cut different',
                   ['fade', 'slideleft', 'dissolve', 'zoomin', 'fadeblack', 'wipeleft', 'smoothup',
                    'circleopen', 'hblur', 'slideright', 'distance', 'fadefast', 'radial', 'smoothleft',
                    'fadegrays', 'slideup', 'squeezeh', 'horzopen', 'diagtl', 'circleclose', 'pixelize',
                    'fadewhite', 'fadeslow']),
}
# Into or out of a person speaking, keep it soft: a slide or a wipe across someone's
# face as they start talking reads as a mistake, not a style.
SPEAKER_SAFE = ['fade', 'dissolve', 'fadefast', 'hblur', 'fadeblack', 'fadegrays']


def auto_documentary(scenes, style='balanced', duration=None, seed=0):
    """{scene index: (key, frames)} for every real cut, each different from the last.

    `seed` reshuffles the order the style's transitions are used in, so pressing Auto
    again gives a fresh mix. The same seed always gives the same result.
    """
    import random
    pool = list(AUTO_STYLES.get(style, AUTO_STYLES['balanced'])[1])
    if seed:
        random.Random(seed).shuffle(pool)
    cuts = documentary_cuts(scenes)
    lengths = shot_frames(scenes, cuts)
    result = {}
    previous = None
    turn = 0
    for c in cuts:
        before, after = lengths[c]
        speaker = scene_kind(scenes[c]) == 'sound_bite' or scene_kind(scenes[c + 1]) == 'sound_bite'
        choices = [k for k in pool if k in SPEAKER_SAFE] if speaker else pool
        choices = choices or ['fade']
        key = choices[turn % len(choices)]
        if key == previous and len(choices) > 1:
            turn += 1
            key = choices[turn % len(choices)]
        turn += 1
        key, frames = fit_frames(key, frames_for(key, duration), before, after)
        result[c] = (key, frames)
        previous = key
    return result
