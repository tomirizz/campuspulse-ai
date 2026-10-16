"""One-time local model setup and local web app. No API keys or account required."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'data' / 'local-ai'
VERSION = '0.40.5'
MODEL = os.getenv('LOCAL_MODEL', 'qwen3:1.7b')
BASE = 'http://127.0.0.1:11434'
# Official release checksum, pinned with the runtime version.
DARWIN_SHA = '75f9907dafa2fd4c61b5967de2ebb81ccc17eb28da9172edbad0dbc717474dcf'


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=3) as r:
        return json.load(r)


def runtime():
    existing = shutil.which('ollama')
    if existing:
        return existing
    binary = CACHE / 'runtime' / 'ollama'
    if binary.is_file():
        return str(binary)
    if platform.system() != 'Darwin':
        raise RuntimeError('Установите Ollama с https://ollama.com/download, затем запустите этот файл ещё раз.')
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / 'ollama-darwin.tgz'
    print('Первый запуск: загружаю официальный Ollama (~175 МБ).')
    urllib.request.urlretrieve(f'https://github.com/ollama/ollama/releases/download/v{VERSION}/ollama-darwin.tgz', archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != DARWIN_SHA:
        raise RuntimeError('Контрольная сумма Ollama не совпала. Запуск отменён.')
    with tarfile.open(archive) as tar:
        tar.extractall(CACHE / 'runtime', filter='data')
    archive.unlink()
    return str(binary)


def main():
    os.chdir(ROOT)
    owned = None
    app_process = None
    try:
        try:
            get('/api/tags')
        except Exception:
            binary = runtime()
            CACHE.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, 'OLLAMA_HOST':'127.0.0.1:11434', 'OLLAMA_NO_CLOUD':'1', 'OLLAMA_MODELS':str(CACHE / 'models')}
            log = open(CACHE / 'server.log', 'a')
            owned = subprocess.Popen([binary, 'serve'], env=env, stdout=log, stderr=log)
            log.close()
            for _ in range(30):
                try:
                    get('/api/tags'); break
                except Exception:
                    if owned.poll() is not None:
                        raise RuntimeError('Ollama не запустился. Подробности: data/local-ai/server.log')
                    time.sleep(1)
            else:
                raise RuntimeError('Ollama не отвечает.')
        if not any(m['name'] == MODEL for m in get('/api/tags')['models']):
            print('Первый запуск: загружаю локальную модель Qwen3 1.7B (~1,4 ГБ). Интернет нужен только для загрузки и внешних источников GitHub.')
            req = urllib.request.Request(BASE+'/api/pull', data=json.dumps({'model':MODEL,'stream':True}).encode(), headers={'Content-Type':'application/json'})
            previous = ''
            with urllib.request.urlopen(req, timeout=1800) as r:
                for line in r:
                    event=json.loads(line)
                    if event.get('error'): raise RuntimeError(event['error'])
                    status=event.get('status','')
                    if event.get('total'): status += ' ' + str(100*event.get('completed',0)//event['total'])+'%'
                    if status != previous: print(status, flush=True); previous=status
        print('Локальный ИИ готов. Ключ не требуется. Для выхода нажмите Ctrl+C.')
        port=os.getenv('PORT','8765')
        app_process = subprocess.Popen([sys.executable,'-m','uvicorn','campuspulse.server:app','--host','127.0.0.1','--port',port], env={**os.environ,'AGENT_MODE':'local','OLLAMA_URL':BASE,'LOCAL_MODEL':MODEL})
        for _ in range(40):
            if app_process.poll() is not None:
                raise RuntimeError('Сайт не запустился. Возможно, порт уже занят другой копией.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+port+'/api/health', timeout=1) as response:
                    if json.load(response).get('version') == '0.2.0': break
            except Exception: pass
            time.sleep(.25)
        else: raise RuntimeError('Сайт не ответил после запуска.')
        if '--no-open' not in sys.argv: webbrowser.open('http://127.0.0.1:'+port)
        app_process.wait()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('Не удалось запустить:', exc, file=sys.stderr)
        return 1
    finally:
        if app_process and app_process.poll() is None:
            app_process.terminate()
            try: app_process.wait(timeout=10)
            except subprocess.TimeoutExpired: app_process.kill()
        if owned:
            owned.terminate()
            try: owned.wait(timeout=10)
            except subprocess.TimeoutExpired: owned.kill()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
