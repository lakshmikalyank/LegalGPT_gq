"""
app/services/rag_service.py

RAG pipeline: text extraction, chunking, embedding, vector storage
(ChromaDB), and question answering via LangChain + Groq.
"""

import io
import json
import logging
import os

import pdfplumber
import docx

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_groq import ChatGroq
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

from config import Config



logger = logging.getLogger(__name__)


class DocumentExtractionError(ValueError):
    """Raised when text cannot be extracted; str(exc) is user-displayable."""


class GroqServiceError(Exception):
    """
    Raised when a Groq call fails in a way that could not be resolved
    by trying fallback models — invalid API key, rate limit, every
    candidate model unavailable/decommissioned, or a network failure.

    Carries a ready-to-display friendly message (str(exc)) so callers
    (routes) can surface it directly to the user instead of a generic
    500, and critically so they know NOT to cache the result as if it
    were a real, successful response.
    """
    pass

_embedding_function = None
_vectorstore = None

# EasyOCR readers are loaded lazily (only on first actual OCR use:
# an image upload, or a scanned/image-only PDF page) rather than at
# module-import time. Loading them eagerly at import time means every
# gunicorn worker process loads PyTorch + OCR model weights before
# serving a single request, which previously exceeded Render's 512MB
# free-tier memory limit during deploy.
_ocr_readers = {}


def _get_ocr_reader(langs):
    """
    Return a lazily-initialized, cached EasyOCR reader for the given
    language list. Only loads EasyOCR's PyTorch-backed models the first
    time OCR is actually needed, not at application startup.
    """
    key = tuple(langs)
    if key not in _ocr_readers:
        try:
            import easyocr  # lazy: importing it loads PyTorch
        except ImportError as exc:
            raise DocumentExtractionError(
                "Image text recognition (OCR) is not available on this server."
            ) from exc
        _ocr_readers[key] = easyocr.Reader(
            list(langs),
            gpu=False,
            model_storage_directory=os.path.join(Config.MODEL_CACHE_DIR, "easyocr"),
        )
    return _ocr_readers[key]

RAG_PROMPT_TEMPLATE = """You are a legal assistant helping a user understand their uploaded documents.
Use the following context extracted from the document(s) to answer the question.
If the answer is not found in the context, say so clearly instead of guessing.

Context:
{context}

Question:
{question}

Answer:"""

