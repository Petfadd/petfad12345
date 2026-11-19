"""Read explicit documentary Beat blocks without changing their clocks or sources.

The Beat reader deliberately keeps picture and sound as separate facts.  Earlier
Storyroom Beat scripts used one video for both, so ``source_*`` remains a backwards
compatible alias for the picture source and, when no external audio is supplied, the
sound-bite source.  Newer scripts may name a WAV independently of the B-roll picture.
"""
import copy
import re
from pathlib import Path

HEAD = re.compile(r'^Beat:\s*(\d+)\s*$', re.M | re.I)
CLOCK = r'\d{2}:\d{2}:\d{2}[,.]\d{3}'
PICTURE_STATUSES = {
    'VERIFIED VIDEO', 'PROVISIONAL VIDEO', 'UPLOADED PHOTO',
    'ILLUSTRATIVE VISUAL REQUIRED', 'MISSING PICTURE',
}
_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus'}
_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
_VIDEO_EXTENSIONS = {'.mp4', '.mov'}


def has_structured_beat_blocks(text):
    """Whether text opts into the portable labelled Beat-script format.

    This is deliberately only a lightweight format signal. ``read_beats`` remains
    the fail-closed validator, so a script with malformed, duplicate or out-of-order
    blocks is never treated as ready merely because it has a Beat heading.
    """
    return bool(HEAD.search(str(text or '')))


def structured_beat_block_count(text):
    """Count authored Beat headings for UI guidance without approving them."""
    return len(HEAD.findall(str(text or '')))


def time_ms(value):
    """Read an authored HH:MM:SS,mmm timecode without rounding it to frames."""
    if not re.fullmatch(CLOCK, str(value).strip()):
        raise ValueError('Expected HH:MM:SS,mmm timecode.')
    h, m, s, ms = map(int, re.split(r'[:,.]', str(value).strip()))
    if m >= 60 or s >= 60:
        raise ValueError('Invalid timecode.')
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _time_or_seconds(value, label='Duration'):
    """An explicit duration may be a timecode, decimal seconds, or ``N min N sec``."""
    text = str(value or '').strip()
    if not text:
        raise ValueError(label + ' is required.')
    if re.fullmatch(CLOCK, text):
        return time_ms(text)
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|secs|second|seconds)?', text, re.I)
    if match:
        return round(float(match.group(1)) * 1000)
    match = re.fullmatch(r'(\d+)\s*min(?:ute)?s?\s*(\d+(?:\.\d+)?)?\s*sec(?:ond)?s?', text, re.I)
    if match:
        return round((int(match.group(1)) * 60 + float(match.group(2) or 0)) * 1000)
    raise ValueError(label + ' must be a timecode or a duration in seconds.')


def _range(value, label):
    """Read the first explicit IN → OUT range, ignoring prose such as ``(Duration:)``."""
    text = str(value or '').strip()
    match = re.search(r'(' + CLOCK + r')\s*(?:-->|→|->|–|—)\s*(' + CLOCK + r')', text)
    if not match:
        raise ValueError(label + ' must have IN and OUT.')
    start, end = map(time_ms, match.groups())
    if end <= start:
        raise ValueError(label + ' must have a positive duration.')
    return start, end


def _safe_filename(value, extensions, label, allow_missing=False):
    name = str(value or '').strip()
    if allow_missing and _is_missing(name):
        return ''
    if Path(name).name != name or '\\' in name or '/' in name or Path(name).suffix.lower() not in extensions:
        if extensions == _VIDEO_EXTENSIONS:
            raise ValueError(label + ': use an exact video filename, not a path.')
        raise ValueError(label + ': use an exact filename, not a path.')
    return name


def _is_missing(value):
    return bool(re.search(r'\b(?:MISSING|TBD|TO BE SOURCED)\b', str(value or ''), re.I))


def _is_illustrative(value):
    return bool(re.search(r'\bILLUSTRATIVE\b', str(value or ''), re.I))


def _normal_status(value, filename=''):
    text = ' '.join((str(value or '') + ' ' + str(filename or '')).upper().split())
    if _is_missing(text):
        return 'MISSING PICTURE'
    if _is_illustrative(text):
        return 'ILLUSTRATIVE VISUAL REQUIRED'
    if any(text.startswith(x) for x in PICTURE_STATUSES):
        return next(x for x in PICTURE_STATUSES if text.startswith(x))
    ext = Path(str(filename or '')).suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return 'UPLOADED PHOTO'
    if 'VERIFIED' in text:
        return 'VERIFIED VIDEO'
    return 'PROVISIONAL VIDEO'


