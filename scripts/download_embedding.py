"""Resumable, hash-verified public weights download for unreliable connections."""
import hashlib
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import settings
import httpx
from huggingface_hub import HfApi, get_hf_file_metadata, hf_hub_url, snapshot_download


def main():
    repo = settings.embedding_model
    revision = HfApi().model_info(repo).sha
    directory = Path(snapshot_download(repo, revision=revision, cache_dir=str(settings.data_dir / 'models'),
        allow_patterns=['*.json', '*.txt', '*.md', '*.py'], max_workers=2))
    metadata = get_hf_file_metadata(hf_hub_url(repo, 'model.safetensors', revision=revision))
    parts = settings.data_dir / 'models' / 'download-parts'
    parts.mkdir(parents=True, exist_ok=True)
    step = 2*1024*1024
    def fetch(start):
        end = min(start+step, metadata.size)-1
        path = parts / f'{metadata.etag}-{start}'
        if path.exists() and path.stat().st_size == end-start+1:
            return path
        for attempt in range(8):
            try:
                with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as client:
                    response = client.get(metadata.location, headers={'Range':f'bytes={start}-{end}'})
                if response.status_code != 206 or len(response.content) != end-start+1 or not response.headers.get('content-range', '').startswith(f'bytes {start}-{end}/'):
                    raise ValueError('Unexpected range response')
                path.write_bytes(response.content)
                return path
            except (httpx.HTTPError, ValueError):
                if attempt == 7:
                    raise
                time.sleep(min(2**attempt, 10))
    starts = list(range(0, metadata.size, step))
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths=[]
        for i,path in enumerate(pool.map(fetch, starts)):
            paths.append(path)
            if i%20==0:
                print(f'Verified ranges: {i+1}/{len(starts)}', flush=True)
    output = directory / 'model.safetensors'
    digest = hashlib.sha256()
    with output.open('wb') as file:
        for path in paths:
            data = path.read_bytes()
            digest.update(data)
            file.write(data)
    if digest.hexdigest() != metadata.etag:
        raise ValueError('Model hash mismatch')
    (settings.data_dir / 'models' / 'revision.json').write_text(json.dumps({'model':repo,'revision':revision}), encoding='utf-8')
    print('Verified model SHA256:', digest.hexdigest())
    from app.search import encode_segments
    print('Real embedding dimensions:', len(encode_segments('实践是认识的来源')[0]))


if __name__ == '__main__':
    main()