def get_embedding_function():
    """Return a lazily-initialized SentenceTransformers embedding function."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = SentenceTransformerEmbeddings(
            model_name=Config.EMBEDDING_MODEL_NAME
        )
    return _embedding_function


def get_vectorstore():
    """Return a lazily-initialized persistent Chroma vector store."""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name=Config.CHROMA_COLLECTION_NAME,
            embedding_function=get_embedding_function(),
            persist_directory=Config.CHROMA_DB_DIR,
        )
    return _vectorstore

_llm_cache = {}  # model_name -> ChatGroq instance, built lazily

# --------------------------------------------------------------------
# Groq error classification + friendly messaging
# --------------------------------------------------------------------
# Every direct Groq call in this module goes through
# _call_llm_with_resilience() below, which uses these categories to
# decide (a) whether retrying with a different model could help, and
# (b) what user-friendly message to show instead of a raw stack trace.

GROQ_ERROR_INVALID_KEY = "invalid_api_key"
GROQ_ERROR_QUOTA = "quota_exceeded"
GROQ_ERROR_MODEL_UNAVAILABLE = "model_unavailable"
GROQ_ERROR_NETWORK = "network_error"
GROQ_ERROR_UNKNOWN = "unknown"

GROQ_FRIENDLY_MESSAGES = {
    GROQ_ERROR_INVALID_KEY: (
        "The AI service isn't configured correctly (missing or invalid "
        "Groq API key). Please contact the site administrator."
    ),
    GROQ_ERROR_QUOTA: (
        "The AI service has hit its rate/usage limit for now. Please "
        "wait a few minutes and try again."
    ),
    GROQ_ERROR_MODEL_UNAVAILABLE: (
        "The AI service is temporarily unavailable. Please try again "
        "shortly."
    ),
    GROQ_ERROR_NETWORK: (
        "Could not reach the AI service due to a network issue. Please "
        "check your connection and try again."
    ),
    GROQ_ERROR_UNKNOWN: (
        "Something went wrong while generating a response. Please try "
        "again."
    ),
}


def _classify_groq_error(exc):
    """
    Classify a Groq/LangChain exception into one of the categories
    above, using the exception type name, message text, and (where
    present) HTTP status code. Matches on keywords rather than
    isinstance() checks, since exceptions here can come from groq's own
    SDK (groq.APIStatusError and subclasses), langchain_groq's wrapper,
    or requests/httpx connection errors.

    Reference: Groq's documented error codes (console.groq.com/docs/errors)
    — 401/403 auth, 404 model not found/decommissioned, 429 rate limit,
    498 flex-tier capacity, 500/502/503 server-side issues.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    status_code = getattr(exc, "status_code", None)

    if status_code in (401, 403) or any(
        k in text
        for k in (
            "invalid api key",
            "invalid_api_key",
            "incorrect api key",
            "authentication",
            "unauthorized",
            "permission_denied",
            "401",
            "403",
        )
    ):
        return GROQ_ERROR_INVALID_KEY

    if status_code == 429 or any(
        k in text
        for k in (
            "rate_limit",
            "rate limit",
            "too many requests",
            "quota",
            "429",
        )
    ):
        return GROQ_ERROR_QUOTA

    if status_code == 404 or any(
        k in text
        for k in (
            "404",
            "not_found",
            "not found",
            "decommissioned",
            "does not exist",
            "no longer available",
            "is not supported",
            "unsupported",
            "model_not_active",
        )
    ):
        return GROQ_ERROR_MODEL_UNAVAILABLE

    if status_code in (498, 500, 502, 503) or any(
        k in text
        for k in (
            "connection",
            "timeout",
            "timed out",
            "network",
            "dns",
            "unreachable",
            "temporarily unavailable",
            "capacity",
            "498",
            "500",
            "502",
            "503",
        )
    ):
        return GROQ_ERROR_NETWORK

    return GROQ_ERROR_UNKNOWN


def _friendly_groq_message(exc):
    """Map an exception to the user-facing message for its category."""
    return GROQ_FRIENDLY_MESSAGES[_classify_groq_error(exc)]


def _model_candidates(primary):
    """
    Build an ordered, de-duplicated list starting with `primary` and
    followed by Config.GROQ_FALLBACK_MODELS, for use when `primary`
    turns out to be unavailable at request time.
    """
    ordered = []
    seen = set()
    for name in [primary, *Config.GROQ_FALLBACK_MODELS]:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _build_llm(model_name, is_translation=False):
    """Construct (and cache) a ChatGroq instance for a given model name."""
    if model_name not in _llm_cache:
        kwargs = dict(
            model=model_name,
            groq_api_key=Config.GROQ_API_KEY,
            temperature=0.2,
        )
        if is_translation:
            kwargs["max_tokens"] = 1024
        _llm_cache[model_name] = ChatGroq(**kwargs)
    return _llm_cache[model_name]


def get_llm():
    """
    Return a Groq chat model for RAG Q&A and document analysis, using
    Config.GROQ_MODEL_NAME.

    Requires Config.GROQ_API_KEY to be set (via the GROQ_API_KEY
    environment variable) — no valid API key means every LLM call below
    will raise, which callers already handle with a friendly error.

    Prefer _call_llm_with_resilience() over calling this directly where
    possible, since it also handles model fallback and error messaging.
    """
    if not Config.GROQ_API_KEY:
        logger.warning(
            "GROQ_API_KEY is not set. Set it as an environment variable "
            "before making chat/analysis requests."
        )
    return _build_llm(Config.GROQ_MODEL_NAME)


def get_translation_llm():
    """
    Return a Groq chat model for translation, using
    Config.GROQ_TRANSLATION_MODEL_NAME (defaults to the same model as
    get_llm() unless explicitly overridden).
    """
    return _build_llm(Config.GROQ_TRANSLATION_MODEL_NAME, is_translation=True)


