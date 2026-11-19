"""Fit each scripted Beat's picture range to its own narration clock.

Every change is mechanical and recorded: a range is only ever trimmed or extended
inside the one video the script names for that beat. No other file is chosen, no
shot is repeated, and no playback speed is changed. A person still has to review
the result; this is not identity, content or rights verification.
"""
from pathlib import Path


_LIMITS = {}


def frame_limits(root, assets, path_of=None):
    """Highest usable exclusive OUT (ms) per asset, from real container metadata.

    ``nb_frames``/stream frame counts are header data, so this stays cheap. When a
    count is unavailable the stored duration is used unchanged and the existing
    frame audit still fails closed.
    """
    import av
    from fractions import Fraction
    limits = {}
    for asset in assets:
        path = (path_of(asset) if path_of else Path(root)/str(asset.get('path') or ''))
        # A file's frame limit is a fact about that exact file; remember it.
        try:
            st = Path(path).stat(); fkey = (str(path), st.st_size, st.st_mtime_ns)
        except OSError:
            fkey = None
        if fkey in _LIMITS:
            if _LIMITS[fkey] is not None:
                limits[asset.get('id')] = _LIMITS[fkey]
            continue
        try:
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                rate = Fraction(stream.average_rate)
                frames = stream.frames or 0
                value = int(Fraction(frames, 1)*1000/rate) if frames and rate > 0 else None
        except Exception:
            continue
        if fkey is not None:
            _LIMITS[fkey] = value
        if value is not None:
            limits[asset.get('id')] = value
    return limits


def unused_ranges(beats, filename, limit):
    """Intervals of one upload that no scripted Beat uses, longest first.

    A suggestion only: what those seconds show still has to be watched.
    """
    used = sorted((b['source_in_ms'], b['source_out_ms']) for b in beats
                  if b.get('source_file') == filename and b.get('source_in_ms') is not None and b.get('source_out_ms') is not None)
    free, cursor = [], 0
    for start, end in used:
        if start > cursor:
            free.append((cursor, min(start, limit)))
        cursor = max(cursor, end)
    if cursor < limit:
        free.append((cursor, limit))
    return sorted(((a, b) for a, b in free if b - a >= 1000), key=lambda r: r[0] - r[1])


def _limit_ms(asset, frame_limit):
    """Highest usable exclusive OUT for one asset: a real frame boundary if known."""
    stored = round(float(asset.get('duration') or 0)*1000)
    snapped = (frame_limit or {}).get(asset.get('id'))
    return min(stored, snapped) if snapped else stored


