"""Screen probe: vendored local_screen + privacy from hermes-jev-skills (MIT).

Vendored verbatim (adapted imports/typing only) from:
  - https://github.com/kerpopule/hermes-jev-skills
    jevkit/rerank.py (local_screen, INSTRUCTION_PATTERNS, _orders, _url_exfiltration, ...)
    jevkit/privacy.py  (normalize, is_sensitive, redact)
License: MIT (see repo LICENSE). No functional changes to detection logic.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

# ── privacy.py (verbatim) ────────────────────────────────────────────────────

_SECRET_WORDS = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|authorization\s*:|bearer\s+[a-z0-9._-]{8,}|password|passwd|"
    r"client[_ -]?secret|session[_ -]?cookie|credit[_ -]?card|card[_ -]?number|"
    r"\bcvv\b|\bssn\b|private[_ -]?key|BEGIN [A-Z ]*PRIVATE KEY)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*[_-]"
    r"(?:SECRET|SECRET[_-]?\w*KEY|API[_-]?KEY|KEY|TOKEN|PASSWORD|PASSWD|CREDENTIALS?|AUTH)\b"
    r"\s*[:=]\s*\S*"
)
_SECRET_NAME = re.compile(r"(?i)\bsecret[_ -](?:access[_ -])?key\b|\bsecret[_ -]?key\b")
_TOKEN_SHAPES = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|apikey_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})\b"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_CARD = re.compile(r"(?<![\d.-])(?:\d[ -]?){12,18}\d(?![.\d-])")
_INTL_PHONE = re.compile(r"(?<![\d+])\+\d{1,3}[\s.-]?(?:\d[\s.-]?){7,13}\d(?!\d)")
_HIGH_ENTROPY = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/=_-])")
_TRACKING = re.compile(r"\b1Z[0-9A-Z]{16}\b", re.IGNORECASE)
_LONG_HEX = re.compile(r"\b[a-fA-F0-9]{32,}\b")


def _luhn(digits: str) -> bool:
    total, alternate = 0, False
    for char in reversed(digits):
        value = ord(char) - 48
        if alternate:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        alternate = not alternate
    return total % 10 == 0


def _mask_card(match: "re.Match[str]") -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[card]" if 13 <= len(digits) <= 19 and _luhn(digits) else match.group(0)


def _mask_credential(match: "re.Match[str]") -> str:
    run = match.group(0)
    mixed = (any(c.isupper() for c in run) and any(c.islower() for c in run)
             and any(c.isdigit() for c in run))
    return "[secret]" if mixed else run


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(c for c in folded if unicodedata.category(c) not in {"Cf", "Cc"} or c in "\n\t")


def is_sensitive(text: str) -> bool:
    probe = normalize(text)
    return bool(_SECRET_WORDS.search(probe) or _SECRET_NAME.search(probe)
                or _SECRET_ASSIGNMENT.search(probe) or _TOKEN_SHAPES.search(probe))


def redact(text: str, limit: int = 4000) -> str:
    out = normalize(text)
    held: List[str] = []

    def _hold(match: "re.Match[str]") -> str:
        held.append(match.group(0))
        return f"\x00TRK{len(held) - 1}\x00"

    out = _TRACKING.sub(_hold, out)
    out = _TOKEN_SHAPES.sub("[secret]", out)
    out = _SECRET_ASSIGNMENT.sub(lambda m: re.split(r"[:=]", m.group(0), maxsplit=1)[0].rstrip() + "=[secret]", out)
    out = _LONG_HEX.sub("[hex]", out)
    out = _HIGH_ENTROPY.sub(_mask_credential, out)
    out = _CARD.sub(_mask_card, out)
    out = _EMAIL.sub("[email]", out)
    out = _PHONE.sub("[phone]", out)
    out = _INTL_PHONE.sub("[phone]", out)
    for index, value in enumerate(held):
        out = out.replace(f"\x00TRK{index}\x00", value)
    if len(out) > limit:
        half = limit // 2
        out = out[:half] + "\n[…]\n" + out[-half:]
    return out


# ── rerank.py local_screen (verbatim) ────────────────────────────────────────

INSTRUCTION_PATTERNS = re.compile(
    r"(?i)("
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)"
    r"|disregard\s+(your\s+|all\s+|the\s+)?(previous|prior|instructions?|rules?|safety)"
    r"|forget\s+(everything|anything|all|what)\s+(you|that)\s+(were|was|have\s+been)\s+told"
    r"|(new|updated|revised)\s+instructions\s+(from|for)\s+(the\s+|your\s+)?(developer|system|admin\w*|operator|assistant|model|ai)\b"
    r"|system\s*:\s*you|system\s+override"
    r"|developer\s+mode"
    r"|you\s+are\s+now\s+(in|a|an|the|dan|free|unrestricted|jailbroken)\b"
    r"|(reveal|print|output|repeat|show)\s+(me\s+)?your\s+(system\s+)?(prompt|instructions)"
    r"|(do\s+not|don'?t|never)\s+(tell|inform|alert|notify)\s+the\s+(user|operator|human|person)\s+(about|that\s+you)"
    r"|skip\s+(the\s+)?(privacy|safety)\s+(gate|check|rules?)"
    r")"
)

_COMMAND = re.compile(r"(?i)\b(?:run|execute)\s+(?:this|the\s+following)\s+(?:command|script|curl)\b")
_COMMAND_RISK = re.compile(
    r"(?i)(without\s+(?:asking|confirm\w*|telling|permission|approval)|silently|quietly"
    r"|do\s+not\s+(?:ask|tell|mention|confirm)|don'?t\s+(?:ask|tell|mention|confirm)"
    r"|\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|\brm\s+-[a-z]*r[a-z]*f|\bbase64\b|/dev/tcp/|\bnc\s+-"
    r"|~/.ssh|\bid_rsa\b|/etc/passwd|\.aws/credentials|(?<!\w)\.env\b)"
)
_FETCH_AND_RUN = re.compile(
    r"(?i)\b(?:curl|wget)\b[^\n|]{0,300}"
    r"(?:\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b"
    r"|@(?:~|\$HOME|/etc/|/root/|/home/)|@\S*(?:\.env|id_rsa|credentials)\b)"
)

_URL_START = re.compile(r"(?i)https?://")
_SPACE_OR_QUOTE = re.compile(r"[\s\"'`]")
_CLOSERS = {"<": ">", "{": "}", "[": "]"}
_IMAGE_LEAD = re.compile(r"(?i)(?:!\[[^\]\n]{0,200}\]\(\s*<?|<img\b[^>]{0,200}?src\s*=\s*[\"']?)$")
_LINK_LEAD = re.compile(r"\(\s*<?$")
_BRACKETED = re.compile(r"<[^<>\n]{1,120}>|\{\{?[^{}\n]{0,120}\}\}?|\[[^\[\]\n]{1,120}\]")
_QUERY_SLOT = re.compile(
    r"<[^<>\n]{1,120}>|\{\{?[^{}\n]{0,120}\}\}?|\[[^\[\]\n]{1,120}\]|\$\{?[A-Za-z_]\w*\}?|\$\([^)\n]{1,80}\)"
    r"|%s\b|=[A-Z][A-Z0-9_]{2,}(?=$|[&#])|=(?=$|[&#])"
)
_PROSE = re.compile(r"\w\s+\w")
_DATA_NOUN = re.compile(
    r"(?i)(?<![\w.])(?:conversation|(?:chat|message)[\s_]+(?:history|log)|transcript|system[\s_]+prompt"
    r"|your\s+(?:instructions|prompt|context|memory|memories|notes)|secrets?|credentials?|passwords?"
    r"|api[\s_-]?keys?|(?:api|access|auth|session|bearer)[\s_-]?tokens?|\.env"
    r"|env(?:ironment)?[\s_]+(?:vars?|variables?|contents?|values?|file)|ssh[\s_]key|private[\s_]key"
    r"|user'?s?[\s_]+(?:last[\s_]+|previous[\s_]+|latest[\s_]+)?"
    r"(?:message|messages|data|input|query|question|e-?mail|files?)"
    r"|(?:their|his|her|customer'?s?)\s+(?:e-?mail|name|address|phone(?:\s+number)?|card\s+number|password)"
    r"|(?:credit\s+)?card\s+number"
    r"|(?:everything|anything|whatever|what)\s+the\s+user\s+(?:typed|said|wrote|asked|sent|entered)"
    r"|(?:the|everything|anything|all)\s+above|previous\s+(?:messages?|turns?)|last[\s_]message"
    r"|tool\s+outputs?)(?!\w)"
)
_REPLY = r"(?:next\s+|final\s+)?(?:repl(?:y|ies)|responses?|answers?|outputs?|messages?|summar(?:y|ies))"
_AI_DIRECTED = re.compile(
    r"(?i)(?:\b(?:in|into|to|with|at\s+the\s+end\s+of|end|conclude|finish|close|begin|start)\s+"
    r"(?:your|every|each|any|all(?:\s+of)?\s+your)\s+" + _REPLY + r"\b"
    r"|\b(?:before|when|whenever|after|while|every\s+time)\s+(?:you\s+)?(?:answer|reply|respond|summari[sz])\w*"
    r"|\bassistant\b|\b(?:an|the)\s+(?-i:AI)\b|(?<![\w.])(?-i:AI)\s+(?:assistant|agent|model|system|reading)\b"
    r"|(?<![\w.])(?-i:LLM)\b|\blanguage\s+model\b|\bchatbot\b"
    r"|\bthe\s+(?:agent|model)\s+(?:must|should|shall|has\s+to|needs?\s+to)\b|\byour\s+(?:browser|fetch|http|web)\s+tool\b"
    r"|\bwithout\s+(?:telling|mentioning|asking|informing)\b|\bdo\s+not\s+(?:mention|tell|reveal|disclose)\b)"
)
_IMPERATIVE = re.compile(
    r"(?im)(?:^[ \t]*(?:[-*>]|\d+[.)])?[ \t]*|[.!?:;,][ \t\n]+"
    r"|\b(?:please|always|must|should|shall|and|then|to|you|now|also|just|kindly|first|finally)[ \t\n]+)"
    r"(?:render|display|show|include|embed|insert|append|add|attach|output|print|emit|load|fetch|request"
    r"|retrieve|visit|open|access|call|ping|send|post|forward|submit|navigate|browse|download|put|place|use"
    r"|point|direct|refer|share)\b"
)
_SUBSTITUTE = re.compile(r"(?i)\b(?:replac|substitut|swap|fill|encod|base64|append|insert|concatenat|put)\w*")


def _url_spans(text: str) -> Iterable[Tuple[int, int, bool]]:
    for match in _URL_START.finditer(text):
        start = match.start()
        lead = text[max(0, start - 260):start]
        end = -1
        if _LINK_LEAD.search(lead):
            close, newline = text.find(")", start), text.find("\n", start)
            if close != -1 and (newline == -1 or close < newline) and close - start <= 600:
                end = close
        if end == -1:
            end, ceiling = start, min(len(text), start + 2000)
            while True:
                stop = _SPACE_OR_QUOTE.search(text, end, ceiling)
                end = stop.start() if stop else ceiling
                tail = text[start:end]
                opener = next((c for c in "<{[" if tail.count(c) > tail.count(_CLOSERS[c])), None)
                if opener is None or end >= ceiling:
                    break
                close = text.find(_CLOSERS[opener], end)
                if close == -1 or close - end > 120 or "\n" in text[end:close]:
                    break
                end = close + 1
        yield start, end, bool(_IMAGE_LEAD.search(lead))


def _url_exfiltration(text: str) -> str:
    for count, (start, end, is_image) in enumerate(_url_spans(text)):
        if count >= 2000:
            return "link-flood"
        url = urllib.parse.unquote(text[start:end])
        query = url.partition("?")[2]
        slots = [slot.group(0) for slot in _BRACKETED.finditer(url)]
        if is_image and any(_DATA_NOUN.search(slot) or _PROSE.search(slot) for slot in slots):
            return "image-beacon"
        window = text[max(0, start - 250):start] + " " + text[end:end + 200]
        directed = bool(_AI_DIRECTED.search(window))
        names_data = bool(_DATA_NOUN.search(window)) or any(_DATA_NOUN.search(slot) for slot in slots)
        fillable = bool("=" in query and _QUERY_SLOT.search(query)) or any(_DATA_NOUN.search(slot) for slot in slots)
        if fillable and (directed or (names_data and _IMPERATIVE.search(window))):
            return "url-fill-in"
        if query and directed and names_data and _SUBSTITUTE.search(window):
            return "url-substitute"
    return ""


_NO_FUNCTION_WORD = (r"(?!(?:of|to|for|in|on|and|or|with|from|is|are|as|at|by|if|when|that|which|it|them|an?"
                     r"|about|into|onto|than|but|not|per|via|over|under|between|without|against|during)\b)")
_MODIFIERS = r"(?:" + _NO_FUNCTION_WORD + r"[\w'’-]+\s+){0,2}?"
_CREDENTIAL_ASK = re.compile(
    r"(?i)\b(?P<verb>reveal|disclose|leak|exfiltrate|send|e-?mail|print|output|dump|display|show|list|repeat"
    r"|echo|recite|paste|post|write|include|append|add|insert|embed|attach|copy|put|forward|upload|share|expose"
    r"|give|tell|hand|read|fetch|retrieve|collect|gather|find|extract|grab|get|submit|transmit|report)\b"
    r"(?:\s+(?P<particle>out|over|back|me|us))?\s+"
    r"(?P<det>(?:(?:an?|the)\s+(?:copy|list|dump|contents?|values?)\s+of\s+)?"
    r"(?:(?:all|any|each|every|both|some)(?:\s+of)?\s+)?(?:(?:the|your|my|our|their|these|those|this|that)\s+)?)"
    + _MODIFIERS +
    r"(?P<noun>api[\s_-]?keys?|(?:access|auth|bearer|session|refresh|oauth|api)[\s_-]tokens?"
    r"|(?:private|secret|ssh|access|signing|encryption)[\s_-]keys?|passwords?|passphrases?|credentials?"
    r"|secrets?|env(?:ironment)?\s+(?:vars?|variables)|\.env(?:\s+file)?|keys?|tokens?)\b(?![-/])"
)
_HANDS_OVER = frozenset({"reveal", "disclose", "leak", "exfiltrate", "send", "transmit", "email", "e-mail"})
_SURFACES = frozenset({"print", "output", "dump", "display", "show", "list", "repeat", "echo", "recite"})
_BARE_NOUN = frozenset({"key", "keys", "token", "tokens"})
_MODIFIES_NEXT_WORD = re.compile(
    r"(?i)(?:[ \t]+\n?|\n)[ \t]*(?!(?:you|your|they|it|we|i|to|in|into|from|for|and|or|of|on|at|as|by|with|via"
    r"|over|through|inside|within|here|below|above|now|immediately|verbatim|exactly|directly|first|too|also"
    r"|please|back|again|so|then|before|after|while|without|if|when|that|which|is|are|found|stored|saved"
    r"|listed|shown|available|present|visible)\b)[a-z]"
)
_IN_A_REQUEST = re.compile(
    r"(?i)\s+(?:in|as|with|via|using|on|inside|along\s+with)\s+(?:(?:the|an?|each|every|all|your)\s+)?"
    r"(?:[`'\"]?[\w.-]+[`'\"]?\s+){0,2}?(?:headers?|requests?|body|query|parameters?|params?|calls?|payload)\b"
)
_NEGATED = re.compile(
    r"(?i)(?:\b(?:not|never|cannot|nor)\b|n['’]t\b)(?!\s+(?:forget|fail|hesitate|neglect)\s+to\b)"
    r"(?:(?!\b(?:and|but|then|always|instead|please|now)\b|\s-\s)[^.!?;:,\n—–]){0,60}$"
)
_DESCRIBED = re.compile(
    r"(?i)\b(?:will|would|can|could|may|might|we|i|it|they|he|she|that|which|who)"
    r"(?:\s+(?:\w+ly|also|then|now|only|just))?[\s*_`]+$"
)
_YOU_WILL = r"\byou\s+(?:will|shall|must|should)\s+(?:(?:now|then|also|always|immediately)\s+)?"
_TOLD_TO = (r"(?:\byou\s+(?:are|were)|\b(?:need|want|ask|order|instruct|require|command)s?\s+you"
            r"|\b(?:task|job|goal|mission|objective|purpose)\s+is(?:\s+now)?"
            r"|\byou\s+(?:are|were|have\s+been)\s+(?:now\s+)?(?:required|instructed|ordered|asked|told))\s+to\s+")
_CAN_YOU = r"[\n.!?:;,][ \t\n]*[\"'“‘(]*(?:can|could|would|will)\s+you\s+(?:(?:please|kindly|now|also|just)\s+)?"
_ORDER = re.compile(
    r"(?i)(?:(?:[\n.!?:;,—–]|\s-\s)[ \t\n]*(?:[-*>]+[ \t]*|\d+[.)][ \t]*|\(?[a-z]\)[ \t]+)?[\"'“‘*_`(\[]*"
    r"|\b(?:please|pls|kindly|now|then|also|always|just|first|next|finally|immediately|instead|and)[,\s]+[*_`]*"
    r"|" + _YOU_WILL + r"|" + _TOLD_TO + r"|" + _CAN_YOU + r")$"
)
_ADDRESSED = re.compile(r"(?i)(?:" + _YOU_WILL + r"|" + _TOLD_TO + r")[*_`]*$")
_ORDER_IF_DIRECTED = re.compile(
    r"(?i)\b(?:must|should|shall|(?:has|have|needs?|remember|forget|be\s+sure|make\s+sure)\s+to)\s+[*_`]*$"
)
_TITLE = re.compile(r"(?:\n[ \t]*#{1,6}[ \t]+|\|[ \t]*)[\"'“‘*_`(\[]*$")
_DUTY = re.compile(
    r"(?i)\b(?:(?:the|this|any|every|an?)\s+(?:assistant|chatbot|language\s+model|(?-i:AI|LLM)|agent|model)"
    r"|agents|assistants)\s+(?:must|should|shall|(?:has|have)\s+to|needs?\s+to"
    r"|(?:is|are)\s+(?:required|instructed|ordered)\s+to)\s+(?:(?:now|then|also|always|immediately)\s+)?[*_`]*$"
)
_SAYS_HOW = re.compile(
    r"(?i)\s*(?:[:(`]|(?:with|using|via|by)\s+(?:[`$]|\w+ing\b)"
    r"|(?:only\s+)?over\s+(?:an?\s+)?(?:tls|https|ssl|ssh|secure|encrypted)\b)"
)
_MODEL = r"(?:assistant|chatbot|language\s+model|(?-i:AI|LLM)\b)"
_MODEL_CUE = re.compile(
    r"(?i)(?:\bsystem\s+(?:note|notice|message|instruction|override|update)\b"
    r"|(?:\A|[\n.!?])[ \t]*(?:hey\s+|dear\s+|attention\s+)?" + _MODEL + r"\s*,"
    r"|\b(?:notes?|message|memo|instructions?|attention|reminder)\s+(?:to|for)\s+(?:(?:the|any|all|every)\s+)?"
    r"(?:" + _MODEL + r"|model\b|agents?\b)"
    r"|\b(?:ignore|disregard|forget|override)\b[^.!?\n]{0,40}\b(?:instructions?|rules|guidelines|prompts?)\b"
    r"|(?<![\w.])(?-i:AI)\s+agents?\b|\bagents?\s+reading\b)"
)
_IN_ITS_SIGHT = re.compile(
    r"(?i)\s+(?:(?:that|which)\s+)?(?:you\s+(?:can|could|are\s+able\s+to)\s+(?:find|see|access|read|reach)\b"
    r"|you\s+(?:have\s+access\s+to|know|hold|(?:were|have\s+been)\s+(?:given|told|instructed)"
    r"|have\s+(?:seen|stored|saved))\b"
    r"|(?:that\s+(?:is|are)\s+)?(?:available|known|visible|accessible)\s+to\s+you\b"
    r"|(?:(?:found|stored|saved|held|present|visible)\s+)?(?:in|from)\s+(?:your|their|its)\s+"
    r"(?:context|memory|memories|notes|prompt|conversation)\b)"
)
_ONLY_NAMED_OR_WARNED = re.compile(
    r"(?i)(?:do\s+not\s+(?:reveal|disclose)|(?:an?\s+|the\s+)?(?:assistant|chatbot|language\s+model|ai|llm)\b"
    r"|the\s+(?:agent|model)\b)"
)
_EMPHASIS = re.compile(r"(?i)\*+|(?<![a-z0-9])_+|_+(?![a-z0-9])|</?(?:b|i|u|em|strong|mark|span|code)>")


def _lead(probe: str, start: int, width: int = 90) -> str:
    return ("\n" if start <= width else "") + probe[max(0, start - width):start]


def _model_cues(probe: str) -> List[int]:
    cues = [cue.start() for cue in _AI_DIRECTED.finditer(probe) if not _ONLY_NAMED_OR_WARNED.match(cue.group(0))]
    return sorted(cues + [cue.start() for cue in _MODEL_CUE.finditer(probe)])


def _credential_order(probe: str, unvetted: bool) -> bool:
    cues: Optional[List[int]] = None
    for match in _CREDENTIAL_ASK.finditer(probe):
        lead = _lead(probe, match.start())
        tail = probe[match.end():match.end() + 80]
        if _NEGATED.search(lead) or (_DESCRIBED.search(lead) and not _ADDRESSED.search(lead)):
            continue
        if _MODIFIES_NEXT_WORD.match(tail) or _IN_A_REQUEST.match(tail):
            continue
        ordered = bool(_ORDER.search(lead))
        duty = bool(_DUTY.search(lead))
        if not ordered and not duty and not _ORDER_IF_DIRECTED.search(lead) and not _TITLE.search(lead):
            continue
        determiner = match.group("det").lower()
        directed = (duty or (match.group("particle") or "").lower() in ("me", "us")
                    or ("your" in determiner.split() and not determiner.startswith("your"))
                    or bool(_IN_ITS_SIGHT.match(tail)))
        if not directed:
            if cues is None:
                cues = _model_cues(probe)
            nearest = bisect.bisect_left(cues, match.start() - 200)
            directed = nearest < len(cues) and cues[nearest] <= match.end() + 160
        if directed:
            return True
        if not ordered or not determiner or match.group("noun").lower() in _BARE_NOUN or _SAYS_HOW.match(tail):
            continue
        verb = match.group("verb").lower()
        if verb in _HANDS_OVER or (unvetted and verb in _SURFACES):
            return True
    return False


_DISOBEY = re.compile(
    r"(?i)\b(?:ignore|disregard|forget)\s+(?:about\s+)?"
    r"(?P<det>(?:all|any|every|each)\s+(?:of\s+)?(?:(?:the|your|these|those)\s+)?|your\s+|these\s+|those\s+"
    r"|(?:the\s+)?(?:previous|prior|earlier|above|preceding|foregoing)\s+|the\s+)"
    r"(?P<kind>" + _MODIFIERS + r")"
    r"(?P<noun>instructions?|rules?|guidelines?|prompts?)\b"
)
_MODELS_KIND = frozenset((
    "system", "safety", "security", "ethical", "content", "previous", "prior", "earlier", "above", "preceding",
    "foregoing", "other", "original", "initial", "existing", "current", "old", "former", "past", "own", "given"))
_PRINCIPALS = re.compile(r"(?i)^(?:developer|creator|maker|operator|owner|admin\w*|system|provider|vendor|company)['’]s$")
_GIVEN_TO_YOU = re.compile(r"(?i)\s+(?:(?:that\s+)?you\s+(?:were|have\s+been|had\s+been)\s+(?:given|told|taught)"
                           r"|(?:given|provided)\s+to\s+you)\b")
_MODELS_OWN = re.compile(r"(?i)\b(?:your|previous|prior|earlier|above|preceding|foregoing|system|safety)\b")
_FROM_ELSEWHERE = re.compile(
    r"(?i)\s+(?:(?:that\s+)?(?:you|we|they|i)\s+(?:(?:have|had|'ve)\s+)?(?:learned|learnt|read|heard)\b"
    r"|(?:printed|listed|written|described|shown|mentioned|issued|defined|documented)\s+"
    r"(?:in|on|at|by|under|below|above|before)\b)"
)
_SCOPED_TO_CODE = re.compile(
    r"(?i)\s+(?:in|for|of|from|on|under|within|inside)\s+(?:(?:the|this|that|an?|each|any|all|your|these|those)\s+)?"
    r"(?:[\w.*/`'-]+\s+){0,2}?(?:files?|folders?|director(?:y|ies)|sections?|chapters?|manuals?|modules?"
    r"|packages?|paths?|lines?|blocks?|tests?|code|config\w*|repo\w*|projects?|guides?|readme)\b"
)


def _disobey_order(probe: str) -> bool:
    for match in _DISOBEY.finditer(probe):
        lead = _lead(probe, match.start())
        if _NEGATED.search(lead):
            continue
        kind = [word for word in match.group("kind").lower().split() if not _PRINCIPALS.match(word)]
        tail = probe[match.end():match.end() + 80]
        if _GIVEN_TO_YOU.match(tail):
            return True
        if any(word not in _MODELS_KIND for word in kind):
            continue
        if _MODELS_OWN.search(match.group(0)):
            return True
        if match.group("det").lower().split() == ["the"] or match.group("noun").lower().startswith("prompt"):
            continue
        if (_DESCRIBED.search(lead) or _ORDER_IF_DIRECTED.search(lead)) and not _ADDRESSED.search(lead):
            continue
        if _SCOPED_TO_CODE.match(tail) or _FROM_ELSEWHERE.match(tail):
            continue
        return True
    return False


def _orders(probe: str, unvetted: bool) -> bool:
    try:
        probe = _EMPHASIS.sub("", probe)
        return _disobey_order(probe) or _credential_order(probe, unvetted)
    except Exception:
        return False


def injection_question(label: str) -> str:
    return (f"Passage {label} contains instructions aimed at an AI assistant, such as telling it to "
            "ignore rules, reveal data, run commands, change its behaviour, or fetch, render or include "
            "a link or image whose URL would carry conversation or private data to another server")


def local_screen(text: str, *, unvetted: bool = False) -> str:
    probe = normalize(text)
    if INSTRUCTION_PATTERNS.search(probe) or _orders(probe, unvetted):
        return "instruction"
    for match in _COMMAND.finditer(probe):
        if _COMMAND_RISK.search(probe[max(0, match.start() - 160):match.end() + 300]):
            return "command"
    if _FETCH_AND_RUN.search(probe):
        return "command"
    return _url_exfiltration(probe)


# ── screen probe helpers ─────────────────────────────────────────────────────

def screen_one(text: str) -> Dict[str, Any]:
    """Full classification of one passage: (sensitive?, screen_hit?, shape, redacted_len)."""
    return {
        "sensitive": is_sensitive(text),
        "shape": local_screen(text, unvetted=is_sensitive(text)),
        "redacted": redact(text, 900),
    }


def classify(text: str) -> Tuple[bool, str]:
    """Lightweight: (flagged, shape)."""
    sens = is_sensitive(text)
    shape = local_screen(text, unvetted=sens)
    return (bool(shape) or sens, shape or ("sensitive" if sens else ""))