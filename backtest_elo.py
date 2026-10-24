"""Historical comparison for the provisional V3 Elo model.
Uses game outcomes in V2 walkforward_predictions.csv, never V2 probabilities as features.
2024-25 warms up ratings; 2025-26 is an unseen evaluation season.
"""
import csv,json,math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).parent
with open(ROOT/'walkforward_predictions.csv',newline='') as f:
    rows=[r for r in csv.DictReader(f) if r['model']=='Base' and int(r['season']) in (2024,2025)]
rows.sort(key=lambda r:(r['date'],r['game_id']))
ratings=defaultdict(lambda:1500.0)
output=[]
for date in sorted({r['date'] for r in rows}):
    day=[r for r in rows if r['date']==date]
    predictions=[]
    for r in day:
        p=1/(1+10**(-(ratings[r['home']]+35-ratings[r['away']])/400))
        predictions.append((r,p))
        if int(r['season'])==2025:
            output.append({'date':date,'game_id':r['game_id'],'home':r['home'],'away':r['away'],
                           'home_win':int(r['home_win']),'home_probability':p})
    for r,p in predictions:
        delta=18*(int(r['home_win'])-p)
        ratings[r['home']]+=delta
        ratings[r['away']]-=delta
n=len(output)
accuracy=sum((r['home_probability']>=.5)==bool(r['home_win']) for r in output)/n
brier=sum((r['home_probability']-r['home_win'])**2 for r in output)/n
logloss=-sum(r['home_win']*math.log(max(r['home_probability'],1e-12))+(1-r['home_win'])*math.log(max(1-r['home_probability'],1e-12)) for r in output)/n
metrics={'model':'V3_ELO_PROVISIONAL_1','holdout_season':'2025-26','games':n,'accuracy':round(accuracy,5), 'brier':round(brier,5),'log_loss':round(logloss,5),
         'limitation':'Warmup uses only games present in V2 Base predictions (2024-25); incomplete warmup, no historical market odds.'}
(ROOT/'elo_holdout_metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
with open(ROOT/'elo_holdout_predictions.csv','w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['date','game_id','home','away','home_win','home_probability']);writer.writeheader();writer.writerows(output)
print(json.dumps(metrics,indent=2))
