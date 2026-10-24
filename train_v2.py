"""NHL EDGE proof-of-concept: pregame rolling shot-quality features, chronological holdout.
Requires pandas numpy scikit-learn. Run: python train.py
"""
from pathlib import Path
import zipfile, json
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss,brier_score_loss,accuracy_score,roc_auc_score
ROOT=Path(__file__).resolve().parent.parent
OUT=Path(__file__).resolve().parent
SHOT=ROOT/'shots_2021-2025.zip'
GOALIE=ROOT/'2025 (1).zip'
cols=['season','game_id','homeTeamCode','awayTeamCode','teamCode','isPlayoffGame','homeTeamWon','goal','xGoal','shotRebound','shotRush','shotDistance','shotOnEmptyNet']
with zipfile.ZipFile(SHOT) as z:
 with z.open(z.namelist()[0]) as f:
  shots=pd.read_csv(f,usecols=lambda c:c in cols,low_memory=False)
shots=shots[(shots.isPlayoffGame==0)&(shots.season.between(2021,2025))].copy()
shots['gid']=shots.season.astype(str)+'_'+shots.game_id.astype(str)
shots['teamCode']=shots.teamCode.astype(str)
shots['xGoal']=pd.to_numeric(shots.xGoal,errors='coerce').fillna(0)
shots['goal']=pd.to_numeric(shots.goal,errors='coerce').fillna(0)
shots['shotRebound']=pd.to_numeric(shots.shotRebound,errors='coerce').fillna(0)
shots['shotRush']=pd.to_numeric(shots.shotRush,errors='coerce').fillna(0)
shots['shotOnEmptyNet']=pd.to_numeric(shots.shotOnEmptyNet,errors='coerce').fillna(0)
shots['danger']=((shots.xGoal>=.15)&(shots.shotOnEmptyNet==0)).astype(int)
shots['nonempty_xg']=shots.xGoal.where(shots.shotOnEmptyNet==0,0)
agg=shots.groupby(['gid','teamCode'],sort=False).agg(xgf=('nonempty_xg','sum'),shots=('goal','size'),goals=('goal','sum'),danger=('danger','sum'),rebounds=('shotRebound','sum'),rush=('shotRush','sum')).reset_index().rename(columns={'teamCode':'team'})
meta=shots.groupby('gid',sort=False).agg(season=('season','first'),game_id=('game_id','first'),home=('homeTeamCode','first'),away=('awayTeamCode','first'),home_win=('homeTeamWon','first')).reset_index()
# Game ID is chronological within season, with occasional rescheduled games; recover actual dates from goalie logs for correct ordering.
dates=[]
for fname in ['2008_to_2024 (1).zip','2025 (1).zip']:
 with zipfile.ZipFile(ROOT/fname) as z:
  with z.open(z.namelist()[0]) as f:
   d=pd.read_csv(f,usecols=['season','gameId','gameDate','situation'],low_memory=False)
 d=d[d.situation=='all'][['season','gameId','gameDate']].drop_duplicates()
 d['gid']=d.season.astype(str)+'_'+(d.gameId.astype(int)%100000).astype(str)
 dates.append(d[['gid','gameDate']])
cal=pd.concat(dates).drop_duplicates('gid')
meta=meta.merge(cal,on='gid',how='left')
meta['gameDate']=pd.to_datetime(meta.gameDate.astype('Int64').astype(str),format='%Y%m%d',errors='coerce')
# Never use rows without reliable chronology.
meta=meta.dropna(subset=['gameDate'])
# Filter ambiguous/invalid game outcomes; verify one row per game and both teams shot records.
meta=meta.drop_duplicates('gid').sort_values(['gameDate','game_id'])
agg=agg[agg.gid.isin(meta.gid)]
teamgames=pd.concat([meta[['gid','gameDate','season','home']].rename(columns={'home':'team'}).assign(side='home'),meta[['gid','gameDate','season','away']].rename(columns={'away':'team'}).assign(side='away')],ignore_index=True)
teamgames=teamgames.merge(agg,on=['gid','team'],how='left')
opp=teamgames[['gid','team','xgf','goals']].rename(columns={'team':'opponent','xgf':'xga','goals':'ga'})
teamgames['opponent']=np.where(teamgames.side=='home',teamgames.gid.map(meta.set_index('gid').away),teamgames.gid.map(meta.set_index('gid').home))
teamgames=teamgames.merge(opp,on=['gid','opponent'],how='left')
teamgames=teamgames.dropna(subset=['xgf','xga','goals','ga'])
# Pregame-only TEAM goaltending form, not a forecast of the named starting goalie.
# Sum multiple goalies in a game; prior 5 TEAM games are shifted before merging.
keepers=[]
for fn in ['2008_to_2024 (1).zip','2025 (1).zip']:
 with zipfile.ZipFile(ROOT/fn) as z:
  with z.open(z.namelist()[0]) as f:
   g=pd.read_csv(f,usecols=['season','gameId','playerTeam','situation','xGoals','goals','icetime'],low_memory=False)
 g=g[(g.situation=='all') & g.season.between(2021,2025)].copy()
 g['gid']=g.season.astype(str)+'_'+(g.gameId.astype('int64')%100000).astype(str)
 g['goalie_gsax']=pd.to_numeric(g.xGoals,errors='coerce')-pd.to_numeric(g.goals,errors='coerce')
 keepers.append(g.groupby(['gid','playerTeam'],as_index=False).agg(goalie_gsax=('goalie_gsax','sum'),goalie_minutes=('icetime','sum')))
