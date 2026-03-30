from flask import Flask, request, jsonify, Response
from werkzeug.utils import secure_filename
import json
import io
import hashlib
import uuid
import os
import shutil
import time

# from document_loader import load_multiple_pdfs, load_pptx, load_xlsx
# from vector_store import create_vector_store
# from rag_engine import RAGEngine


import threading

app = Flask(__name__)

# ── Configuration ──
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_CHUNK_SIZE = 5 * 1024 * 1024     # 5 MB
CHUNK_DIR = os.path.join("data", "uploads", "chunks")
ALLOWED_EXTENSIONS = {
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "txt", "md",
    "jpg", "jpeg", "png", "webp", "svg",
    "mp4", "webm", "mov", "avi", "mkv"
}
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX = 30      # max chunk uploads per window per IP
SESSION_TTL = 3600       # 1 hour stale session timeout

GLOBAL_STATE = {
    "documents": [],
    "vector_store": None,
}

UPLOAD_SESSIONS = {}
RATE_LIMIT_STORE = {}
rate_lock = threading.Lock()

vs_lock = threading.Lock()

def rebuild_vector_store():
    from vector_store import create_vector_store
    with vs_lock:
        try:
            all_text = "\n\n".join([doc["text"] for doc in GLOBAL_STATE["documents"]])
            if all_text.strip():
                GLOBAL_STATE["vector_store"] = create_vector_store(all_text)
            else:
                GLOBAL_STATE["vector_store"] = None
        except Exception as e:
            app.logger.error(f"[Rebuild Vector Store Error] {e}", exc_info=True)
            # Don't let indexing errors crash the app/background tasks
            GLOBAL_STATE["vector_store"] = None

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"[Unhandled Error] {e}", exc_info=True)
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/api/api-key", methods=["GET", "POST"])
def api_key_route():
    """Legacy endpoint kept for backward compatibility."""
    if request.method == "POST":
        return jsonify({"message": "API Key saved successfully"})
    return jsonify({"has_key": True})

