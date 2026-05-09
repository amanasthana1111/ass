from __future__ import annotations

import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


MAX_PAGES = 25
MAX_CLAIMS = 5
SEARCH_RESULTS = 6
REQUEST_TIMEOUT = 12
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TIMEOUT = 35
GEMINI_MAX_RETRIES = 5


@dataclass
class Claim:
    id: int
    text: str
    kind: str
    page: int
    query: str
    values: list[str]


@dataclass
class Evidence:
    title: str
    url: str
    snippet: str
    source: str


STAT_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?%",
    r"\$[\d,.]+(?:\s?(?:million|billion|trillion|m|bn|k))?",
    r"\b\d+(?:\.\d+)?\s?(?:million|billion|trillion|m|bn|k)\b",
    r"\b\d+(?:\.\d+)?\s?(?:users|customers|employees|revenue|downloads|market share|growth|ARR|MRR)\b",
    r"\b(?:19|20)\d{2}\b",
    r"\bQ[1-4]\s?(?:FY)?(?:19|20)?\d{2}\b",
    r"\b\d+(?:\.\d+)?\s?(?:ms|seconds?|minutes?|hours?|GB|TB|MB|kbps|Mbps|Gbps|nm|kWh|MW|GW)\b",
]


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "over",
    "under",
    "than",
    "our",
    "their",
    "they",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "its",
    "can",
    "will",
    "would",
    "should",
}


class LLMRequestError(RuntimeError):
    def __init__(self, status_code: int, message: str, error_type: str = "", error_code: str = ""):
        self.provider = provider_name()
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.error_code = error_code
        super().__init__(self.describe())

    def describe(self) -> str:
        detail = self.message
        if self.error_type or self.error_code:
            detail = f"{detail} (type={self.error_type or 'unknown'}, code={self.error_code or 'unknown'})"
        return f"{self.provider} API error {self.status_code}: {detail}"


FACT_CHECK_SYSTEM_PROMPT = """You are a strict semantic fact-checking adjudicator.

Your job is to compare the FULL MEANING of one claim against the supplied web evidence.
Do not verify a claim because a date, number, or keyword appears in the evidence.
Compare entities, relationships, objects, dates, quantities, locations, and qualifiers.

Use only the supplied evidence. Do not use outside knowledge to invent support.

Verdict rules:
- VERIFIED: the evidence states the same fact as the claim, allowing normal paraphrase.
- FALSE: the evidence directly contradicts the claim, names a different entity/object/value for the same relationship, or no evidence supports the claim.
- INACCURATE: the claim is related to the evidence but materially outdated, imprecise, incomplete, or has a wrong numeric/date/technical value while the correct fact is recoverable.

Examples:
- Claim: India won FIFA World Cup 2022. Evidence: Argentina won FIFA World Cup 2022. Verdict: FALSE.
- Claim: Google was founded in 2015. Evidence: Google was founded in 1998. Verdict: FALSE.
- Claim: Microsoft acquired LinkedIn in 2016. Evidence: Microsoft completed its acquisition of LinkedIn in 2016. Verdict: VERIFIED.

Return only valid JSON with this exact shape:
{
  "verdict": "Verified|Inaccurate|False",
  "confidence": "High|Medium|Low",
  "semantic_relation": "entails|contradicts|related_mismatch|no_support",
  "claim_fact": {
    "subject": "...",
    "relationship": "...",
    "object": "...",
    "time": "...",
    "quantity": "...",
    "qualifiers": ["..."]
  },
  "evidence_fact": {
    "subject": "...",
    "relationship": "...",
    "object": "...",
    "time": "...",
    "quantity": "...",
    "qualifiers": ["..."]
  },
  "contradictions": ["..."],
  "reason": "...",
  "correct_fact": "..."
}
"""


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf_text(uploaded_file: io.BytesIO | bytes) -> list[tuple[int, str]]:
    stream = io.BytesIO(uploaded_file) if isinstance(uploaded_file, bytes) else uploaded_file
    reader = PdfReader(stream)
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((index, normalize_spaces(text)))
    return pages


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$])", text)
    return [piece.strip(" -•\t") for piece in pieces if 35 <= len(piece.strip()) <= 320]


