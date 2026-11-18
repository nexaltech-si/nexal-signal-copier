"""
Log monitor endpoints used by the dashboard's /logs page.

The dashboard reads and groups the log files itself (its logs mount is read-only);
these endpoints cover what needs the bot process: sending a digest of issues to the
configured AI provider chain, and deleting/truncating log files.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

logs_router = APIRouter(prefix="/api/logs", tags=["logs"])

LOGS_DIR = Path("logs")
# Any plain .log file in logs/; the date in the name (if any) decides old vs current.
LOG_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.log$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Secrets that must not leave the box inside a log digest.
_REDACTIONS = [
    (re.compile(r"(?i)\bbearer\s+[^\s,'\"}]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(api[ _-]?key|secret|password|token|authorization)(\s*[:=]\s*)([^\s,'\"}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"\b(sk|pk|rk|xox[abp])-[A-Za-z0-9_-]{10,}\b"), "[REDACTED]"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED_BOT_TOKEN]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class IssueDigest(BaseModel):
    id: str
    level: str
    count: int
    firstSeen: str
    lastSeen: str
    sample: str
    samples: List[str] = Field(default_factory=list)
    details: Optional[str] = None
    hint: Optional[str] = None


class AnalyzeRequest(BaseModel):
    issues: List[IssueDigest] = Field(..., min_length=1, max_length=40)
    question: Optional[str] = Field(None, max_length=1000)


ANALYZE_SYSTEM_PROMPT = """You are the on-call engineer for an automated trading bot.
It reads Telegram trading signals, parses them with LLMs (provider fallback chain), and
executes trades on MetaTrader 5 through a REST bridge. A dashboard shows its logs.

You receive grouped log issues (same message, numbers stripped) with counts and samples.
For each real problem: explain the likely cause in plain language and give the concrete
fix the operator should do. Mark harmless noise as such so it can be muted.
Never invent facts not supported by the logs; say when you are unsure.

Reply with JSON only, no prose around it:
{
  "summary": "one or two sentences on overall health",
  "severity": "ok" | "low" | "medium" | "high" | "critical",
  "findings": [
    {
      "title": "short name",
      "issueIds": ["ids of the issues this covers"],
      "cause": "likely cause",
      "fix": "what the operator should do, step by step if needed",
      "urgency": "now" | "soon" | "later" | "noise"
    }
  ]
}"""


def _ai_context(config) -> str:
    from ai.llm_client import provider_chain, build_llm_client_for

    chain = provider_chain(config)
    keyed = [p for p in chain if build_llm_client_for(config, p) is not None]
    return f"AI provider chain (in order): {', '.join(chain) or 'none'}. Providers with an API key configured: {', '.join(keyed) or 'none'}."


def _build_user_prompt(req: AnalyzeRequest, context: str) -> str:
    parts = [f"Context: {context}", f"Now (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}", "", "Issues:"]
    for i in req.issues:
        parts.append(f"- id={i.id} level={i.level} count={i.count} first={i.firstSeen} last={i.lastSeen}")
        if i.hint:
            parts.append(f"  known pattern: {i.hint}")
        for s in (i.samples or [i.sample])[:3]:
            parts.append(f"  sample: {s[:600]}")
        if i.details:
            parts.append("  traceback/details:\n" + "\n".join("    " + l for l in i.details[:2500].splitlines()))
    if req.question:
        parts += ["", f"Operator question: {req.question}"]
    return redact("\n".join(parts))


def _parse_analysis(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict) and "summary" in data:
                data.setdefault("findings", [])
                return data
        except json.JSONDecodeError:
            pass
    return {"summary": text.strip(), "severity": None, "findings": []}


@logs_router.post("/analyze")
async def analyze_logs(req: AnalyzeRequest):
    from ai.llm_client import complete_with_fallback, provider_chain, extract_content, max_tokens_for
    from src.services.signal_service import signal_service

    config = signal_service.ai_config
    user_prompt = _build_user_prompt(req, _ai_context(config))
    used = {}

    def _call(client, model, provider):
        used["provider"], used["model"] = provider, model
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens_for(config, provider, output_tokens=1500),
            timeout=90.0,
        )

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: complete_with_fallback(
                config,
                provider_chain(config),
                _call,
                validate=lambda r: bool(extract_content(r).strip()),
                caller="log_monitor",
            ),
        )
    except Exception as e:
        logger.error(f"❌ Log analysis failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")

    return {
        "provider": used.get("provider"),
        "model": used.get("model"),
        "analysis": _parse_analysis(extract_content(response)),
    }


class ClearRequest(BaseModel):
    scope: Literal["old", "all", "file"]
    file: Optional[str] = None


def _file_date(p: Path) -> Optional[str]:
    m = DATE_RE.search(p.name)
    return m.group(1) if m else None


def _log_files() -> List[Path]:
    if not LOGS_DIR.is_dir():
        return []
    return sorted(p for p in LOGS_DIR.iterdir() if p.is_file() and LOG_FILE_RE.match(p.name))


@logs_router.post("/clear")
async def clear_logs(req: ClearRequest):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    files = _log_files()

    if req.scope == "file":
        if not req.file or not LOG_FILE_RE.match(req.file):
            raise HTTPException(status_code=400, detail="Unknown log file")
        files = [p for p in files if p.name == req.file]
        if not files:
            raise HTTPException(status_code=404, detail="Log file not found")
    elif req.scope == "old":
        files = [p for p in files if (_file_date(p) or today) < today]

    deleted, truncated, freed = [], [], 0
    for p in files:
        size = p.stat().st_size
        if (_file_date(p) or today) >= today:
            # loguru holds today's file open in append mode (and undated files may be
            # open too): truncate in place so new lines keep landing in it, rather
            # than in an unlinked inode.
            with open(p, "r+") as fh:
                fh.truncate(0)
            truncated.append(p.name)
        else:
            p.unlink()
            deleted.append(p.name)
        freed += size

    logger.info(
        f"🧹 Logs cleared from dashboard (scope={req.scope}): "
        f"deleted={len(deleted)} truncated={len(truncated)} freed={freed / 1024:.0f}KB"
    )
    return {"deleted": deleted, "truncated": truncated, "freedBytes": freed}
