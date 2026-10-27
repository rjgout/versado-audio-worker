import unittest
from app.pronunciation import Rule, prepare

class PronunciationTests(unittest.TestCase):
    def test_isolation_and_word_boundary(self):
        r = Rule(1, 1, 'nl', 'bom', 'Nephi', 'Nefi')
        self.assertEqual(prepare('Nephi, nephiër en NEPHI.', [r], 'nl', 'bom', 'piper', 'ronnie')[0], 'Nefi, nephiër en Nefi.')
        for language in ['en', 'de', 'fr', 'es']:
            self.assertEqual(prepare('Nephi', [r], language, 'bom', 'piper', 'ronnie')[0], 'Nephi')
        self.assertEqual(prepare('Nephi', [r], 'nl', 'bible', 'piper', 'ronnie')[0], 'Nephi')

    def test_priority_and_nonrecursive(self):
        rules = [Rule(1, 1, 'nl', 'bom', 'Nephi', 'Nefi'), Rule(2, 2, 'nl', 'bom', 'Nephi', 'Néfi', engine='piper'), Rule(3, 1, 'nl', 'bom', 'Néfi', 'wrong')]
        text, used = prepare('Nephi', rules, 'nl', 'bom', 'piper', 'ronnie')
        self.assertEqual(text, 'Néfi')
        self.assertEqual(used[0]['version'], 2)

    def test_unapproved_and_combining_marks(self):
        rules = [Rule(1, 1, 'nl', 'bom', 'café', 'kafee'), Rule(2, 1, 'nl', 'bom', 'Nephi', 'Nefi', status='proposal')]
        self.assertEqual(prepare('cafe\u0301 Nephi', rules, 'nl', 'bom', 'piper', 'ronnie')[0], 'kafee Nephi')
