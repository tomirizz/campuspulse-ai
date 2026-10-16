"""Real local inference smoke checks; synthetic inputs are explicitly identified."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campuspulse.local_agent import local_run
from campuspulse.progress import complete_task

async def main():
    now=datetime.now(timezone.utc)
    completed=complete_task({'id':'example-done','title':'[Пример] Семинар','course':'Test','estimated_minutes':90,'due_at':(now+timedelta(days=2)).isoformat(),'completed':False},True,now)
    context={'tasks':[completed, {'id':'example-open','title':'[Пример] Лабораторная','course':'Test','estimated_minutes':60,'due_at':(now+timedelta(days=3)).isoformat(),'completed':False}],
             'materials':[{'id':'example-lecture','name':'[Пример] gradient.txt','page_count':1,'pages':[{'page':1,'text':'Градиентный спуск уменьшает функцию потерь.\nШаг обучения в этом учебном примере равен 0.01.\nЭто синтетический текст для проверки цитирования.'}]}]}
    results=[]
    for message,tool,expected in [('Почему у меня столько опыта? Покажи XP и уровень.','study_progress','35'),('Составь план учебной недели.','plan_week','60'),('Какой шаг обучения указан в загруженном материале gradient.txt?','read_material','0.01')]:
        r=await local_run(message,context)
        passed = r['inference_verified'] and r['grounded'] and any(t['tool']==tool for t in r['trace']) and expected in r['answer'] and bool(r['evidence'])
        print(json.dumps({'question':message,'passed':passed,'tools':[t['tool'] for t in r['trace']],'answer':r['answer']},ensure_ascii=False),flush=True)
        results.append({'question':message,'passed':passed,'model':r['model'],'tools':[t['tool'] for t in r['trace']],'answer':r['answer'],'evidence':r['evidence']})
    Path('data').mkdir(exist_ok=True)
    Path('data/local-verification.json').write_text(json.dumps({'synthetic_inputs':True,'at':now.isoformat(),'results':results},ensure_ascii=False,indent=2))
    return 0 if all(r['passed'] for r in results) else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
