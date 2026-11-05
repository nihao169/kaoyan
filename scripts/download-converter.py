"""Resume the official installer in bounded ranges and verify its published hash."""
import base64
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]/'.runtime'
parts=root/'converter-parts'
parts.mkdir(parents=True,exist_ok=True)
url='https://ftp.osuosl.org/pub/tdf/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi'
total=374870016
chunk=4*1024*1024
expected='ximLEM+hdIvL7a2UxiznceJA5QIb/W16lnzVcbBLUxI='

def download(index):
    start=index*chunk;end=min(total,start+chunk)-1
    path=parts/f'{index:04d}.part'
    if path.exists() and path.stat().st_size==end-start+1:
        return
    for attempt in range(6):
        try:
            with httpx.Client(timeout=90,follow_redirects=True) as client:
                response=client.get(url,headers={'Range':f'bytes={start}-{end}'})
                if response.status_code!=206 or len(response.content)!=end-start+1:
                    raise RuntimeError('Range response was incomplete')
                path.write_bytes(response.content)
                return
        except Exception:
            if attempt==5:
                raise
            time.sleep(min(attempt+1,5))

with ThreadPoolExecutor(max_workers=6) as pool:
    for done,_ in enumerate(pool.map(download,range((total+chunk-1)//chunk)),1):
        if done%10==0:
            print(f'Downloaded {done} verified-length parts',flush=True)
target=root/'libreoffice.msi'
digest=hashlib.sha256()
with target.open('wb') as output:
    for index in range((total+chunk-1)//chunk):
        data=(parts/f'{index:04d}.part').read_bytes();digest.update(data);output.write(data)
if base64.b64encode(digest.digest()).decode()!=expected:
    raise RuntimeError('Official SHA-256 mismatch; do not install this file')
print('Official installer SHA-256 verified.',flush=True)