def fit(beats, assets, focus_beat=None, focus_source=None, frame_limit=None):
    """Return (adjusted beats, adjustment records, blocking issues).

    A beat whose scripted range is longer than its video cannot be fitted inside
    that video. When the caller has explicitly named a replacement, verified
    source for that one beat, the beat is re-pointed there and the change is
    recorded like every other adjustment.
    """
    files = {}
    for asset in assets:
        name = asset.get('original_name') or asset.get('name')
        files.setdefault(name, asset)
    frame_limit = frame_limit or {}
    adjusted, adjustments, issues = [], [], []
    for beat in beats:
        beat = dict(beat)
        # A deliberately missing picture is a review placeholder, not a request to
        # silently borrow a different clip. Its narration/sound timing survives the
        # plan unchanged and the storyboard can later replace picture only.
        if beat.get('picture_status') == 'MISSING PICTURE' or not beat.get('source_file'):
            adjusted.append(beat)
            continue
        if beat.get('picture_status') in ('UPLOADED PHOTO', 'ILLUSTRATIVE VISUAL REQUIRED') or str(beat.get('source_file','')).lower().endswith(('.jpg','.jpeg','.png','.webp')):
            adjusted.append(beat)
            continue
        if beat['kind'] != 'narration':
            # Sound bites are picture too. Leaving a bite pointing past the end of
            # its file let the review storyboard fail later with a bare "source OUT
            # exceeds video duration" and no explanation of what to change.
            label = beat['label']
            asset = files.get(beat['source_file'])
            if not asset:
                issues.append(f'Beat {label}: script source {beat["source_file"]} is not uploaded.')
                adjusted.append(beat)
                continue
            limit = _limit_ms(asset, frame_limit)
            before = (beat['source_in_ms'], beat['source_out_ms'])
            if before[1] > limit:
                room = max(0, limit - before[0])
                scripted = (before[1]-before[0])/1000
                if room >= 1000:
                    beat['source_out_ms'] = limit
                    beat['duration_ms'] = limit - before[0]
                    adjustments.append(f'Beat {label}: source OUT {before[1]/1000:.3f}s is past the end of '
                                       f'{beat["source_file"]} ({limit/1000:.3f}s); clamped to {limit/1000:.3f}s, '
                                       f'so this bite plays {room/1000:.3f}s instead of {scripted:.3f}s.')
                else:
                    # Shifting the IN back would move the spoken words, which is an
                    # editorial decision. Ask instead of guessing, and name the
                    # seconds of this upload that no other Beat is using yet.
                    left = f'{room/1000:.3f}s left after source IN {before[0]/1000:.3f}s'
                    spare = unused_ranges(beats, beat['source_file'], limit)
                    offer = ''
                    if spare:
                        a, b = spare[0]
                        offer = (f' The longest unused stretch of this upload is {a/1000:.3f}–{b/1000:.3f}s '
                                 f'({(b-a)/1000:.3f}s); check what it shows before using it.')
                    else:
                        offer = (' Every other second of this upload is already claimed by another Beat, '
                                 'so this project needs a longer source file or one more video.')
                    issues.append(f'Beat {label}: {beat["source_file"]} has only {left}, which cannot cover this '
                                  f'{scripted:.3f}s bite. Choose an earlier source IN or a different uploaded file for this Beat; '
                                  f'nothing was moved or shortened.{offer}')
                adjusted.append(beat)
                continue
            adjusted.append(beat)
            continue
        label = beat['label']
        asset = files.get(beat['source_file'])
        if not asset:
            issues.append(f'Beat {label}: script source {beat["source_file"]} is not uploaded.')
            adjusted.append(beat)
            continue
        if focus_beat == label and focus_source:
            replacement = files.get(focus_source)
            if not replacement:
                issues.append(f'Beat {label}: the chosen replacement source {focus_source} is not uploaded.')
                adjusted.append(beat)
                continue
            if float(replacement.get('duration') or 0)*1000+.001 < beat['narration_out_ms']-beat['narration_in_ms']:
                issues.append(f'Beat {label}: {focus_source} is too short for the {((beat["narration_out_ms"]-beat["narration_in_ms"])/1000):.3f}s narration.')
                adjusted.append(beat)
                continue
            adjustments.append(f'Beat {label}: scripted {beat["source_file"]} {beat["source_in_ms"]/1000:.3f}–{beat["source_out_ms"]/1000:.3f}s '
                               f'cannot cover the {(beat["narration_out_ms"]-beat["narration_in_ms"])/1000:.3f}s narration; '
                               f're-pointed to your chosen {focus_source} 0.000s onward instead.')
            beat['source_file'] = focus_source
            beat['source_in_ms'], beat['source_out_ms'] = 0, beat['narration_out_ms']-beat['narration_in_ms']
            adjusted.append(beat)
            continue
        limit = _limit_ms(asset, frame_limit)
        need = beat['narration_out_ms']-beat['narration_in_ms']
        start, end = beat['source_in_ms'], beat['source_out_ms']
        before = (start, end)
        if end > limit:
            end = limit
            adjustments.append(f'Beat {label}: source OUT {before[1]/1000:.3f}s is past the end of {beat["source_file"]} '
                               f'({limit/1000:.3f}s); clamped to {end/1000:.3f}s.')
        # A frame-snapped OUT must still name a frame that exists. One source
        # frame shorter is honest; asking for a missing frame would be a stretch.
        frame_end = frame_limit.get(asset.get('id'))
        if end >= limit and frame_end is not None and frame_end < end:
            adjustments.append(f'Beat {label}: source OUT {end/1000:.3f}s is not a frame boundary in {beat["source_file"]}; '
                               f'using the nearest frame at {frame_end/1000:.3f}s.')
            end = frame_end
        span = end-start
        if span == need:
            pass
        elif span > need:
            end = start+need
            adjustments.append(f'Beat {label}: {span/1000:.3f}s of picture trimmed to the {need/1000:.3f}s narration span '
                               f'({start/1000:.3f}–{end/1000:.3f}s).')
        else:
            # Keep the script's own start where the file allows it; only borrow
            # outside it when the remaining file cannot cover the narration.
            if start+need <= limit:
                end = start+need
                side = 'forward' if end <= before[1] else 'forward, from the scripted IN'
            elif end-need >= 0:
                start = end-need
                side = 'backward, from the scripted OUT'
            else:
                issues.append(f'Beat {label}: {beat["source_file"]} only has {float(asset.get("duration") or 0):.3f}s, '
                              f'which cannot cover the {need/1000:.3f}s narration without repeating or slowing it.')
                adjusted.append(beat)
                continue
            if span > 0:
                lead = f'{span/1000:.3f}s of picture is shorter than the {need/1000:.3f}s narration'
            else:
                # The scripted range begins past the end of the file, so there is
                # no picture inside it at all. Say that instead of a negative number.
                lead = f'the scripted range {before[0]/1000:.3f}–{before[1]/1000:.3f}s is past the end of ' \
                       f'{beat["source_file"]}, so it is shorter than the {need/1000:.3f}s narration'
            adjustments.append(f'Beat {label}: {lead}; extended {side} inside {beat["source_file"]} '
                               f'to {start/1000:.3f}–{end/1000:.3f}s.')
        if end <= start:
            issues.append(f'Beat {label}: the fitted source range is empty.')
        if (start, end) == before and span >= need:
            pass
        beat['source_in_ms'], beat['source_out_ms'] = start, end
        adjusted.append(beat)
    return adjusted, adjustments, issues