def claim_kind(sentence: str) -> str | None:
    lowered = sentence.lower()
    if re.search(r"\$|revenue|valuation|profit|loss|market cap|arr|mrr|funding", lowered):
        return "financial"
    if re.search(r"%|percent|growth|share|increase|decrease|cagr", lowered):
        return "statistic"
    if re.search(r"\b(?:19|20)\d{2}\b|q[1-4]|since|launched|founded|released", lowered):
        return "date"
    if re.search(r"\b(?:ms|gb|tb|mb|mbps|gbps|nm|kwh|mw|gw|latency|throughput|capacity)\b", lowered):
        return "technical"
    if re.search(r"\b(?:million|billion|trillion|users|customers|employees|downloads)\b", lowered):
        return "figure"
    return None


def extract_values(sentence: str) -> list[str]:
    values: list[str] = []
    for pattern in STAT_PATTERNS:
        values.extend(re.findall(pattern, sentence, flags=re.IGNORECASE))
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if isinstance(value, tuple):
            value = " ".join(value)
        key = re.sub(r"[^a-z0-9.]+", "", value.lower())
        if key and key not in seen:
            seen.add(key)
            unique.append(value.strip())
    filtered: list[str] = []
    for value in unique:
        compact = re.sub(r"[^a-z0-9.]+", "", value.lower())
        if any(
            compact != re.sub(r"[^a-z0-9.]+", "", other.lower())
            and compact in re.sub(r"[^a-z0-9.]+", "", other.lower())
            for other in unique
        ):
            continue
        filtered.append(value)
    return filtered


def keywords(sentence: str, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9&.-]{2,}", sentence)
    scored: list[tuple[int, str]] = []
    for word in words:
        low = word.lower().strip(".")
        if low in STOPWORDS:
            continue
        score = 1
        if word[:1].isupper():
            score += 2
        if any(char.isdigit() for char in word):
            score += 2
        if len(word) > 7:
            score += 1
        scored.append((score, word.strip(".")))
    chosen: list[str] = []
    seen: set[str] = set()
    for _, word in sorted(scored, reverse=True):
        key = word.lower()
        if key not in seen:
            chosen.append(word)
            seen.add(key)
        if len(chosen) == limit:
            break
    return list(reversed(chosen))


def build_query(sentence: str) -> str:
    vals = extract_values(sentence)[:4]
    terms = keywords(sentence, limit=9)
    return " ".join([*terms, *vals, "official source latest"])


def extract_claims(pages: list[tuple[int, str]]) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[str] = set()
    for page_number, text in pages:
        for sentence in split_sentences(text):
            values = extract_values(sentence)
            kind = claim_kind(sentence)
            if not values or kind is None:
                continue
            key = re.sub(r"\W+", "", sentence.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                Claim(
                    id=len(claims) + 1,
                    text=sentence,
                    kind=kind,
                    page=page_number,
                    query=build_query(sentence),
                    values=values,
                )
            )
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims


def search_tavily(query: str) -> list[Evidence]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": SEARCH_RESULTS,
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return [
        Evidence(
            title=item.get("title", "Untitled"),
            url=item.get("url", ""),
            snippet=normalize_spaces(item.get("content", "")),
            source=source_name(item.get("url", "")),
        )
        for item in payload.get("results", [])
        if item.get("url")
    ]


def search_duckduckgo(query: str) -> list[Evidence]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 fact-checker/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[Evidence] = []
    for result in soup.select(".result")[:SEARCH_RESULTS]:
        link = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")
        if not link:
            continue
        href = unwrap_result_url(link.get("href", ""))
        title = normalize_spaces(link.get_text(" "))
        summary = normalize_spaces(snippet.get_text(" ") if snippet else "")
        if href and title:
            results.append(Evidence(title=title, url=href, snippet=summary, source=source_name(href)))
    return results


