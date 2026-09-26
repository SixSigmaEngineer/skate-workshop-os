import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ui'))
from onenote_import import build_plan


class OneNoteImportTests(unittest.TestCase):
    def test_word_pages_folder_grouping_and_media_limitation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = root / 'ETSU'
            notebook.mkdir()
            with zipfile.ZipFile(notebook / 'Section.docx', 'w') as archive:
                archive.writestr('word/document.xml', '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Meeting A</w:t></w:r></w:p>
                <w:p><w:r><w:t>Original meeting text</w:t></w:r></w:p>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Meeting B</w:t></w:r></w:p>
                <w:p><w:r><w:drawing/></w:r></w:p></w:body></w:document>''')
                archive.writestr('word/media/photo.png', b'photo fixture')
                archive.writestr('word/embeddings/file.bin', b'attachment fixture')
            plan = build_plan(str(root), include_bodies=True)
            self.assertEqual(plan['total_notes'], 2)
            self.assertEqual(plan['notebooks'][0]['session_slug'], 'etsu')
            self.assertEqual([n['title'] for n in plan['notebooks'][0]['notes']], ['Meeting A', 'Meeting B'])
            self.assertIn('Original meeting text', plan['notebooks'][0]['notes'][0]['body'])
            self.assertIn('not copied', plan['warnings'][0])
            single = build_plan(str(root), mode='single', session_name='My notebook', split_pages=False)
            self.assertEqual(single['total_notes'], 1)
            self.assertEqual(single['notebooks'][0]['session_slug'], 'my-notebook')

    def test_export_dialog_unsupported_formats_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ext in ('.one', '.onepkg', '.mht', '.xps', '.zip'):
                (root / ('export' + ext)).write_bytes(b'fixture')
            plan = build_plan(str(root))
            self.assertEqual(plan['total_notes'], 0)
            self.assertEqual(len(plan['skipped']), 5)
            self.assertTrue(all('.docx' in item['reason'] for item in plan['skipped']))
