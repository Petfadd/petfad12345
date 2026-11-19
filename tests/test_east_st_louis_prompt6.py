"""Compatibility checks for the corrected East St. Louis Prompt 6 Beat format.

These tests use tiny synthetic media registers: they test parsing/planning facts, not
identity, rights or the contents of a real person's footage.
"""
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from documentary import build_timeline, narration_clock_s
from documentary_beats import apply_overrides, audit_beats, media_preflight, read_beats
from documentary_beat_plan import proposal
from documentary_storyboard import prepare, verified_source_interval


def tc(ms):
    h, ms = divmod(ms, 3_600_000); m, ms = divmod(ms, 60_000); s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def narration(number, narr_in, master_in, source='S03.mp4', missing=False):
    duration = 1000
    picture = ('Full source: MISSING\nPicture Status: MISSING PICTURE\nImage-generation Prompt: Respectful non-identifying streetscape; no actual case footage'
               if missing else f'Video File: {source}\nSource IN: 00:00:00,000\nSource OUT: 00:00:01,000')
    return f'''Beat: {number:03d}
Type: Narration (Voice Over)
{picture}
Narration State: PLAYING
Footage Audio: MUTED
Narration Clock: {tc(narr_in)} --> {tc(narr_in + duration)}
Master Timeline: {tc(master_in)} --> {tc(master_in + duration)}
Visual Direction: Documentary review picture
On-screen Caption: None
'''


def bite(number, pause, master_in, picture='S03.mp4', wav='S11 Marcus May.wav', missing=False, audible=800, sbid='SB-009', slot=1000):
    duration = slot
    picture_fields = ('Full source: MISSING\nPicture Status: MISSING PICTURE\nImage Prompt: Illustration only — not actual case footage'
                      if missing else f'Picture File: {picture}\nPicture Source IN: 00:00:00,000\nPicture Source OUT: {tc(slot)}\nPicture Status: PROVISIONAL VIDEO')
    return f'''Beat: {number:03d}
Type: Documentary Sound Bite
Soundbite ID: {sbid}
{picture_fields}
Soundbite Audio File: {wav}
WAV-local IN: 00:00:10,000
WAV-local OUT: 00:00:11,000
Audible Dialogue Duration: {tc(audible)}
Audio State Segments: dialogue then muted handle
Narration State: PAUSED (Suspended at {tc(pause)})
Footage Audio: UNMUTED
Duration: 00:00:01,000
Master Timeline: {tc(master_in)} --> {tc(master_in + duration)}
Visual Direction: B-roll is non-identifying and independent of the speaker WAV
On-screen Caption: None
'''


def prompt6_script():
    """233 sequential Beats: 208 narration + 25 bites with a 27s cold open."""
    rows = [bite(1, 0, 0, sbid='SB-001', slot=9000), bite(2, 0, 9000, sbid='SB-002', slot=9000), bite(3, 0, 18000, sbid='SB-003', slot=9000)]
    number, narration_clock, master_clock, later_bites = 4, 0, 27000, 0
    for index in range(208):
        rows.append(narration(number, narration_clock, master_clock)); number += 1; narration_clock += 1000; master_clock += 1000
        # 22 remaining bites, placed at real narration pause points.  Three IDs repeat
        # so the total is 25 placements but 22 distinct IDs.
        if index < 22:
            sbid = f'SB-{(index % 22) + 1:03d}'
            rows.append(bite(number, narration_clock, master_clock, sbid=sbid)); number += 1; master_clock += 1000; later_bites += 1
    assert number == 234 and later_bites == 22
    return '\n'.join(rows)


