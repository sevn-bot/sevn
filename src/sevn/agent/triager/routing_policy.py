"""Deterministic post-decode routing rules (`specs/13-rlm-triager.md`).

Ported utterance families (legacy ``intents.yaml`` / ``fast_mode`` when unavailable):
  - **GREETING / tier A:** hi, hello, thanks, bye, short social openers without questions.
  - **Identity / tier B:** who are you, what can you do, capabilities, model questions.
  - **Anti-echo:** ``first_message`` must not repeat ``current_message`` verbatim.

Module: sevn.agent.triager.routing_policy
Depends: re, sevn.agent.triager.models

Exports:
    apply_routing_policy — coerce tier/intent/first_message after LLM decode.
    try_fast_greeting_triage — optional pre-LLM tier-A synthesis.
    try_fast_continuation_triage — optional pre-LLM replay of prior routing.
    is_strict_greeting_message — greeting detector for fast path.
    classify_greeting — map a strict greeting to hello/thanks/bye.
    is_obvious_continuation_message — short follow-up continuation detector.
    prior_triage_indicates_in_progress — whether prior routing warrants replay.
    is_identity_or_capability_message — informational → tier B detector.
    is_lcm_status_message — LCM status/contents intent detector.
    is_session_recall_message — past-session/conversation recall intent detector.
    is_package_install_message — uv sync / playwright install / option-1 install detector.
    is_playwright_browser_message — screenshot / playwright-browser automation detector.
    is_live_factual_message — live scores, news, weather, schedules detector.
    is_workspace_file_intent_message — workspace markdown read/edit detector.
    is_file_search_intent_message — workspace file content search / grep intent detector (W3).
    is_pdf_file_pipeline_message — PDF render/send/extract multi-step pipeline detector.
    is_repo_code_intent_message — sevn.bot / source_code / gateway source questions.
    is_memorize_message — 'memorize this' / 'remember this' detector.
    is_evolution_fix_intent_message — explicit issue-fix directive detector (FL-4B).
    is_github_repo_eval_intent_message — external GitHub repo evaluate/integrate detector.
    is_registry_capability_intent_message — registry/capability/meta-tool how-to detector.
    is_registry_meta_howto_message — meta-tool how-it-works question detector.
    is_skill_status_intent_message — named-skill status/operational question detector.
    is_log_provenance_intent_message — log/tool-provenance audit question detector.
    resolve_skill_status_target — map a status question to a registry skill id.
    default_early_ack — rotate canned tier B/C/D early ack lines.
    default_tier_a_reply — rotate canned tier-A greeting replies.
    first_message_passes_opener_rule — True when a first_message is a clean opener (W5.1).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Final, Literal

from loguru import logger

from sevn.agent.openers import BARE_OPENERS
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.tier_a_replies import (
    TIER_A_BYE_REPLIES,
    TIER_A_HELLO_REPLIES,
    TIER_A_NAME_PLACEHOLDER,
    TIER_A_THANKS_REPLIES,
    tier_a_bye_generic_replies,
    tier_a_hello_generic_replies,
    tier_a_thanks_generic_replies,
)
from sevn.config.defaults import (
    DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
)
from sevn.prompts.fallbacks import (
    CONTINUATION_MAX_WORDS,
    match_continuation_phrase,
    normalize_short_message,
)

GreetingKind = Literal["hello", "thanks", "bye"]

# Complexity clamp (`specs/13-rlm-triager.md`): a low-confidence C/D decision on a
# short/vague turn is almost always a misroute. MiniMax-M3 in particular routed
# vague follow-ups ("all this needs to be fixed", "so?") to C with confidence 0.78,
# and the C/D decompose contract then failed to parse, surfacing a raw planner error.
# Below this confidence, a short message (or a FOLLOWUP with no concrete task) clamps
# down to tier B, which answers directly without the structured-plan contract.
# Configurable via ``triager.complexity_clamp_*`` in ``sevn.json``.
COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD: Final[float] = DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
COMPLEXITY_CLAMP_SHORT_WORD_LIMIT: Final[int] = DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT

# Tier-A canned replies — strict greetings/thanks/bye only (rotate by turn_id hash).
# Category pools live in ``tier_a_replies.py`` (hello 100, bye 50, thanks 25).
_TIER_A_HELLO_REPLIES: Final[tuple[str, ...]] = TIER_A_HELLO_REPLIES
_TIER_A_BYE_REPLIES: Final[tuple[str, ...]] = TIER_A_BYE_REPLIES
_TIER_A_THANKS_REPLIES: Final[tuple[str, ...]] = TIER_A_THANKS_REPLIES
_TIER_A_HELLO_GENERIC_REPLIES: Final[tuple[str, ...]] = tier_a_hello_generic_replies
_TIER_A_BYE_GENERIC_REPLIES: Final[tuple[str, ...]] = tier_a_bye_generic_replies
_TIER_A_THANKS_GENERIC_REPLIES: Final[tuple[str, ...]] = tier_a_thanks_generic_replies
_TIER_A_NAME_MAX_LEN: Final[int] = 32
_TIER_A_FIRST_MESSAGE_MAX_LEN: Final[int] = 100

# Early ack lines for B/C/D (rotate by turn_id).
# W5.2: none of these may start with a prefix in :data:`sevn.agent.openers.BARE_OPENERS`.
# Any entry that violates this rule trains both the model and the operator to expect bad
# openers, and the harness's opener-only guard can classify our own ack as a "no answer"
# output.
_EARLY_ACKS: Final[tuple[str, ...]] = (
    "Hmm, interesting…",
    "Reading now…",
    "A moment…",
    "Right with you…",
)

_FIRST_SESSION_ACKS: Final[tuple[str, ...]] = (
    "Hey — give me a moment to introduce myself…",
    "Hi! Let me tell you a bit about who I am…",
)

_REGISTRY_META_HOWTO_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(how does|how do|what is|what's|explain|how to use)\b.+\b"
        r"(list_?registry|load_tool|load_skill|request_escalation)\b",
        re.I,
    ),
    re.compile(
        r"\b(list_?registry|load_tool|load_skill|request_escalation)\b.+\bwork\b",
        re.I,
    ),
)

_REGISTRY_CAPABILITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    *_REGISTRY_META_HOWTO_PATTERNS,
    re.compile(r"\b(registry|callable tools?|available tools?)\b", re.I),
    re.compile(r"\blist_?registry\b", re.I),
    re.compile(r"\b(do you have|can you|are you able to)\b", re.I),
)

_REGISTRY_CAPABILITY_TOOL_IDS: Final[tuple[str, ...]] = ("list_registry",)
_REGISTRY_META_HOWTO_READ_TOOL_IDS: Final[tuple[str, ...]] = ("read",)

_IDENTITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*who\s+are\s+you\b", re.I),
    re.compile(r"^\s*what\s+are\s+you\b", re.I),
    re.compile(r"^\s*what('s|\s+is)\s+your\s+name\b", re.I),
    re.compile(r"^\s*what\s+can\s+you\s+do\b", re.I),
    re.compile(r"^\s*what\s+do\s+you\s+do\b", re.I),
    re.compile(r"^\s*list\s+(your\s+)?(tools|skills)\b", re.I),
    re.compile(r"^\s*what\s+(tools|skills)\b", re.I),
    re.compile(r"^\s*which\s+model\b", re.I),
    # "which LLM model are you using?", "what model are you using?", "what llm are you"
    # — anchored on you/your so model-*choice* questions ("which model should I use?") miss.
    re.compile(
        r"^\s*(which|what)\s+(?:llm\s+|ai\s+|language\s+)?models?\b.*\byou(?:'?re|r)?\b", re.I
    ),
    re.compile(r"^\s*(which|what)\s+llm\b.*\byou(?:'?re|r)?\b", re.I),
    re.compile(r"^\s*introduce\s+yourself\b", re.I),
    re.compile(r"^\s*tell\s+me\s+about\s+yourself\b", re.I),
)

_GREETING_PATTERN_KINDS: Final[tuple[tuple[re.Pattern[str], GreetingKind], ...]] = (
    (re.compile(r"^\s*(hi|hello|hey|hiya|howdy|yo|sup)\b[!.,?\s]*$", re.I), "hello"),
    (re.compile(r"^\s*(good\s+)?(morning|afternoon|evening|night)\b[!.,?\s]*$", re.I), "hello"),
    (re.compile(r"^\s*(thanks|thank\s+you|thx|ty)\b[!.,?\s]*$", re.I), "thanks"),
    (re.compile(r"^\s*(bye|goodbye|see\s+ya|cya)\b[!.,?\s]*$", re.I), "bye"),
    (re.compile(r"^\s*bonjour\b[!.,?\s]*$", re.I), "hello"),
    (re.compile(r"^\s*hol+a\b[!.,?\s]*$", re.I), "hello"),
)

_GREETING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    pattern for pattern, _kind in _GREETING_PATTERN_KINDS
)

_EMOJI_ONLY: Final[re.Pattern[str]] = re.compile(
    r"^[\s\U0001F300-\U0001FAFF\U00002600-\U000027BF]+$",
)

# Base exact-token greeting/ack allowlist (`specs/13-rlm-triager.md`). Elongations
# ("helloo", "heyyy", "thanksss") match via :func:`_normalize_greeting_token` (D5)
# instead of enumerating every variant. Regex ``_GREETING_PATTERNS`` still catch
# phrase-shaped greetings the token set does not cover.
#
# Matching is exact against the *normalised* whole message — punctuation-trimmed,
# lowercased, internal whitespace collapsed — so only a message that is ENTIRELY one
# of these tokens fast-paths. Follow-ups/continuations are deliberately absent:
# "so" / "so?" is a follow-up prompt, never a greeting, and multi-word phrases like
# "ok now I see it" never normalise to a single allowlisted token.
_GREETING_HELLO_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "hi",
        "hello",
        "helo",
        "hey",
        "hiya",
        "howdy",
        "yo",
        "sup",
        "hallo",
        "bonjour",
        "hola",
        "holla",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "morning",
        "afternoon",
        "evening",
        "night",
    },
)
_GREETING_THANKS_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "okay",
        "k",
        "got it",
        "gotcha",
        "noted",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "merci",
        "gracias",
    },
)
_GREETING_BYE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "bye",
        "goodbye",
        "cya",
        "see ya",
    },
)
_GREETING_ACK_TOKENS: Final[frozenset[str]] = (
    _GREETING_HELLO_TOKENS | _GREETING_THANKS_TOKENS | _GREETING_BYE_TOKENS
)
_TOKEN_TO_GREETING_KIND: Final[dict[str, GreetingKind]] = {
    **{token: "hello" for token in _GREETING_HELLO_TOKENS},
    **{token: "thanks" for token in _GREETING_THANKS_TOKENS},
    **{token: "bye" for token in _GREETING_BYE_TOKENS},
}

# Tokens that look like the above but are follow-ups/continuations — never greeting-pathed.
# Kept explicit as a guard so an allowlist edit can't accidentally swallow them.
_GREETING_ACK_DENYLIST: Final[frozenset[str]] = frozenset({"so", "and", "but", "then", "now"})

# Short follow-up continuations when a prior turn already routed to tier B/C/D.
# Phrase set lives in ``sevn.prompts.fallbacks.CONTINUATION_PHRASES``.
_CONTINUATION_MAX_WORDS: Final[int] = CONTINUATION_MAX_WORDS


def _normalize_short_message(text: str) -> str:
    """Return a punctuation-trimmed, lowercased message key for token matching.

    Delegates to :func:`sevn.prompts.fallbacks.normalize_short_message`.

    Args:
        text (str): Raw user message.

    Returns:
        str: Normalised comparison key (may be empty).

    Examples:
        >>> _normalize_short_message("  So?  ")
        'so'
        >>> _normalize_short_message("Go Ahead!!")
        'go ahead'
    """
    return normalize_short_message(text)


_TRAILING_ELONGATION: Final[re.Pattern[str]] = re.compile(r"(.)\1{2,}$")


def _normalize_greeting_token(text: str) -> str:
    """Collapse elongated spellings before greeting token lookup (D5).

      Repeatedly collapses 3+ identical trailing letters to one, then peels a
    single trailing duplicate when that yields a known base token (``helloo`` →
      ``hello``, ``hii`` → ``hi``).

      Args:
          text (str): Normalised whole-message token (lowercased, trimmed).

      Returns:
          str: Token ready for allowlist lookup.

      Examples:
          >>> _normalize_greeting_token("heyyy")
          'hey'
          >>> _normalize_greeting_token("thanksss")
          'thanks'
          >>> _normalize_greeting_token("helloo")
          'hello'
          >>> _normalize_greeting_token("yoyo")
          'yo'
    """
    token = text
    prev = ""
    while prev != token:
        prev = token
        token = _TRAILING_ELONGATION.sub(r"\1", token)
    if token in _GREETING_ACK_TOKENS:
        return token
    if len(token) >= 2 and token[-1] == token[-2]:
        shortened = token[:-1]
        if shortened in _GREETING_ACK_TOKENS:
            return shortened
    # Reduplicated greetings ("yoyo", "hihi", "heyhey", "byebye") collapse to their base
    # token so they fast-path like the single form instead of missing the greeting allowlist,
    # invoking the Triager model (~8 s), and then being escalated to tier B by the scope guard.
    if len(token) % 2 == 0 and len(token) >= 2:
        half = len(token) // 2
        first_half = token[:half]
        if first_half == token[half:] and first_half in _GREETING_ACK_TOKENS:
            return first_half
    return token


def _greeting_ack_token(text: str) -> str | None:
    """Return the normalised whole-message token when it is a known greeting/ack.

    Strips surrounding punctuation/whitespace and lowercases; returns the token only
    when the ENTIRE message reduces to a single :data:`_GREETING_ACK_TOKENS` entry and
    is not on :data:`_GREETING_ACK_DENYLIST`. Follow-ups ("so?", "ok now I see it")
    return ``None``.

    Args:
        text (str): Raw user message.

    Returns:
        str | None: The matched allowlist token, else ``None``.

    Examples:
        >>> _greeting_ack_token("helloo")
        'hello'
        >>> _greeting_ack_token("THANKS!!")
        'thanks'
        >>> _greeting_ack_token("so?") is None
        True
        >>> _greeting_ack_token("ok now I see it") is None
        True
    """
    norm = _normalize_short_message(text)
    if not norm or norm in _GREETING_ACK_DENYLIST:
        return None
    canonical = _normalize_greeting_token(norm)
    return canonical if canonical in _GREETING_ACK_TOKENS else None


def classify_greeting(message: str) -> GreetingKind | None:
    """Map a strict greeting/ack/closer message to its tier-A reply category.

    Args:
        message (str): Raw user message (locale prefix already stripped by caller
            when used from :func:`is_strict_greeting_message`).

    Returns:
        GreetingKind | None: ``hello``, ``thanks``, or ``bye`` when matched.

    Examples:
        >>> classify_greeting("hi")
        'hello'
        >>> classify_greeting("thanks")
        'thanks'
        >>> classify_greeting("bye")
        'bye'
        >>> classify_greeting("heyyy")
        'hello'
        >>> classify_greeting("who are you?") is None
        True
    """
    text = message.strip()
    if not text:
        return None
    token = _greeting_ack_token(text)
    if token is not None:
        return _TOKEN_TO_GREETING_KIND[token]
    for pattern, kind in _GREETING_PATTERN_KINDS:
        if pattern.match(text):
            return kind
    return None


def _continuation_phrase(text: str) -> str | None:
    """Return the normalised phrase when the message is an obvious continuation.

    Delegates to :func:`sevn.prompts.fallbacks.match_continuation_phrase`.

    Args:
        text (str): Raw user message.

    Returns:
        str | None: Matched continuation phrase, else ``None``.

    Examples:
        >>> _continuation_phrase("so?")
        'so'
        >>> _continuation_phrase("go ahead")
        'go ahead'
        >>> _continuation_phrase("try again!")
        'try again'
        >>> _continuation_phrase("ok now I see it") is None
        True
    """
    return match_continuation_phrase(text)


_FILE_INTENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bUSER\.md\b", re.I),
    re.compile(r"\bMEMORY\.md\b", re.I),
    re.compile(r"\bIDENTITY\.md\b", re.I),
    re.compile(r"\bSOUL\.md\b", re.I),
    re.compile(r"\bTOOLS\.md\b", re.I),
    re.compile(r"\bBOOTSTRAP\.md\b", re.I),
    re.compile(r"\bread\s+.+\.(?:md|txt|json|ya?ml)\b", re.I),
    re.compile(r"\bwrite\s+to\s+.+\.(?:md|txt)\b", re.I),
)

_FILE_SEARCH_INTENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bsearch(?:ing)?\b.+\b(?:file|markdown|md|workspace|folder|directory)\b", re.I),
    re.compile(
        r"\b(?:grep|find|look)\b.+\b(?:in|through|across)\b.+\b(?:file|markdown|md|workspace)\b",
        re.I,
    ),
    re.compile(r"\bsearch_in_file\b", re.I),
    re.compile(r"\b(?:markdown|file|md|workspace)\b.+\b(?:for|containing)\b", re.I),
    re.compile(r"\b(?:for|containing)\b.+\b(?:markdown|file|md|workspace)\b", re.I),
)

_FILE_OPS_TOOL_IDS: Final[tuple[str, ...]] = ("read", "edit", "write")
_FILE_PIPELINE_TOOL_IDS: Final[tuple[str, ...]] = (
    "glob",
    "search_in_file",
    "find_file",
    "file_info",
    "get_page_content",
    "terminal_run",
    "sandbox_exec",
)
_PDF_FILE_PIPELINE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\brender\b.+\b(markdown|md|html|page|article)\b", re.I),
    re.compile(r"\b(convert|extract|export|save)\b.+\b(pdf|markdown|md|page|article)\b", re.I),
    re.compile(r"\b(send|deliver)\b.+\b(file|pdf|document|attachment)\b", re.I),
    re.compile(r"\bget_page_content\b", re.I),
    re.compile(r"\brun_skill_script\b.+\bpdf\b", re.I),
)
_REPO_FILE_OPS_TOOL_IDS: Final[tuple[str, ...]] = (
    "read",
    "glob",
    "list_dir",
    "search_in_file",
    "find_file",
    "get_module_docstring",
    "get_symbol_docstring",
    "list_symbols",
)
_REPO_CODE_INTENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bsevn\.bot\b", re.I),
    re.compile(r"\bsource_code/", re.I),
    re.compile(r"\bsource\s+code\b", re.I),
    re.compile(r"\babout-sevn\.bot\b", re.I),
    re.compile(r"\brepo\s+root\b", re.I),
    re.compile(r"\bfolders?\s+on\s+(the\s+)?root\b", re.I),
    # W4: specific self-architecture phrases (trimmed generics from grounding markers).
    re.compile(r"\bwhere\s+(is|are)\s+the\s+code\s+for\b", re.I),
    re.compile(r"\bcode\s+for\s+cron\b", re.I),
    re.compile(r"\bcron\s+code\b", re.I),
    re.compile(r"\bhow\s+does\s+the\s+gateway\b", re.I),
    re.compile(r"\bhow\s+do\s+you\s+dispatch\b", re.I),
    re.compile(r"\byour\s+architecture\b", re.I),
)

_MEMORIZE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bmemorize\s+(this|that)\b", re.I),
    re.compile(r"\bremember\s+(this|that)\b", re.I),
    re.compile(r"\bnote\s+(this|that)\b", re.I),
    re.compile(r"\bsave\s+(this|that)\s+(to|in)\s+memory\b", re.I),
)

_LCM_STATUS_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bwhat('?s|\s+is)\s+in\s+your\s+lcm\b", re.I),
    re.compile(r"\blcm\s+status\b", re.I),
    re.compile(r"\bshow\s+(me\s+)?(your\s+)?lcm\b", re.I),
    re.compile(r"\bstatus\s+of\s+(your\s+)?lcm\b", re.I),
)

_SESSION_RECALL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bwhat\s+did\s+we\s+(talk|chat|discuss|cover|say|do|work)\b", re.I),
    re.compile(r"\bwhat\s+(?:were|was)\s+we\s+(talking|working|discussing)\b", re.I),
    re.compile(r"\b(last|previous|earlier|prior|recent)\s+(session|conversation|chat)\b", re.I),
    re.compile(r"\bour\s+(?:last|previous|recent|earlier)?\s*(conversation|chat|session)\b", re.I),
    re.compile(
        r"\b(recall|remind\s+me\s+(?:about|what)|summari[sz]e)\b.{0,40}\b(conversation|session|chat|we\s+(?:talked|discussed))\b",
        re.I,
    ),
    re.compile(r"\bwhat\s+did\s+(?:i|you)\s+say\s+(?:earlier|before|last)\b", re.I),
)

_SKILL_STATUS_PHRASE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bwhat(?:'s|\s+is)\s+", re.I),
    re.compile(r"\bwhat\s+does\b.+\bdo\b", re.I),
    re.compile(r"\bis\b.+\boperational\b", re.I),
)

_SKILL_STATUS_TOOL_IDS: Final[tuple[str, ...]] = (
    "list_registry",
    "load_skill",
    "read",
    "search_in_file",
    "run_skill_script",
)

_LOG_PROVENANCE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bcheck\s+(your|the)\s+logs\b", re.I),
    re.compile(r"\blook\s+at\s+(your|the|gateway)\s+log", re.I),
    re.compile(r"\bwhat\s+tools?\s+(and\s+skills?\s+)?(did\s+you|were)\s+use", re.I),
    re.compile(r"\bwhich\s+tools?\s+(did\s+you|were)\s+use", re.I),
    re.compile(r"\bwhich\s+source\b", re.I),
    re.compile(r"\btools?\s+and\s+skills?\s+were\s+used\b", re.I),
    re.compile(r"\bwhat\s+did\s+you\s+use\s+for\b", re.I),
    re.compile(r"\bwhat\s+(tool|source)\s+did\s+you\s+use\b", re.I),
)

_LOG_PROVENANCE_TOOL_IDS: Final[tuple[str, ...]] = (
    "log_query",
    "read_transcript",
)

_PACKAGE_INSTALL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\buv\s+sync\b", re.I),
    re.compile(r"\bplaywright\s+install\b", re.I),
    re.compile(r"\bpip\s+install\b", re.I),
    re.compile(r"\bnpm\s+install\b", re.I),
    re.compile(r"\binstall\s+(playwright|chromium|browser\s+extra)\b", re.I),
    re.compile(r"\boption\s+1\b", re.I),
    re.compile(r"\b(install|sync)\b.+\b(browser|playwright|chromium)\b", re.I),
)

_PLAYWRIGHT_BROWSER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bscreenshot\b.+\b(url|page|http|https)\b", re.I),
    re.compile(r"\b(take|get|capture)\b.+\bscreenshot\b", re.I),
    re.compile(r"\bsearch\s+\S+\.(?:com|org|net)\b", re.I),
    re.compile(r"\b(?:nba|espn)\.com\b", re.I),
)

_LIVE_FACTUAL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:nba|nfl|mlb|nhl|soccer|football)\b.+\b(?:score|finals|playoffs?|schedule)\b", re.I
    ),
    re.compile(r"\b(?:score|finals|playoffs?|schedule)\b.+\b(?:nba|nfl|mlb|nhl)\b", re.I),
    re.compile(r"\b(?:weather|forecast|temperature)\b", re.I),
    re.compile(r"\b(?:headline|breaking)\s+news\b", re.I),
    re.compile(r"\bnews\b.+\b(?:today|now|latest)\b", re.I),
    re.compile(r"\b(?:stock|share)\s+price\b", re.I),
    re.compile(r"\b(?:today|now|current|live)\b.+\b(?:score|schedule|price|weather)\b", re.I),
    re.compile(r"\bwhat(?:'s| is)\s+the\s+(?:score|weather|price)\b", re.I),
)

_LIVE_FACTUAL_TOOL_IDS: Final[tuple[str, ...]] = ("get_page_content", "serp")

_PACKAGE_INSTALL_TOOL_IDS: Final[tuple[str, ...]] = ("process",)
_PLAYWRIGHT_BROWSER_TOOL_IDS: Final[tuple[str, ...]] = (
    "browser",
    "load_tool",
    "send_file",
)

# FL-4B.3: Evolution issue-fix intent detector.
# Matches explicit phrases like "fix issue #42", "fix evolution abc-1", "implement feature abc-2".
# These phrases force tier-B with the pinned evolution bundle (L5).
# The pattern is intentionally narrow — generic repo-code intent (is_repo_code_intent_message)
# covers broader coding questions; this only fires on an explicit issue-fix directive.
_GITHUB_REPO_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"https?://github\.com/[\w.-]+/[\w.-]+",
    re.I,
)
_GITHUB_REPO_EVAL_INTENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(check|evaluat|review|inspect|look\s+at)\b", re.I),
    re.compile(r"\b(integrat|adopt|skill|incorporat)\b", re.I),
    re.compile(r"\bcan\s+it\s+be\b", re.I),
    re.compile(r"\bshould\s+we\b", re.I),
    re.compile(r"\bworth\b", re.I),
)
_GITHUB_REPO_EVAL_TOOL_IDS: Final[tuple[str, ...]] = (
    "terminal_run",
    "read",
    "glob",
    "list_dir",
    "search_in_file",
    "get_page_content",
    "load_skill",
    "run_skill_script",
    "process",
)
_GITHUB_REPO_EVAL_SKILL_IDS: Final[tuple[str, ...]] = ("skill_management",)

_EVOLUTION_FIX_INTENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bfix\s+(github\s+)?issue\s+#?\d+\b", re.I),
    re.compile(r"\bfix\s+evolution\s+\S+\b", re.I),
    re.compile(r"\bimplement\s+(feature|issue)\s+\S+\b", re.I),
    re.compile(r"\bwork\s+on\s+(issue|bug|feature)\s+#?\S+\b", re.I),
    re.compile(r"\bimplement\s+#?\d+\b", re.I),
)

# Pinned evolution tool bundle (same set as FL-4A local implement; L5).
_EVOLUTION_TOOL_IDS: Final[tuple[str, ...]] = (
    "read",
    "edit",
    "write",
    "glob",
    "grep",
    "sandbox_exec",
    "terminal_run",
    "run_skill_script",
    "integration_call",
)


def _normalize(text: str) -> str:
    """Lowercase-stripped comparison key for echo detection.

    Args:
        text (str): Raw user or assistant text.

    Returns:
        str: Whitespace-normalized lowercase string.

    Examples:
        >>> _normalize("  Who   Are You? ")
        'who are you?'
    """
    return " ".join(text.strip().lower().split())


def _normalize_operator_name(operator_name: str | None) -> str | None:
    """Return a trimmed operator name suitable for tier-A greeting interpolation.

    Args:
        operator_name (str | None): Preferred name from ``USER.md``.

    Returns:
        str | None: Non-empty name, or ``None`` when unset/blank.

    Examples:
        >>> _normalize_operator_name("  Alex  ")
        'Alex'
        >>> _normalize_operator_name("   ") is None
        True
    """
    if operator_name is None:
        return None
    stripped = operator_name.strip()
    return stripped or None


def _format_tier_a_reply(template: str, *, operator_name: str | None) -> str:
    """Materialize one tier-A template, substituting ``{name}`` when present.

    Args:
        template (str): Selected canned reply template.
        operator_name (str | None): Resolved ``USER.md`` name.

    Returns:
        str: Final one-line greeting (never leaves ``{name}`` unresolved).

    Examples:
        >>> _format_tier_a_reply("Hi {name}!", operator_name="Alex")
        'Hi Alex!'
        >>> _format_tier_a_reply("Hey there!", operator_name=None)
        'Hey there!'
    """
    if TIER_A_NAME_PLACEHOLDER not in template:
        return template
    name = _normalize_operator_name(operator_name)
    if name is None:
        return template.replace(TIER_A_NAME_PLACEHOLDER, "").replace("  ", " ").strip(" ,—-")
    clipped = name[:_TIER_A_NAME_MAX_LEN]
    rendered = template.format(name=clipped)
    if len(rendered) <= _TIER_A_FIRST_MESSAGE_MAX_LEN:
        return rendered
    overflow = len(rendered) - _TIER_A_FIRST_MESSAGE_MAX_LEN
    shorter = clipped[: max(1, len(clipped) - overflow)]
    return template.format(name=shorter)


def _pick_rotated(options: tuple[str, ...], *, seed: str) -> str:
    """Pick a stable canned line from ``options`` using ``seed``.

    Args:
        options (tuple[str, ...]): Candidate reply strings.
        seed (str): Hash input for deterministic rotation.

    Returns:
        str: Selected line, or ``""`` when ``options`` is empty.

    Examples:
        >>> _pick_rotated(("a", "b"), seed="x")
        'a'
        >>> _pick_rotated((), seed="x")
        ''
    """
    if not options:
        return ""
    idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(options)
    return options[idx]


def is_identity_or_capability_message(message: str) -> bool:
    """Return True when the user asks about the bot (tier B, not greeting A).

    Args:
        message (str): Current user message.

    Returns:
        bool: True for identity/capability questions.

    Examples:
        >>> is_identity_or_capability_message("who are you?")
        True
        >>> is_identity_or_capability_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _IDENTITY_PATTERNS)


