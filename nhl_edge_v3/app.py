"""Read-only mobile dashboard. No betting orders or generated odds."""
import sqlite3
import os
import tempfile
import urllib.request
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title='NHL EDGE V3',page_icon='🏒',layout='wide')
st.title('🏒 NHL EDGE · V3')
st.caption('Free-data moneyline research | Provisional Elo probabilities, NOT verified betting edges')
DB=Path(__file__).parent/'data'/'edge.sqlite'
# For public GitHub repos, configure EDGE_DB_URL in Streamlit Cloud secrets.
# Download a fresh SQLite snapshot periodically; otherwise fall back to packaged DB.
@st.cache_data(ttl=300,show_spinner=False)
def current_database(url):
    request=urllib.request.Request(url,headers={'User-Agent':'NHL-EDGE-V3-Dashboard'})
    with urllib.request.urlopen(request,timeout=20) as response:
        content=response.read(15_000_000)
    if not content.startswith(b'SQLite format 3'):
        raise ValueError('Downloaded file is not a SQLite database')
    path=Path(tempfile.gettempdir())/'nhl_edge_streamlit_latest.sqlite'
    path.write_bytes(content)
    return str(path)
url=os.getenv('EDGE_DB_URL','')
try:
    url=url or st.secrets.get('EDGE_DB_URL','')
except Exception:
    pass
if url:
    try:
        DB=Path(current_database(url))
        st.caption('Dashboard reads the published database snapshot (cached up to five minutes).')
    except Exception as exc:
        st.error('Could not refresh database from GitHub: '+str(exc))
        st.stop()
if not DB.exists():
    st.info('Database not populated. Run the GitHub Actions bootstrap workflow first.')
    st.stop()
with sqlite3.connect(f'file:{DB}?mode=ro',uri=True) as db:
    games=pd.read_sql_query('SELECT * FROM games',db)
    forecasts=pd.read_sql_query('''SELECT f.*,g.game_date,g.home,g.away,g.home_goals,g.away_goals,g.home_win
                                 FROM forecasts f JOIN games g ON g.game_id=f.game_id
                                 ORDER BY f.captured_utc DESC''',db)
    runs=pd.read_sql_query('SELECT * FROM collection_runs ORDER BY id DESC LIMIT 1',db)
settled=forecasts[forecasts.home_win.notna()].copy() if not forecasts.empty else pd.DataFrame()
c1,c2,c3=st.columns(3)
c1.metric('Games stored',len(games))
c2.metric('Forecasts stored',len(forecasts))
c3.metric('Settled forecasts',len(settled))
if not runs.empty:
    st.caption('Last collection: '+str(runs.iloc[0].ran_utc)+' UTC')
st.warning('Research only · All model decisions default to NO BET. No bookmaker odds are fabricated or automatically imported.')
if not forecasts.empty:
    st.subheader('Latest saved pregame predictions')
    pending=forecasts[forecasts.home_win.isna()].copy()
    if not pending.empty:
        pending['Home win %']=(pending.home_probability*100).round(1)
        st.dataframe(pending[['game_date','away','home','Home win %','decision','captured_utc']].rename(columns={'game_date':'Date','away':'Away','home':'Home','decision':'Decision','captured_utc':'Captured UTC'}),hide_index=True,use_container_width=True)
    else:st.info('No pending saved forecasts.')
    if not settled.empty:
        st.subheader('Forward-test results')
        settled['correct']=((settled.home_probability>=.5)==(settled.home_win==1)).astype(int)
        settled['brier']=(settled.home_probability-settled.home_win)**2
        a,b=st.columns(2)
        a.metric('Winner accuracy',f'{settled.correct.mean():.1%}')
        b.metric('Brier score',f'{settled.brier.mean():.4f}')
        st.dataframe(settled[['game_date','away','home','away_goals','home_goals','home_probability','correct','model']].rename(columns={'game_date':'Date'}),hide_index=True,use_container_width=True)
else:st.info('No saved predictions yet. The 11 AM ET scheduled run will create them once the database has games.')
with st.expander('Methodology and limitations'):
    st.write('V3 currently uses a transparent Elo provisional baseline (K=18, home advantage 35 points), based on past completed regular-season results. It is not the trained V2 MoneyPuck model. Features exclude games on the prediction date. Probability calibration and profitability have NOT been validated. Full-game NHL moneyline outcomes include overtime and shootouts. No bets are recommended.')
