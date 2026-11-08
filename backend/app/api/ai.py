from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, has_permission, require_permission
from app.models import AIConversation, AiDraft, Company, Document, DocumentChunk, User
from app.schemas.ai import AskRequest, AskResponse, DocumentOut, DocumentTextIn, SearchHit
from app.services import ai_agent, rag

router = APIRouter(tags=["ai & knowledge"])


@router.post("/ai/ask", response_model=AskResponse)
def ask(payload: AskRequest, user: User = Depends(require_permission("ai:use")), db: Session = Depends(get_db)):
    from app.services import saas
    saas.require_feature(db, user.company_id, "ai")
    saas.consume(db, user.company_id, "ai_requests", "max_ai_requests")
    company = db.get(Company, user.company_id)
    return ai_agent.ask(db, user.company_id, user.id, user.full_name, company.currency, payload.question, payload.history, payload.lang, user=user)


@router.get("/ai/drafts")
def list_drafts(status: str = "pending", user: User = Depends(require_permission("ai:use")), db: Session = Depends(get_db)):
    """Drafts the AI prepared for this user, waiting for a yes/no. Only the user who asked sees and decides them."""
    stmt = select(AiDraft).where(AiDraft.company_id == user.company_id, AiDraft.user_id == user.id)
    if status != "all":
        stmt = stmt.where(AiDraft.status == status)
    rows = db.scalars(stmt.order_by(AiDraft.id.desc()).limit(100)).all()
    return [{"id": d.id, "tool": d.tool, "summary": d.summary, "status": d.status, "result": d.result, "created_at": d.created_at} for d in rows]


@router.post("/ai/drafts/{draft_id}/confirm")
def confirm_draft(draft_id: int, user: User = Depends(require_permission("ai:use")), db: Session = Depends(get_db)):
    """The user explicitly approves an AI-prepared draft. Permissions are re-checked now, not trusted from when the
    draft was prepared — nothing the AI drafted bypasses normal authorization."""
    d = db.get(AiDraft, draft_id)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Draft not found")
    if d.user_id != user.id:
        raise HTTPException(403, "Only the person who asked the AI can confirm this")
    if d.status != "pending":
        raise HTTPException(400, f"This draft was already {d.status}")
    if not has_permission(user, "ai.actions"):
        raise HTTPException(403, "You don't have permission to confirm AI drafts")
    target_perm = ai_agent.TOOL_PERMISSIONS.get(d.tool)
    if target_perm and not has_permission(user, target_perm):
        raise HTTPException(403, f"Missing permission(s): {target_perm}")
    from datetime import datetime
    result = ai_agent.execute_draft(db, user.company_id, user.full_name, d)
    d.status, d.result, d.decided_at = ("rejected" if "error" in result else "confirmed"), result, datetime.utcnow()
    db.commit()
    return {"status": d.status, "result": result}


@router.post("/ai/drafts/{draft_id}/reject", status_code=204)
def reject_draft(draft_id: int, user: User = Depends(require_permission("ai:use")), db: Session = Depends(get_db)):
    from datetime import datetime
    d = db.get(AiDraft, draft_id)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Draft not found")
    if d.user_id != user.id:
        raise HTTPException(403, "Only the person who asked the AI can reject this")
    if d.status == "pending":
        d.status, d.decided_at = "rejected", datetime.utcnow()
        db.commit()


@router.get("/ai/history")
def history(limit: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIConversation).where(AIConversation.company_id == user.company_id, AIConversation.user_id == user.id)
                      .order_by(AIConversation.id.desc()).limit(limit)).all()
    return [{"id": r.id, "question": r.question, "answer": r.answer, "tools_used": r.tools_used, "created_at": r.created_at} for r in reversed(rows)]


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Document).where(Document.company_id == user.company_id).order_by(Document.id.desc())).all()


@router.post("/documents/text", response_model=DocumentOut, status_code=201)
def add_text_document(payload: DocumentTextIn, user: User = Depends(require_permission("documents:write")), db: Session = Depends(get_db)):
    return rag.index_document(db, user.company_id, payload.title, payload.doc_type, payload.content)


