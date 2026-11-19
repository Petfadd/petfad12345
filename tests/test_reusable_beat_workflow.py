"""Tests for production-agnostic structured Beat workflow entry points."""
import shutil
import unittest

from app import PROJECTS, app, script_workflow_info
from documentary_beats import has_structured_beat_blocks, structured_beat_block_count


class ReusableBeatWorkflowTests(unittest.TestCase):
    def test_01_detects_any_labelled_beat_script_without_case_names(self):
        text = '''Beat: 010
Type: Narration (Voice Over)

Beat: 011
Type: Documentary Sound Bite
'''
        self.assertTrue(has_structured_beat_blocks(text))
        self.assertEqual(structured_beat_block_count(text), 2)
        info = script_workflow_info({'edit_mode': 'documentary', 'script_workflow': 'standard',
                                     'production_script': {'text': text}})
        self.assertEqual((info['selected'], info['detected'], info['beat_blocks']), ('standard', 'structured_beat', 2))
        self.assertIn('Any sequential Beat count', info['detail'])

    def test_02_standard_script_preference_keeps_existing_workflow_available(self):
        info = script_workflow_info({'edit_mode': 'documentary', 'script_workflow': 'structured_beat',
                                     'production_script': {'text': 'A standard script with no Beat headings.'}})
        self.assertEqual((info['selected'], info['detected']), ('structured_beat', 'standard'))
        self.assertIn('Existing Storyroom script', info['detail'])

    def test_03_starter_download_is_generic(self):
        with app.test_client() as client:
            response = client.get('/api/structured-beat-script-template')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename=structured-beat-script-starter.txt', response.headers['Content-Disposition'])
        text = response.get_data(as_text=True)
        self.assertIn('Reusable for any documentary project', text)
        self.assertNotIn('East St. Louis', text)
        self.assertNotIn('Marcus May', text)
        response.close()

    def test_04_new_documentary_project_can_choose_structured_beats(self):
        with app.test_client() as client:
            response = client.post('/api/projects', json={'title': 'Reusable workflow test', 'edit_mode': 'documentary',
                                                           'script_workflow': 'structured_beat', 'format': 'landscape',
                                                           'size': '720p'})
        self.assertEqual(response.status_code, 201)
        project = response.get_json()
        try:
            self.assertEqual(project['script_workflow'], 'structured_beat')
            self.assertEqual(project['script_workflow_info']['detected'], 'none')
        finally:
            shutil.rmtree(PROJECTS / project['id'], ignore_errors=True)

    def test_05_structured_beats_rejects_the_non_documentary_workspace(self):
        with app.test_client() as client:
            response = client.post('/api/projects', json={'title': 'Wrong workspace', 'edit_mode': 'review',
                                                           'script_workflow': 'structured_beat', 'format': 'landscape',
                                                           'size': '720p'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Structured Beat scripts use the documentary workspace', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