def _call_llm_with_resilience(build_call, is_translation=False):
    """
    Run `build_call(llm)` against Config.GROQ_MODEL_NAME (or
    GROQ_TRANSLATION_MODEL_NAME), automatically retrying with each
    model in Config.GROQ_FALLBACK_MODELS if the failure looks like
    "this model is unavailable" — e.g. Groq deprecated/decommissioned
    it. Invalid-API-key, rate-limit, and network errors are NOT retried
    against other models, since switching models can't fix those.

    Args:
        build_call (callable): Takes a ChatGroq instance and performs
            the actual LLM call (e.g. `llm.invoke(prompt)` or building/
            running a chain), returning its result.
        is_translation (bool): Use the translation model + fallback
            settings instead of the chat/analysis ones.

    Returns:
        tuple[Any, str | None]: (result, None) on success, or
            (None, friendly_error_message) if every candidate failed.
    """
    primary = (
        Config.GROQ_TRANSLATION_MODEL_NAME
        if is_translation
        else Config.GROQ_MODEL_NAME
    )

    if not Config.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY is not set; Groq call will fail.")

    last_exc = None
    for model_name in _model_candidates(primary):
        try:
            llm = _build_llm(model_name, is_translation=is_translation)
            return build_call(llm), None
        except Exception as exc:
            last_exc = exc
            category = _classify_groq_error(exc)
            logger.warning(
                "Groq call failed (model=%s, category=%s): %s",
                model_name,
                category,
                exc,
            )
            if category == GROQ_ERROR_MODEL_UNAVAILABLE:
                # Try the next candidate model.
                continue
            # Invalid key / rate limit / network / unknown — trying a
            # different model won't help, so stop here.
            break

    return None, _friendly_groq_message(last_exc)


def _llm_text(response):
    """
    Extract plain text from a Groq chat-model response.

    ChatGroq.invoke() returns an AIMessage. response.content is
    normally already a plain string for Groq's text models, but this
    also handles the list-of-parts shape LangChain chat models can use
    in general, so downstream parsing code can keep calling
    .strip() / json.loads() on the result unchanged either way.
    """
    content = getattr(response, "content", response)

    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
        return "".join(parts)

    return content if isinstance(content, str) else str(content)


def extract_text_from_pdf(file_path):
    """
    Extract all text from a PDF file using pdfplumber.

    If pdfplumber finds little or no text (a scanned/image-only PDF,
    common for scanned government/legal documents), falls back to
    rendering each page to an image and running OCR on it, reusing the
    same EasyOCR readers as extract_text_from_image().
    """
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    extracted = "\n".join(text_parts)

    # Heuristic: a PDF with real, extractable text almost always yields
    # much more than a handful of characters. A very short/empty result
    # strongly suggests the PDF is scanned images with no text layer.
    if len(extracted.strip()) < 30:
        ocr_text = _extract_text_from_scanned_pdf(file_path)
        if ocr_text.strip():
            return ocr_text

    if not extracted.strip():
        raise DocumentExtractionError(
            "No readable text was found in this PDF (it may be a blank or "
            "unreadable scan). Try a clearer scan or a text-based PDF."
        )
    return extracted


def _extract_text_from_scanned_pdf(file_path):
    """
    Render each page of a scanned/image-only PDF to an image and run
    OCR on it. Uses PyMuPDF (fitz) for rasterization since it needs no
    external system binary (unlike pdf2image/poppler), which matters
    for a constrained hosting environment like Render.
    """
    try:
        import fitz  # PyMuPDF; imported lazily so it only costs memory
                      # when a scanned document actually needs OCR.
    except ImportError:
        logger.exception(
            "PyMuPDF (pymupdf) is not installed; cannot OCR scanned PDFs."
        )
        return ""

    text_parts = []
    try:
        doc = fitz.open(file_path)
        try:
            max_pages = Config.OCR_MAX_PDF_PAGES
            for page_number, page in enumerate(doc):
                if page_number >= max_pages:
                    logger.warning(
                        "Scanned PDF has more than %s pages; only the first "
                        "%s were OCR'd.", max_pages, max_pages,
                    )
                    break
                # 200 DPI is a reasonable balance of OCR accuracy vs.
                # memory/time for a memory-constrained deployment.
                pix = page.get_pixmap(dpi=200)
                image_bytes = pix.tobytes("png")
                page_text = _ocr_image_bytes(image_bytes)
                if page_text:
                    text_parts.append(page_text)
        finally:
            doc.close()
    except DocumentExtractionError:
        raise
    except Exception:
        logger.exception("Failed to OCR scanned PDF at %s", file_path)
        return ""

    return "\n".join(text_parts)