def unwrap_result_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return url


def source_name(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host or "web"


def search_web(query: str) -> list[Evidence]:
    try:
        tavily = search_tavily(query)
        if tavily:
            return tavily
    except Exception:
        pass
    try:
        return search_duckduckgo(query)
    except Exception:
        return []


def normalize_number(value: str) -> float | None:
    raw = value.lower().replace(",", "").replace("$", "").replace("%", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    number = float(match.group())
    if "trillion" in raw:
        number *= 1_000_000_000_000
    elif "billion" in raw or re.search(r"\bbn\b", raw):
        number *= 1_000_000_000
    elif "million" in raw or re.search(r"\bm\b", raw):
        number *= 1_000_000
    elif re.search(r"\bk\b", raw):
        number *= 1_000
    return number


def numbers_close(a: str, b: str) -> bool:
    first = normalize_number(a)
    second = normalize_number(b)
    if first is None or second is None:
        return False
    if first == second:
        return True
    tolerance = max(abs(first), abs(second)) * 0.03
    return abs(first - second) <= max(tolerance, 0.5)


def evidence_values(evidence: Iterable[Evidence]) -> list[str]:
    values: list[str] = []
    for item in evidence:
        values.extend(extract_values(f"{item.title} {item.snippet}"))
    return values


def semantic_signals(claim: Claim, evidence: list[Evidence]) -> dict:
    ev_values = evidence_values(evidence)
    matched_values = [
        value for value in claim.values if any(value.lower() in ev.lower() or numbers_close(value, ev) for ev in ev_values)
    ]
    claim_terms = set(word.lower() for word in keywords(claim.text, limit=10))
    evidence_text = " ".join(f"{item.title} {item.snippet}" for item in evidence).lower()
    term_hits = sorted(term for term in claim_terms if term in evidence_text)
    return {
        "pdf_values": claim.values,
        "evidence_values": ev_values[:12],
        "matched_values": matched_values,
        "keyword_overlap": term_hits,
        "note": "These are weak signals only. They must not decide the final verdict without semantic reasoning.",
    }


def evidence_payload(evidence: list[Evidence]) -> list[dict]:
    return [
        {
            "id": index,
            "title": item.title[:240],
            "source": item.source,
            "url": item.url,
            "snippet": item.snippet[:500],
        }
        for index, item in enumerate(evidence, start=1)
    ]


def build_llm_messages(claim: Claim, evidence: list[Evidence], signals: dict) -> list[dict]:
    user_payload = {
        "claim": {
            "id": claim.id,
            "text": claim.text,
            "type": claim.kind,
            "page": claim.page,
            "values_extracted_from_pdf": claim.values,
        },
        "evidence": evidence_payload(evidence),
        "weak_matching_signals": signals,
        "task": "Decide whether the evidence semantically entails, contradicts, partially corrects, or does not support the full claim.",
    }
    return [
        {"role": "system", "content": FACT_CHECK_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)},
    ]


def provider_name() -> str:
    provider = configured_provider()
    return {"gemini": "Gemini", "none": "No LLM"}.get(provider, provider)


def configured_provider() -> str:
    # Force the application to use Gemini only for semantic verification.
    # Do not allow switching to other LLM providers at runtime; the GEMINI_API_KEY
    # environment variable still controls whether Gemini is available.
    return "gemini"


def llm_available() -> bool:
    return configured_provider() == "gemini" and bool(os.getenv("GEMINI_API_KEY"))


def call_llm_json(messages: list[dict]) -> dict | None:
    if configured_provider() == "gemini":
        return call_gemini_json(messages)
    return None


def call_gemini_json(messages: list[dict]) -> dict | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    system_text = next((message["content"] for message in messages if message["role"] == "system"), FACT_CHECK_SYSTEM_PROMPT)
    user_text = "\n\n".join(message["content"] for message in messages if message["role"] != "system")
    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_TOKENS", "1600")),
            "responseMimeType": "application/json",
            "responseSchema": fact_check_response_schema(),
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    last_error: LLMRequestError | None = None
    for attempt in range(GEMINI_MAX_RETRIES + 1):
        response = requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=GEMINI_TIMEOUT,
        )
        if response.ok:
            data = response.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as exc:
                raise LLMRequestError(response.status_code, f"Gemini response did not contain text: {exc}") from exc
            return parse_json_text(text)
        error = parse_llm_error(response, "Gemini")
        last_error = error
        if not should_retry_llm_error(error) or attempt == GEMINI_MAX_RETRIES:
            raise error
        time.sleep(retry_delay(response, attempt))
    if last_error:
        raise last_error
    return None


