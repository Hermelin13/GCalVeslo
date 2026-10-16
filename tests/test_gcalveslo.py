import unittest
from datetime import date
from unittest.mock import Mock
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gcalveslo import parse_day, event_key, sync, EXCLUDED

class Tests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_day('29.5.-1.6.',2027,5),(date(2027,5,29),date(2027,6,1)))
        self.assertEqual(parse_day('25.-26.1.',2027,1),(date(2027,1,25),date(2027,1,26)))
        self.assertEqual(parse_day('1.-3.',2027,9),(date(2027,9,1),date(2027,9,3)))
    def test_exclusions(self):
        self.assertTrue(EXCLUDED.search('Mistrovství světa ve veslování'))
        self.assertTrue(EXCLUDED.search('Světový pohár'))
        self.assertFalse(EXCLUDED.search('Pohár ČR'))
    def test_duplicate_no_delete(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items':[{'summary':'Regata', 'start':{'date':'2026-11-03'}, 'end':{'date':'2026-11-04'}}]}
        event = dict(summary='Regata',start=date(2026,11,3),end=date(2026,11,4),description='',location='',international=False,source='https://veslo.cz/test')
        result = sync(service,'calendar',[event],date(2026,10,16),date(2027,10,16),'9')
        self.assertEqual(result,(0,1))
        service.events.return_value.delete.assert_not_called()
        service.events.return_value.insert.assert_not_called()

if __name__=='__main__': unittest.main()