def overlaps(beats):
    """Every repeated interval pair, so the caller can record an explicit decision.

    Sound bites are included: one bite may reuse footage another beat already
    shows, and that is still a decision a person has to make. An identical
    interval is not a decision, though: showing exactly the same frames twice is
    what auto-fitting produces when a file is too short, so it is reported as a
    problem instead of being offered for approval.
    """
    pairs = []
    for i, b in enumerate(beats):
        for a in beats[:i]:
            if (a.get('source_file') and a.get('source_file') == b.get('source_file')
                    and None not in (a.get('source_in_ms'), a.get('source_out_ms'), b.get('source_in_ms'), b.get('source_out_ms'))
                    and b['source_in_ms'] < a['source_out_ms'] and b['source_out_ms'] > a['source_in_ms']):
                pairs.append([a['number'], b['number']])
    return pairs


def exact_duplicates(beats):
    """Interval pairs that are the same frames, not merely overlapping ones."""
    return [[a['number'], b['number']] for i, b in enumerate(beats) for a in beats[:i]
            if a.get('source_file') and a.get('source_file') == b.get('source_file')
            and None not in (a.get('source_in_ms'), a.get('source_out_ms'), b.get('source_in_ms'), b.get('source_out_ms'))
            and (a['source_in_ms'], a['source_out_ms']) == (b['source_in_ms'], b['source_out_ms'])]