def is_repo_code_intent_message(message: str) -> bool:
    """Return True when the user asks about sevn.bot package source or ``source_code/`` paths.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for gateway/source/about-sevn.bot style questions.

    Examples:
        >>> is_repo_code_intent_message("list folders on the sevn.bot repo root")
        True
        >>> is_repo_code_intent_message("where is the code for cron?")
        True
        >>> is_repo_code_intent_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _REPO_CODE_INTENT_PATTERNS)


def is_memorize_message(message: str) -> bool:
    """Return True when the user wants something appended to MEMORY.md.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for 'memorize this', 'remember this', 'note this', etc.

    Examples:
        >>> is_memorize_message("Memorize this: I prefer ls.")
        True
        >>> is_memorize_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _MEMORIZE_PATTERNS)


def _normalize_skill_slug(token: str) -> str:
    """Collapse hyphens/underscores for skill-name matching in user text.

    Args:
        token (str): Raw skill id or user fragment.

    Returns:
        str: Lowercase slug without ``-`` or ``_``.

    Examples:
        >>> _normalize_skill_slug("last-30-days")
        'last30days'
    """
    return re.sub(r"[-_]", "", token.strip().lower())


def resolve_skill_status_target(
    message: str,
    *,
    indexed_skill_ids: frozenset[str],
    triage_skills: Sequence[str],
) -> str | None:
    """Return the skill id for a status/operational question when recognized.

    Args:
        message (str): Current user message.
        indexed_skill_ids (frozenset[str]): Registry skill ids for this session.
        triage_skills (Sequence[str]): Triager-selected skill ids for this turn.

    Returns:
        str | None: Canonical skill id when the message names a known skill.

    Examples:
        >>> ids = frozenset({"last30days", "pdf"})
        >>> resolve_skill_status_target(
        ...     "what is last30days?",
        ...     indexed_skill_ids=ids,
        ...     triage_skills=[],
        ... )
        'last30days'
    """
    text = message.strip()
    if not text:
        return None
    known = sorted(set(indexed_skill_ids) | set(triage_skills), key=len, reverse=True)
    compact = _normalize_skill_slug(text)
    for skill_id in known:
        if _normalize_skill_slug(skill_id) in compact:
            return skill_id
    if re.search(r"\bis\s+it\s+operational\b", text, re.I) and len(triage_skills) == 1:
        return triage_skills[0]
    return None


