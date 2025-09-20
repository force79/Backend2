import re
import json
import os
import glob
import requests
import pdfplumber

OCR_SPACE_API_KEY = "K81247797588957"      
OCR_SPACE_URL     = "https://api.ocr.space/parse/image"

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DATA_DIR     = os.path.join(BASE_DIR, "database")
OUTPUT_JSON  = os.path.join(DATA_DIR, "data.json")


def get_latest_pdf(download_dir: str = DOWNLOAD_DIR) -> str:
    """Return path of the most recently modified PDF in ./downloads folder."""
    pdfs = glob.glob(os.path.join(download_dir, "*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {download_dir}")
    return max(pdfs, key=os.path.getmtime)


def ocr_space_file(file_path: str, api_key: str = OCR_SPACE_API_KEY, timeout: int = 60) -> str:
    """
    Send file to OCR.space and return parsed text.
    Raises RuntimeError if OCR.space signals an error.
    """
    print("Sending file to OCR.space …")
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"apikey": api_key, "language": "eng", "isOverlayRequired": False}
        resp = requests.post(OCR_SPACE_URL, files=files, data=data, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    if result.get("IsErroredOnProcessing"):
        raise RuntimeError("OCR.space error:\n" + json.dumps(result, indent=2))
    return " ".join(item.get("ParsedText", "") for item in result.get("ParsedResults", []))


def extract_text_with_pdfplumber(path: str) -> str:
    """Try extracting text with pdfplumber; return empty string on failure."""
    text_parts = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if txt:
                    text_parts.append(txt)
    except Exception as e:
        print("⚠️ pdfplumber error:", e)
        return ""
    return "\n".join(text_parts)


def parse_attendance_text(text: str) -> dict:
    """Parse key fields from the text into a JSON structure."""
    out = {}

    m_univ = re.search(r"^(SHRI[^\n]+)", text, re.IGNORECASE | re.MULTILINE)
    out["university"] = m_univ.group(1).strip() if m_univ else None

    m_addr = re.search(r"SHRI[^\n]+\n([^\n]+)", text, re.IGNORECASE)
    out["address"] = m_addr.group(1).strip() if m_addr else None

    roll   = re.search(r"Roll No[:\s]*([\dA-Za-z\-]+)", text)
    term   = re.search(r"Term[:\s]*([^\n]+)", text)
    name   = re.search(r"Name[:\s]*([A-Za-z .]+[A-Za-z])", text)
    alevel = re.search(r"Academic Level[:\s]*([0-9A-Za-z]+)", text)
    course = re.search(r"Course[:\s]*([^\n]+)", text)

    out["report_title"] = "Student Attendance Report"
    out["student"] = {
        "roll_no":        roll.group(1).strip() if roll else None,
        "term":           term.group(1).strip() if term else None,
        "name":           name.group(1).strip() if name else None,
        "academic_level": alevel.group(1).strip() if alevel else None,
        "course":         course.group(1).strip() if course else None
    }

    rows = []
    lines = [re.sub(r"\s{2,}", " ", ln.strip()) for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        m = re.match(
            r"^(\d+)\s+(.+?)\s+([A-Z0-9]+)\s+(Theory|Practical)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d{1,3})(?:\b|$)",
            ln, re.IGNORECASE
        )
        if m:
            rows.append({
                "sno": int(m.group(1)),
                "class_title": m.group(2).strip(),
                "subject_code": m.group(3).strip(),
                "component": m.group(4).strip(),
                "total_lecture_conducted": int(m.group(5)),
                "lecture_attended": int(m.group(6)),
                "compensatory": int(m.group(7)),
                "attendance_percent": int(m.group(8))
            })

    if not rows:
        for ln in lines:
            mloose = re.match(
                r"^(\d+)\s+(.+?)\s+([0-9A-Z]+)\s+(Theory|Practical)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)",
                ln, re.IGNORECASE
            )
            if mloose:
                rows.append({
                    "sno": int(mloose.group(1)),
                    "class_title": mloose.group(2).strip(),
                    "subject_code": mloose.group(3).strip(),
                    "component": mloose.group(4).strip(),
                    "total_lecture_conducted": int(mloose.group(5)),
                    "lecture_attended": int(mloose.group(6)),
                    "compensatory": int(mloose.group(7)),
                    "attendance_percent": float(mloose.group(8))
                })

    out["attendance_rows"] = rows

    mo = re.search(r"Overall Attendance %[:=]*[:\s]*([0-9.]+)", text)
    if not mo:
        mo = re.search(r"Overall Attendance %[:=]*[:\s]*([0-9.]+)", text.replace("%", ""))
    out["overall_attendance_percent"] = float(mo.group(1)) if mo else None
    out["overall_attendance_formula"] = (
        "(Total Lecture Attended / Total Lecture Conducted) * 100"
    )
    return out


def main(pdf_path: str, out_json_path: str) -> dict:
    """
    Extract text (pdfplumber first, OCR.space fallback), parse,
    save to JSON, and return the parsed dictionary.
    """
    text = extract_text_with_pdfplumber(pdf_path)

    if not text or len(re.sub(r"\s", "", text)) < 50:
        print("pdfplumber found little/no text — falling back to OCR.space")
        text = ocr_space_file(pdf_path)
    else:
        print("Text extracted using pdfplumber")

    parsed = parse_attendance_text(text)
    parsed["source_file"] = os.path.basename(pdf_path)

    os.makedirs(os.path.dirname(out_json_path), exist_ok=True)
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    print("Saved parsed JSON to", out_json_path)

    return parsed


def run_analysis() -> dict:
    """
    Public entry point for app.py:
    • Finds the latest PDF in ./downloads
    • Parses it and saves to database/data.json
    • Returns the parsed dict
    """
    latest_pdf = get_latest_pdf()
    print(f"Latest PDF found in ./downloads: {latest_pdf}")
    parsed = main(latest_pdf, OUTPUT_JSON)
    return parsed