def fact_check_response_schema() -> dict:
    fact_schema = {
        "type": "OBJECT",
        "properties": {
            "subject": {"type": "STRING"},
            "relationship": {"type": "STRING"},
            "object": {"type": "STRING"},
            "time": {"type": "STRING"},
            "quantity": {"type": "STRING"},
            "qualifiers": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
    }
    return {
        "type": "OBJECT",
        "properties": {
            "verdict": {"type": "STRING", "enum": ["Verified", "Inaccurate", "False"]},
            "confidence": {"type": "STRING", "enum": ["High", "Medium", "Low"]},
            "semantic_relation": {"type": "STRING", "enum": ["entails", "contradicts", "related_mismatch", "no_support"]},
            "claim_fact": fact_schema,
            "evidence_fact": fact_schema,
            "contradictions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "reason": {"type": "STRING"},
            "correct_fact": {"type": "STRING"},
        },
        "required": ["verdict", "confidence", "semantic_relation", "reason", "correct_fact"],
    }


def parse_json_text(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def parse_llm_error(response: requests.Response, provider: str) -> LLMRequestError:
    message = response.text[:500]
    error_type = ""
    error_code = ""
    try:
        payload = response.json()
        error = payload.get("error", {})
        if isinstance(error, dict):
            message = str(error.get("message") or message)
            error_type = str(error.get("type") or "")
            error_code = str(error.get("code") or "")
    except ValueError:
        pass
    err = LLMRequestError(response.status_code, message, error_type, error_code)
    err.provider = provider
    return err


def should_retry_llm_error(error: LLMRequestError) -> bool:
    if error.status_code in {500, 502, 503, 504}:
        return True
    if error.status_code == 429 and error.error_code != "insufficient_quota":
        return True
    return False


def retry_delay(response: requests.Response, attempt: int) -> int:
    retry_after = response.headers.get("retry-after")
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), 8)
    return min(2**attempt, 8)


def verification_worker_count() -> int:
    configured = os.getenv("FACTCHECK_MAX_WORKERS")
    if configured:
        try:
            return max(1, min(4, int(configured)))
        except ValueError:
            pass
    return 1 if llm_available() else 4