def is_log_provenance_intent_message(message: str) -> bool:
    """Return True when the user audits tool/source use for a prior answer.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for log-provenance audit phrases (usually FOLLOWUP).

    Examples:
        >>> is_log_provenance_intent_message(
        ...     "check your logs, what tool did you use and which source?"
        ... )
        True
        >>> is_log_provenance_intent_message("NBA finals score")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _LOG_PROVENANCE_PATTERNS)


def is_skill_status_intent_message(
    message: str,
    *,
    indexed_skill_ids: frozenset[str],
    triage_skills: Sequence[str],
) -> bool:
    """Return True when the user asks about a named skill's purpose or operational status.

    Args:
        message (str): Current user message.
        indexed_skill_ids (frozenset[str]): Registry skill ids for this session.
        triage_skills (Sequence[str]): Triager-selected skill ids for this turn.

    Returns:
        bool: True when a known skill is named in a status-style question.

    Examples:
        >>> is_skill_status_intent_message(
        ...     "what is last30days? is it operational?",
        ...     indexed_skill_ids=frozenset({"last30days"}),
        ...     triage_skills=["last30days"],
        ... )
        True
        >>> is_skill_status_intent_message(
        ...     "how does list_registry work?",
        ...     indexed_skill_ids=frozenset({"last30days"}),
        ...     triage_skills=[],
        ... )
        False
    """
    if is_identity_or_capability_message(message) or is_registry_capability_intent_message(
        message,
    ):
        return False
    if (
        resolve_skill_status_target(
            message,
            indexed_skill_ids=indexed_skill_ids,
            triage_skills=triage_skills,
        )
        is None
    ):
        return False
    return any(p.search(message) for p in _SKILL_STATUS_PHRASE_PATTERNS)


def is_lcm_status_message(message: str) -> bool:
    """Return True when the user asks for LCM status/contents.

    Args:
        message (str): Current user message.

    Returns:
        bool: True when LCM status phrases appear.

    Examples:
        >>> is_lcm_status_message("What's in your LCM?")
        True
        >>> is_lcm_status_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _LCM_STATUS_PATTERNS)