def _ocr_image_bytes(image_bytes):
    """Run both OCR language readers on raw image bytes and merge results."""
    text = []
    for langs in Config.OCR_LANGUAGE_GROUPS:
        text.extend(_get_ocr_reader(langs).readtext(image_bytes, detail=0))
    text = list(dict.fromkeys(text))
    return "\n".join(text)


def extract_text_from_docx(file_path):
    """Extract all text from a DOCX file using python-docx."""
    try:
        document = docx.Document(file_path)
    except Exception as exc:
        raise DocumentExtractionError(
            "This DOCX file could not be opened. It may be corrupted or "
            "password-protected."
        ) from exc
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    if not parts:
        raise DocumentExtractionError("No readable text was found in this DOCX file.")
    return "\n".join(parts)

def extract_text_from_image(file_path):
    """
    OCR a JPG/JPEG (or PNG) image. The image is validated and normalised
    with Pillow first; raises DocumentExtractionError with a clear message
    for unreadable/oversized images or when no text is detected.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(file_path) as img:
            img.verify()
        with Image.open(file_path) as img:
            if img.width * img.height > Config.OCR_MAX_IMAGE_PIXELS:
                raise DocumentExtractionError(
                    "This image is too large to process. Please upload a smaller image."
                )
            img = ImageOps.exif_transpose(img).convert("RGB")
            side = Config.OCR_MAX_IMAGE_SIDE
            if max(img.size) > side:
                img.thumbnail((side, side))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(
            "This image could not be read. It may be corrupted or not a valid JPG."
        ) from exc

    try:
        text = _ocr_image_bytes(buf.getvalue())
    except DocumentExtractionError:
        raise
    except Exception as exc:
        logger.exception("OCR failed for %s", file_path)
        raise DocumentExtractionError(
            "Text recognition failed for this image. Please try again later."
        ) from exc

    if not text.strip():
        raise DocumentExtractionError(
            "No readable text was found in this image. Upload a clearer, "
            "well-lit photo or scan of the document."
        )
    return text


def extract_text(file_path, file_type):
    """
    Extract text from a document based on its file type.

    Args:
        file_path (str): Path to the file on disk.
        file_type (str): "pdf", "docx", "jpg", "jpeg" or "png".

    Returns:
        str: Extracted plain text.

    Raises:
        ValueError: If file_type is unsupported.
    """
    if file_type == "pdf":
       return extract_text_from_pdf(file_path)

    if file_type == "docx":
       return extract_text_from_docx(file_path)

    if file_type in ["jpg", "jpeg", "png"]:
       return extract_text_from_image(file_path)

    raise ValueError(f"Unsupported file type: {file_type}")
def chunk_text(text):
    """Split raw text into overlapping chunks suitable for embedding."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=Config.CHUNK_SIZE,
        chunk_overlap=Config.CHUNK_OVERLAP,
        length_function=len,
    )
    return splitter.split_text(text)


