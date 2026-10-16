from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from campuspulse.progress import complete_task, progress, reward, metrics
from campuspulse.storage import SQLiteStore

NOW = datetime(2026,10,16,12,tzinfo=timezone.utc)
def task(minutes=90, **kw):
    return {'id':'a','title':'Lab','estimated_minutes':minutes,'completed':False,'due_at':(NOW+timedelta(days=1)).isoformat(),**kw}

@pytest.mark.parametrize('minutes,xp',[(15,25),(30,25),(31,30),(90,35),(240,60),(2400,60)])
def test_reward_boundaries(minutes,xp):
    assert reward(minutes)==xp

def test_toggle_edit_delete_no_farming():
    t=complete_task(task(),True,NOW)
    assert progress([t],now=NOW)['xp']==35
    t['estimated_minutes']=2400
    for _ in range(10):
        t=complete_task(t,False,NOW)
        assert progress([t],now=NOW)['xp']==0
        t=complete_task(t,True,NOW+timedelta(days=1))
        assert progress([t],now=NOW)['xp']==35
    assert t['completed_at']==NOW.isoformat()
    assert progress([],now=NOW)['xp']==0

def test_streak_timezone_and_no_penalty():
    tasks=[complete_task(task(id=str(i)),True,NOW-timedelta(days=i)) for i in range(3)]
    assert progress(tasks,now=NOW)['streak']==3
    assert progress(tasks,now=NOW+timedelta(days=1))['streak']==3
    assert progress(tasks,now=NOW+timedelta(days=2))['streak']==0
    assert progress(tasks,now=NOW+timedelta(days=2))['xp']==105
    assert progress(tasks,now=NOW)['level']==2
    assert progress(tasks,now=NOW)['level_progress']==5

def test_legacy_no_invented_date_or_reward():
    assert progress([task(completed=True)],now=NOW)['xp']==0
    assert progress([task(completed=True)],now=NOW)['streak']==0

def test_concurrent_completion_is_atomic(tmp_path):
    store=SQLiteStore(tmp_path/'x.db');store.put('s','tasks','a',task())
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _:store.update('s','tasks','a',lambda t:complete_task(t,True,NOW)),range(20)))
    assert progress(store.list('s','tasks'),now=NOW)['xp']==35

def test_metric_sources_cover_the_result():
    r=metrics([task(),task(60,id='b',due_at=(NOW-timedelta(days=1)).isoformat())],now=NOW)
    assert r['hours']==2.5 and r['due']==1
    assert sum(r['why']['hours']['inputs'].values())/60==r['hours']