def exact_duplicate_groups(beats):
    """Group identical picture ranges without expanding them into every pair.

    A 233-Beat script can contain tens of thousands of identical-range pairs. A
    proposal has to name the defect, but serialising a copy of the same warning for
    every pair makes the review endpoint unusable. The full Beat list remains in
    the response; this compact group is the scalable review description.
    """
    grouped = {}
    for beat in beats:
        filename, start, end = beat.get('source_file'), beat.get('source_in_ms'), beat.get('source_out_ms')
        if not filename or start is None or end is None:
            continue
        grouped.setdefault((filename, start, end), []).append(beat)
    return [{'source_file': key[0], 'source_in_ms': key[1], 'source_out_ms': key[2],
             'beats': [beat['number'] for beat in rows], 'labels': [beat['label'] for beat in rows],
             'pair_count': len(rows) * (len(rows) - 1) // 2}
            for key, rows in grouped.items() if len(rows) > 1]


def consecutive_bites(beats):
    """True when two sound bites share a pause point with no narration between."""
    found = []
    for a, b in zip(beats, beats[1:]):
        if a['kind'] == 'sound_bite' and b['kind'] == 'sound_bite':
            found.append([a['number'], b['number']])
    return found


def narration_gaps(project, beats, frame_limit=None):
    """Narration time that no Beat covers, with footage proposed for each hole.

    The build refuses to guess: it needs one explicit source range per uncovered
    interval. This proposes those ranges from seconds of the named file that no
    Beat is already using, so the decision is a review, not a blank page.
    """
    narratives = [b for b in beats if b['kind'] == 'narration']
    cursor, holes = 0, []
    for b in narratives:
        if b['narration_in_ms'] > cursor:
            holes.append((cursor, b['narration_in_ms']))
        cursor = max(cursor, b['narration_out_ms'])
    # The review plan uses the authored narration clock when a short decoded-file
    # tail has already been reconciled with the script/SRT.  Otherwise the proposal
    # would ask for phantom picture over that tail while `prepare` correctly builds
    # only through the authored endpoint.
    from documentary import narration_clock_s
    voice_ms = round(narration_clock_s(project)*1000)
    if voice_ms > cursor:
        holes.append((cursor, voice_ms))
    names = []
    for b in beats:
        if b.get('source_file') and b['source_file'] not in names:
            names.append(b['source_file'])
    files = {a.get('original_name') or a.get('name'): a
             for a in (project.get('assets') or []) if isinstance(a, dict)}
    proposed, issues = [], []
    # Footage already promised to an earlier hole. Without this, every hole was
    # proposed the same spare stretch -- typically the very start of the first file --
    # and the build then rejected its own proposal with "Proposed gap footage overlaps
    # another gap." Measured on a real 15-gap script: 105 overlapping pairs, and no
    # way for the user to accept the proposal as offered.
    claimed = {}
    for start, end in holes:
        need = end - start
        choice = None
        for name in names:
            asset = files.get(name)
            if not asset:
                continue
            limit = _limit_ms(asset, frame_limit)
            taken = claimed.setdefault(name, [])
            spare = []
            for a, b in unused_ranges(beats, name, limit):
                if b - a < need:
                    continue
                # Walk past every stretch an earlier hole already claimed, so each
                # proposal is a genuinely different piece of picture.
                cursor = a
                for ta, tb in sorted(taken):
                    if tb <= cursor or ta >= b:
                        continue
                    if ta - cursor >= need:
                        break
                    cursor = max(cursor, tb)
                if b - cursor >= need:
                    spare.append((cursor, b))
            spare.sort(key=lambda r: r[1] - r[0])
            if spare:
                choice = (name, spare[0])
                break
        if choice:
            name, (a, b) = choice
            claimed.setdefault(name, []).append((a, a + need))
            proposed.append({'narration_in_ms': start, 'narration_out_ms': end,
                             'source_file': name, 'source_in_ms': a,
                             'source_out_ms': a + need})
        else:
            issues.append(
                f'Narration from {start/1000:.3f}s to {end/1000:.3f}s ({(need)/1000:.3f}s) has no Beat, and the '
                f'file(s) named in the script have no unused {need/1000:.3f}s stretch to cover it. '
                f'If the narration is still speaking there, a Beat clock ends too early in the script; '
                f'otherwise upload footage with a spare {need/1000:.3f}s, or shorten the narration. '
                f'Nothing was invented.')
    return proposed, issues


def proposal(project, beats, focus_beat=None, focus_source=None, frame_limit=None):
    """Everything a person needs to see before a Beat storyboard is built.

    ``frame_limit`` maps asset id to the highest decodable exclusive OUT in ms.
    """
    from documentary_beats import apply_overrides
    beats = apply_overrides(beats, project)
    adjusted, adjustments, issues = fit(beats, project.get('assets') or [], focus_beat, focus_source, frame_limit)
    # A short file used to "fit" by replaying the same closing seconds in several
    # beats. That is silent repetition of the picture, not a range choice. Report
    # each identical range once: a long script can otherwise expand one authored
    # error into tens of thousands of pairwise warnings and an unresponsive review.
    duplicate_groups = exact_duplicate_groups(adjusted)
    duplicate_key_by_beat = {
        number: (group['source_file'], group['source_in_ms'], group['source_out_ms'])
        for group in duplicate_groups for number in group['beats']
    }
    for group in duplicate_groups:
        labels = group['labels']
        shown = ', '.join(labels[:8]) + (f' and {len(labels)-8} more' if len(labels) > 8 else '')
        issues.append(f'Beats {shown} would show exactly the same frames of {group["source_file"]} '
                      f'({group["source_in_ms"]/1000:.3f}–{group["source_out_ms"]/1000:.3f}s; '
                      f'{group["pair_count"]} repeated pair(s)). That repeats the same picture instead of '
                      f'covering the later Beat(s). Give each Beat an earlier unused source range, a longer '
                      f'source, or another uploaded video; nothing was repeated automatically.')
    gaps, gap_issues = narration_gaps(project, adjusted, frame_limit)
    issues.extend(gap_issues)
    all_overlaps = overlaps(adjusted)
    # Exact duplicates already block this proposal above. For ordinary overlaps, a
    # bounded list is all that can be explicitly reviewed in this dialog. Do not
    # silently turn an omitted pair into an approval: a truncation is its own blocker.
    pairs = [pair for pair in all_overlaps
             if not (duplicate_key_by_beat.get(pair[0]) is not None
                     and duplicate_key_by_beat.get(pair[0]) == duplicate_key_by_beat.get(pair[1]))]
    pair_limit = 500
    repeated_ranges_total = len(pairs)
    repeated_ranges_truncated = repeated_ranges_total > pair_limit
    if repeated_ranges_truncated:
        issues.append(f'The script has {repeated_ranges_total} non-identical overlapping picture ranges. '
                      f'Only the first {pair_limit} can be shown in this review; resolve the overlaps or narrow '
                      f'the review before any can be approved. Nothing was approved in bulk.')
    pairs = pairs[:pair_limit]
    runs = consecutive_bites(adjusted)
    total_ms = sum(int(b.get('master_duration_ms') or b.get('duration_ms') or
                       ((b.get('source_out_ms') or 0) - (b.get('source_in_ms') or 0))) for b in adjusted)
    missing = [b for b in adjusted if b.get('picture_status') == 'MISSING PICTURE']
    provisional = [b for b in adjusted if b.get('picture_status') in ('PROVISIONAL VIDEO', 'ILLUSTRATIVE VISUAL REQUIRED')]
    return {'beats': adjusted, 'adjustments': adjustments, 'issues': issues, 'narration_gaps': gaps,
            'repeated_ranges': pairs, 'repeated_ranges_total': repeated_ranges_total,
            'repeated_ranges_truncated': repeated_ranges_truncated, 'exact_duplicate_groups': duplicate_groups,
            'consecutive_bites': runs,
            'planned_ms': total_ms, 'narration_ms': round(float((project.get('voiceover') or {}).get('duration') or 0)*1000),
            'source_files': sorted({b['source_file'] for b in adjusted if b.get('source_file')}),
            'missing_pictures': [{'beat': b['label'], 'prompt': b.get('image_prompt',''),
                                  'review_reason': b.get('picture_review_reason',''),
                                  'status': b.get('picture_status')} for b in missing],
            'provisional_sources': [{'beat': b['label'], 'picture_file': b.get('picture_file',''),
                                    'status': b.get('picture_status')} for b in provisional]}
