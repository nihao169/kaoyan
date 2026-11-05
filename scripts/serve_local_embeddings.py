"""Optional OpenAI-compatible embedding endpoint for isolated DeepTutor preview."""
import hmac
import os
from pathlib import Path
import sys
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import settings
from app.search import encoder, resolved_revision

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Input(BaseModel):
    model: str
    input: list[str] = Field(min_length=1, max_length=64)


@app.post('/v1/embeddings')
def embed(body: Input, authorization: str = Header(default='')):
    token = os.environ.get('ZX_LOCAL_EMBEDDING_KEY', '')
    if len(token) < 32 or not hmac.compare_digest(authorization.encode(), ('Bearer ' + token).encode()):
        raise HTTPException(403, 'Invalid embedding token')
    if body.model != settings.embedding_model or any(len(text) > 32000 for text in body.input):
        raise HTTPException(422, 'Unsupported embedding input')
    model = encoder(settings.embedding_model, resolved_revision(), True)
    vectors = model.encode(body.input, normalize_embeddings=True, show_progress_bar=False).tolist()
    tokens = sum(len(model.tokenizer.encode(text, truncation=True, max_length=model.max_seq_length)) for text in body.input)
    return {'object': 'list', 'model': body.model, 'usage': {'prompt_tokens': tokens, 'total_tokens': tokens},
            'data': [{'object': 'embedding', 'index': i, 'embedding': v} for i, v in enumerate(vectors)]}