def index_document(document_id, user_id, text):
    """
    Chunk document text and store the resulting embeddings in ChromaDB.

    Each chunk is tagged with document_id/user_id metadata so retrieval
    can later be scoped to a specific document or user.

    Returns:
        int: Number of chunks indexed.
    """
    chunks = chunk_text(text)
    if not chunks:
        logger.warning("No text extracted for document_id=%s", document_id)
        return 0

    metadatas = [
        {"document_id": str(document_id), "user_id": str(user_id), "chunk_index": i}
        for i in range(len(chunks))
    ]
    ids = [f"doc{document_id}_chunk{i}" for i in range(len(chunks))]

    vectorstore = get_vectorstore()
    vectorstore.add_texts(texts=chunks, metadatas=metadatas, ids=ids)

    # Explicitly persist to disk. Depending on the installed chromadb/
    # langchain_community version, writes may otherwise only live in
    # memory for the current process and be lost on the next request
    # or app restart, causing analyze_document() to later find nothing
    # for a document that was actually uploaded successfully.
    if hasattr(vectorstore, "persist"):
        vectorstore.persist()

    logger.info("Indexed %d chunks for document_id=%s", len(chunks), document_id)
    return len(chunks)


def delete_document_embeddings(document_id):
    """Remove all vector store entries belonging to a given document."""
    vectorstore = get_vectorstore()
    vectorstore._collection.delete(where={"document_id": str(document_id)})

    if hasattr(vectorstore, "persist"):
        vectorstore.persist()

    logger.info("Deleted embeddings for document_id=%s", document_id)


def answer_question(question, user_id, document_id=None):
    """
    Run the RAG pipeline to answer a question using indexed documents.

    Retrieval is scoped to the requesting user, and optionally further
    scoped to a single document.

    Args:
        question (str): The user's natural-language question.
        user_id (int): ID of the requesting user (for access scoping).
        document_id (int, optional): Restrict retrieval to one document.

    Returns:
        str: The generated answer.
    """
    vectorstore = get_vectorstore()

    where_filter = {"user_id": str(user_id)}
    if document_id is not None:
        where_filter = {
            "$and": [
                {"user_id": str(user_id)},
                {"document_id": str(document_id)},
            ]
        }

    retriever = vectorstore.as_retriever(
        search_kwargs={"k": Config.RETRIEVER_TOP_K, "filter": where_filter}
    )

    prompt = PromptTemplate(
        template=RAG_PROMPT_TEMPLATE,
        input_variables=["context", "question"]
    )

    def build_call(llm):
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            chain_type_kwargs={"prompt": prompt},
        )
        result = qa_chain.invoke({"query": question})
        return result.get("result", "").strip()

    answer, error_message = _call_llm_with_resilience(build_call)
    if error_message:
        return error_message
    return answer


# ==========================================================================
# Document Analysis
# ==========================================================================

ANALYSIS_PROMPT_TEMPLATE = """You are a legal document analysis assistant. Analyze the
following legal document text and return your findings as a single valid JSON object
and NOTHING else — no markdown, no code fences, no commentary before or after.

The JSON object must have exactly these keys:

"summary": A concise, plain-English explanation of the document (3-6 sentences),
avoiding legal jargon where possible, understandable by a non-lawyer.

"important_dates": An object with these keys, each a string. If a date is not
present in the document, use the exact string "Not Found":
  "agreement_date", "effective_date", "expiry_date", "renewal_date",
  "payment_deadlines", "court_dates"

"people_mentioned": A list of objects, each with "name" and "role" (e.g. "Plaintiff",
"Defendant", "Landlord", "Tenant", "Company", "Government Authority"). Include
individuals, organizations, government authorities, and companies. If none are
found, return an empty list.

"actions_required": A list of strings describing obligations found in the document
(payments, signatures, renewals, filing deadlines, notices, compliance requirements).
If none are found, return an empty list.

"important_clauses": A list of objects, each with "clause_name" and "explanation"
(a brief plain-English explanation of that clause as it appears in this document).
Look for: Termination, Confidentiality, Payment, Liability, Arbitration,
Jurisdiction, Penalties, Force Majeure. If none of these clauses are found, return
an empty list.

Document Text:
{document_text}

Respond with ONLY the JSON object described above."""