@app.route("/api/upload", methods=["POST"])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    # secure_filename can strip non-ASCII names to empty
    if not filename:
        filename = "uploaded_file"

    try:
        from document_loader import load_multiple_pdfs, load_pptx, load_xlsx
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        text = ""

        if ext == 'pdf':
            file_bytes = file.read()
            if not file_bytes:
                return jsonify({"error": "Uploaded file is empty"}), 400
            pdf_stream = io.BytesIO(file_bytes)
            try:
                text = load_multiple_pdfs([pdf_stream])
            except Exception as pdf_err:
                app.logger.error(f"[PDF Parse Error] {pdf_err}", exc_info=True)
                return jsonify({"error": f"Failed to parse PDF: {pdf_err}"}), 400
        elif ext in ['pptx', 'ppt']:
            file_bytes = file.read()
            if not file_bytes:
                return jsonify({"error": "Uploaded file is empty"}), 400
            file_stream = io.BytesIO(file_bytes)
            try:
                text = load_pptx(file_stream)
            except Exception as ppt_err:
                app.logger.error(f"[PPT Parse Error] {ppt_err}", exc_info=True)
                return jsonify({"error": f"Failed to parse PowerPoint: {ppt_err}"}), 400
        elif ext in ['xlsx', 'xls']:
            file_stream = io.BytesIO(file.read())
            try:
                text = load_xlsx(file_stream)
            except Exception as xls_err:
                app.logger.error(f"[Excel Parse Error] {xls_err}", exc_info=True)
                return jsonify({"error": f"Failed to parse Excel: {xls_err}"}), 400
        else:
            # Fallback for all other file types: Try to read as text, otherwise register as non-indexable
            raw = file.read()
            if not raw:
                return jsonify({"error": "Uploaded file is empty"}), 400
            try:
                text = raw.decode('utf-8')
            except (UnicodeDecodeError, Exception):
                try:
                    text = raw.decode('latin-1')
                except Exception:
                    # If it's binary or can't be decoded, we still register it
                    text = f"[Binary/Non-text content for {filename}]"

        if not text.strip():
            return jsonify({"error": "Could not extract text from the file (might be empty or scanned)"}), 400

        chunks_estimate = max(1, len(text) // 1000)

        GLOBAL_STATE["documents"] = [d for d in GLOBAL_STATE["documents"] if d["name"] != filename]
        GLOBAL_STATE["documents"].append({
            "name": filename,
            "text": text,
            "chunks": chunks_estimate,
            "size": len(text)
        })

        # Rebuild vector store in background — returns immediately
        threading.Thread(target=rebuild_vector_store, daemon=True).start()

        return jsonify({
            "message": f"Successfully processed {filename}",
            "chunks": chunks_estimate
        })

    except Exception as e:
        app.logger.error(f"[Upload Error] {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════
#  Chunked Upload System
# ═══════════════════════════════════════════════════

def _check_rate_limit(ip):
    now = time.time()
    with rate_lock:
        entries = RATE_LIMIT_STORE.get(ip, [])
        entries = [t for t in entries if now - t < RATE_LIMIT_WINDOW]
        if len(entries) >= RATE_LIMIT_MAX:
            return False
        entries.append(now)
        RATE_LIMIT_STORE[ip] = entries
        return True


def _validate_extension(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


def _process_assembled_file(filepath, filename):
    """Extract text from an assembled file, reusing existing loader logic."""
    from document_loader import load_multiple_pdfs, load_pptx, load_xlsx
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    text = ""

    with open(filepath, "rb") as fh:
        raw = fh.read()

    if not raw:
        raise ValueError("Assembled file is empty")

    if ext == "pdf":
        text = load_multiple_pdfs([io.BytesIO(raw)])
    elif ext in ("pptx", "ppt"):
        text = load_pptx(io.BytesIO(raw))
    elif ext in ("xlsx", "xls"):
        text = load_xlsx(io.BytesIO(raw))
    else:
        try:
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, Exception):
            try:
                text = raw.decode("latin-1")
            except Exception:
                text = f"[Binary/Non-text content for {filename}]"

    return text


def _purge_stale_sessions():
    """Remove upload sessions older than SESSION_TTL."""
    now = time.time()
    stale_ids = [
        uid for uid, s in UPLOAD_SESSIONS.items()
        if now - s["created_at"] > SESSION_TTL
    ]
    for uid in stale_ids:
        session_dir = os.path.join(CHUNK_DIR, uid)
        if os.path.isdir(session_dir):
            shutil.rmtree(session_dir, ignore_errors=True)
        UPLOAD_SESSIONS.pop(uid, None)


@app.route("/api/upload/init", methods=["POST"])
def upload_init():
    _purge_stale_sessions()

    data = request.json or {}
    filename = data.get("filename", "").strip()
    total_size = data.get("total_size", 0)
    total_chunks = data.get("total_chunks", 0)
    content_type = data.get("content_type", "")

    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    safe_name = secure_filename(filename) or "uploaded_file"

    if not _validate_extension(safe_name):
        return jsonify({
            "error": f"File type not allowed. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))} (Text & Images only)"
        }), 400

    if total_size > MAX_UPLOAD_SIZE:
        return jsonify({
            "error": f"File exceeds maximum size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
        }), 400

    if total_chunks < 1 or total_chunks > 100000:
        return jsonify({"error": "Invalid chunk count"}), 400

    upload_id = uuid.uuid4().hex
    session_dir = os.path.join(CHUNK_DIR, upload_id)
    os.makedirs(session_dir, exist_ok=True)

    UPLOAD_SESSIONS[upload_id] = {
        "filename": safe_name,
        "total_size": total_size,
        "total_chunks": total_chunks,
        "content_type": content_type,
        "received": set(),
        "created_at": time.time(),
    }

    return jsonify({"upload_id": upload_id, "filename": safe_name})


@app.route("/api/upload/chunk", methods=["POST"])
def upload_chunk():
    client_ip = request.remote_addr or "unknown"
    if not _check_rate_limit(client_ip):
        return jsonify({"error": "Rate limit exceeded. Try again shortly."}), 429

    upload_id = request.form.get("upload_id", "")
    chunk_index_str = request.form.get("chunk_index", "")
    chunk_hash = request.form.get("chunk_hash", "")

    if upload_id not in UPLOAD_SESSIONS:
        return jsonify({"error": "Invalid or expired upload session"}), 404

    session = UPLOAD_SESSIONS[upload_id]

    try:
        chunk_index = int(chunk_index_str)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid chunk index"}), 400

    if chunk_index < 0 or chunk_index >= session["total_chunks"]:
        return jsonify({"error": "Chunk index out of range"}), 400

    if "chunk" not in request.files:
        return jsonify({"error": "No chunk data provided"}), 400

    chunk_file = request.files["chunk"]
    chunk_data = chunk_file.read()

    if len(chunk_data) > MAX_CHUNK_SIZE:
        return jsonify({"error": f"Chunk exceeds max size of {MAX_CHUNK_SIZE // (1024 * 1024)} MB"}), 400

    if chunk_hash:
        computed = hashlib.sha256(chunk_data).hexdigest()
        if computed != chunk_hash:
            return jsonify({
                "error": "Chunk integrity check failed",
                "expected": chunk_hash,
                "received": computed,
            }), 400

    chunk_path = os.path.join(CHUNK_DIR, upload_id, f"chunk_{chunk_index:06d}.bin")
    with open(chunk_path, "wb") as f:
        f.write(chunk_data)

    session["received"].add(chunk_index)

    return jsonify({
        "received": chunk_index,
        "verified": True,
        "total_received": len(session["received"]),
        "total_chunks": session["total_chunks"],
    })


@app.route("/api/upload/finalize", methods=["POST"])
def upload_finalize():
    data = request.json or {}
    upload_id = data.get("upload_id", "")

    if upload_id not in UPLOAD_SESSIONS:
        return jsonify({"error": "Invalid or expired upload session"}), 404

    session = UPLOAD_SESSIONS[upload_id]
    expected = set(range(session["total_chunks"]))
    missing = expected - session["received"]

    if missing:
        return jsonify({
            "error": "Missing chunks",
            "missing": sorted(missing),
        }), 400

    session_dir = os.path.join(CHUNK_DIR, upload_id)
    assembled_path = os.path.join(session_dir, session["filename"])

    try:
        with open(assembled_path, "wb") as out:
            for i in range(session["total_chunks"]):
                chunk_path = os.path.join(session_dir, f"chunk_{i:06d}.bin")
                with open(chunk_path, "rb") as cp:
                    out.write(cp.read())

        text = _process_assembled_file(assembled_path, session["filename"])

        if not text.strip():
            shutil.rmtree(session_dir, ignore_errors=True)
            UPLOAD_SESSIONS.pop(upload_id, None)
            return jsonify({"error": "Could not extract text from the file"}), 400

        chunks_estimate = max(1, len(text) // 1000)
        filename = session["filename"]

        GLOBAL_STATE["documents"] = [
            d for d in GLOBAL_STATE["documents"] if d["name"] != filename
        ]
        GLOBAL_STATE["documents"].append({
            "name": filename,
            "text": text,
            "chunks": chunks_estimate,
            "size": len(text),
        })

        # Rebuild in background
        threading.Thread(target=rebuild_vector_store, daemon=True).start()

        shutil.rmtree(session_dir, ignore_errors=True)
        UPLOAD_SESSIONS.pop(upload_id, None)

        return jsonify({
            "message": f"Successfully processed {filename}",
            "chunks": chunks_estimate,
        })

    except Exception as e:
        app.logger.error(f"[Finalize Error] {e}", exc_info=True)
        shutil.rmtree(session_dir, ignore_errors=True)
        UPLOAD_SESSIONS.pop(upload_id, None)
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload/<upload_id>", methods=["DELETE"])
def upload_cancel(upload_id):
    if upload_id not in UPLOAD_SESSIONS:
        return jsonify({"error": "Upload session not found"}), 404

    session_dir = os.path.join(CHUNK_DIR, upload_id)
    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)

    UPLOAD_SESSIONS.pop(upload_id, None)
    return jsonify({"message": "Upload cancelled"})


@app.route("/api/upload/status/<upload_id>", methods=["GET"])
def upload_status(upload_id):
    if upload_id not in UPLOAD_SESSIONS:
        return jsonify({"error": "Upload session not found"}), 404

    session = UPLOAD_SESSIONS[upload_id]
    return jsonify({
        "upload_id": upload_id,
        "filename": session["filename"],
        "total_chunks": session["total_chunks"],
        "received_chunks": len(session["received"]),
        "received": sorted(session["received"]),
    })


@app.route("/api/documents", methods=["GET"])
def get_documents():
    docs = []
    total_chunks = 0
    for doc in GLOBAL_STATE["documents"]:
        docs.append({
            "name": doc["name"],
            "chunks": doc["chunks"],
            "size_formatted": f"{doc['size'] // 1024} KB"
        })
        total_chunks += doc["chunks"]

    return jsonify({
        "documents": docs,
        "total_chunks": total_chunks
    })

@app.route("/api/documents/<filename>", methods=["DELETE"])
def delete_document(filename):
    initial_length = len(GLOBAL_STATE["documents"])
    GLOBAL_STATE["documents"] = [d for d in GLOBAL_STATE["documents"] if d["name"] != filename]

    if len(GLOBAL_STATE["documents"]) != initial_length:
        threading.Thread(target=rebuild_vector_store, daemon=True).start()
        return jsonify({"message": "Document deleted"})
    else:
        return jsonify({"error": "Document not found"}), 404

@app.route("/api/clear-history", methods=["POST"])
def clear_history():
    return jsonify({"message": "Chat history cleared"})

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    query = data.get("query", "").strip()
    provider = data.get("provider", "groq")
    model = data.get("model", "llama-3.3-70b-versatile")
    api_key = data.get("api_key", "")

    if not query:
        return jsonify({"error": "Query cannot be empty"}), 400

    if not api_key and provider != "nvidia":
        return jsonify({"error": f"API key for {provider} is missing. Please add it in the sidebar."}), 400


    try:
        from rag_engine import RAGEngine
        engine = RAGEngine(
            GLOBAL_STATE["vector_store"],
            provider=provider,
            model_name=model,
            api_key=api_key
        )

        def generate():
            try:
                for chunk in engine.stream_generate_response(query):
                    yield chunk
            except Exception as e:
                yield f'data: {{"error": "{str(e)}"}}\n\n'

        return Response(generate(), mimetype="text/event-stream")

    except Exception as e:
        app.logger.error(f"[Chat Error] {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=True, use_reloader=False)

