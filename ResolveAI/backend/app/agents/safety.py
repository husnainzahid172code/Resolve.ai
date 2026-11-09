"""Deterministic input handling: order-ID extraction and prompt-injection detection.

Customer text is untrusted. It is (1) scanned for injection patterns, which are
recorded as risk flags, and (2) always passed to the LLM inside a delimited
<customer_message> block that the system prompt declares to be data, not
instructions. Detection is defence-in-depth: even an undetected injection
cannot approve anything, because the LLM has no approval tool and every
proposal goes through the deterministic validator and a human.
"""
from __future__ import annotations

import re

_ORDER_PATTERNS = [
    re.compile(r"\bORD[-\s#]?(\d{4,6})\b", re.IGNORECASE),
    re.compile(r"\border\s*(?:id|number|no\.?|#)?\s*[:#]?\s*(\d{4,6})\b", re.IGNORECASE),
]

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier|your)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|store|your)",
    r"ignore\s+(the\s+)?(store\s+)?polic(y|ies)",
    r"(reveal|show|print)\s+(me\s+)?(your\s+)?(system\s+prompt|instructions)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(an?\s+)?(admin|administrator|developer|system)",
    r"(developer|god|jailbreak|dan)\s+mode",
    r"approve\s+(my|the|this)\s+refund\s+(immediately|now|right\s+away|without)",
    r"override\s+(the\s+)?(policy|policies|rules|system|validation)",
    r"(i\s+am|i'm)\s+(the\s+)?(admin|administrator|manager|owner)\b",
    r"</?\s*(system|assistant|customer_message)\s*>",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def extract_order_ids(text: str) -> list[str]:
    found: list[str] = []
    for pat in _ORDER_PATTERNS:
        for m in pat.finditer(text or ""):
            oid = f"ORD{m.group(1)}"
            if oid not in found:
                found.append(oid)
    return found


def detect_prompt_injection(text: str) -> list[str]:
    return [p.pattern for p in _INJECTION_RE if p.search(text or "")]


def wrap_untrusted(text: str) -> str:
    # neutralise attempts to close the delimiter early
    cleaned = re.sub(r"</?\s*customer_message\s*>", "[removed tag]", text or "", flags=re.IGNORECASE)
    return f"<customer_message>\n{cleaned[:4000]}\n</customer_message>"