def fallback_semantic_judge(claim: Claim, evidence: list[Evidence], signals: dict) -> dict:
    if not evidence:
        return {
            "verdict": "False",
            "confidence": "Low",
            "semantic_relation": "no_support",
            "claim_fact": {},
            "evidence_fact": {},
            "contradictions": ["No live web evidence was returned."],
            "reason": "No evidence was available to support the full claim.",
            "correct_fact": "No supported replacement fact found.",
            "llm_used": False,
        }

    claim_text = claim.text.lower()
    evidence_text = " ".join(item.snippet or item.title for item in evidence).lower()

    world_cup_claim = re.search(r"([a-z .-]+?)\s+won\s+(?:the\s+)?fifa world cup\s+((?:19|20)\d{2})", claim_text)
    world_cup_evidence = re.search(r"([a-z .-]+?)\s+won\s+(?:the\s+)?fifa world cup\s+((?:19|20)\d{2})", evidence_text)
    if world_cup_claim and world_cup_evidence and world_cup_claim.group(2) == world_cup_evidence.group(2):
        claim_winner = normalize_entity(world_cup_claim.group(1))
        evidence_winner = normalize_entity(world_cup_evidence.group(1))
        if claim_winner != evidence_winner:
            return contradiction_result(
                f"The claim says {claim_winner} won the FIFA World Cup {world_cup_claim.group(2)}, but evidence says {evidence_winner} won.",
                f"{evidence_winner.title()} won the FIFA World Cup {world_cup_evidence.group(2)}.",
            )

    founded_claim = re.search(r"([a-z0-9 .&-]+?)\s+was founded in\s+((?:19|20)\d{2})", claim_text)
    founded_evidence = re.search(r"([a-z0-9 .&-]+?)\s+was founded in\s+((?:19|20)\d{2})", evidence_text)
    if founded_claim and founded_evidence:
        claim_entity = normalize_entity(founded_claim.group(1))
        evidence_entity = normalize_entity(founded_evidence.group(1))
        if claim_entity == evidence_entity and founded_claim.group(2) != founded_evidence.group(2):
            return contradiction_result(
                f"The claim says {claim_entity} was founded in {founded_claim.group(2)}, but evidence says {founded_evidence.group(2)}.",
                f"{claim_entity.title()} was founded in {founded_evidence.group(2)}.",
            )

    acquired_claim = re.search(r"([a-z0-9 .&-]+?)\s+acquired\s+([a-z0-9 .&-]+?)\s+in\s+((?:19|20)\d{2})", claim_text)
    acquired_evidence = re.search(
        r"([a-z0-9 .&-]+?)\s+(?:completed\s+(?:its\s+)?)?acquisition of\s+([a-z0-9 .&-]+?)\s+in\s+((?:19|20)\d{2})",
        evidence_text,
    )
    if acquired_claim and acquired_evidence:
        claim_buyer = normalize_entity(acquired_claim.group(1))
        claim_target = normalize_entity(acquired_claim.group(2))
        evidence_buyer = normalize_entity(acquired_evidence.group(1))
        evidence_target = normalize_entity(acquired_evidence.group(2))
        if claim_buyer == evidence_buyer and claim_target == evidence_target and acquired_claim.group(3) == acquired_evidence.group(3):
            return {
                "verdict": "Verified",
                "confidence": "Medium",
                "semantic_relation": "entails",
                "claim_fact": {
                    "subject": claim_buyer,
                    "relationship": "acquired",
                    "object": claim_target,
                    "time": acquired_claim.group(3),
                    "quantity": "",
                    "qualifiers": [],
                },
                "evidence_fact": {
                    "subject": evidence_buyer,
                    "relationship": "completed acquisition of",
                    "object": evidence_target,
                    "time": acquired_evidence.group(3),
                    "quantity": "",
                    "qualifiers": [],
                },
                "contradictions": [],
                "reason": "The evidence semantically states the same acquisition relationship and year.",
                "correct_fact": claim.text,
                "llm_used": False,
            }

    if signals["matched_values"] and len(signals["keyword_overlap"]) >= 3:
        return {
    "verdict": "Inaccurate",
    "confidence": "Low",
    "semantic_relation": "no_support",
    "claim_fact": {},
    "evidence_fact": {},
    "contradictions": [
        "LLM verification unavailable and deterministic semantic verification was insufficient."
    ],
    "reason": "The system could not confidently verify the full semantic meaning of the claim.",
    "correct_fact": "Unable to determine a verified fact from available evidence.",
    "llm_used": False,
}

    return {
        "verdict": "False",
        "confidence": "Low",
        "semantic_relation": "no_support",
        "claim_fact": {},
        "evidence_fact": {},
        "contradictions": ["Fallback verifier could not establish semantic support for the full claim."],
        "reason": "No LLM key is configured, and deterministic contradiction checks did not find enough support.",
        "correct_fact": "No supported replacement fact found.",
        "llm_used": False,
    }


def normalize_entity(value: str) -> str:
    return re.sub(r"\b(the|a|an)\b", "", value.lower()).strip(" .,-")