def is_session_recall_message(message: str) -> bool:
    """Return True when the user asks to recall a past session / conversation.

    Recall questions ("what did we talk about in the last session?", "summarize our
    conversation") must bind the reliable recall surface (``history`` first, with
    ``memory_search`` + the ``lcm`` skill as backups) instead of leaving the triager LLM to
    pick the lower-level memory/LCM path, which it tends to call with invalid arguments
    (transcript-review-2026-06-22).

    Args:
        message (str): Current user message.

    Returns:
        bool: True when a session-recall phrase appears.

    Examples:
        >>> is_session_recall_message("what did we talk about in the last session?")
        True
        >>> is_session_recall_message("summarize our conversation")
        True
        >>> is_session_recall_message("what's the weather?")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _SESSION_RECALL_PATTERNS)


def is_registry_meta_howto_message(message: str) -> bool:
    """Return True when the user asks how a meta tool works.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for meta-tool how-to questions.

    Examples:
        >>> is_registry_meta_howto_message("how does listregistry work?")
        True
        >>> is_registry_meta_howto_message("what is load_tool")
        True
        >>> is_registry_meta_howto_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _REGISTRY_META_HOWTO_PATTERNS)


def is_registry_capability_intent_message(message: str) -> bool:
    """Return True for registry, capability, or meta-tool inventory questions.

    Excludes repo-code and live-factual intents so those routers keep their pins.

    Args:
        message (str): Current user message.

    Returns:
        bool: True when ``list_registry`` should be triager-bound.

    Examples:
        >>> is_registry_capability_intent_message("how does listregistry work?")
        True
        >>> is_registry_capability_intent_message("do you have a pdf skill?")
        True
        >>> is_registry_capability_intent_message("where is the code for cron?")
        False
        >>> is_registry_capability_intent_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    if is_repo_code_intent_message(text) or is_live_factual_message(text):
        return False
    return any(p.search(text) for p in _REGISTRY_CAPABILITY_PATTERNS)


def is_github_repo_eval_intent_message(message: str) -> bool:
    """Return True when the user shares a GitHub repo URL to evaluate or integrate.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for evaluate/integrate/skill-fit questions about an external repo.

    Examples:
        >>> msg = "Check https://github.com/VectifyAI/PageIndex — integrate as a skill?"
        >>> is_github_repo_eval_intent_message(msg)
        True
        >>> is_github_repo_eval_intent_message("https://github.com/foo/bar")
        False
        >>> is_github_repo_eval_intent_message("hello")
        False
    """
    text = message.strip()
    if not text or _GITHUB_REPO_URL_RE.search(text) is None:
        return False
    return any(p.search(text) for p in _GITHUB_REPO_EVAL_INTENT_PATTERNS)


def is_evolution_fix_intent_message(message: str) -> bool:
    """Return True when the user gives an explicit issue-fix / implement directive (FL-4B).

    Matches phrases like "fix issue #42", "fix evolution abc-1", "implement feature abc-2",
    "work on bug abc-3".  Intentionally **narrow** — generic "fix the bug in my code"
    questions are NOT matched here (those hit ``is_repo_code_intent_message`` instead).

    When True, ``apply_routing_policy`` forces tier-B with the pinned evolution bundle
    (``_merge_evolution_tools``) so ``gh-pr``/file-ops survive any subsequent B→C escalation.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for explicit issue-fix directives only.

    Examples:
        >>> is_evolution_fix_intent_message("fix issue #42")
        True
        >>> is_evolution_fix_intent_message("fix evolution abc-123")
        True
        >>> is_evolution_fix_intent_message("implement feature xyz-1")
        True
        >>> is_evolution_fix_intent_message("implement #99")
        True
        >>> is_evolution_fix_intent_message("fix the general bug in my code")
        False
        >>> is_evolution_fix_intent_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _EVOLUTION_FIX_INTENT_PATTERNS)


def is_pdf_file_pipeline_message(message: str) -> bool:
    """Return True when the user wants a PDF/file produce-send pipeline (P3).

    Args:
        message (str): Current user message.

    Returns:
        bool: True for render-to-PDF, extract-page, or send-file intents.

    Examples:
        >>> is_pdf_file_pipeline_message("extract the Wikipedia page into a PDF and send it")
        True
        >>> is_pdf_file_pipeline_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _PDF_FILE_PIPELINE_PATTERNS)


def is_workspace_file_intent_message(message: str) -> bool:
    """Return True when the user asks to read or edit workspace markdown files.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for USER.md-style paths or explicit read/edit file requests.

    Examples:
        >>> is_workspace_file_intent_message("read USER.md and fix my name")
        True
        >>> is_workspace_file_intent_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _FILE_INTENT_PATTERNS)


def is_file_search_intent_message(message: str) -> bool:
    """Return True when the user asks to search file contents (W3 / msg=816cba).

    Args:
        message (str): Current user message.

    Returns:
        bool: True for workspace/markdown file search or grep-style requests.

    Examples:
        >>> is_file_search_intent_message("search markdown for temperature")
        True
        >>> is_file_search_intent_message("run uv sync")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _FILE_SEARCH_INTENT_PATTERNS)


def is_package_install_message(message: str) -> bool:
    """Return True when the user wants a long non-interactive install/sync command.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for ``uv sync``, ``playwright install``, or similar.

    Examples:
        >>> is_package_install_message("do option 1")
        True
        >>> is_package_install_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _PACKAGE_INSTALL_PATTERNS)


