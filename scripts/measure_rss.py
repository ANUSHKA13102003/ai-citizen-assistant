"""Measure peak RSS memory with EMBEDDINGS_BACKEND=gemini for a realistic 5-doc + wizard + 10-chat session."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ["EMBEDDINGS_BACKEND"] = "gemini"
os.environ["FLASK_ENV"] = "production"

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app  # noqa: E402
from tests.conftest import make_pdf_bytes  # noqa: E402


def _rss_mb() -> float:
    import subprocess

    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {os.getpid()}).PeakWorkingSet64"],
        text=True,
    ).strip()
    return int(out) / (1024 * 1024)


def main() -> None:
    app = create_app("testing")
    app.config["TESTING"] = True
    client = app.test_client()

    hz = client.get("/healthz").get_json()
    print(f"healthz: {hz}")

    # 1. Upload 5 realistic PDFs
    files = []
    for i in range(5):
        pdf = make_pdf_bytes(
            [
                f"Citizen Document {i+1}. Name: Priya Verma. Uttar Pradesh. "
                f"Annual Family Income: Rs. 2,40,000. Marks: 78.2%. B.Sc."
            ]
        )
        files.append((io.BytesIO(pdf), f"doc_{i+1}.pdf"))

    up = client.post("/api/upload", data={"files": files}, content_type="multipart/form-data")
    assert up.status_code == 200, up.get_data(as_text=True)

    # 2. Run Find Schemes wizard match
    m = client.post(
        "/api/scheme-match",
        json={"answers": {"state": "Uttar Pradesh", "age": 19, "occupation": "student", "annual_income_inr": 240000}},
    )
    assert m.status_code == 200

    # 3. 10 chat turns (greetings + scheme Q&A)
    for i in range(10):
        q = "Namaste" if i % 2 == 0 else "What is my passport number?"
        r = client.post("/api/chat", json={"question": q})
        assert r.status_code == 200

    peak = round(_rss_mb(), 1)
    torch_loaded = "torch" in sys.modules
    st_loaded = "sentence_transformers" in sys.modules
    chroma_loaded = "chromadb" in sys.modules
    print(
        f"PEAK_RSS_MB={peak} | torch={torch_loaded} sentence_transformers={st_loaded} chromadb={chroma_loaded}"
    )
    assert peak < 400.0, f"Peak RSS {peak} MB exceeded 400 MB budget!"


if __name__ == "__main__":
    main()
