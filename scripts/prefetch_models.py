"""Build-time helper: download embedding + OCR models into MODEL_CACHE_DIR.

Never fails the build; models are simply downloaded on first use instead.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import Config  # noqa: E402  (also sets HF/ST cache env vars)


def main():
    try:
        from app.services.rag_service import get_embedding_function

        get_embedding_function().embed_query("warm up")
        print("Embedding model ready.")
    except Exception as exc:
        print(f"WARNING: embedding model prefetch skipped: {exc}")
    if Config.OCR_BACKEND == "easyocr":
        try:
            import easyocr

            for langs in Config.OCR_LANGUAGE_GROUPS:
                easyocr.Reader(
                    langs, gpu=False,
                    model_storage_directory=os.path.join(Config.MODEL_CACHE_DIR, "easyocr"),
                )
            print("OCR models ready.")
        except Exception as exc:
            print(f"WARNING: OCR model prefetch skipped: {exc}")

if __name__ == "__main__":
    main()