def contradiction_result(reason: str, correct_fact: str) -> dict:
    return {
        "verdict": "False",
        "confidence": "Medium",
        "semantic_relation": "contradicts",
        "claim_fact": {},
        "evidence_fact": {},
        "contradictions": [reason],
        "reason": reason,
        "correct_fact": correct_fact,
        "llm_used": False,
    }


def validate_judgment(payload: dict, claim: Claim, evidence: list[Evidence], signals: dict) -> dict:
    verdict = str(payload.get("verdict", "False")).strip()
    verdict_map = {"verified": "Verified", "inaccurate": "Inaccurate", "false": "False"}
    verdict = verdict_map.get(verdict.lower(), "False")
    confidence = str(payload.get("confidence", "Low")).strip().title()
    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Low"
    relation = str(payload.get("semantic_relation", "no_support")).strip().lower()
    if relation not in {"entails", "contradicts", "related_mismatch", "no_support"}:
        relation = "no_support"
    if relation in {"contradicts", "no_support"} and verdict == "Verified":
        verdict = "False"
    if relation == "entails" and verdict == "False":
        verdict = "Verified"
    return {
        "verdict": verdict,
        "confidence": confidence,
        "semantic_relation": relation,
        "claim_fact": payload.get("claim_fact") if isinstance(payload.get("claim_fact"), dict) else {},
        "evidence_fact": payload.get("evidence_fact") if isinstance(payload.get("evidence_fact"), dict) else {},
        "contradictions": payload.get("contradictions") if isinstance(payload.get("contradictions"), list) else [],
        "reason": str(payload.get("reason") or "Semantic verification completed."),
        "correct_fact": str(payload.get("correct_fact") or ("No supported replacement fact found." if verdict != "Verified" else claim.text)),
        "llm_used": True,
        "weak_matching_signals": signals,
    }


def infer_verdict(claim: Claim, evidence: list[Evidence]) -> dict:
    signals = semantic_signals(claim, evidence)
    if not evidence:
        return fallback_semantic_judge(claim, evidence, signals) | {"weak_matching_signals": signals}
    try:
        llm_payload = call_llm_json(build_llm_messages(claim, evidence, signals))
        if llm_payload:
            return validate_judgment(llm_payload, claim, evidence, signals)
    except Exception as exc:
        fallback = fallback_semantic_judge(claim, evidence, signals)
        fallback["reason"] = f"Gemini semantic adjudication failed, so fallback checks were used: {human_llm_error(exc)}"
        fallback["llm_error"] = str(exc)
        fallback["weak_matching_signals"] = signals
        return fallback
    return fallback_semantic_judge(claim, evidence, signals) | {"weak_matching_signals": signals}


def verify_claim(claim: Claim) -> dict:
    evidence = search_web(claim.query)
    result = infer_verdict(claim, evidence)
    return {
        "id": claim.id,
        "page": claim.page,
        "claim": claim.text,
        "type": claim.kind,
        "values_found_in_pdf": ", ".join(claim.values),
        "search_query": claim.query,
        **result,
        "sources": evidence,
    }


def serialize_result(result: dict) -> dict:
    return {
        **{key: value for key, value in result.items() if key != "sources"},
        "sources": [asdict(source) if isinstance(source, Evidence) else source for source in result.get("sources", [])],
    }


def human_llm_error(exc: Exception) -> str:
    if isinstance(exc, LLMRequestError):
        if exc.status_code == 429 and exc.error_code == "insufficient_quota":
            return f"{exc.provider} quota or billing limit was reached. Check project usage limits and credits."
        if exc.status_code == 429:
            return f"{exc.provider} rate limit was reached after retries. The app slowed LLM calls, but this key still needs more rate capacity or fewer claims per run."
        if exc.status_code == 401:
            return f"{exc.provider} authentication failed. Check that the provider API key is valid for this Vercel project."
        return exc.describe()
    return str(exc)
