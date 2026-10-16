import unittest
from datetime import date, timedelta
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
        for name in (
            'World Rowing Indoor Championships',
            'World Rowing Coastal Championships',
            'World Rowing Beach Sprint Championships',
            'World Rowing Under 23 Championships',
            'World Rowing Masters Championships',
            'World Rowing Junior Championships',
            'World Championships',
            'European Rowing Coastal Championships',
            'European Indoor Rowing Championships',
            'Indoor Championships',
            'Coastal Rowing Championships',
            'World Rowing Cup II',
            'MS ve veslování', 'ME ve veslování',
            'WRICH 2027', 'WRCH', 'ERICH', 'ERCH', 'WRBSCH',
            'World Rowing Para Rowing Championships',
            'Para Rowing International Regatta', 'Para-veslování',
            'World Rowing Beach Sprint Series I.kolo',
            'World Rowing Beach Sprint Finals',
            'YOG Dakar 2026 - coastal rowing',
            'Coupe de la Jeunesse 2027', '4th European Games',
        ):
            with self.subTest(name=name):
                self.assertTrue(EXCLUDED.search(name), name)
        for name in ('Mistrovství ČR', 'Národní mistrovství', 'Pražské primátorky', 'International Regatta', 'Kontrolní závody juniorů', 'Kontrolní závody seniorů', 'Kontrolní závody seniorů A', 'Český pohár v beach sprintu'):
            with self.subTest(name=name):
                self.assertFalse(EXCLUDED.search(name), name)
    def test_same_name_day_even_if_end_differs(self):
        self.assertEqual(event_key(dict(summary='  ČESKÁ  REGATA ', start=date(2027,5,2), end=date(2027,5,3))),
                         event_key(dict(summary='česká regata', start=date(2027,5,2), end=date(2027,5,4))))

    def test_senior_control_race_alias(self):
        a = dict(summary='Kontrolní závody seniorů A', start=date(2027, 6, 5))
        b = dict(summary='Kontrolní závody seniorů', start=date(2027, 6, 5))
        self.assertEqual(event_key(a), event_key(b))
        self.assertNotEqual(event_key(a), event_key(dict(b, start=date(2027, 6, 6))))

    def test_existing_senior_control_race_alias(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {
            'items': [{'summary': 'Kontrolní závody seniorů A', 'start': {'date': '2027-06-05'}}]}
        event = dict(summary='Kontrolní závody seniorů', start=date(2027, 6, 5),
                     end=date(2027, 6, 7), description='', location='', international=False,
                     source='https://veslo.cz/a')
        self.assertEqual(sync(service, 'calendar', [event], date(2027, 1, 1), date(2028, 1, 1), '9'), (0, 1))
        service.events.return_value.insert.assert_not_called()

    def test_exact_existing_duplicate_is_skipped(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {
            'items': [
                {'summary': 'Kontrolní závody seniorů A', 'start': {'date': '2027-06-05'}},
                {'summary': 'Kontrolní závody seniorů A', 'start': {'date': '2027-06-05'}},
            ]}
        event = dict(summary='Kontrolní závody seniorů A', start=date(2027, 6, 5),
                     end=date(2027, 6, 7), description='', location='', international=False,
                     source='https://veslo.cz/a')
        with self.assertLogs('gcalveslo', level='WARNING') as messages:
            self.assertEqual(sync(service, 'calendar', [event], date(2027, 1, 1), date(2028, 1, 1), '9'), (0, 1))
        self.assertTrue(any('Already duplicated' in msg for msg in messages.output))
        service.events.return_value.insert.assert_not_called()
        service.events.return_value.delete.assert_not_called()

    def test_identical_races_in_same_import_insert_only_once(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items': []}
        event = dict(summary='Kontrolní závody seniorů A', start=date(2027, 6, 5),
                     end=date(2027, 6, 7), description='', location='', international=False,
                     source='https://veslo.cz/a')
        self.assertEqual(sync(service, 'calendar', [event, dict(event)], date(2027, 1, 1),
                              date(2028, 1, 1), '9'), (1, 1))
        self.assertEqual(service.events.return_value.insert.call_count, 1)

    def test_duplicate_in_input_only_insert_once(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items': []}
        first = dict(summary='Regata', start=date(2027,5,2), end=date(2027,5,3),
                     description='',location='',international=False,source='https://veslo.cz/a')
        second = dict(first, summary=' regata ', end=date(2027,5,4), source='https://veslo.cz/b')
        self.assertEqual(sync(service,'calendar',[first,second],date(2027,1,1),date(2028,1,1),'9'), (1,1))
        self.assertEqual(service.events.return_value.insert.call_count, 1)

    def test_existing_timed_event_blocks_import(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {
            'items':[{'summary':'REGATA', 'start':{'dateTime':'2027-05-02T09:00:00+02:00'},
                      'end':{'dateTime':'2027-05-02T16:00:00+02:00'}}]}
        event = dict(summary='Regata',start=date(2027,5,2),end=date(2027,5,4),
                     description='',location='',international=False,source='https://veslo.cz/a')
        self.assertEqual(sync(service,'calendar',[event],date(2027,1,1),date(2028,1,1),'9'),(0,1))
        service.events.return_value.insert.assert_not_called()

    def test_duplicate_no_delete(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items':[{'summary':'Regata', 'start':{'date':'2026-11-03'}, 'end':{'date':'2026-11-04'}}]}
        event = dict(summary='Regata',start=date(2026,11,3),end=date(2026,11,4),description='',location='',international=False,source='https://veslo.cz/test')
        result = sync(service,'calendar',[event],date(2026,10,16),date(2027,10,16),'9')
        self.assertEqual(result,(0,1))
        service.events.return_value.delete.assert_not_called()
        service.events.return_value.insert.assert_not_called()

if __name__=='__main__': unittest.main()
