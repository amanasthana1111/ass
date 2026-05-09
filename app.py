from __future__ import annotations

import concurrent.futures
import csv
import io
import json
from datetime import datetime

import streamlit as st

from factcheck_core import (
    GEMINI_MODEL,
    MAX_CLAIMS,
    MAX_PAGES,
    Claim,
    configured_provider,
    extract_claims,
    extract_pdf_text,
    llm_available,
    serialize_result,
    verification_worker_count,
    verify_claim,
)


def inject_theme() -> None:
    st.markdown(
        """
        <style>
            :root {
                --ink: #17202a;
                --muted: #657181;
                --line: #d9e1ea;
                --panel: #ffffff;
                --blue: #315f9f;
                --green: #147a53;
                --amber: #a75c10;
                --red: #b3261e;
            }

            .stApp {
                background: linear-gradient(180deg, #f7fafc 0%, #eef3f7 48%, #f7fafc 100%);
                color: var(--ink);
            }

            [data-testid="stSidebar"] {
                background: #ffffff;
                border-right: 1px solid var(--line);
            }

            .block-container {
                max-width: 1180px;
                padding-bottom: 3rem;
                padding-top: 2rem;
            }

            .hero {
                background: #ffffff;
                border: 1px solid var(--line);
                border-radius: 8px;
                box-shadow: 0 14px 38px rgba(23, 32, 42, 0.07);
                margin-bottom: 1.1rem;
                padding: 1.4rem 1.55rem;
            }

            .eyebrow {
                color: var(--blue);
                font-size: 0.78rem;
                font-weight: 700;
                letter-spacing: 0;
                margin-bottom: 0.35rem;
                text-transform: uppercase;
            }

            .hero h1 {
                color: var(--ink);
                font-size: 2.25rem;
                line-height: 1.1;
                margin: 0 0 0.55rem 0;
            }

            .hero p {
                color: var(--muted);
                font-size: 1rem;
                margin: 0;
                max-width: 780px;
            }

            .status-strip {
                display: grid;
                gap: 0.75rem;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                margin: 1rem 0 1.25rem 0;
            }

            .status-card {
                background: #ffffff;
                border: 1px solid var(--line);
                border-radius: 8px;
                padding: 0.9rem 1rem;
            }

            .status-card b {
                color: var(--ink);
                display: block;
                font-size: 1.15rem;
                margin-bottom: 0.15rem;
            }

            .status-card span {
                color: var(--muted);
                font-size: 0.86rem;
            }

            .result-card {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: 8px;
                box-shadow: 0 8px 24px rgba(23, 32, 42, 0.055);
                margin: 0.85rem 0;
                padding: 1rem 1.05rem;
            }

            .result-title {
                align-items: center;
                display: flex;
                font-weight: 700;
                gap: 0.55rem;
                margin-bottom: 0.45rem;
            }

            .pill {
                align-items: center;
                border-radius: 999px;
                color: white;
                display: inline-flex;
                font-size: 0.78rem;
                font-weight: 700;
                min-height: 1.55rem;
                padding: 0.12rem 0.55rem;
            }

            .pill-verified { background: var(--green); }
            .pill-inaccurate { background: var(--amber); }
            .pill-false { background: var(--red); }
            .pill-default { background: #53606f; }

            .meta-line {
                color: var(--muted);
                font-size: 0.84rem;
                margin: 0.3rem 0 0.65rem 0;
            }

            div[data-testid="stFileUploader"] section {
                background: #ffffff;
                border-color: var(--blue);
                border-radius: 8px;
            }

            div.stButton > button:first-child,
            div.stDownloadButton > button:first-child {
                border-radius: 6px;
                font-weight: 700;
            }

            @media (max-width: 700px) {
                .status-strip { grid-template-columns: 1fr; }
                .hero h1 { font-size: 1.75rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(verdict: str) -> str:
    class_name = {
        "Verified": "pill-verified",
        "Inaccurate": "pill-inaccurate",
        "False": "pill-false",
    }.get(verdict, "pill-default")
    return f"<span class='pill {class_name}'>{verdict}</span>"


def render_fact_box(title: str, fact: dict) -> None:
    if not fact:
        return
    lines = []
    for key in ["subject", "relationship", "object", "time", "quantity"]:
        value = fact.get(key)
        if value:
            lines.append(f"**{key.title()}**: {value}")
    qualifiers = fact.get("qualifiers")
    if qualifiers:
        lines.append(f"**Qualifiers**: {', '.join(str(item) for item in qualifiers)}")
    if lines:
        st.markdown(f"**{title}**")
        st.markdown("  \n".join(lines))


def render_result(result: dict) -> None:
    st.markdown("<div class='result-card'>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='result-title'>{badge(result['verdict'])}<span>Claim {result['id']}</span></div>",
        unsafe_allow_html=True,
    )
    st.write(result["claim"])
    st.markdown(
        "<div class='meta-line'>"
        f"Page {result['page']} / {result['type']} / Confidence: {result['confidence']} / "
        f"Semantic relation: {result.get('semantic_relation', 'unknown')} / "
        f"LLM used: {'yes' if result.get('llm_used') else 'no'}"
        "</div>",
        unsafe_allow_html=True,
    )
    st.write(result["reason"])
    contradictions = result.get("contradictions") or []
    if contradictions:
        st.warning("\n".join(f"- {item}" for item in contradictions))
    if result["verdict"] != "Verified":
        st.info(result["correct_fact"])
    with st.expander("Semantic analysis"):
        render_fact_box("Claim fact", result.get("claim_fact", {}))
        render_fact_box("Evidence fact", result.get("evidence_fact", {}))
        st.markdown("**Weak matching signals, not final verdict logic**")
        st.json(result.get("weak_matching_signals", {}))
    with st.expander("Evidence and query"):
        st.code(result["search_query"], language="text")
        if not result["sources"]:
            st.write("No sources returned.")
        for source in result["sources"]:
            st.markdown(f"- [{source.title}]({source.url})  \n  `{source.source}` - {source.snippet}")
    st.markdown("</div>", unsafe_allow_html=True)


def csv_export(results: list[dict]) -> bytes:
    rows = []
    for result in results:
        rows.append(
            {
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "semantic_relation": result.get("semantic_relation", ""),
                "llm_used": result.get("llm_used", False),
                "page": result["page"],
                "claim": result["claim"],
                "type": result["type"],
                "pdf_values": result["values_found_in_pdf"],
                "reason": result["reason"],
                "contradictions": " | ".join(result.get("contradictions") or []),
                "correct_fact": result["correct_fact"],
                "sources": " | ".join(source.url for source in result["sources"]),
            }
        )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def run_verification(claims: list[Claim]) -> list[dict]:
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=verification_worker_count()) as executor:
        futures = {executor.submit(verify_claim, claim): claim for claim in claims}
        for future in concurrent.futures.as_completed(futures):
            claim = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "id": claim.id,
                        "page": claim.page,
                        "claim": claim.text,
                        "type": claim.kind,
                        "values_found_in_pdf": ", ".join(claim.values),
                        "search_query": claim.query,
                        "verdict": "False",
                        "confidence": "Low",
                        "semantic_relation": "no_support",
                        "claim_fact": {},
                        "evidence_fact": {},
                        "contradictions": [f"Verification failed: {exc}"],
                        "reason": f"Verification failed: {exc}",
                        "correct_fact": "No supported replacement fact found.",
                        "llm_used": False,
                        "weak_matching_signals": {},
                        "sources": [],
                    }
                )
    return sorted(results, key=lambda item: item["id"])


def main() -> None:
    st.set_page_config(page_title="Claim Audit Desk", page_icon="CA", layout="wide")
    inject_theme()
    st.markdown(
        """
        <section class="hero">
            <div class="eyebrow">PDF verification workspace</div>
            <h1>Claim Audit Desk</h1>
            <p>Upload a document, extract measurable claims, compare them with live evidence, and export a clean audit report.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="status-strip">
            <div class="status-card"><b>{MAX_PAGES} pages</b><span>Maximum scanned per PDF</span></div>
            <div class="status-card"><b>{MAX_CLAIMS} claims</b><span>Maximum checks per upload</span></div>
            <div class="status-card"><b>{configured_provider()}</b><span>Active semantic verifier</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Control Panel")
        st.write(f"Document limit: `{MAX_PAGES}` pages")
        st.write(f"Claim limit: `{MAX_CLAIMS}` per PDF")
        st.write("Add `GEMINI_API_KEY` for LLM-based adjudication.")
        st.write("Add `TAVILY_API_KEY` for stronger search results.")
        st.divider()
        st.subheader("Verifier")
        st.write(f"Provider: `{configured_provider()}`")
        st.write(f"LLM enabled: {'yes' if llm_available() else 'no'}")
        st.write(f"Gemini model: `{GEMINI_MODEL}`")
        st.divider()
        st.subheader("Verdicts")
        st.write("Verified: evidence entails the full claim.")
        st.write("Inaccurate: evidence shows a related but materially wrong or outdated claim.")
        st.write("False: evidence contradicts the claim or does not support it.")

    uploaded = st.file_uploader("Upload PDF for audit", type=["pdf"])
    if not uploaded:
        st.stop()

    with st.spinner("Reading PDF and extracting claims..."):
        pages = extract_pdf_text(uploaded)
        claims = extract_claims(pages)

    if not pages:
        st.error("No selectable text was found in this PDF. OCR is not enabled in this lightweight deployment.")
        st.stop()
    if not claims:
        st.warning("No checkable statistical, date, financial, or technical claims were found.")
        st.stop()

    st.subheader("Claims Ready For Review")
    st.dataframe(
        [{"id": c.id, "page": c.page, "type": c.kind, "claim": c.text, "values": ", ".join(c.values)} for c in claims],
        use_container_width=True,
        hide_index=True,
    )

    if st.button("Start Claim Audit", type="primary"):
        progress = st.progress(0)
        status = st.empty()
        results: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=verification_worker_count()) as executor:
            futures = {executor.submit(verify_claim, claim): claim for claim in claims}
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                claim = futures[future]
                status.write(f"Checking claim {claim.id}/{len(claims)}...")
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        {
                            "id": claim.id,
                            "page": claim.page,
                            "claim": claim.text,
                            "type": claim.kind,
                            "values_found_in_pdf": ", ".join(claim.values),
                            "search_query": claim.query,
                            "verdict": "False",
                            "confidence": "Low",
                            "semantic_relation": "no_support",
                            "claim_fact": {},
                            "evidence_fact": {},
                            "contradictions": [f"Verification failed: {exc}"],
                            "reason": f"Verification failed: {exc}",
                            "correct_fact": "No supported replacement fact found.",
                            "llm_used": False,
                            "weak_matching_signals": {},
                            "sources": [],
                        }
                    )
                progress.progress(index / len(claims))
        st.session_state["results"] = sorted(results, key=lambda item: item["id"])
        status.write("Audit complete.")

    if "results" in st.session_state:
        results = st.session_state["results"]
        counts = {verdict: sum(1 for result in results if result["verdict"] == verdict) for verdict in ["Verified", "Inaccurate", "False"]}
        cols = st.columns(3)
        cols[0].metric("Verified", counts.get("Verified", 0))
        cols[1].metric("Inaccurate", counts.get("Inaccurate", 0))
        cols[2].metric("False", counts.get("False", 0))

        st.download_button(
            "Download CSV Report",
            data=csv_export(results),
            file_name=f"claim_audit_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        st.subheader("Audit Report")
        for result in results:
            render_result(result)

        st.subheader("Machine-Readable JSON")
        st.code(json.dumps([serialize_result(result) for result in results], indent=2), language="json")


if __name__ == "__main__":
    main()