# Lightweight prompt for "summary" mode: only the two fields useful for a
# quick at-a-glance view. Skips people/actions/clauses extraction entirely,
# which noticeably reduces LLM generation time compared to full mode.
SUMMARY_PROMPT_TEMPLATE = """You are a legal document analysis assistant. Read the
following legal document text and return your findings as a single valid JSON object
and NOTHING else — no markdown, no code fences, no commentary before or after.

The JSON object must have exactly these keys:

"summary": A concise, plain-English explanation of the document (3-6 sentences),
avoiding legal jargon where possible, understandable by a non-lawyer.

"important_dates": An object with these keys, each a string. If a date is not
present in the document, use the exact string "Not Found":
  "agreement_date", "effective_date", "expiry_date", "renewal_date",
  "payment_deadlines", "court_dates"

Document Text:
{document_text}

Respond with ONLY the JSON object described above."""

# Valid values for the `mode` parameter of analyze_document().
ANALYSIS_MODES = {"summary", "full"}

# Maximum characters of document text sent to # Maximum characters of document text sent to the LLM in one analysis request.
# Keeps the prompt at a reasonable size/cost even though Groq's context
# window is large enough to fit far more.
ANALYSIS_MAX_CHARS = 12000

_EMPTY_ANALYSIS = {
    "summary": "Analysis could not be generated for this document.",
    "important_dates": {
        "agreement_date": "Not Found",
        "effective_date": "Not Found",
        "expiry_date": "Not Found",
        "renewal_date": "Not Found",
        "payment_deadlines": "Not Found",
        "court_dates": "Not Found",
    },
    "people_mentioned": [],
    "actions_required": [],
    "important_clauses": [],
}

# Reduced fallback used for "summary" mode, which only ever returns these
# two keys — no people/actions/clauses fields are included at all, so the
# frontend can tell the two modes apart by which keys are present.
_EMPTY_SUMMARY = {
    "summary": "Summary could not be generated for this document.",
    "important_dates": dict(_EMPTY_ANALYSIS["important_dates"]),
}


def _get_all_document_text(document_id, user_id):
    """
    Retrieve and reassemble the full text of a document from its indexed
    chunks in ChromaDB, ordered by chunk_index.

    Unlike answer_question(), this does not run a similarity search — it
    fetches every chunk belonging to the document directly by metadata,
    since document analysis needs the whole document, not top-k matches.

    Returns:
        str: The reassembled document text, or "" if no chunks are found.
    """
    vectorstore = get_vectorstore()

    results = vectorstore._collection.get(
        where={
            "$and": [
                {"document_id": str(document_id)},
                {"user_id": str(user_id)},
            ]
        }
    )

    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []

    if not documents:
        return ""

    # Re-order by chunk_index so the reassembled text reads in the
    # original document order, not ChromaDB's internal storage order.
    paired = sorted(
        zip(documents, metadatas),
        key=lambda item: item[1].get("chunk_index", 0),
    )
    return "\n".join(text for text, _ in paired)


def _parse_analysis_json(raw_text, empty_fallback=None):
    """
    Safely parse the LLM's analysis response into a dict.

    Strips markdown code fences if present, and falls back to the given
    empty structure if the response is not valid JSON.

    Args:
        raw_text (str): The raw LLM response.
        empty_fallback (dict, optional): Structure to fall back to and to
            fill in missing keys from. Defaults to the full analysis shape.
    """
    fallback = empty_fallback if empty_fallback is not None else _EMPTY_ANALYSIS
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.exception("Failed to parse analysis JSON from LLM response")
        return dict(fallback)

    # Ensure all expected keys for this mode exist even if the model
    # omitted one — but only the keys relevant to this mode, so summary
    # mode responses never gain unrelated full-mode keys.
    for key, default_value in fallback.items():
        if key not in parsed:
            parsed[key] = default_value

    return parsed


