"""Append-only pregame prediction log and separate results log. Python standard library only."""
import argparse,csv,datetime as dt,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent
PRED=HERE/'forward_predictions.csv'; RESULTS=HERE/'forward_results.csv'
PH=['recorded_at_utc','game_id','game_date','home','away','model_version','home_win_probability','book','home_moneyline_american','away_moneyline_american','odds_recorded_at_utc','decision','notes']
RH=['settled_at_utc','game_id','home_goals','away_goals','home_win_including_ot_so','notes']
def read(path):
 if not path.exists():return []
 with path.open(newline='') as f:return list(csv.DictReader(f))
def append(path,headers,row):
 with path.open('a',newline='') as f:
  w=csv.DictWriter(f,fieldnames=headers)
  if path.stat().st_size==0:w.writeheader()
  w.writerow(row)
def utc():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def main():
 p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
 r=sub.add_parser('record');r.add_argument('--game-id',required=True);r.add_argument('--game-date',required=True);r.add_argument('--home',required=True);r.add_argument('--away',required=True);r.add_argument('--prob',type=float,required=True);r.add_argument('--model',default='v2_base_candidate');r.add_argument('--book',default='');r.add_argument('--home-odds',type=int);r.add_argument('--away-odds',type=int);r.add_argument('--odds-time',default='');r.add_argument('--decision',choices=['NO BET','HOME','AWAY'],default='NO BET');r.add_argument('--notes',default='')
 s=sub.add_parser('settle');s.add_argument('--game-id',required=True);s.add_argument('--home-goals',type=int,required=True);s.add_argument('--away-goals',type=int,required=True);s.add_argument('--home-win',type=int,choices=[0,1],required=True);s.add_argument('--notes',default='')
 sub.add_parser('summary');a=p.parse_args();pred=read(PRED);res=read(RESULTS)
 if a.command=='record':
  if not 0<a.prob<1: p.error('Probability must be between 0 and 1')
  if any(x['game_id']==a.game_id for x in pred):p.error('Game already recorded; historical predictions are immutable')
  if a.decision!='NO BET' and (not a.book or a.home_odds is None or a.away_odds is None or not a.odds_time):p.error('Bet decision requires documented book, both odds, and odds timestamp')
  if (a.home_odds is None)!=(a.away_odds is None):p.error('Provide both sides of the moneyline or neither')
  row=dict(zip(PH,[utc(),a.game_id,a.game_date,a.home,a.away,a.model,a.prob,a.book,a.home_odds if a.home_odds is not None else '',a.away_odds if a.away_odds is not None else '',a.odds_time,a.decision,a.notes]));append(PRED,PH,row);print('Recorded',a.game_id)
 elif a.command=='settle':
  if not any(x['game_id']==a.game_id for x in pred):p.error('No pregame prediction exists for this game')
  if any(x['game_id']==a.game_id for x in res):p.error('Already settled; original result is immutable')
  if a.home_goals==a.away_goals:p.error('Final NHL score cannot be tied')
  if int(a.home_goals>a.away_goals)!=a.home_win:p.error('Winner and final score disagree')
  append(RESULTS,RH,dict(zip(RH,[utc(),a.game_id,a.home_goals,a.away_goals,a.home_win,a.notes])));print('Settled',a.game_id)
 else:
  settled={x['game_id']:x for x in res};joined=[(x,settled[x['game_id']]) for x in pred if x['game_id'] in settled]
  if not joined: print(json.dumps({'predictions':len(pred),'settled':0,'note':'No results yet; no performance claims.'},indent=2));return
  import math
  n=len(joined);acc=sum((float(x['home_win_probability'])>=.5)==bool(int(y['home_win_including_ot_so'])) for x,y in joined)/n
  brier=sum((float(x['home_win_probability'])-int(y['home_win_including_ot_so']))**2 for x,y in joined)/n
  ll=-sum(int(y['home_win_including_ot_so'])*math.log(float(x['home_win_probability']))+(1-int(y['home_win_including_ot_so']))*math.log1p(-float(x['home_win_probability'])) for x,y in joined)/n
  print(json.dumps({'predictions':len(pred),'settled':n,'accuracy':round(acc,5),'brier':round(brier,5),'log_loss':round(ll,5),'roi':'Not computed without documented odds and a verified betting policy'},indent=2))
if __name__=='__main__':main()
