"""FastAPI application: the HTTP layer only.

Each route loads objects, calls one service (parser, translation memory, glossary,
pipeline, review, exporter) and returns a schema. The business rules live in the services.

Run:  uvicorn app.main:create_app --factory --reload
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import init_db, make_engine, make_session_factory
from app.export.exporter import export_docx, export_text
from app.glossary.glossary import Glossary
from app.ingestion.parsers import UnsupportedFormatError, parse_document
from app.memory.translation_memory import TranslationMemory
from app.models import Document, GlossaryTerm, Segment
from app.pipeline.review import ReviewError, ReviewService
from app.pipeline.translate import TranslationPipeline
from app.rag.translators import OfflineTranslator, OpenAITranslator, Translator
from app.rag.vector_store import PineconeVectorStore, TfidfVectorStore
from app.schemas import (DocumentOut, DocumentSummary, GlossaryIn, GlossaryOut, RejectIn,
                         SegmentEdit, SegmentOut, TMMatchOut, TranslationReportOut)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router = APIRouter(prefix="/api")


def get_session(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def _document_or_404(session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return document


def _segment_or_404(session: Session, segment_id: int) -> Segment:
    segment = session.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "Segment not found")
    return segment


def _document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id, filename=document.filename, source_lang=document.source_lang,
        target_lang=document.target_lang, created_at=document.created_at,
        segment_count=len(document.segments),
        segments=[SegmentOut.model_validate(s) for s in document.segments],
    )


# ── documents ─────────────────────────────────────────────

@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(request: Request,
                    file: UploadFile = File(...),
                    source_lang: str = Form(...),
                    target_lang: str = Form(...),
                    session: Session = Depends(get_session)):
    settings: Settings = request.app.state.settings
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "File is too large")
    try:
        blocks = parse_document(file.filename or "upload.txt", data)
    except UnsupportedFormatError as exc:
        raise HTTPException(415, str(exc))
    except Exception as exc:  # corrupt file, bad encoding, etc.
        raise HTTPException(400, f"Could not read the file: {exc}")
    if not blocks:
        raise HTTPException(400, "No text was found in the file")

    document = Document(filename=file.filename or "upload", source_lang=source_lang.strip().lower(),
                        target_lang=target_lang.strip().lower())
    document.segments = [
        Segment(position=i, block_type=b.block_type, heading_level=b.heading_level,
                table_index=b.table_index, row_index=b.row_index, col_index=b.col_index,
                page=b.page, source_text=b.text, target_text="", status="pending")
        for i, b in enumerate(blocks)
    ]
    session.add(document)
    session.commit()
    return _document_out(document)


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(session: Session = Depends(get_session)):
    documents = session.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [DocumentSummary(id=d.id, filename=d.filename, source_lang=d.source_lang,
                            target_lang=d.target_lang, created_at=d.created_at,
                            segment_count=len(d.segments)) for d in documents]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: Session = Depends(get_session)):
    return _document_out(_document_or_404(session, document_id))


@router.post("/documents/{document_id}/translate", response_model=TranslationReportOut)
def translate_document(document_id: int, request: Request, session: Session = Depends(get_session)):
    document = _document_or_404(session, document_id)
    state = request.app.state
    pipeline = TranslationPipeline(
        session, state.translator,
        fuzzy_threshold=state.settings.fuzzy_threshold,
        retrieval_k=state.settings.retrieval_k,
        vector_store_factory=state.vector_store_factory,
    )
    report = pipeline.run(document)
    return TranslationReportOut(**report.__dict__)


@router.get("/documents/{document_id}/export")
def export_document(document_id: int,
                    format: str = Query("docx", pattern="^(docx|txt)$"),
                    force: bool = False,
                    session: Session = Depends(get_session)):
    document = _document_or_404(session, document_id)
    unapproved = [s for s in document.segments if s.status != "approved"]
    if unapproved and not force:
        raise HTTPException(409, detail={
            "message": "Approve every segment before exporting, or pass force=true.",
            "unapproved_segments": len(unapproved),
        })

    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(document.filename).stem) or "document"
    filename = f"{stem}_{document.target_lang}.{format}"
    if format == "docx":
        return Response(export_docx(document.segments),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return Response(export_text(document.segments), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── review ────────────────────────────────────────────────

@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def edit_segment(segment_id: int, body: SegmentEdit, session: Session = Depends(get_session)):
    segment = _segment_or_404(session, segment_id)
    return SegmentOut.model_validate(ReviewService(session).edit(segment, body.target_text, body.comment))


@router.post("/segments/{segment_id}/approve", response_model=SegmentOut)
def approve_segment(segment_id: int, session: Session = Depends(get_session)):
    segment = _segment_or_404(session, segment_id)
    try:
        return SegmentOut.model_validate(ReviewService(session).approve(segment))
    except ReviewError as exc:
        raise HTTPException(422, str(exc))


@router.post("/segments/{segment_id}/reject", response_model=SegmentOut)
def reject_segment(segment_id: int, body: RejectIn, session: Session = Depends(get_session)):
    segment = _segment_or_404(session, segment_id)
    return SegmentOut.model_validate(ReviewService(session).reject(segment, body.comment))


# ── glossary and translation memory ───────────────────────

@router.post("/glossary", response_model=GlossaryOut, status_code=201)
def add_glossary_term(body: GlossaryIn, session: Session = Depends(get_session)):
    try:
        row = Glossary(session).add(body.source_lang.lower(), body.target_lang.lower(), body.kind,
                                    body.source_term.strip(), body.target_term, body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    session.commit()
    return GlossaryOut.model_validate(row)


@router.get("/glossary", response_model=list[GlossaryOut])
def list_glossary(source_lang: str | None = None, target_lang: str | None = None,
                  session: Session = Depends(get_session)):
    return [GlossaryOut.model_validate(r) for r in Glossary(session).list(source_lang, target_lang)]


@router.delete("/glossary/{term_id}", status_code=204)
def delete_glossary_term(term_id: int, session: Session = Depends(get_session)):
    if not Glossary(session).delete(term_id):
        raise HTTPException(404, "Glossary term not found")
    session.commit()
    return Response(status_code=204)


@router.get("/tm/search", response_model=list[TMMatchOut])
def search_translation_memory(q: str = Query(min_length=1), source_lang: str = Query(...),
                              target_lang: str = Query(...), limit: int = Query(5, ge=1, le=50),
                              session: Session = Depends(get_session)):
    matches = TranslationMemory(session).search(q, source_lang.lower(), target_lang.lower(), limit)
    return [TMMatchOut(entry_id=m.entry_id, source_text=m.source_text, target_text=m.target_text,
                       score=m.score, kind=m.kind) for m in matches]


@router.get("/health")
def health():
    return {"status": "ok"}


# ── application factory ───────────────────────────────────

def _default_translator(settings: Settings) -> Translator:
    if settings.openai_api_key:
        return OpenAITranslator(settings.openai_api_key, settings.openai_model)
    return OfflineTranslator()


def _vector_store_factory(settings: Settings):
    if settings.pinecone_api_key and settings.pinecone_index and settings.openai_api_key:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

        def embed(texts: list[str]) -> list[list[float]]:
            response = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return [item.embedding for item in response.data]

        return lambda: PineconeVectorStore(settings.pinecone_api_key, settings.pinecone_index, embed)
    return TfidfVectorStore


def create_app(settings: Settings | None = None, translator: Translator | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_db(engine)

    app = FastAPI(title="Glossify AI", version="1.0.0",
                  description="AI-assisted document translation with translation memory, "
                              "glossary enforcement and human review.")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.translator = translator or _default_translator(settings)
    app.state.vector_store_factory = _vector_store_factory(settings)

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