def analyze_document(document_id, user_id, mode="full"):
    """
    Run a structured legal analysis of a document using the configured
    Groq LLM, reusing the same indexed chunks from the RAG pipeline.

    Args:
        document_id (int): ID of the document to analyze.
        user_id (int): ID of the requesting user (for access scoping).
        mode (str): "full" (default) returns all 5 sections: summary,
            important_dates, people_mentioned, actions_required,
            important_clauses. "summary" returns only summary and
            important_dates, and skips the heavier extraction work,
            making it faster for a quick at-a-glance view.

    Returns:
        dict: Structured analysis. Keys present depend on `mode`.

    Raises:
        ValueError: If no indexed content is found for the document, or
            if `mode` is not a recognized value.
    """
    if mode not in ANALYSIS_MODES:
        raise ValueError(f"Unsupported analysis mode: {mode}")

    full_text = _get_all_document_text(document_id, user_id)

    if not full_text:
        raise ValueError("No indexed content found for this document.")

    was_truncated = len(full_text) > ANALYSIS_MAX_CHARS
    if was_truncated:
        full_text = full_text[:ANALYSIS_MAX_CHARS]

    if mode == "summary":
        prompt_template = SUMMARY_PROMPT_TEMPLATE
        empty_fallback = _EMPTY_SUMMARY
    else:
        prompt_template = ANALYSIS_PROMPT_TEMPLATE
        empty_fallback = _EMPTY_ANALYSIS

    prompt = prompt_template.format(document_text=full_text)

    def build_call(llm):
        return _llm_text(llm.invoke(prompt))

    raw_response, error_message = _call_llm_with_resilience(build_call)
    if error_message:
        logger.error(
            "LLM call failed during document analysis (mode=%s): %s",
            mode,
            error_message,
        )
        # Raise rather than returning the empty-fallback dict: this is a
        # transient failure (quota/network/model outage), not "the
        # document couldn't be analyzed" — the caller (chat.py) must NOT
        # cache this as if it were a real analysis result, or the user
        # would keep seeing a stale "quota exceeded" message long after
        # the underlying issue is resolved.
        raise GroqServiceError(error_message)

    result = _parse_analysis_json(raw_response, empty_fallback=empty_fallback)
    result["mode"] = mode
    result["truncated"] = was_truncated
    return result


# ==========================================================================
# Indian Language Translation
# ==========================================================================
# Uses the same Groq LLM integration as analysis/chat — no separate
# translation API and no new dependency. Translation is a post-processing
# step applied to an already-generated English analysis, so it works with
# both "full" and "summary" mode results unchanged.

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
}

SINGLE_FIELD_TRANSLATE_PROMPT_TEMPLATE = """You are a professional legal translator. Translate the following text
accurately into fluent, natural {language_name}. Preserve the original meaning exactly —
do not add, remove, or invent any information.
Respond with ONLY the translated text — no quotes, no explanation, no notes,
no original text, nothing else.

Text: {text}

Translation:"""


def translate_text(text, language_name):
    if not text or not text.strip():
        return text

    prompt = SINGLE_FIELD_TRANSLATE_PROMPT_TEMPLATE.format(
        language_name=language_name,
        text=text,
    )

    def build_call(llm):
        return _llm_text(llm.invoke(prompt))

    raw_response, error_message = _call_llm_with_resilience(
        build_call, is_translation=True
    )

    if error_message:
        logger.error("Translation to %s failed: %s", language_name, error_message)
        return text

    cleaned = raw_response.strip()

    if len(cleaned) > 1 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()

    return cleaned if cleaned else text

BATCH_TRANSLATE_PROMPT_TEMPLATE = """You are a professional legal translator. Translate each numbered line below
accurately into fluent, natural {language_name}. Preserve the original meaning exactly for
each line — do not add, remove, or invent any information.
Return the same numbering, one translated line per number, in the same order.
Do not merge, skip, add, or reorder lines. Do not add any commentary.

{numbered_items}

Translation:"""


