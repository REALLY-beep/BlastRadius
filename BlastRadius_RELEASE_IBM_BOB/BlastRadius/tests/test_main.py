from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
DIFF = (ROOT / "examples" / "change.diff").read_text(encoding="utf-8")


def test_home_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "BlastRadius" in response.text
    assert "Analyze blast radius" in response.text


def test_demo_analysis():
    response = client.post("/analyze", data={"diff_text": DIFF})
    assert response.status_code == 200
    assert "Impact overview" in response.text
    assert "checkout" in response.text
    assert "test_blast_radius_calculate_total_1.py" in response.text


def test_zip_analysis():
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("project/shop.py", (ROOT / "examples/sample_project/shop.py").read_text())
        archive.writestr("project/test_shop.py", (ROOT / "examples/sample_project/test_shop.py").read_text())
    buffer.seek(0)

    response = client.post(
        "/analyze",
        data={"diff_text": DIFF},
        files={"project_zip": ("project.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 200
    assert "Uploaded project ZIP" in response.text
    assert "process_order" in response.text


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "BlastRadius"}