@router.post("/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...), doc_type: str = "policy", user: User = Depends(require_permission("documents:write")), db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 20MB)")
    text = rag.extract_text(file.filename, data)
    if not text.strip():
        raise HTTPException(400, "No extractable text in file")
    return rag.index_document(db, user.company_id, file.filename.rsplit(".", 1)[0], doc_type, text, filename=file.filename)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, user: User = Depends(require_permission("documents:write")), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Document not found")
    db.delete(d)
    db.commit()


@router.get("/documents/search", response_model=list[SearchHit])
def search_documents(q: str, k: int = 5, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return rag.search(db, user.company_id, q, k)


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or d.company_id != user.company_id:
        raise HTTPException(404, "Document not found")
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == d.id).order_by(DocumentChunk.chunk_index)).all()
    return {**DocumentOut.model_validate(d).model_dump(), "content": "\n\n".join(c.content for c in chunks)}


@router.post("/ai/read-invoice")
async def read_supplier_invoice(file: UploadFile = File(...), user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    """Photo/PDF of a supplier invoice → supplier, lines matched to our products, ready to become a purchase."""
    from difflib import SequenceMatcher

    from app.core.config import settings
    from app.models import Product, Supplier
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(400, "AI is not configured: add ANTHROPIC_API_KEY to backend/.env")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 20MB)")
    try:
        inv = ai_agent.extract_supplier_invoice(file.filename or "", data)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"AI service error: {ex}")

    def best(name: str, options: list, key) -> tuple[object, float]:
        scored = [(o, SequenceMatcher(None, name.lower(), key(o).lower()).ratio()) for o in options]
        return max(scored, key=lambda x: x[1]) if scored else (None, 0)

    cid = user.company_id
    products = db.scalars(select(Product).where(Product.company_id == cid, Product.is_active.is_(True))).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.company_id == cid)).all()
    sup, sup_score = best(inv.get("supplier_name", ""), suppliers, lambda s: s.name)
    lines = []
    for ln in inv.get("lines", []):
        code = (ln.get("code") or "").strip()
        match = next((p for p in products if code and code in (p.sku, p.barcode, p.pack_barcode)), None)
        score = 1.0 if match else 0
        if not match:
            match, score = best(ln.get("name", ""), products, lambda p: p.name)
        lines.append({**ln, "product_id": match.id if match and score >= 0.55 else None,
                      "product_name": match.name if match and score >= 0.55 else None, "match_score": round(score, 2)})
    return {**inv, "lines": lines, "supplier_id": sup.id if sup and sup_score >= 0.6 else None,
            "matched_supplier": sup.name if sup and sup_score >= 0.6 else None}



@router.post("/ai/read-receipt")
async def read_receipt(file: UploadFile = File(...), user: User = Depends(require_permission("finance:write"))):
    """Photo/PDF of an expense receipt → vendor, date, total, VAT and category to prefill the expense form."""
    from app.core.config import settings
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(400, "AI is not configured: add ANTHROPIC_API_KEY to backend/.env")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 20MB)")
    try:
        return ai_agent.extract_receipt(file.filename or "", data)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"AI service error: {ex}")


@router.get("/insights/pricing")
def pricing(user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    from app.services.smart import pricing_suggestions
    return pricing_suggestions(db, user.company_id)


@router.get("/insights/risk")
def risk(days: int = 30, user: User = Depends(require_permission("audit:read")), db: Session = Depends(get_db)):
    from app.services.smart import risk_signals
    return risk_signals(db, user.company_id, days)


@router.get("/insights/anomalies")
def anomalies(days: int = 14, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """Days where sales or expenses jumped or dropped well outside the company's own recent baseline."""
    from app.services.smart import detect_anomalies
    return detect_anomalies(db, user.company_id, days)


@router.get("/insights/daily")
def daily(user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    from app.services.smart import daily_summary, summary_text
    company = db.get(Company, user.company_id)
    s = daily_summary(db, user.company_id)
    return {**s, "text": summary_text(s, company.name, company.currency)}