def is_playwright_browser_message(message: str) -> bool:
    """Return True when the user wants playwright-browser automation or screenshots.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for screenshot/navigation intents via the browser skill.

    Examples:
        >>> is_playwright_browser_message("get a screenshot of https://example.com")
        True
        >>> is_playwright_browser_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _PLAYWRIGHT_BROWSER_PATTERNS)


def is_live_factual_message(message: str) -> bool:
    """Return True when the user asks for live/current factual web information.

    Args:
        message (str): Current user message.

    Returns:
        bool: True for scores, schedules, news, weather, or price intents.

    Examples:
        >>> is_live_factual_message("NBA finals score")
        True
        >>> is_live_factual_message("hello")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _LIVE_FACTUAL_PATTERNS)


def _merge_live_factual_tools(tools: list[str]) -> list[str]:
    """Ensure live-factual turns include page fetch and discovery companions.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Input plus ``get_page_content`` and ``serp`` when missing, then web companions.

    Examples:
        >>> _merge_live_factual_tools(["serp"])
        ['serp', 'get_page_content', 'web_fetch', 'web_search']
    """
    out = list(tools)
    for tool_id in _LIVE_FACTUAL_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return _merge_web_fetch_tools(out)


def _merge_package_install_tools(tools: list[str]) -> list[str]:
    """Prefer ``process`` over ``terminal_run`` for dependency installs.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Tools with ``process`` present and ``terminal_run`` removed.

    Examples:
        >>> _merge_package_install_tools(["terminal_run", "load_tool"])
        ['load_tool', 'process']
    """
    out = [tool_id for tool_id in tools if tool_id != "terminal_run"]
    for tool_id in _PACKAGE_INSTALL_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return out


def _merge_playwright_browser_surface(
    tools: list[str],
    skills: list[str],
) -> tuple[list[str], list[str]]:
    """Pin the native ``browser`` tool for screenshot/navigation turns.

    Args:
        tools (list[str]): Triager-selected tool ids (ignored except for doctest parity).
        skills (list[str]): Triager-selected skill ids.

    Returns:
        tuple[list[str], list[str]]: Pinned ``(tools, skills)`` without ``terminal_run``.

    Examples:
        >>> _merge_playwright_browser_surface(["terminal_run", "process"], ["canvas"])
        (['browser', 'load_tool', 'send_file'], ['canvas'])
    """
    _ = tools
    tool_out: list[str] = list(_PLAYWRIGHT_BROWSER_TOOL_IDS)
    return tool_out, list(skills)


def _merge_repo_file_ops_tools(tools: list[str]) -> list[str]:
    """Ensure read-only repo discovery tools appear in the triager tool list.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Input plus read-only repo discovery and docstring lookup tools.

    Examples:
        >>> _merge_repo_file_ops_tools([])
        ['read', 'glob', 'list_dir', 'search_in_file', 'find_file', 'get_module_docstring', 'get_symbol_docstring', 'list_symbols']
    """
    out = list(tools)
    for tool_id in _REPO_FILE_OPS_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return out


_WEB_FETCH_COMPANION_TOOL_IDS: Final[tuple[str, ...]] = (
    "serp",
    "web_fetch",
    "web_search",
)


def _merge_web_fetch_tools(tools: list[str]) -> list[str]:
    """Ensure web-fetch turns include discovery companions for CodeMode composites (W8).

    When the triager scopes ``get_page_content`` alone, tier-B under CodeMode needs
    ``serp`` / ``web_fetch`` available inside the same ``run_code`` script for URL
    discovery and fallback.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Input plus missing web companions when ``get_page_content`` is present.

    Examples:
        >>> _merge_web_fetch_tools(["get_page_content"])
        ['get_page_content', 'serp', 'web_fetch', 'web_search']
    """
    if "get_page_content" not in tools:
        return list(tools)
    out = list(tools)
    for tool_id in _WEB_FETCH_COMPANION_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return out


def _merge_evolution_tools(tools: list[str]) -> list[str]:
    """Ensure the pinned evolution implement bundle appears in the tool list (FL-4B, L5).

    The bundle covers the full implement surface:
    read/edit/write/glob/grep for file ops, sandbox_exec/terminal_run for CI
    execution, run_skill_script for ``gh-pr`` / ``make``, integration_call for
    GitHub API calls.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Input plus any missing evolution bundle ids (stable append order).

    Examples:
        >>> _merge_evolution_tools([])
        ['read', 'edit', 'write', 'glob', 'grep', 'sandbox_exec', 'terminal_run', 'run_skill_script', 'integration_call']
        >>> _merge_evolution_tools(["read", "edit"])
        ['read', 'edit', 'write', 'glob', 'grep', 'sandbox_exec', 'terminal_run', 'run_skill_script', 'integration_call']
    """
    out = list(tools)
    for tool_id in _EVOLUTION_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return out


def _merge_registry_capability_surface(
    *,
    tools: list[str],
    skills: list[str],
    include_read: bool = False,
) -> tuple[list[str], list[str]]:
    """Pin ``list_registry`` (and optionally ``read``) for capability/registry turns.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.
        include_read (bool): When True, also pin ``read`` for meta-tool source lookup.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_registry_capability_surface(tools=[], skills=[])
        (['list_registry'], [])
        >>> _merge_registry_capability_surface(tools=[], skills=[], include_read=True)
        (['list_registry', 'read'], [])
    """
    tool_out = list(tools)
    for tool_id in _REGISTRY_CAPABILITY_TOOL_IDS:
        if tool_id not in tool_out:
            tool_out.append(tool_id)
    if include_read:
        for tool_id in _REGISTRY_META_HOWTO_READ_TOOL_IDS:
            if tool_id not in tool_out:
                tool_out.append(tool_id)
    return tool_out, list(skills)


def _merge_github_repo_eval_surface(
    *,
    tools: list[str],
    skills: list[str],
) -> tuple[list[str], list[str]]:
    """Pin clone/read tools and ``skill_management`` for external repo evaluation.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_github_repo_eval_surface(tools=[], skills=[])
        (['terminal_run', 'read', 'glob', 'list_dir', 'search_in_file', 'get_page_content', 'load_skill', 'run_skill_script', 'process'], ['skill_management'])
    """
    tool_out = list(tools)
    for tool_id in _GITHUB_REPO_EVAL_TOOL_IDS:
        if tool_id not in tool_out:
            tool_out.append(tool_id)
    skill_out = list(skills)
    for skill_id in _GITHUB_REPO_EVAL_SKILL_IDS:
        if skill_id not in skill_out:
            skill_out.append(skill_id)
    return tool_out, skill_out


def _merge_log_provenance_surface(
    *,
    tools: list[str],
    skills: list[str],
) -> tuple[list[str], list[str]]:
    """Pin log audit tools for provenance follow-up turns.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_log_provenance_surface(tools=[], skills=[])
        (['log_query', 'read_transcript'], [])
    """
    tool_out = list(tools)
    for tool_id in _LOG_PROVENANCE_TOOL_IDS:
        if tool_id not in tool_out:
            tool_out.append(tool_id)
    return tool_out, list(skills)


def _merge_skill_status_surface(
    *,
    tools: list[str],
    skills: list[str],
    skill_id: str,
) -> tuple[list[str], list[str]]:
    """Pin registry + progressive-load tools for named-skill status turns.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.
        skill_id (str): Resolved skill id from the user message.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_skill_status_surface(tools=[], skills=[], skill_id="last30days")
        (['list_registry', 'load_skill', 'read', 'search_in_file', 'run_skill_script'], ['last30days'])
    """
    tool_out = list(tools)
    for tool_id in _SKILL_STATUS_TOOL_IDS:
        if tool_id not in tool_out:
            tool_out.append(tool_id)
    skill_out = list(skills)
    if skill_id not in skill_out:
        skill_out.append(skill_id)
    return tool_out, skill_out


def _merge_lcm_status_surface(
    *,
    tools: list[str],
    skills: list[str],
) -> tuple[list[str], list[str]]:
    """Ensure LCM status turns have the canonical skill/script execution surface.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_lcm_status_surface(tools=[], skills=[])
        (['load_skill', 'run_skill_script'], ['lcm'])
    """
    tool_out = list(tools)
    for tool_id in ("load_skill", "run_skill_script"):
        if tool_id not in tool_out:
            tool_out.append(tool_id)
    skill_out = list(skills)
    if "lcm" not in skill_out:
        skill_out.append("lcm")
    return tool_out, skill_out


def _merge_session_recall_surface(
    *,
    tools: list[str],
    skills: list[str],
) -> tuple[list[str], list[str]]:
    """Pin the session-recall surface: ``history`` first, ``memory_search`` + ``lcm`` as backups.

    ``history`` is the SESSIONS.md primary recall path (reliable inline rows), so it leads and
    is the bound tool the must-satisfy guard can satisfy. ``memory_search`` plus the ``lcm``
    skill (via ``load_skill`` / ``run_skill_script``) stay bound as backups so the model can
    cross-check all three recall paths.

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids.

    Returns:
        tuple[list[str], list[str]]: Updated ``(tools, skills)`` pair.

    Examples:
        >>> _merge_session_recall_surface(tools=[], skills=[])
        (['history', 'memory_search', 'load_skill', 'run_skill_script'], ['lcm'])
        >>> _merge_session_recall_surface(tools=['history'], skills=['lcm'])
        (['history', 'memory_search', 'load_skill', 'run_skill_script'], ['lcm'])
    """
    ordered = ("history", "memory_search", "load_skill", "run_skill_script")
    tool_out = [t for t in ordered if t in tools]
    tool_out += [t for t in ordered if t not in tool_out]
    tool_out += [t for t in tools if t not in tool_out]
    skill_out = list(skills)
    if "lcm" not in skill_out:
        skill_out.append("lcm")
    return tool_out, skill_out


def _merge_file_ops_tools(tools: list[str]) -> list[str]:
    """Ensure ``read``, ``edit``, and ``write`` appear in the triager tool list.

    Args:
        tools (list[str]): Triager-selected tool ids.

    Returns:
        list[str]: Input plus missing file-op ids (stable order).

    Examples:
        >>> _merge_file_ops_tools(["memory_search"])
        ['memory_search', 'read', 'edit', 'write']
    """
    out = list(tools)
    for tool_id in _FILE_OPS_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    return out


