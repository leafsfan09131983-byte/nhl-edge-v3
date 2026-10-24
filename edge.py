"""NHL EDGE V3: stdlib-only collection, SQLite persistence, provisional Elo forecasts.
NOT the validated V2 model. No odds are inferred or invented.
"""
import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

DB = Path(os.getenv('EDGE_DB', str(Path(__file__).parent / 'data' / 'edge.sqlite')))
BASE = 'https://api-web.nhle.com/v1'
ET = ZoneInfo('America/Toronto')
TEAMS = 'ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LAK MIN MTL NJD NSH NYI NYR OTT PHI PIT SEA SJS STL TBL TOR UTA VAN VGK WPG WSH'.split()
MODEL = 'V3_ELO_PROVISIONAL_1'


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS games (
      game_id INTEGER PRIMARY KEY, season INTEGER NOT NULL, game_type INTEGER NOT NULL,
      game_date TEXT NOT NULL, start_utc TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
      state TEXT NOT NULL, home_goals INTEGER, away_goals INTEGER,
      home_win INTEGER, updated_utc TEXT NOT NULL,
      CHECK (home_win IN (0,1) OR home_win IS NULL)
    );
    CREATE TABLE IF NOT EXISTS forecasts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER NOT NULL,
      captured_utc TEXT NOT NULL, scheduled_start_utc TEXT NOT NULL,
      model TEXT NOT NULL, home_probability REAL NOT NULL,
      away_probability REAL NOT NULL, decision TEXT NOT NULL DEFAULT 'NO BET',
      reason TEXT NOT NULL, snapshot TEXT NOT NULL,
      UNIQUE(game_id, model, captured_utc),
      CHECK (home_probability BETWEEN 0 AND 1),
      FOREIGN KEY(game_id) REFERENCES games(game_id)
    );
    CREATE TABLE IF NOT EXISTS odds (
      id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER NOT NULL,
      bookmaker TEXT NOT NULL, home_decimal REAL, away_decimal REAL,
      observed_utc TEXT NOT NULL, source TEXT NOT NULL,
      UNIQUE(game_id, bookmaker, observed_utc)
    );
    CREATE TABLE IF NOT EXISTS collection_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ran_utc TEXT NOT NULL,
      mode TEXT NOT NULL, fetched INTEGER NOT NULL, error TEXT
    );
    ''')
    return conn


def get_json(path, retries=3):
    req = urllib.request.Request(BASE + path, headers={'User-Agent':'NHL-EDGE-V3/1.0 (research; public game results)', 'Accept':'application/json'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except Exception:
            if attempt == retries-1:
                raise
            time.sleep(2**attempt)


def iso_utc(value):
    return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(dt.timezone.utc).isoformat()


def ingest_game(conn, g, fetched=None):
    if int(g.get('gameType', 0)) != 2:  # NHL regular-season games only
        return False
    home, away = g.get('homeTeam') or {}, g.get('awayTeam') or {}
    h, a = home.get('abbrev'), away.get('abbrev')
    start = g.get('startTimeUTC')
    if not (g.get('id') and h and a and start):
        return False
    state = str(g.get('gameState','UNKNOWN')).upper()
    # FINAL is definitive; OFF is often postgame. OFF is only accepted when both scores exist.
    complete = state in ('FINAL','OFF') and isinstance(home.get('score'),int) and isinstance(away.get('score'),int)
    hg = int(home['score']) if complete else None
    ag = int(away['score']) if complete else None
    # Full-game winner including OT/SO. Do not settle tied scores.
    hw = int(hg > ag) if complete and hg != ag else None
    ts = (fetched or now_utc()).isoformat()
    conn.execute('''INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(game_id) DO UPDATE SET
       state=excluded.state,
       home_goals=CASE WHEN excluded.home_win IS NOT NULL THEN excluded.home_goals ELSE games.home_goals END,
       away_goals=CASE WHEN excluded.home_win IS NOT NULL THEN excluded.away_goals ELSE games.away_goals END,
       home_win=COALESCE(excluded.home_win,games.home_win),updated_utc=excluded.updated_utc''',
       (int(g['id']),int(g.get('season') or str(g['id'])[:4]),2,
        str(g.get('gameDate') or start[:10]),iso_utc(start),h,a,state,hg,ag,hw,ts))
    return True


def ingest_payload(conn, payload):
    games = list(payload.get('games') or [])
    for day in payload.get('gameWeek') or []:
        games.extend(day.get('games') or [])
    count = 0
    for g in games:
        count += bool(ingest_game(conn,g))
    conn.commit()
    return count


def collect_daily(conn, date=None):
    local = date or now_utc().astimezone(ET).date()
    count = 0
    # Check last 3 days for delayed final scores and next 7 for schedule.
    for offset in range(-3,8):
        d = local + dt.timedelta(days=offset)
        payload = get_json('/score/' + d.isoformat())
        count += ingest_payload(conn,payload)
    conn.execute('INSERT INTO collection_runs(ran_utc,mode,fetched,error) VALUES (?,?,?,NULL)',(now_utc().isoformat(),'daily',count))
    conn.commit()
    return count


def bootstrap(conn, seasons=(20242025,20252026,20262027)):
    total = 0
    for season in seasons:
        for team in TEAMS:
            payload = get_json(f'/club-schedule-season/{team}/{season}')
            total += ingest_payload(conn,payload)
            time.sleep(.15)
    conn.execute('INSERT INTO collection_runs(ran_utc,mode,fetched,error) VALUES (?,?,?,NULL)',(now_utc().isoformat(),'bootstrap',total))
    conn.commit()
    return total


def elo_prob(rh,ra,home_adv=35):
    return 1/(1+10**(-(rh+home_adv-ra)/400))


def ratings_as_of(conn, cutoff_utc):
    """Only games completed before cutoff. Uses scheduled start as a conservative proxy
    for ordering; excludes games on the forecast date entirely to prevent same-day leakage.
    """
    cutoff_date = dt.datetime.fromisoformat(cutoff_utc).astimezone(ET).date().isoformat()
    rows = conn.execute('''SELECT * FROM games WHERE home_win IS NOT NULL AND game_type=2
        AND game_date < ? ORDER BY start_utc, game_id''',(cutoff_date,)).fetchall()
    ratings = {}
    for g in rows:
        h,a = g['home'],g['away']
        rh,ra = ratings.get(h,1500.),ratings.get(a,1500.)
        p = elo_prob(rh,ra)
        delta = 18*(g['home_win']-p)
        ratings[h],ratings[a] = rh+delta,ra-delta
    return ratings, len(rows)


def forecast(conn, capture=None):
    captured = capture or now_utc()
    if captured.tzinfo is None:
        raise ValueError('Capture timestamp must be timezone-aware')
    cap = captured.astimezone(dt.timezone.utc).isoformat()
    local_day = captured.astimezone(ET).date().isoformat()
    ratings, history_n = ratings_as_of(conn,cap)
    upcoming = conn.execute('''SELECT * FROM games WHERE game_date=? AND home_win IS NULL
        ORDER BY start_utc, game_id''',(local_day,)).fetchall()
    count = 0
    for g in upcoming:
        start = dt.datetime.fromisoformat(g['start_utc'])
        if start <= captured.astimezone(dt.timezone.utc):
            continue
        exists = conn.execute('SELECT 1 FROM forecasts WHERE game_id=? AND model=? AND substr(captured_utc,1,10)=?',
                              (g['game_id'],MODEL,cap[:10])).fetchone()
        # One daily immutable snapshot per game/model; never overwrite.
        if exists:
            continue
        h,a = ratings.get(g['home'],1500.),ratings.get(g['away'],1500.)
        p = elo_prob(h,a)
        context = json.dumps({'home_rating':round(h,2),'away_rating':round(a,2),'historical_games':history_n,
                              'features':'past final regular-season outcomes; 35 Elo home points; K=18'},sort_keys=True)
        conn.execute('''INSERT INTO forecasts(game_id,captured_utc,scheduled_start_utc,model,home_probability,
          away_probability,decision,reason,snapshot) VALUES (?,?,?,?,?,?,?,?,?)''',
          (g['game_id'],cap,g['start_utc'],MODEL,p,1-p,'NO BET',
           'Provisional uncalibrated Elo; no verified sportsbook price or validated edge',context))
        count+=1
    conn.commit()
    return count


def summary(conn):
    rows=conn.execute('''SELECT f.*,g.home,g.away,g.home_win,g.home_goals,g.away_goals,g.game_date
       FROM forecasts f JOIN games g USING(game_id) ORDER BY f.captured_utc DESC''').fetchall()
    settled=[r for r in rows if r['home_win'] is not None]
    brier=sum((r['home_probability']-r['home_win'])**2 for r in settled)/len(settled) if settled else None
    accuracy=sum((r['home_probability']>=.5)==bool(r['home_win']) for r in settled)/len(settled) if settled else None
    return {'predictions':len(rows),'settled':len(settled),'accuracy':accuracy,'brier':brier,'bets_recommended':0}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['bootstrap','collect','forecast','daily','summary'])
    parser.add_argument('--date',help='ET YYYY-MM-DD for collection')
    args=parser.parse_args()
    with connect() as db:
        if args.command=='bootstrap':print('Ingested',bootstrap(db))
        if args.command=='collect':print('Ingested',collect_daily(db,dt.date.fromisoformat(args.date) if args.date else None))
        if args.command=='forecast':print('New forecasts',forecast(db))
        if args.command=='daily':
            print('Ingested',collect_daily(db))
            print('New forecasts',forecast(db))
        if args.command=='summary':print(json.dumps(summary(db),indent=2))

if __name__=='__main__':main()
