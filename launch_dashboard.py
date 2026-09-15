import subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

root=Path(__file__).resolve().parent
url='http://127.0.0.1:8765/'
def ready():
    try:
        with urllib.request.urlopen(url,timeout=1) as r:
            return 'LOCAL AI OFFICE' in r.read().decode('utf-8')
    except Exception: return False
if not ready():
    subprocess.Popen([sys.executable,str(root/'office.py'),'serve'],cwd=root,
      creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,
      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(20):
        if ready(): break
        time.sleep(.2)
if not ready(): raise SystemExit('Dashboard did not start on port 8765')
webbrowser.open(url)