def _merge_file_pipeline_tools(tools: list[str], *, skills: list[str]) -> list[str]:
    """Ensure file-ops cluster and code-exec path appear for PDF/file pipelines (P3).

    Args:
        tools (list[str]): Triager-selected tool ids.
        skills (list[str]): Triager-selected skill ids (``pdf`` triggers merge).

    Returns:
        list[str]: Input plus missing file-pipeline tool ids (stable order).

    Examples:
        >>> _merge_file_pipeline_tools(["run_skill_script"], skills=["pdf"])
        ['run_skill_script', 'glob', 'search_in_file', 'find_file', 'file_info', 'get_page_content', 'terminal_run', 'sandbox_exec', 'send_file']
    """
    out = list(tools)
    for tool_id in _FILE_PIPELINE_TOOL_IDS:
        if tool_id not in out:
            out.append(tool_id)
    if "pdf" in skills and "run_skill_script" not in out:
        out.append("run_skill_script")
    if "pdf" in skills and "send_file" not in out:
        out.append("send_file")
    return out


def is_strict_greeting_message(message: str) -> bool:
    """Return True for pure social openers/closers suitable for tier A.

    Args:
        message (str): Current user message.

    Returns:
        bool: True when message is a short greeting without informational intent.

    Examples:
        >>> is_strict_greeting_message("hi")
        True
        >>> is_strict_greeting_message("helloo")
        True
        >>> is_strict_greeting_message("ok")
        True
        >>> is_strict_greeting_message("so?")
        False
        >>> is_strict_greeting_message("who are you?")
        False
    """
    text = message.strip()
    if not text:
        return False
    if is_identity_or_capability_message(text):
        return False
    if classify_greeting(text) is not None:
        return True
    words = text.split()
    if len(words) > 12:
        return False
    if "?" in text and not _GREETING_PATTERNS[0].match(text):
        return False
    if _EMOJI_ONLY.match(text):
        return True
    return any(p.match(text) for p in _GREETING_PATTERNS)


def first_message_passes_opener_rule(text: str) -> bool:
    """Return True when ``text`` is a clean tier-B/C/D opener (W5.1).

    A ``first_message`` passes when it:
    * is non-empty after stripping,
    * contains no newlines (single-line opener, not a multi-sentence answer),
    * does not start with any prefix in :data:`sevn.agent.openers.BARE_OPENERS`, and
    * is at most 200 characters (a one-liner, not a paragraph that overstepped).

    Use this to decide whether to keep the triager LLM's own ``first_message``
    instead of replacing it with a canned ``default_early_ack()`` line.

    Args:
        text (str): Candidate ``first_message`` from the triager LLM.

    Returns:
        bool: ``True`` when the text is a suitable clean opener.

    Examples:
        >>> first_message_passes_opener_rule("Hey Alex — what are we working on today?")
        True
        >>> first_message_passes_opener_rule("On it — give me a moment.")
        False
        >>> first_message_passes_opener_rule("Let me check that for you.")
        False
        >>> first_message_passes_opener_rule("")
        False
        >>> first_message_passes_opener_rule("Working on it\\nmore text")
        False
    """
    stripped = text.strip()
    if not stripped:
        return False
    if "\n" in stripped:
        return False
    if len(stripped) > 200:
        return False
    normed = " ".join(stripped.lower().split())
    return not any(normed.startswith(prefix) for prefix in BARE_OPENERS)


def default_early_ack(*, turn_id: str = "", first_session: bool = False) -> str:
    """Return a locale-neutral early ack for tier B/C/D.

    Args:
        turn_id (str): Correlation id for rotation.
        first_session (bool): Use warmer first-session ack when True.

    Returns:
        str: Non-empty ack string.

    Examples:
        >>> default_early_ack(turn_id="t1")
        'Reading now…'
    """
    pool = _FIRST_SESSION_ACKS if first_session else _EARLY_ACKS
    seed = turn_id or "default"
    return _pick_rotated(pool, seed=seed)


def _tier_a_pools_for_kind(
    kind: GreetingKind,
    *,
    named: bool,
) -> tuple[str, ...]:
    """Return the full or generic tier-A pool for a greeting category.

    Args:
        kind (GreetingKind): Reply category.
        named (bool): When True, return the full pool (generic + named templates).

    Returns:
        tuple[str, ...]: Rotating reply templates.

    Examples:
        >>> len(_tier_a_pools_for_kind("hello", named=False)) == 50
        True
        >>> len(_tier_a_pools_for_kind("bye", named=True)) == 50
        True
    """
    if kind == "hello":
        return _TIER_A_HELLO_REPLIES if named else _TIER_A_HELLO_GENERIC_REPLIES
    if kind == "bye":
        return _TIER_A_BYE_REPLIES if named else _TIER_A_BYE_GENERIC_REPLIES
    return _TIER_A_THANKS_REPLIES if named else _TIER_A_THANKS_GENERIC_REPLIES


def default_tier_a_reply(
    *,
    turn_id: str = "",
    operator_name: str | None = None,
    kind: GreetingKind = "hello",
) -> str:
    """Return a canned tier-A greeting reply for the given category.

    Args:
        turn_id (str): Correlation id for rotation.
        operator_name (str | None): Preferred name from ``USER.md`` for ``{name}``
            templates (half the pool). When absent, only generic templates rotate.
        kind (GreetingKind): Greeting category (hello / thanks / bye).

    Returns:
        str: Friendly short reply.

    Examples:
        >>> bool(default_tier_a_reply(turn_id="x"))
        True
        >>> "{name}" not in default_tier_a_reply(turn_id="x")
        True
        >>> default_tier_a_reply(turn_id="bye-1", kind="bye").strip()
        'Bye — talk soon!'
    """
    named = _normalize_operator_name(operator_name) is not None
    pool = _tier_a_pools_for_kind(kind, named=named)
    template = _pick_rotated(pool, seed=f"{turn_id}:{kind}")
    return _format_tier_a_reply(template, operator_name=operator_name)


def is_obvious_continuation_message(message: str) -> bool:
    """Return True for short follow-up continuations ("so?", "go ahead", "try again").

    Args:
        message (str): Current user message.

    Returns:
        bool: True when the entire message is a known continuation phrase.

    Examples:
        >>> is_obvious_continuation_message("so?")
        True
        >>> is_obvious_continuation_message("go ahead")
        True
        >>> is_obvious_continuation_message("hello")
        False
        >>> is_obvious_continuation_message("ok now I see it")
        False
    """
    return _continuation_phrase(message) is not None


def prior_triage_indicates_in_progress(prior: TriageResult) -> bool:
    """Return True when prior routing should be replayed for a continuation turn.

    A prior tier-B/C/D decision or a non-empty tool/skill surface signals an
    in-progress task worth reusing without another slow triage LLM call.

    Args:
        prior (TriageResult): Finalised triage from the previous gateway turn.

    Returns:
        bool: True when continuation fast-path may replay ``prior``.

    Examples:
        >>> from sevn.agent.triager.models import ComplexityTier, Intent
        >>> busy = TriageResult.model_construct(
        ...     intent=Intent.NEW_REQUEST, complexity=ComplexityTier.B,
        ...     first_message="On it.", tools=["read"], skills=[], mcp_servers_required=[],
        ...     confidence=0.9, requires_vision=False, disregard=False,
        ... )
        >>> prior_triage_indicates_in_progress(busy)
        True
        >>> idle = busy.model_copy(update={"complexity": ComplexityTier.A, "tools": []})
        >>> prior_triage_indicates_in_progress(idle)
        False
    """
    if prior.disregard:
        return False
    if prior.complexity in (ComplexityTier.B, ComplexityTier.C, ComplexityTier.D):
        return True
    return bool(prior.tools or prior.skills)


def try_fast_continuation_triage(
    *,
    current_message: str,
    prior: TriageResult,
    turn_id: str = "",
) -> TriageResult | None:
    """Optional pre-LLM replay of prior routing for obvious continuations.

    Reuses tools/skills/complexity from ``prior`` with ``intent=FOLLOWUP`` and
    ``replay_provider_history=true`` so tier-B can continue the in-flight task
    without a 30s triage tax on "so?" / "go ahead" / "try again".

    Args:
        current_message (str): User message text.
        prior (TriageResult): Previous turn's finalised triage result.
        turn_id (str): Turn correlation id for ack rotation.

    Returns:
        TriageResult | None: Synthetic FOLLOWUP replay when matched, else ``None``.

    Examples:
        >>> from sevn.agent.triager.models import ComplexityTier, Intent
        >>> prior = TriageResult.model_construct(
        ...     intent=Intent.NEW_REQUEST, complexity=ComplexityTier.B,
        ...     first_message="Working.", tools=["read"], skills=["pdf"],
        ...     mcp_servers_required=[], confidence=0.85, requires_vision=False,
        ...     requires_document=False,
        ...     disregard=False,
        ... )
        >>> r = try_fast_continuation_triage(
        ...     current_message="go ahead", prior=prior, turn_id="2",
        ... )
        >>> r is not None and r.intent == Intent.FOLLOWUP and r.tools == ["read"]
        True
    """
    if _continuation_phrase(current_message) is None:
        return None
    if not prior_triage_indicates_in_progress(prior):
        return None
    return prior.model_copy(
        update={
            "intent": Intent.FOLLOWUP,
            "first_message": default_early_ack(turn_id=turn_id),
            "replay_provider_history": True,
            "confidence": max(prior.confidence, 0.9),
        },
    )