class _Fields:
    """Case-insensitive labelled fields, preserving duplicate-field failures."""
    def __init__(self, body, label):
        self.label = label
        self.values = {}
        for line in body.splitlines():
            key, sep, value = line.partition(':')
            if not sep:
                continue
            key = ' '.join(key.strip().casefold().split())
            if key:
                self.values.setdefault(key, []).append(value.strip())

    def get(self, *names, required=False, display=None):
        found = []
        seen = set()
        for name in names:
            normalized = ' '.join(name.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            found.extend(self.values.get(normalized, []))
        label = display or names[0]
        if len(found) > 1:
            raise ValueError(f'Beat {self.label}: provide exactly one {label} field.')
        if required and (not found or not found[0].strip()):
            raise ValueError(f'Beat {self.label}: provide exactly one {label} field.')
        return found[0].strip() if found else ''


def _clock_from_state(fields, label, kind):
    state = fields.get('Narration State', 'VO State', 'Voiceover State')
    clock = fields.get('Narration Clock', 'VO Clock', 'Narration clock')
    if kind == 'narration':
        shown = re.sub(r'^\s*(?:RESUMES|RESUMING|PLAYING|CONTINUES|CONTINUING)\s+(?:at\s+)?', '', clock, flags=re.I)
        return _range(shown, 'Narration Clock'), state, clock
    match = re.search(r'PAUSED\s*\(\s*Suspended at\s+(' + CLOCK + r')\s*\)', state, re.I)
    if not match:
        match = re.search(r'PAUSED\s+(?:\([^)]*\)\s*)?at\s+(' + CLOCK + r')', state + ' ' + clock, re.I)
    if not match:
        raise ValueError(f'Beat {label}: Sound bite must give PAUSED (Suspended at <timecode>) or a paused VO Clock.')
    return time_ms(match.group(1)), state, clock


def _optional_range(fields, range_names, in_names, out_names, label):
    value = fields.get(*range_names)
    if value:
        return _range(value, label)
    start = fields.get(*in_names)
    end = fields.get(*out_names)
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError(label + ' must have both IN and OUT.')
    start_ms, end_ms = time_ms(start), time_ms(re.sub(r'\s*,?\s*(?:exclusive)?\s*$', '', end, flags=re.I))
    if end_ms <= start_ms:
        raise ValueError(label + ' OUT must be after IN.')
    return start_ms, end_ms


def _master_range(fields):
    value = fields.get('Documentary Master Timeline', 'Master Timeline', 'Master Clock', 'Documentary master IN/OUT')
    return _range(value, 'Master Timeline') if value else None


def _picture(fields, label):
    raw = fields.get('Picture File', 'Picture Source', 'Picture Source File', 'Video File', 'Full Source')
    status = _normal_status(fields.get('Picture Status', 'Verification Status', 'Picture Verification Status'), raw)
    missing = status == 'MISSING PICTURE'
    illustrative = status == 'ILLUSTRATIVE VISUAL REQUIRED'
    # An illustrative treatment may still be waiting for its generated/approved file.
    if missing or (illustrative and (not raw or _is_missing(raw))):
        filename = ''
    else:
        ext = Path(raw).suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            filename = _safe_filename(raw, _IMAGE_EXTENSIONS, f'Beat {label}')
            if status not in ('MISSING PICTURE', 'ILLUSTRATIVE VISUAL REQUIRED'):
                status = 'UPLOADED PHOTO'
        else:
            filename = _safe_filename(raw, _VIDEO_EXTENSIONS, f'Beat {label}')
    source = _optional_range(
        fields,
        ('Picture Source IN → OUT', 'Picture Source In/Out', 'Picture Source Range'),
        ('Picture Source IN', 'Picture IN', 'Video IN', 'Source IN'),
        ('Picture Source OUT', 'Picture OUT', 'Video OUT', 'Source OUT'),
        'Picture source time',
    )
    if filename and Path(filename).suffix.lower() in _VIDEO_EXTENSIONS and source is None:
        raise ValueError(f'Beat {label}: video picture requires Picture Source IN and OUT.')
    if filename and Path(filename).suffix.lower() in _IMAGE_EXTENSIONS:
        source = source or (0, 0)
    prompt = fields.get('Image-generation Prompt', 'Image Generation Prompt', 'Image Prompt', 'Illustrative Visual Prompt')
    direction = fields.get('Visual Direction', 'Visual Description', 'Picture Description')
    return {
        'picture_file': filename, 'picture_in_ms': source[0] if source else None,
        'picture_out_ms': source[1] if source else None, 'picture_status': status,
        'missing_picture': missing, 'illustrative_visual': illustrative,
        'image_prompt': prompt, 'direction': direction,
    }


def _soundbite(fields, label, picture, master):
    pause, state, clock = _clock_from_state(fields, label, 'sound_bite')
    external = fields.get('Soundbite Audio File', 'Sound Bite Audio File', 'Sound Source File', 'Sound Source',
                          'WAV Audio File', 'WAV File', 'Audio File', 'Soundbite WAV')
    # The old scripts named their one combined source under Video File / Full Source.
    audio_file = _safe_filename(external, _AUDIO_EXTENSIONS, f'Beat {label}') if external else picture['picture_file']
    audio_range = _optional_range(
        fields,
        ('WAV-local IN → OUT', 'WAV Local IN → OUT', 'WAV-local In/Out', 'Sound Source IN → OUT', 'Audio Source IN → OUT'),
        ('WAV-local IN', 'WAV Local IN', 'Sound Source IN', 'Audio Source IN'),
        ('WAV-local OUT', 'WAV Local OUT', 'Sound Source OUT', 'Audio Source OUT'),
        'WAV-local time',
    )
    # Backward compatible combined-source range.
    if audio_range is None and audio_file:
        if external:
            raise ValueError(f'Beat {label}: external soundbite audio requires WAV-local IN and OUT.')
        if picture['picture_in_ms'] is not None and picture['picture_out_ms'] is not None:
            audio_range = picture['picture_in_ms'], picture['picture_out_ms']
    if not audio_file or audio_range is None:
        raise ValueError(f'Beat {label}: sound bite must name an audio source and local IN/OUT range.')
    explicit_duration = fields.get('Duration', 'Soundbite Duration')
    # Older alternate Beat scripts put the Duration parenthesis on the Master
    # Timeline line.  It is still an explicit declaration and must agree with a
    # legacy combined source window.
    if not explicit_duration:
        master_text = fields.get('Documentary Master Timeline', 'Master Timeline', 'Master Clock', 'Documentary master IN/OUT')
        duration_match = re.search(r'\(\s*Duration\s*:\s*([^)]*?)\s*\)', master_text or '', re.I)
        explicit_duration = duration_match.group(1).strip() if duration_match else ''
    dialogue_duration = fields.get('Audible Dialogue Duration', 'Final Audible Dialogue Duration', 'Audible Dialogue')
    declared = _time_or_seconds(explicit_duration, 'Duration') if explicit_duration else None
    audible = _time_or_seconds(dialogue_duration, 'Audible dialogue duration') if dialogue_duration else None
    audio_span = audio_range[1] - audio_range[0]
    legacy_combined = not external and audio_file == picture['picture_file']
    if legacy_combined:
        duration = declared if declared is not None else audio_span
        if duration != audio_span:
            raise ValueError(f'Beat {label}: Sound-bite Duration does not match source IN–OUT.')
        audible = audible if audible is not None else duration
    else:
        # Master is the program slot; `Duration` remains the authored audible range
        # unless an explicit Audible Dialogue Duration is more precise.
        duration = (master[1] - master[0]) if master else (declared if declared is not None else (picture['picture_out_ms'] or 0) - (picture['picture_in_ms'] or 0))
        audible = audible if audible is not None else (declared if declared is not None else audio_span)
    if audible <= 0 or audible > audio_span:
        raise ValueError(f'Beat {label}: audible dialogue must fit inside WAV-local IN–OUT.')
    if duration <= 0:
        raise ValueError(f'Beat {label}: sound bite must have a positive master/picture duration.')
    if picture['picture_file'] and picture['picture_out_ms'] is not None and picture['picture_in_ms'] is not None:
        pspan = picture['picture_out_ms'] - picture['picture_in_ms']
        if abs(pspan - duration) > 1:
            raise ValueError(f'Beat {label}: picture source duration must match its master slot; no stretch or freeze was assumed.')
    if legacy_combined and not re.match(r'^UNMUTED\b', fields.get('Footage Audio', 'Audio State') or '', re.I):
        raise ValueError(f'Beat {label}: Sound-bite source audio must be explicitly unmuted.')
    return {
        'pause_ms': pause, 'duration_ms': duration, 'audio_file': audio_file,
        'audio_in_ms': audio_range[0], 'audio_out_ms': audio_range[1],
        'audible_dialogue_duration_ms': audible, 'silent_picture_tail_ms': max(0, duration - audible),
        'audio_state_segments': fields.get('Audio State Segments', 'Audio States', 'Audio State'),
        'speaker': fields.get('Speaker', 'Speaker & Role'), 'narration_state': state,
        'narration_clock_text': clock,
    }


def read_beats(text):
    """Return every explicit Beat, preserving all authored clocks and source roles.

    No media is selected here.  Missing pictures become explicit review slots rather
    than a parser crash; missing required *audio* is still an error because the spoken
    material cannot be invented.
    """
    heads = list(HEAD.finditer(text or ''))
    if not heads:
        raise ValueError('No numbered Beat blocks found.')
    beats, seen = [], set()
    for i, head in enumerate(heads):
        label = head.group(1)
        number = int(label)
        if number in seen:
            raise ValueError(f'Beat {label}: duplicate beat number.')
        if beats and number <= beats[-1]['number']:
            raise ValueError(f'Beat {label}: beat numbers must be in order.')
        seen.add(number)
        body = text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        fields = _Fields(body, label)
        typ = fields.get('Type', required=True).upper()
        if typ in ('NARRATION (VOICE OVER)', 'VOICE OVER', 'NARRATION', 'NARRATION (VO)'):
            kind = 'narration'
        elif typ in ('DOCUMENTARY SOUND BITE', 'DOCUMENTARY SOUNDBITE', 'SOUNDBITE', 'SOUND BITE'):
            kind = 'sound_bite'
        else:
            raise ValueError(f'Beat {label}: unsupported beat Type {typ!r}.')
        master = _master_range(fields)
        picture = _picture(fields, label)
        srt_reference = fields.get('SRT Cue Reference', 'SRT Cue', 'SRT Reference', 'SRT Cues')
        srt_blocks = [int(x) for x in re.findall(r'\d+', srt_reference)]
        # ``source_*`` is intentionally retained for all existing callers.  It is
        # picture only; sound-bite audio gets its own explicit fields below.
        beat = {
            'number': number, 'label': label, 'kind': kind,
            'source_file': picture['picture_file'], 'source_in_ms': picture['picture_in_ms'],
            'source_out_ms': picture['picture_out_ms'], **picture,
            'caption': fields.get('On-screen Caption', 'On Screen Caption', 'Caption'),
            'cut_action': fields.get('Cut Action'),
            'master_in_ms': master[0] if master else None,
            'master_out_ms': master[1] if master else None,
            'master_duration_ms': (master[1] - master[0]) if master else None,
            'soundbite_id': fields.get('Soundbite ID', 'Sound Bite ID', 'SB ID'),
            'srt_cue_reference': srt_reference, 'srt_blocks': srt_blocks,
            'audio_state_segments': fields.get('Audio State Segments', 'Audio States', 'Audio State'),
        }
        try:
            if kind == 'narration':
                (ni, no), state, _ = _clock_from_state(fields, label, kind)
                audio = fields.get('Footage Audio', 'Picture Audio', 'Audio State')
                # Old Beat scripts explicitly say PLAYING/MUTED.  New scripts may use
                # a separate sound-source column, but picture audio remains muted.
                if state and not re.match(r'^(PLAYING|RESUMING|CONTINUES)\b', state, re.I):
                    raise ValueError('Narration must be playing.')
                if audio and not re.match(r'^MUTED\b', audio, re.I):
                    raise ValueError('Narration picture audio must be explicitly muted.')
                picture_span = None
                if picture['picture_file'] and picture['picture_out_ms'] is not None and picture['picture_in_ms'] is not None:
                    if Path(picture['picture_file']).suffix.lower() in _VIDEO_EXTENSIONS:
                        picture_span = picture['picture_out_ms'] - picture['picture_in_ms']
                # Keep a document-declared mismatch as a fact for the fitting review;
                # refusing to parse would hide the remaining authored Beats.
                if picture_span is not None and picture_span != no - ni:
                    beat['duration_mismatch_ms'] = picture_span - (no - ni)
                elif master and master[1] - master[0] != no - ni:
                    beat['duration_mismatch_ms'] = (master[1] - master[0]) - (no - ni)
                beat.update(narration_in_ms=ni, narration_out_ms=no, narration_state=state,
                            duration_ms=no-ni, audio_file='', audio_in_ms=None, audio_out_ms=None,
                            audible_dialogue_duration_ms=0, silent_picture_tail_ms=0,
                            speaker='')
            else:
                beat.update(_soundbite(fields, label, picture, master))
        except ValueError as exc:
            message = str(exc)
            if message.startswith('Beat '):
                raise
            raise ValueError(f'Beat {label}: {message}') from exc
        beats.append(beat)
    validate_beats(beats)
    return beats


def validate_beats(beats):
    """Validate clock relationships without rewriting any authored timestamps."""
    if not beats:
        return []
    problems = []
    narration = [b for b in beats if b['kind'] == 'narration']
    cursor = 0
    for beat in narration:
        if beat['narration_in_ms'] != cursor:
            problems.append(f"Beat {beat['label']}: narration gap or overlap from {cursor/1000:.3f}s to {beat['narration_in_ms']/1000:.3f}s.")
        cursor = beat['narration_out_ms']
    with_master = [b for b in beats if b.get('master_in_ms') is not None]
    if with_master:
        if len(with_master) != len(beats):
            problems.append('Every Beat must provide a Documentary Master Timeline when any Beat provides one.')
        else:
            master_cursor = 0
            for beat in with_master:
                if beat['master_in_ms'] != master_cursor:
                    problems.append(f"Beat {beat['label']}: documentary master clock is not continuous at {master_cursor/1000:.3f}s.")
                master_cursor = beat['master_out_ms']
    # A cold open is explicit, not an SRT offset.  Three consecutive bites at
    # narration 0 are valid and narration then starts at its original SRT time 0.
    opening = []
    for beat in beats:
        if beat['kind'] != 'sound_bite' or beat.get('pause_ms') != 0:
            break
        opening.append(beat)
    if len(opening) >= 3:
        if narration and narration[0]['narration_in_ms'] != 0:
            problems.append('Cold open narration must begin at original narration clock 00:00:00,000.')
        if all(b.get('master_out_ms') is not None for b in opening):
            cold_end = opening[-1]['master_out_ms']
            first_narration = next((b for b in beats if b['kind'] == 'narration'), None)
            if first_narration and first_narration.get('master_in_ms') != cold_end:
                problems.append('The first narration Beat must begin immediately after the cold-open sound bites on the documentary master clock.')
    if problems:
        raise ValueError(' '.join(problems))
    return []


def apply_overrides(beats, project):
    """Apply separately-saved picture and sound replacements to parsed Beat data.

    Overrides are deliberately project metadata, not an edit of the uploaded script.
    Replacing picture therefore cannot rename, trim, or replace a specified WAV, and
    replacing audio cannot alter the approved picture source.
    """
    saved = project.get('documentary_beat_overrides') or {}
    result = []
    for original in beats:
        beat = copy.deepcopy(original)
        entry = saved.get(str(beat.get('label'))) or saved.get(str(beat.get('number'))) or {}
        picture = entry.get('picture') if isinstance(entry, dict) else None
        audio = entry.get('audio') if isinstance(entry, dict) else None
        if isinstance(picture, dict) and picture.get('file'):
            beat['picture_file'] = beat['source_file'] = str(picture['file'])
            if picture.get('in_ms') is not None:
                beat['picture_in_ms'] = beat['source_in_ms'] = int(picture['in_ms'])
            if picture.get('out_ms') is not None:
                beat['picture_out_ms'] = beat['source_out_ms'] = int(picture['out_ms'])
            beat['picture_status'] = str(picture.get('status') or 'PROVISIONAL VIDEO').upper()
            beat['missing_picture'] = False
            beat['picture_replaced'] = True
        if isinstance(audio, dict) and audio.get('file'):
            beat['audio_file'] = str(audio['file'])
            if audio.get('in_ms') is not None:
                beat['audio_in_ms'] = int(audio['in_ms'])
            if audio.get('out_ms') is not None:
                beat['audio_out_ms'] = int(audio['out_ms'])
            beat['audio_replaced'] = True
        result.append(beat)
    return result


def _asset_name(asset):
    return str(asset.get('original_name') or asset.get('name') or '')


def media_preflight(beats, project, root):
    """Structured, fail-closed media report for the Beat build dialog.

    It separates permitted *explicit* MISSING PICTURE review slots from absent
    required media.  The latter remains a hard blocker, including an illustrative
    visual that has not yet been supplied: an illustrative label is not a licence to
    invent a visual.
    """
    root = Path(root).resolve(); assets = project.get('assets') or []
    result = {'missing_pictures': [], 'missing_media': [], 'unresolved_sources': [],
              'blocking_issues': [], 'placeholder_notes': []}
    def matches(filename):
        return [a for a in assets if _asset_name(a) == filename]
    def missing(beat, role, filename, reason):
        row = {'beat': beat['label'], 'role': role, 'file': filename or '', 'reason': reason}
        result['missing_media'].append(row)
        named = (' '+filename) if filename else ''
        result['blocking_issues'].append(f"Beat {beat['label']}: {role}{named} {reason}. No substitution was made.")
    for beat in beats:
        status = str(beat.get('picture_status') or 'PROVISIONAL VIDEO').upper()
        picture = str(beat.get('picture_file') or '')
        if status == 'MISSING PICTURE':
            row = {'beat': beat['label'], 'status': status, 'prompt': beat.get('image_prompt',''),
                   'type': beat['kind'], 'duration_ms': beat.get('duration_ms')}
            result['missing_pictures'].append(row)
            result['placeholder_notes'].append(f"Beat {beat['label']}: explicit MISSING PICTURE is an approved review placeholder, not completed footage.")
        elif not picture:
            reason = ('is marked ILLUSTRATIVE VISUAL REQUIRED but has no uploaded illustration/picture'
                      if status == 'ILLUSTRATIVE VISUAL REQUIRED' else 'has no required picture source')
            missing(beat, 'picture source', picture, reason)
        else:
            found = matches(picture)
            if len(found) != 1:
                missing(beat, 'picture source', picture, 'is missing or ambiguous')
            else:
                asset = found[0]; path = (root / asset.get('path','')).resolve()
                allowed = (root/'sources').resolve() if asset.get('kind') == 'video' else (root/'assets').resolve()
                if asset.get('kind') not in ('video','image') or not path.is_relative_to(allowed) or not path.is_file():
                    missing(beat, 'picture source', picture, 'is not an available uploaded picture file')
                elif asset.get('kind') == 'video':
                    start, end = beat.get('picture_in_ms'), beat.get('picture_out_ms')
                    if start is None or end is None or start < 0 or end <= start:
                        missing(beat, 'picture source range', picture, 'has an invalid IN/OUT range')
                    elif end > float(asset.get('duration') or 0)*1000 + .001:
                        missing(beat, 'picture source range', picture, f"ends at {end/1000:.3f}s beyond the uploaded file")
            if status in ('PROVISIONAL VIDEO', 'ILLUSTRATIVE VISUAL REQUIRED'):
                result['unresolved_sources'].append({'beat': beat['label'], 'role': 'picture', 'file': picture,
                                                     'status': status, 'reason': 'Requires visual, identity, context and rights review.'})
        if beat.get('kind') != 'sound_bite':
            continue
        audio = str(beat.get('audio_file') or '')
        found = matches(audio)
        if len(found) != 1:
            missing(beat, 'soundbite audio', audio, 'is missing or ambiguous')
            continue
        asset = found[0]; path = (root / asset.get('path','')).resolve()
        allowed = (root/'audio').resolve() if asset.get('kind') == 'audio' else (root/'sources').resolve()
        if asset.get('kind') not in ('audio','video') or not path.is_relative_to(allowed) or not path.is_file():
            missing(beat, 'soundbite audio', audio, 'is not an available uploaded WAV/audio file')
            continue
        start, end = beat.get('audio_in_ms'), beat.get('audio_out_ms')
        range_valid = start is not None and end is not None and start >= 0 and end > start
        if not range_valid:
            missing(beat, 'WAV-local range', audio, 'has an invalid IN/OUT range')
        elif end > float(asset.get('duration') or 0)*1000 + .001:
            missing(beat, 'WAV-local range', audio, f"ends at {end/1000:.3f}s beyond the uploaded audio")
        audible = beat.get('audible_dialogue_duration_ms')
        if not range_valid or not isinstance(audible, int) or audible <= 0 or audible > end-start:
            missing(beat, 'soundbite duration', audio, 'does not fit WAV-local IN/OUT')
    return result


def audit_beats(beats, project, root):
    """Validate independent picture/audio uploads and ranges. Return readable issues.

    A MISSING PICTURE remains a review warning, never a fake match or a parser error.
    Missing soundbite WAVs are blocking because no dialogue may be substituted.
    """
    root = Path(root).resolve()
    issues, missing_picture_notes, missing_names = [], [], set()
    assets = project.get('assets') or []
    for beat in beats:
        label = beat['label']
        if beat.get('picture_status') == 'MISSING PICTURE':
            prompt = beat.get('image_prompt')
            missing_picture_notes.append(f"Beat {label}: MISSING PICTURE review placeholder" + (f" — prompt: {prompt}" if prompt else '') + '.')
        elif beat.get('picture_file'):
            matches = [a for a in assets if _asset_name(a) == beat['picture_file']]
            if len(matches) != 1:
                key = ('picture', beat['picture_file'])
                if key not in missing_names:
                    issues.append(f"Beat {label}: exact picture source {beat['picture_file']} is missing or ambiguous (no substitution was made).")
                    missing_names.add(key)
            else:
                asset = matches[0]; path = (root / asset.get('path', '')).resolve()
                if asset.get('kind') not in ('video', 'image') or not path.is_file():
                    issues.append(f'Beat {label}: picture source is not an available uploaded video or still.')
                elif asset.get('kind') == 'video' and beat.get('picture_out_ms') is not None and beat['picture_out_ms'] > float(asset.get('duration') or 0) * 1000 + .001:
                    issues.append(f"Beat {label}: picture source OUT {beat['picture_out_ms']/1000:.3f}s exceeds {beat['picture_file']} duration.")
        if beat['kind'] == 'sound_bite':
            audio = beat.get('audio_file')
            matches = [a for a in assets if _asset_name(a) == audio]
            if len(matches) != 1:
                key = ('audio', audio)
                if key not in missing_names:
                    issues.append(f"Beat {label}: exact soundbite audio {audio} is missing or ambiguous; the specified dialogue will not be replaced with picture-source audio.")
                    missing_names.add(key)
            else:
                asset = matches[0]; path = (root / asset.get('path', '')).resolve()
                if asset.get('kind') not in ('video', 'audio') or not path.is_file():
                    issues.append(f'Beat {label}: soundbite audio is not an available uploaded audio/video file.')
                elif beat['audio_out_ms'] > float(asset.get('duration') or 0) * 1000 + .001:
                    issues.append(f"Beat {label}: WAV-local OUT {beat['audio_out_ms']/1000:.3f}s exceeds {audio} duration.")
    # Clock and picture-reuse diagnostics are intentionally separate from file
    # matching above.  They work even when an asset is unavailable, and preserve the
    # legacy Beat audit's one-actionable-message behaviour.
    narration_cursor = 0
    used_picture = {}
    for index, beat in enumerate(beats):
        if beat['kind'] == 'narration':
            start, end = beat['narration_in_ms'], beat['narration_out_ms']
            if start != narration_cursor:
                issues.append(f"Beat {beat['label']}: narration gap or overlap from {narration_cursor/1000:.3f}s to {start/1000:.3f}s.")
            narration_cursor = end
        else:
            previous = next((b for b in reversed(beats[:index]) if b['kind'] == 'narration'), None)
            if previous is None:
                if beat.get('pause_ms') != 0:
                    issues.append(f"Beat {beat['label']}: opening sound bite must pause narration at 0.000s.")
            elif beat.get('pause_ms') != previous.get('narration_out_ms'):
                issues.append(f"Beat {beat['label']}: pause {beat.get('pause_ms',0)/1000:.3f}s does not match the preceding narration endpoint.")
        name, start, end = beat.get('source_file'), beat.get('source_in_ms'), beat.get('source_out_ms')
        if name and start is not None and end is not None:
            previous = used_picture.setdefault(name, [])
            if any(start < old_end and end > old_start for old_start, old_end in previous):
                if not any(name+' source ranges overlap' in issue for issue in issues):
                    issues.append(f'{name} source ranges overlap between scripted Beats. Reuse is a review decision; no range was changed.')
            previous.append((start, end))
    voice=(project.get('voiceover') or {}).get('duration')
    if voice is not None and narration_cursor and abs(float(voice)-narration_cursor/1000)>.25:
        issues.append(f'Last scripted narration ends at {narration_cursor/1000:.3f}s; uploaded narration lasts {float(voice):.3f}s. Review the difference; no audio was trimmed.')
    issues.extend(missing_picture_notes)
    return issues
