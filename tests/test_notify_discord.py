import unittest
from notify_discord import build_message

class TestDiscord(unittest.TestCase):
    def test_success_counts(self):
        data=build_message('success', {'added':3,'skipped':5,'loaded':8,'from':'2026-10-16','until':'2027-10-16'},'https://github.com/acme/repo/actions/runs/123')
        msg=data['embeds'][0]['description']
        self.assertIn('**3**',msg)
        self.assertIn('**5**',msg)
        self.assertEqual(data['allowed_mentions'], {'parse':[]})
    def test_failure_no_secrets(self):
        data=build_message('failure',None,'https://github.com/acme/repo/actions/runs/123')
        self.assertIn('chyba',data['embeds'][0]['title'])
        self.assertIn('GitHub Actions',data['embeds'][0]['description'])

if __name__=='__main__': unittest.main()