def try_fast_greeting_triage(
    *,
    current_message: str,
    turn_id: str = "",
    operator_name: str | None = None,
) -> TriageResult | None:
    """Optional pre-LLM tier-A synthesis for strict greetings.

    Args:
        current_message (str): User message text.
        turn_id (str): Turn correlation id for reply rotation.
        operator_name (str | None): Preferred name from ``USER.md`` for named templates.

    Returns:
        TriageResult | None: Synthetic GREETING/A when matched, else None.

    Examples:
        >>> r = try_fast_greeting_triage(current_message="hello", turn_id="1")
        >>> r is not None and r.complexity == ComplexityTier.A
        True
    """
    if not is_strict_greeting_message(current_message):
        return None
    kind = classify_greeting(current_message) or "hello"
    return TriageResult.model_construct(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message=default_tier_a_reply(
            turn_id=turn_id,
            operator_name=operator_name,
            kind=kind,
        ),
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        followup_anchor=None,
        permission_scope_narrowing=None,
    )


def _should_clamp_cd_to_b(
    result: TriageResult,
    *,
    current_message: str,
    confidence_threshold: float = COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    short_word_limit: int = COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
) -> bool:
    """Return whether a low-confidence C/D decision should clamp to tier B.

    A C/D route only earns its structured-plan overhead when the model is
    reasonably sure. Below :data:`COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD`, a short
    message (``≤ COMPLEXITY_CLAMP_SHORT_WORD_LIMIT`` words) or a FOLLOWUP carries
    no concrete multi-step task, so it clamps to B rather than risking a decompose
    contract that open models (e.g. ``minimax/*``) cannot reliably satisfy.

    Args:
        result (TriageResult): Policy-adjusted result so far.
        current_message (str): Latest user message text.
        confidence_threshold (float): Minimum confidence to keep a C/D route.
        short_word_limit (int): Word-count ceiling for clamping short messages.

    Returns:
        bool: ``True`` when the C/D decision should become B.

    Examples:
        >>> from sevn.agent.triager.models import TriageResult
        >>> low = TriageResult.model_construct(
        ...     intent=Intent.FOLLOWUP, complexity=ComplexityTier.C,
        ...     first_message="ok", tools=[], skills=[], mcp_servers_required=[],
        ...     confidence=0.78, requires_vision=False, disregard=False,
        ... )
        >>> _should_clamp_cd_to_b(low, current_message="all this needs to be fixed")
        True
        >>> hi = low.model_copy(update={"confidence": 0.95})
        >>> _should_clamp_cd_to_b(hi, current_message="all this needs to be fixed")
        False
    """
    if result.complexity not in (ComplexityTier.C, ComplexityTier.D):
        return False
    if result.confidence >= confidence_threshold:
        return False
    word_count = len(current_message.split())
    if word_count <= short_word_limit:
        return True
    return result.intent == Intent.FOLLOWUP


def _intent_router_changed_routing(before: TriageResult, after: TriageResult) -> bool:
    """Return True when an intent router materially changed tier, tools, or skills.

    Args:
        before (TriageResult): Routing state before the router block.
        after (TriageResult): Routing state after ``model_copy(update=...)``.

    Returns:
        bool: ``True`` when tier changed or new tools/skills were added.

    Examples:
        >>> from sevn.agent.triager.models import TriageResult
        >>> prior = TriageResult.model_construct(
        ...     intent=Intent.GREETING, complexity=ComplexityTier.A,
        ...     first_message="hi", tools=[], skills=[], mcp_servers_required=[],
        ...     confidence=0.9, requires_vision=False, disregard=False,
        ... )
        >>> after = prior.model_copy(
        ...     update={"complexity": ComplexityTier.B, "tools": ["read"]},
        ... )
        >>> _intent_router_changed_routing(prior, after)
        True
        >>> same = prior.model_copy(update={"complexity": ComplexityTier.A})
        >>> _intent_router_changed_routing(prior, same)
        False
    """
    if before.complexity != after.complexity:
        return True
    if set(after.tools) - set(before.tools):
        return True
    return bool(set(after.skills) - set(before.skills))


def _log_intent_router_applied(
    router: str,
    before: TriageResult,
    after: TriageResult,
) -> None:
    """Emit one observability line when an intent router changed tier or tools.

    Args:
        router (str): Router detector name (for example ``is_memorize_message``).
        before (TriageResult): Routing state before the router block.
        after (TriageResult): Routing state after ``model_copy(update=...)``.

    Examples:
        >>> from sevn.agent.triager.models import TriageResult
        >>> prior = TriageResult.model_construct(
        ...     intent=Intent.GREETING, complexity=ComplexityTier.A,
        ...     first_message="hi", tools=[], skills=[], mcp_servers_required=[],
        ...     confidence=0.9, requires_vision=False, disregard=False,
        ... )
        >>> after = prior.model_copy(
        ...     update={"complexity": ComplexityTier.B, "tools": ["read", "edit"]},
        ... )
        >>> _log_intent_router_applied("is_workspace_file_intent_message", prior, after)
    """
    if not _intent_router_changed_routing(before, after):
        return
    changed_tier = before.complexity != after.complexity
    added_tools = sorted(set(after.tools) - set(before.tools))
    logger.info(
        "routing_policy.intent_router_applied router={} changed_tier={} added_tools={}",
        router,
        changed_tier,
        added_tools,
    )


def _apply_intent_router_update(
    before: TriageResult,
    update: dict[str, object],
    *,
    router: str,
) -> TriageResult:
    """Apply one intent-router ``model_copy`` and log when routing materially changed.

    Args:
        before (TriageResult): Current routing state.
        update (dict[str, object]): Fields to pass to ``model_copy(update=...)``.
        router (str): Router detector name for observability.

    Returns:
        TriageResult: Updated routing state.

    Examples:
        >>> from sevn.agent.triager.models import TriageResult
        >>> prior = TriageResult.model_construct(
        ...     intent=Intent.GREETING, complexity=ComplexityTier.A,
        ...     first_message="hi", tools=[], skills=[], mcp_servers_required=[],
        ...     confidence=0.9, requires_vision=False, disregard=False,
        ... )
        >>> out = _apply_intent_router_update(
        ...     prior,
        ...     {"complexity": ComplexityTier.B, "tools": ["read"]},
        ...     router="is_workspace_file_intent_message",
        ... )
        >>> out.complexity == ComplexityTier.B
        True
    """
    after = before.model_copy(update=update)
    _log_intent_router_applied(router, before, after)
    return after


