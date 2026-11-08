"""RAG pipeline: Documents → Processing → Chunking → Embeddings → Vector store → Retrieval.

Embeddings: uses a deterministic hashed n-gram embedding (no external service needed) so the
system works fully offline. Swap `embed()` for an API embedding model + pgvector in production.
"""
import hashlib
import math
import re
from io import BytesIO

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk

DIM = 512


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if name.endswith(".docx"):
        import docx

        d = docx.Document(BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    return data.decode("utf-8", errors="ignore")


def chunk_text(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        # try to break on sentence / paragraph boundary
        cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
        if cut <= start + size // 2:
            cut = end
        chunks.append(text[start:cut].strip())
        start = max(cut - overlap, start + 1)
    return [c for c in chunks if len(c) > 20]


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[\w\u0600-\u06FF]+", text.lower())
    grams = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return grams


def embed(text: str) -> list[float]:
    vec = np.zeros(DIM, dtype=np.float32)
    toks = _tokens(text)
    if not toks:
        return vec.tolist()
    for t in toks:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        idx, sign = h % DIM, 1.0 if (h >> 9) & 1 else -1.0
        vec[idx] += sign
    # sublinear tf + l2 normalisation
    vec = np.sign(vec) * np.log1p(np.abs(vec))
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist() if norm else vec.tolist()


def index_document(db: Session, cid: int, title: str, doc_type: str, text: str, filename: str | None = None) -> Document:
    doc = Document(company_id=cid, title=title, doc_type=doc_type, filename=filename, status="processing")
    db.add(doc)
    db.flush()
    chunks = chunk_text(text)
    for i, c in enumerate(chunks):
        db.add(DocumentChunk(company_id=cid, document_id=doc.id, chunk_index=i, content=c, embedding=embed(c)))
    doc.chunk_count = len(chunks)
    doc.status = "indexed"
    db.commit()
    db.refresh(doc)
    return doc


def search(db: Session, cid: int, query: str, k: int = 4) -> list[dict]:
    q = np.array(embed(query), dtype=np.float32)
    rows = db.execute(
        select(DocumentChunk, Document.title)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == cid)  # tenant isolation
    ).all()
    scored = []
    for chunk, title in rows:
        v = np.array(chunk.embedding, dtype=np.float32)
        score = float(np.dot(q, v))
        if not math.isnan(score):
            scored.append({"document_id": chunk.document_id, "document_title": title, "content": chunk.content, "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return [s for s in scored[:k] if s["score"] > 0.05]
