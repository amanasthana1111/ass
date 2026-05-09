from __future__ import annotations

import concurrent.futures
import json
from dataclasses import asdict
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler

from factcheck_core import extract_claims, extract_pdf_text, serialize_result, verification_worker_count, verify_claim


def parse_pdf_from_multipart(handler: BaseHTTPRequestHandler) -> bytes:
    content_length = int(handler.headers.get("content-length", "0"))
    content_type = handler.headers.get("content-type", "")
    raw_body = handler.rfile.read(content_length)
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw_body
    )
    for part in message.iter_parts():
        disposition = part.get("content-disposition", "")
        if "form-data" in disposition and part.get_param("name", header="content-disposition") == "pdf":
            return part.get_payload(decode=True) or b""
    return b""


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(200, {"ok": True})

    def do_POST(self) -> None:
        try:
            pdf_data = parse_pdf_from_multipart(self)
            if not pdf_data:
                self._send(400, {"error": "Upload a PDF field named 'pdf'."})
                return
            pages = extract_pdf_text(pdf_data)
            if not pages:
                self._send(422, {"error": "No selectable text found. OCR is not enabled."})
                return
            claims = extract_claims(pages)
            if not claims:
                self._send(200, {"claims": [], "results": [], "counts": {}})
                return
            results: list[dict] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=verification_worker_count()) as executor:
                futures = [executor.submit(verify_claim, claim) for claim in claims]
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())
            results.sort(key=lambda item: item["id"])
            counts = {verdict: sum(1 for item in results if item["verdict"] == verdict) for verdict in ["Verified", "Inaccurate", "False"]}
            self._send(
                200,
                {
                    "claims": [asdict(claim) for claim in claims],
                    "results": [serialize_result(result) for result in results],
                    "counts": counts,
                },
            )
        except Exception as exc:
            self._send(500, {"error": str(exc)})