def apply_routing_policy(
    result: TriageResult,
    *,
    current_message: str,
    turn_id: str = "",
    is_first_session: bool = False,
    bootstrap_capture_active: bool = False,
    operator_name: str | None = None,
    indexed_skill_ids: frozenset[str] | None = None,
    complexity_clamp_confidence_threshold: float = COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    complexity_clamp_short_word_limit: int = COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
) -> TriageResult:
    """Coerce tier, intent, and ``first_message`` after schema validation.

    Args:
        result (TriageResult): Parsed Triager output.
        current_message (str): User message for echo and heuristic checks.
        turn_id (str): Correlation id for ack rotation.
        is_first_session (bool): First user message in scope (BOOTSTRAP intro).
        bootstrap_capture_active (bool): Bootstrap follow-up turn needing tier-B capture.
        operator_name (str | None): Preferred name from ``USER.md`` for tier-A replies.
        indexed_skill_ids (frozenset[str] | None): Registry skill ids for status routing.
        complexity_clamp_confidence_threshold (float): Effective
            ``triager.complexity_clamp_confidence_threshold``.
        complexity_clamp_short_word_limit (int): Effective
            ``triager.complexity_clamp_short_word_limit``.

    Returns:
        TriageResult: Policy-adjusted result.

    Examples:
        >>> from sevn.agent.triager.models import TriageResult
        >>> r = TriageResult(
        ...     intent=Intent.GREETING,
        ...     complexity=ComplexityTier.A,
        ...     first_message="who are you?",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.9,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> out = apply_routing_policy(r, current_message="who are you?", turn_id="t")
        >>> out.complexity == ComplexityTier.B
        True
    """
    msg = current_message.strip()
    out = result
    skill_index = indexed_skill_ids or frozenset()

    if out.disregard:
        return out

    # D8: follow-ups that continue a tool conversation should replay provider-native
    # assistant blocks when structured history is available in the workspace.
    if out.intent == Intent.FOLLOWUP and not out.replay_provider_history:
        out = out.model_copy(update={"replay_provider_history": True})

    # First-session intro: force tier B with warm early ack (unless already C/D).
    if is_first_session and out.complexity == ComplexityTier.A:
        out = out.model_copy(
            update={
                "intent": Intent.NEW_REQUEST,
                "complexity": ComplexityTier.B,
                "first_message": default_early_ack(
                    turn_id=turn_id,
                    first_session=True,
                ),
                "tools": [],
                "skills": out.skills,
            },
        )

    # Bootstrap follow-up (e.g. "I'm Alex"): tier B so write_workspace_md is available.
    if bootstrap_capture_active and not is_first_session and out.complexity == ComplexityTier.A:
        out = out.model_copy(
            update={
                "intent": Intent.NEW_REQUEST,
                "complexity": ComplexityTier.B,
                "first_message": default_early_ack(turn_id=turn_id),
                "tools": [],
                "skills": out.skills,
            },
        )

    # Identity/capability must not be GREETING + A; always pin list_registry.
    if is_identity_or_capability_message(msg):
        _id_tools, id_skills = _merge_registry_capability_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        # Capability/identity turns only need list_registry — drop model-picked tools
        # (e.g. read) so Guard 2 must-satisfy does not demand an unnecessary read.
        id_tools = list(_REGISTRY_CAPABILITY_TOOL_IDS)
        id_updates: dict[str, object] = {
            "tools": id_tools,
            "skills": id_skills,
        }
        if out.complexity == ComplexityTier.A or out.intent == Intent.GREETING:
            id_updates.update(
                {
                    "intent": Intent.NEW_REQUEST,
                    "complexity": ComplexityTier.B,
                    "first_message": default_early_ack(
                        turn_id=turn_id,
                        first_session=is_first_session,
                    ),
                },
            )
        out = _apply_intent_router_update(
            out,
            id_updates,
            router="is_identity_or_capability_message",
        )

    # Greeting misclassified as informational question → tier B heuristics.
    elif (
        out.intent == Intent.GREETING
        and out.complexity == ComplexityTier.A
        and ("?" in msg or len(msg.split()) > 8)
        and not is_strict_greeting_message(msg)
    ):
        out = out.model_copy(
            update={
                "intent": Intent.NEW_REQUEST,
                "complexity": ComplexityTier.B,
                "first_message": default_early_ack(turn_id=turn_id),
            },
        )

    # Anti-echo: first_message must not equal user text.
    if msg and _normalize(out.first_message) == _normalize(msg):
        if is_identity_or_capability_message(msg) or out.complexity != ComplexityTier.A:
            out = out.model_copy(
                update={
                    "intent": Intent.NEW_REQUEST,
                    "complexity": ComplexityTier.B,
                    "first_message": default_early_ack(
                        turn_id=turn_id,
                        first_session=is_first_session,
                    ),
                },
            )
        elif is_strict_greeting_message(msg):
            kind = classify_greeting(msg) or "hello"
            out = out.model_copy(
                update={
                    "intent": Intent.GREETING,
                    "complexity": ComplexityTier.A,
                    "first_message": default_tier_a_reply(
                        turn_id=turn_id,
                        operator_name=operator_name,
                        kind=kind,
                    ),
                },
            )
        else:
            out = out.model_copy(
                update={
                    "complexity": ComplexityTier.B,
                    "first_message": default_early_ack(turn_id=turn_id),
                },
            )

    # Mandatory non-empty first_message for B/C/D.
    if (
        out.complexity
        in (
            ComplexityTier.B,
            ComplexityTier.C,
            ComplexityTier.D,
        )
        and not out.first_message.strip()
    ):
        out = out.model_copy(
            update={
                "first_message": default_early_ack(
                    turn_id=turn_id,
                    first_session=is_first_session,
                ),
            },
        )

    # Tier A echo guard after replacements.
    if (
        out.complexity == ComplexityTier.A
        and msg
        and _normalize(out.first_message) == _normalize(msg)
    ):
        kind = classify_greeting(msg) or "hello"
        out = out.model_copy(
            update={
                "first_message": default_tier_a_reply(
                    turn_id=turn_id,
                    operator_name=operator_name,
                    kind=kind,
                ),
            },
        )

    if is_workspace_file_intent_message(msg):
        out = _apply_intent_router_update(
            out,
            {
                "intent": Intent.NEW_REQUEST,
                "complexity": ComplexityTier.B,
                "tools": _merge_file_ops_tools(list(out.tools)),
            },
            router="is_workspace_file_intent_message",
        )

    if is_pdf_file_pipeline_message(msg) or (
        "pdf" in out.skills and {"run_skill_script", "send_file"} <= set(out.tools)
    ):
        pipeline_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": _merge_file_pipeline_tools(list(out.tools), skills=list(out.skills)),
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            pipeline_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            pipeline_updates,
            router="is_pdf_file_pipeline_message",
        )

    if is_memorize_message(msg):
        mem_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": _merge_file_ops_tools(list(out.tools)),
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            mem_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            mem_updates,
            router="is_memorize_message",
        )

    if is_repo_code_intent_message(msg):
        tools = _merge_repo_file_ops_tools(list(out.tools))
        updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": tools,
        }
        if out.complexity == ComplexityTier.A:
            updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            updates,
            router="is_repo_code_intent_message",
        )

    if is_session_recall_message(msg) and not is_lcm_status_message(msg):
        recall_tools, recall_skills = _merge_session_recall_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        recall_updates: dict[str, object] = {
            "intent": Intent.FOLLOWUP if out.intent == Intent.GREETING else out.intent,
            "complexity": ComplexityTier.B,
            "tools": recall_tools,
            "skills": recall_skills,
        }
        if not out.first_message.strip() or out.complexity == ComplexityTier.A:
            recall_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            recall_updates,
            router="is_session_recall_message",
        )

    if is_lcm_status_message(msg):
        merged_tools, merged_skills = _merge_lcm_status_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        updates = {
            "intent": Intent.FOLLOWUP if out.intent == Intent.GREETING else out.intent,
            "complexity": ComplexityTier.B,
            "tools": merged_tools,
            "skills": merged_skills,
        }
        if not out.first_message.strip() or out.complexity == ComplexityTier.A:
            updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            updates,
            router="is_lcm_status_message",
        )

    if not is_lcm_status_message(msg) and is_skill_status_intent_message(
        msg,
        indexed_skill_ids=skill_index,
        triage_skills=out.skills,
    ):
        skill_target = resolve_skill_status_target(
            msg,
            indexed_skill_ids=skill_index,
            triage_skills=out.skills,
        )
        if skill_target is not None:
            ss_tools, ss_skills = _merge_skill_status_surface(
                tools=list(out.tools),
                skills=list(out.skills),
                skill_id=skill_target,
            )
            ss_updates: dict[str, object] = {
                "intent": Intent.NEW_REQUEST,
                "complexity": ComplexityTier.B,
                "tools": ss_tools,
                "skills": ss_skills,
            }
            if out.complexity == ComplexityTier.A or not out.first_message.strip():
                ss_updates["first_message"] = default_early_ack(turn_id=turn_id)
            out = _apply_intent_router_update(
                out,
                ss_updates,
                router="is_skill_status_intent_message",
            )

    if is_github_repo_eval_intent_message(msg):
        gh_tools, gh_skills = _merge_github_repo_eval_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        gh_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": gh_tools,
            "skills": gh_skills,
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            gh_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            gh_updates,
            router="is_github_repo_eval_intent_message",
        )

    if is_log_provenance_intent_message(msg):
        lp_tools, lp_skills = _merge_log_provenance_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        lp_updates: dict[str, object] = {
            "intent": Intent.FOLLOWUP if out.intent == Intent.GREETING else out.intent,
            "complexity": ComplexityTier.B,
            "tools": lp_tools,
            "skills": lp_skills,
            "replay_provider_history": False,
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            lp_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            lp_updates,
            router="is_log_provenance_intent_message",
        )

    if is_live_factual_message(msg) and not is_playwright_browser_message(msg):
        lf_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": _merge_live_factual_tools(list(out.tools)),
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            lf_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            lf_updates,
            router="is_live_factual_message",
        )

    if is_registry_capability_intent_message(msg):
        reg_tools, reg_skills = _merge_registry_capability_surface(
            tools=list(out.tools),
            skills=list(out.skills),
            include_read=is_registry_meta_howto_message(msg),
        )
        reg_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": reg_tools,
            "skills": reg_skills,
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            reg_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            reg_updates,
            router="is_registry_capability_intent_message",
        )

    if is_playwright_browser_message(msg):
        pw_tools, pw_skills = _merge_playwright_browser_surface(
            tools=list(out.tools),
            skills=list(out.skills),
        )
        if is_live_factual_message(msg):
            pw_tools = _merge_live_factual_tools(pw_tools)
        pw_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": pw_tools,
            "skills": pw_skills,
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            pw_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            pw_updates,
            router="is_playwright_browser_message",
        )

    if is_package_install_message(msg):
        install_updates: dict[str, object] = {
            "intent": Intent.FOLLOWUP if out.intent == Intent.GREETING else Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": _merge_package_install_tools(list(out.tools)),
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            install_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            install_updates,
            router="is_package_install_message",
        )

    # FL-4B.3: explicit evolution issue-fix directive → tier B with pinned bundle (L5).
    # Runs before the complexity clamp so the pinned tools survive even if the clamp fires.
    # Do NOT coerce generic repo-code intent here — is_repo_code_intent_message handles that.
    if is_evolution_fix_intent_message(msg):
        evo_updates: dict[str, object] = {
            "intent": Intent.NEW_REQUEST,
            "complexity": ComplexityTier.B,
            "tools": _merge_evolution_tools(list(out.tools)),
        }
        if out.complexity == ComplexityTier.A or not out.first_message.strip():
            evo_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = _apply_intent_router_update(
            out,
            evo_updates,
            router="is_evolution_fix_intent_message",
        )

    # Complexity clamp: a low-confidence C/D route on a short/vague turn drops to B
    # (`specs/13-rlm-triager.md`). Runs last so earlier B-coercions are already applied.
    if _should_clamp_cd_to_b(
        out,
        current_message=msg,
        confidence_threshold=complexity_clamp_confidence_threshold,
        short_word_limit=complexity_clamp_short_word_limit,
    ):
        clamp_updates: dict[str, object] = {"complexity": ComplexityTier.B}
        if not out.first_message.strip():
            clamp_updates["first_message"] = default_early_ack(turn_id=turn_id)
        out = out.model_copy(update=clamp_updates)

    # W5.1: Prefer the triager LLM's own ``first_message`` when it passes the opener
    # rule — i.e. it is a clean single-line opener that does not start with a forbidden
    # prefix (``on it``, ``let me``, etc.).  If the policy replaced it with a canned
    # ack that *does* start with a forbidden prefix, restore the LLM's version.
    #
    # Only applies for B/C/D turns where ``first_message`` is used as a user-visible
    # placeholder ack: tier-A replies are complete answers, not placeholders.
    #
    # Guard: do NOT restore when the result's first_message is empty, was echoing the
    # user message (already fixed above), or is a first-session intro opener (those
    # are intentionally warm/longer greetings, kept as-is).
    if (
        out.complexity in (ComplexityTier.B, ComplexityTier.C, ComplexityTier.D)
        and not is_first_session
        and first_message_passes_opener_rule(result.first_message)
        and not first_message_passes_opener_rule(out.first_message)
        and (msg and _normalize(result.first_message) != _normalize(msg))
    ):
        out = out.model_copy(update={"first_message": result.first_message})

    if "get_page_content" in out.tools:
        out = out.model_copy(update={"tools": _merge_web_fetch_tools(list(out.tools))})

    return out