class EastStLouisPrompt6CompatibilityTests(unittest.TestCase):
    def test_01_existing_legacy_beat_format_still_reads(self):
        text = '''Beat: 001
Type: Narration (Voice Over)
Video File: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:01,000
Narration State: PLAYING
Footage Audio: MUTED
Narration Clock: 00:00:00,000 --> 00:00:01,000
On-screen Caption: None
Visual Direction: Legacy B-roll

Beat: 002
Type: Documentary Sound Bite
Video File: S01.mp4
Source IN: 00:00:01,000
Source OUT: 00:00:02,000
Narration State: PAUSED (Suspended at 00:00:01,000)
Footage Audio: UNMUTED
Duration: 00:00:01,000
Speaker: Declared speaker
On-screen Caption: None
Visual Direction: Legacy bite

Beat: 003
Type: Narration (Voice Over)
Video File: S01.mp4
Source IN: 00:00:02,000
Source OUT: 00:00:03,000
Narration State: PLAYING
Footage Audio: MUTED
Narration Clock: 00:00:01,000 --> 00:00:02,000
On-screen Caption: None
Visual Direction: Legacy B-roll
'''
        beats = read_beats(text)
        self.assertEqual([b['kind'] for b in beats], ['narration', 'sound_bite', 'narration'])
        self.assertEqual(beats[1]['audio_file'], 'S01.mp4')
        self.assertEqual(beats[1]['picture_file'], 'S01.mp4')

    def test_02_full_233_beat_structure(self):
        beats = read_beats(prompt6_script())
        self.assertEqual(len(beats), 233)
        self.assertEqual(sum(b['kind'] == 'narration' for b in beats), 208)
        bites = [b for b in beats if b['kind'] == 'sound_bite']
        self.assertEqual(len(bites), 25)
        self.assertEqual(len({b['soundbite_id'] for b in bites}), 22)

    def test_03_three_consecutive_cold_open_bites_keep_srt_clock_zero(self):
        beats = read_beats(prompt6_script())
        self.assertEqual([b['pause_ms'] for b in beats[:3]], [0, 0, 0])
        self.assertEqual((beats[0]['master_in_ms'], beats[2]['master_out_ms']), (0, 27000))
        first_narration = next(b for b in beats if b['kind'] == 'narration')
        self.assertEqual((first_narration['narration_in_ms'], first_narration['master_in_ms']), (0, 27000))

    def test_04_external_wav_is_independent_of_broll_picture(self):
        beat = read_beats(bite(1, 0, 0))[0]
        self.assertEqual(beat['picture_file'], 'S03.mp4')
        self.assertEqual(beat['audio_file'], 'S11 Marcus May.wav')
        self.assertNotEqual(beat['picture_file'], beat['audio_file'])

    def test_05_soundbite_silent_picture_tail_is_preserved(self):
        beat = read_beats(bite(1, 0, 0, audible=650))[0]
        self.assertEqual(beat['audible_dialogue_duration_ms'], 650)
        self.assertEqual(beat['silent_picture_tail_ms'], 350)
        project = {'voiceover': {'duration': 2}, 'assets': []}
        plan = {'bites': [{'id': 'b', 'pause_s': 0, 'asset_id': 'audio', 'asset_name': 'S11 Marcus May.wav',
                           'source_in_s': 10, 'source_out_s': 10.65, 'picture_duration_s': 1,
                           'picture_asset_id': 'picture', 'picture_asset_name': 'S03.mp4',
                           'picture_source_in_s': 0, 'picture_source_out_s': 1, 'created': 0}]}
        segment = build_timeline(project, plan)['segments'][0]
        self.assertEqual((segment['audible_duration_s'], segment['silent_tail_s'], segment['picture_duration_s']), (.65, .35, 1.0))

    def test_06_missing_picture_narration_is_a_review_slot(self):
        beat = read_beats(narration(1, 0, 0, missing=True))[0]
        self.assertEqual(beat['picture_status'], 'MISSING PICTURE')
        self.assertTrue(beat['missing_picture'])
        self.assertEqual(beat['narration_out_ms'], 1000)

    def test_07_missing_picture_soundbite_keeps_external_audio(self):
        beat = read_beats(bite(1, 0, 0, missing=True))[0]
        self.assertEqual(beat['picture_status'], 'MISSING PICTURE')
        self.assertEqual(beat['audio_file'], 'S11 Marcus May.wav')
        self.assertEqual(beat['duration_ms'], 1000)

    def test_07b_missing_picture_review_card_has_a_verifiable_schedule_slot(self):
        project = {'documentary_beat_review': {'fitted_beats': [
            {'label': '001', 'picture_status': 'MISSING PICTURE'}
        ]}}
        scene = {'plan_row': {'continuity': 'Documentary beat 001', 'script_beat': '001',
                              'picture_status': 'MISSING PICTURE'}}
        asset = {'id': 'missing-picture-0001', 'storyroom_placeholder': True}
        self.assertEqual(verified_source_interval(project, scene, asset), (0.0, 0.0))

    def test_08_wav_local_ranges_are_checked_against_audio_upload(self):
        beat = read_beats(bite(1, 0, 0))[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'sources').mkdir(); (root / 'audio').mkdir()
            (root / 'sources' / 'S03.mp4').write_bytes(b'x'); (root / 'audio' / 'S11 Marcus May.wav').write_bytes(b'x')
            project = {'assets': [
                {'id': 'p', 'original_name': 'S03.mp4', 'name': 'S03.mp4', 'kind': 'video', 'path': 'sources/S03.mp4', 'duration': 20},
                {'id': 'a', 'original_name': 'S11 Marcus May.wav', 'name': 'S11 Marcus May.wav', 'kind': 'audio', 'path': 'audio/S11 Marcus May.wav', 'duration': 10.5},
            ]}
            issues = audit_beats([beat], project, root)
            self.assertTrue(any('WAV-local OUT' in issue for issue in issues))

    def test_09_srt_narration_clock_is_not_cold_open_shifted(self):
        beats = read_beats(prompt6_script())
        narration = [b for b in beats if b['kind'] == 'narration']
        self.assertEqual(narration[0]['narration_in_ms'], 0)
        self.assertEqual(narration[-1]['narration_out_ms'], 208000)

    def test_10_master_clock_is_exactly_continuous(self):
        beats = read_beats(prompt6_script())
        self.assertEqual(beats[0]['master_in_ms'], 0)
        self.assertTrue(all(a['master_out_ms'] == b['master_in_ms'] for a, b in zip(beats, beats[1:])))

    def test_11_picture_replacement_does_not_change_audio(self):
        original = read_beats(bite(1, 0, 0))[0]
        changed = apply_overrides([original], {'documentary_beat_overrides': {'001': {'picture': {'file': 'BR-01.mp4', 'in_ms': 2000, 'out_ms': 3000}}}})[0]
        self.assertEqual(changed['picture_file'], 'BR-01.mp4')
        self.assertEqual(changed['audio_file'], 'S11 Marcus May.wav')

    def test_12_audio_replacement_does_not_change_picture(self):
        original = read_beats(bite(1, 0, 0))[0]
        changed = apply_overrides([original], {'documentary_beat_overrides': {'001': {'audio': {'file': 'S11 replacement.wav', 'in_ms': 0, 'out_ms': 1000}}}})[0]
        self.assertEqual(changed['audio_file'], 'S11 replacement.wav')
        self.assertEqual(changed['picture_file'], 'S03.mp4')

    def test_12b_picture_review_rejection_keeps_soundbite_audio(self):
        original = read_beats(bite(1, 0, 0))[0]
        changed = apply_overrides([original], {'documentary_beat_overrides': {'001': {'picture': {
            'status': 'MISSING PICTURE', 'review_reason': 'The supplied clip is an anchor shot, not the named speaker.'
        }}}})[0]
        self.assertEqual(changed['picture_status'], 'MISSING PICTURE')
        self.assertEqual(changed['source_file'], '')
        self.assertEqual(changed['picture_review_reason'], 'The supplied clip is an anchor shot, not the named speaker.')
        self.assertEqual(changed['audio_file'], 'S11 Marcus May.wav')

    def test_13_provisional_and_missing_picture_warnings_are_exposed(self):
        beats = read_beats(narration(1, 0, 0, missing=True) + narration(2, 1000, 1000))
        result = proposal({'assets': [], 'voiceover': {'duration': 2}}, beats)
        self.assertEqual(result['missing_pictures'][0]['beat'], '001')
        self.assertTrue(any(x['status'] == 'PROVISIONAL VIDEO' for x in result['provisional_sources']))

    def test_14_no_false_speaker_picture_association(self):
        beat = read_beats(bite(1, 0, 0))[0]
        self.assertIn('non-identifying', beat['direction'])
        self.assertEqual(beat['speaker'], '')
        self.assertEqual(beat['audio_file'], 'S11 Marcus May.wav')
        self.assertEqual(beat['picture_file'], 'S03.mp4')

    def test_15_srt_reference_and_structured_preflight_are_exposed(self):
        script = narration(1, 0, 0, missing=True).replace('Type: Narration (Voice Over)', 'Type: Narration (Voice Over)\nSRT Cue Reference: 17')
        beat = read_beats(script)[0]
        self.assertEqual((beat['srt_cue_reference'], beat['srt_blocks']), ('17', [17]))
        report = media_preflight([beat], {'assets': []}, Path('.'))
        self.assertEqual(report['missing_pictures'][0]['beat'], '001')
        self.assertEqual(report['blocking_issues'], [])

    def test_16_illustrative_without_a_file_is_a_specific_build_blocker(self):
        script = '''Beat: 001
Type: Narration (Voice Over)
Picture Status: ILLUSTRATIVE VISUAL REQUIRED
Image Prompt: Neutral map illustration — not actual case footage
Narration State: PLAYING
Footage Audio: MUTED
Narration Clock: 00:00:00,000 --> 00:00:01,000
Master Timeline: 00:00:00,000 --> 00:00:01,000
Visual Direction: Illustration review
On-screen Caption: None
'''
        report = media_preflight(read_beats(script), {'assets': []}, Path('.'))
        self.assertTrue(any('ILLUSTRATIVE VISUAL REQUIRED' in issue for issue in report['blocking_issues']))

    def test_17_closing_bite_keeps_the_authored_pause_before_a_short_file_tail(self):
        # The original narration file can carry a few silent milliseconds after the
        # last SRT/script endpoint. A closing bite at that endpoint must not be moved
        # to the container duration: doing so splits a final consecutive-bite run and
        # makes the saved plan fail its own frame audit.
        # Empty WAV field exercises the legacy combined picture/sound source form.
        closing = bite(2, 1000, 1000, picture='S01.mp4', wav='').replace(
            'Picture Source IN: 00:00:00,000\nPicture Source OUT: 00:00:01,000',
            'Picture Source IN: 00:00:01,000\nPicture Source OUT: 00:00:02,000')
        script = narration(1, 0, 0, source='S01.mp4') + closing
        beats = read_beats(script)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'sources').mkdir(); (root / 'inputs').mkdir()
            (root / 'sources' / 'S01.mp4').write_bytes(b'placeholder source')
            (root / 'inputs' / 'voiceover.mp3').write_bytes(b'placeholder narration')
            project = {
                'id': 'closing-tail', 'profile': 'documentary', 'production_script': {'text': script},
                'voiceover': {'name': 'voiceover.mp3', 'path': 'inputs/voiceover.mp3', 'duration': 1.214},
                'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 1000, 'text': 'Narration'}]},
                'assets': [{'id': 'source', 'name': 'S01.mp4', 'original_name': 'S01.mp4',
                            'kind': 'video', 'path': 'sources/S01.mp4', 'duration': 20,
                            'revision': 'source-revision'}], 'scenes': [],
            }
            with patch('documentary_storyboard.source_rate', return_value=Fraction(30, 1)):
                staged, plan = prepare(project, root, [], [], False, lambda path: True, beats=beats)
        self.assertEqual(narration_clock_s(staged), 1.0)
        self.assertEqual(plan['bites'][0]['pause_s'], 1.0)
        timeline = build_timeline(staged, plan)
        self.assertEqual(timeline['segments'][-1]['kind'], 'sound_bite')
        self.assertEqual(timeline['segments'][-1]['narration_resume_s'], 1.0)

    def test_17b_proposal_does_not_invent_a_gap_for_an_authored_short_tail(self):
        beats = read_beats(narration(1, 0, 0, source='S01.mp4'))
        result = proposal({'voiceover': {'duration': 1.214, 'clock_s': 1.0}, 'assets': []}, beats)
        self.assertEqual(result['narration_gaps'], [])

    def test_18_full_233_beat_review_is_compact_when_ranges_repeat(self):
        # Pairwise duplicate diagnostics would turn these repeated authored ranges
        # into tens of thousands of strings and make the review endpoint time out.
        result = proposal({'assets': [], 'voiceover': {'duration': 208}}, read_beats(prompt6_script()))
        self.assertEqual(len(result['beats']), 233)
        self.assertLess(len(result['issues']), 300)
        self.assertTrue(result['exact_duplicate_groups'])
        self.assertTrue(result['repeated_ranges_truncated'])
        self.assertLessEqual(len(result['repeated_ranges']), 500)


if __name__ == '__main__':
    unittest.main()
