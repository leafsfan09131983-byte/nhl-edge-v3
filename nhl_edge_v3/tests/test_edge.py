import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo
import edge

class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=edge.connect(Path(self.tmp.name)/'test.sqlite')
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def game(self,game_id,date,home='TOR',away='MTL',state='FUT',hg=None,ag=None):
        return {'id':game_id,'season':20262027,'gameType':2,'gameDate':date,
                'startTimeUTC':date+'T23:00:00Z','homeTeam':{'abbrev':home,**({'score':hg} if hg is not None else {})},
                'awayTeam':{'abbrev':away,**({'score':ag} if ag is not None else {})},'gameState':state}
    def test_idempotent_ingest_and_settlement(self):
        g=self.game(2026020001,'2026-10-24')
        edge.ingest_game(self.db,g);edge.ingest_game(self.db,g)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM games').fetchone()[0],1)
        edge.ingest_game(self.db,self.game(2026020001,'2026-10-24',state='OFF',hg=3,ag=2))
        self.assertEqual(self.db.execute('SELECT home_win FROM games').fetchone()[0],1)
        edge.ingest_game(self.db,g)
        self.assertEqual(self.db.execute('SELECT home_win FROM games').fetchone()[0],1)
    def test_snapshot_no_lookahead_and_no_duplicate(self):
        edge.ingest_game(self.db,self.game(2026020001,'2026-10-23',state='OFF',hg=3,ag=1))
        edge.ingest_game(self.db,self.game(2026020002,'2026-10-24'))
        capture=dt.datetime(2026,10,24,11,tzinfo=ZoneInfo('America/Toronto'))
        self.assertEqual(edge.forecast(self.db,capture),1)
        self.assertEqual(edge.forecast(self.db,capture),0)
        f=self.db.execute('SELECT * FROM forecasts').fetchone()
        self.assertEqual(f['decision'],'NO BET')
        self.assertLess(f['home_probability'],1)
        self.assertEqual(edge.summary(self.db)['settled'],0)
        edge.ingest_game(self.db,self.game(2026020002,'2026-10-24',state='OFF',hg=2,ag=4))
        self.assertEqual(edge.summary(self.db)['settled'],1)
    def test_non_regular_excluded(self):
        g=self.game(2026030001,'2026-10-24');g['gameType']=3
        self.assertFalse(edge.ingest_game(self.db,g))
    def test_no_forecast_after_puck_drop(self):
        edge.ingest_game(self.db,self.game(2026020002,'2026-10-24'))
        capture=dt.datetime(2026,10,24,21,tzinfo=ZoneInfo('America/Toronto'))
        self.assertEqual(edge.forecast(self.db,capture),0)

if __name__=='__main__':unittest.main()