keeper=pd.concat(keepers,ignore_index=True).drop_duplicates(['gid','playerTeam']).rename(columns={'playerTeam':'team'})
teamgames=teamgames.merge(keeper,on=['gid','team'],how='left')
teamgames=teamgames.sort_values(['team','gameDate','gid'])
teamgames['goalie_gsax_5']=teamgames.groupby('team').goalie_gsax.transform(lambda s:s.shift(1).rolling(5,min_periods=3).mean())
# Rolling means shift(1) ensures no current game or future data enters features.
base=['goals','ga','shots']
extra=['xgf','xga','danger','rebounds','rush']
for feature in base+extra:
 for window in [5,15]:
  teamgames[f'{feature}_{window}']=teamgames.groupby('team')[feature].transform(lambda s:s.shift(1).rolling(window,min_periods=3).mean())
teamgames['days_rest']=teamgames.groupby('team').gameDate.diff().dt.days.clip(0,10)
featurecols=[f'{f}_{w}' for f in base+extra for w in [5,15]]+['days_rest','goalie_gsax_5']
home=teamgames[teamgames.side=='home'][['gid','team']+featurecols].rename(columns={'team':'home',**{c:'h_'+c for c in featurecols}})
away=teamgames[teamgames.side=='away'][['gid','team']+featurecols].rename(columns={'team':'away',**{c:'a_'+c for c in featurecols}})
games=meta.merge(home,on=['gid','home']).merge(away,on=['gid','away'])
for c in featurecols: games['diff_'+c]=games['h_'+c]-games['a_'+c]
features=['diff_'+c for c in featurecols]
games=games.dropna(subset=features+['home_win']).copy()
# Exclude ties/invalid outcomes and potential labels outside 0/1.
games=games[games.home_win.isin([0,1])]
# Walk-forward holdouts; do not train on the holdout season.
train=games[games.season.between(2021,2024)]
test=games[games.season==2025]
basecols=['diff_'+c for c in featurecols if c.split('_')[0] in ['goals','ga','shots','days']]
results={}
rows=[]
for holdout in [2024,2025]:
 tr=games[games.season<holdout]
 te=games[games.season==holdout]
 for label,cols in [('Base',basecols),('Base+Goalie',basecols+['diff_goalie_gsax_5']),('Shot+',features)]:
  model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000))
  model.fit(tr[cols],tr.home_win.astype(int))
  prob=model.predict_proba(te[cols])[:,1]
  y=te.home_win.astype(int)
  metrics={'train_games':len(tr),'holdout_games':len(te),'log_loss':round(float(log_loss(y,prob)),5),'brier':round(float(brier_score_loss(y,prob)),5),'accuracy':round(float(accuracy_score(y,prob>=.5)),5),'auc':round(float(roc_auc_score(y,prob)),5)}
  results[f'{holdout}_{label}']=metrics
  rows.extend({'season':holdout,'model':label,'game_id':gid,'date':dt.strftime('%Y-%m-%d'),'home':h,'away':a,'home_win':int(yy),'home_probability':float(pp)} for gid,dt,h,a,yy,pp in zip(te.gid,te.gameDate,te.home,te.away,y,prob))
pd.DataFrame(rows).to_csv(OUT/'walkforward_predictions.csv',index=False)
with open(OUT/'metrics.json','w') as f:json.dump(results,f,indent=2)
print(json.dumps(results,indent=2))
print('games missing dates',shots.gid.nunique()-meta.gid.nunique())