def translate_list(items, language_name):
    """
    Translate a list of short strings in a single LLM call instead of one
    call per item. This is what makes translating a full-mode analysis
    (which can have many people/actions/clauses) fast — a document with
    10 items now costs 1 call here instead of 10 calls to translate_text().

    Falls back to per-item translate_text() calls if the batched response
    can't be reliably parsed back into the original number of items, and
    falls back further to the original text for any item that still can't
    be matched — so a batching hiccup never loses or corrupts an item.

    Args:
        items (list[str]): Strings to translate, in order.
        language_name (str): Human-readable target language, e.g. "Hindi".

    Returns:
        list[str]: Translated strings, same length and order as `items`.
    """
    non_empty_indices = [i for i, item in enumerate(items) if item and item.strip()]
    if not non_empty_indices:
        return list(items)

    numbered_items = "\n".join(f"{i + 1}. {items[i]}" for i in non_empty_indices)
    prompt = BATCH_TRANSLATE_PROMPT_TEMPLATE.format(
        language_name=language_name, numbered_items=numbered_items
    )

    def build_call(llm):
        return _llm_text(llm.invoke(prompt))

    raw_response, error_message = _call_llm_with_resilience(
        build_call, is_translation=True
    )
    if error_message:
        logger.error(
            "Batch translation to %s failed (%s); falling back to per-item translation",
            language_name,
            error_message,
        )
        return [translate_text(item, language_name) for item in items]

    parsed = {}
    for line in raw_response.strip().splitlines():
        line = line.strip()
        if not line or "." not in line:
            continue
        number_part, _, text_part = line.partition(".")
        number_part = number_part.strip()
        text_part = text_part.strip()
        if number_part.isdigit() and text_part:
            parsed[int(number_part)] = text_part

    result = list(items)
    for i in non_empty_indices:
        translated = parsed.get(i + 1)
        # Fall back to the original English item if this specific line
        # wasn't present or didn't parse — never drop or blank an item.
        result[i] = translated if translated else items[i]

    return result


def translate_analysis(analysis, target_language_code):
    """
    Translate an already-generated English analysis dict into the given
    Indian language, reusing the existing Groq LLM.

    Each list field (people roles, actions, clause names, clause
    explanations) is translated in one batched call via translate_list()
    rather than one call per item, keeping translation fast even for a
    full-mode analysis with many items. A failure translating one field
    only affects that field — it never fails the whole analysis.

    Never translated: JSON keys, "mode", "truncated", "language",
    "Not Found", date values, people's names, and company names.

    Args:
        analysis (dict): The English analysis result from analyze_document().
        target_language_code (str): A key from SUPPORTED_LANGUAGES, e.g. "hi".

    Returns:
        dict: The translated analysis. Only keys present in the input are
            included in the output — mode/summary-scoped shape is preserved
            so the frontend's key-presence checks keep working unchanged.
            If target_language_code is "en", the original analysis is
            returned unchanged (just tagged with "language": "en").

    Raises:
        ValueError: If target_language_code is not in SUPPORTED_LANGUAGES.
    """
    if target_language_code == "en":
        result = dict(analysis)
        result["language"] = "en"
        return result

    if target_language_code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language code: {target_language_code}")

    language_name = SUPPORTED_LANGUAGES[target_language_code]
    result = dict(analysis)

    if "summary" in result:
        result["summary"] = translate_text(result["summary"], language_name)

    # Date values are never translated (e.g. "Not Found" and raw dates
    # must stay exactly as generated), so important_dates is copied as-is.
    if "important_dates" in result:
        result["important_dates"] = dict(result["important_dates"])

    if "people_mentioned" in result:
        people = result["people_mentioned"]
        translated_roles = translate_list(
            [p.get("role", "") for p in people], language_name
        )
        result["people_mentioned"] = [
            {"name": p.get("name"), "role": translated_roles[i]}
            for i, p in enumerate(people)
        ]

    if "actions_required" in result:
        result["actions_required"] = translate_list(
            result["actions_required"], language_name
        )

    if "important_clauses" in result:
        clauses = result["important_clauses"]
        translated_names = translate_list(
            [c.get("clause_name", "") for c in clauses], language_name
        )
        translated_explanations = translate_list(
            [c.get("explanation", "") for c in clauses], language_name
        )
        result["important_clauses"] = [
            {"clause_name": translated_names[i], "explanation": translated_explanations[i]}
            for i in range(len(clauses))
        ]

    result["mode"] = analysis.get("mode", "full")
    result["truncated"] = analysis.get("truncated", False)
    result["language"] = target_language_code
    return result