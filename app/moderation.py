"""
Content moderation and name validation utilities for Studiamo.

Provides fast, server-side filtering of offensive language, hate speech, slurs,
leetspeak evasions, Zalgo/unicode exploits, and reserved system handles for
usernames and public leaderboard display names.
"""

import re
import unicodedata
from typing import Optional, Tuple

# System reserved names that users cannot claim for username or display name
RESERVED_EXACT_NAMES = {
    "admin",
    "administrator",
    "studiamo",
    "studiamo_admin",
    "studiamo_official",
    "studiamo_team",
    "moderator",
    "mod",
    "official",
    "support",
    "system",
    "staff",
    "helpdesk",
    "root",
    "superuser",
    "owner",
    "null",
    "undefined",
    "anonymous",
    "learner",
    "guest",
    "bot",
}

# Substring patterns for system impersonation
RESERVED_SUBSTRINGS = (
    "studiamo",
    "administrator",
    "official_support",
    "system_admin",
)

# Invisible, zero-width, and directional unicode control characters to strip
ZERO_WIDTH_CHARS = re.compile(
    r"[\u200B-\u200D\uFEFF\u00AD\u2060\u200E\u200F\u202A-\u202E\u034F\u180E\uFFF9-\uFFFB]"
)

# Character translation for leetspeak and common obfuscation normalization
LEET_TRANS = str.maketrans({
    "@": "a",
    "4": "a",
    "8": "b",
    "(": "c",
    "[": "c",
    "{": "c",
    "3": "e",
    "€": "e",
    "9": "g",
    "!": "i",
    "1": "i",
    "|": "i",
    "0": "o",
    "5": "s",
    "$": "s",
    "§": "s",
    "7": "t",
    "+": "t",
})

# Unequivocal offensive roots (English and German) that match as substrings (e.g. "fucking", "dumbfuck", "motherfucker")
SUBSTRING_PROFANITY_PATTERNS = [
    # Slurs and hate speech
    r"n+[i1!|]+g+g+[a4e3iouy\d]+",
    r"n+[i1!|]+g+g+a+r?",
    r"n+e+g+e+r+",
    r"f+a+g+g+o+t+",
    r"f+a+g+s+",
    r"k+i+k+e+s?",
    r"c+h+i+n+k+s?",
    r"w+e+t+b+a+c+k+",
    r"t+r+a+n+n+y+",
    r"g+o+o+k+s?",
    r"h+i+t+l+e+r+",
    r"n+a+z+i+s?",
    r"s+w+a+s+t+i+k+a+",
    r"h+a+k+e+n+k+r+e+u+z+",
    r"s+i+e+g+\s*h+e+i+l+",
    r"h+e+i+l+\s*h+i+t+l+e+r+",
    r"k+k+k+",

    # Severe vulgarities / sexual explicitness
    r"f+[\*u_.-]*c+k+",
    r"f+u+k+k+",
    r"f+c+k+",
    r"b+[\*i!1_.-]*t+c+h+",
    r"c+u+n+t+",
    r"m+o+t+h+e+r+f+u+c+k+",
    r"c+o+c+k+s+u+c+k+",
    r"d+i+c+k+h+e+a+d+",
    r"p+u+s+s+y+",
    r"b+l+o+w+j+o+b+",
    r"c+u+m+s+h+o+t+",
    r"b+i+t+c+h+",
    r"a+s+s+h+o+l+e+",
    r"b+a+s+t+a+r+d+",
    r"r+a+p+i+s+t+",

    # Common German vulgarities / slurs
    r"h+u+r+e+n+s+o+h+n+",
    r"h+u+r+e+n?",
    r"f+o+t+z+e+",
    r"w+i+c+h+s+e+r+",
    r"w+i+c+h+s+e+n+",
    r"s+c+h+l+a+m+p+e+",
    r"m+i+s+s+g+e+b+u+r+t+",
    r"a+r+s+c+h+l+o+c+h+",
    r"v+o+t+z+e+",
    r"s+p+a+s+t+i+",
    r"k+a+n+a+k+e+",
    r"k+a+n+a+c+k+e+",
]

# Standalone or boundary-guarded words to avoid False Positives (e.g. "pass", "compass", "classic", "title")
BOUNDARY_PROFANITY_PATTERNS = [
    r"a+s+s+",
    r"a+s+s+e+s",
    r"d+i+c+k+s?",
    r"c+o+c+k+s?",
    r"s+l+u+t+s?",
    r"w+h+o+r+e+s?",
    r"p+o+r+n+o?",
    r"s+h+i+t+s?",
    r"s+h+i+t+t+y+",
    r"c+u+m+s?",
    r"s+p+i+c+s?",
    r"k+y+s+",
]

COMPILED_SUBSTRING_REGEXES = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in SUBSTRING_PROFANITY_PATTERNS
]

COMPILED_BOUNDARY_REGEXES = [
    re.compile(rf"(?:^|\b|\W|_{{1,2}}){pattern}(?:$|\b|\W|_{{1,2}})", re.IGNORECASE)
    for pattern in BOUNDARY_PROFANITY_PATTERNS
]


def strip_invisible_characters(text: str) -> str:
    """Removes zero-width, invisible, and control characters from text."""
    if not text:
        return ""
    # Strip known zero-width characters
    cleaned = ZERO_WIDTH_CHARS.sub("", text)
    # Strip ASCII control characters except standard space
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Cc")
    return cleaned


def normalize_text_for_moderation(text: str) -> str:
    """
    Normalizes a string for moderation checks.
    Decomposes unicode diacritics, translates leetspeak, and collapses repeated characters.
    """
    if not text:
        return ""

    # 1. Strip zero-width & invisible characters
    cleaned = strip_invisible_characters(text).lower()

    # 2. Decompose unicode characters (e.g., e-acute -> e + accent) and remove combining marks
    decomposed = unicodedata.normalize("NFKD", cleaned)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))

    # 3. Translate common leetspeak substitutions
    translated = without_marks.translate(LEET_TRANS)

    # 4. Collapse consecutive duplicate characters (e.g., "fuuuuck" -> "fuck")
    collapsed = re.sub(r"(.)\1{2,}", r"\1\1", translated)

    return collapsed


def is_inappropriate_text(text: str) -> bool:
    """
    Returns True if the text contains prohibited profanity, hate speech, slurs,
    or evasive leetspeak variants.
    """
    if not text:
        return False

    raw_lower = text.lower()
    normalized = normalize_text_for_moderation(text)

    # Substitute common symbol wildcards (e.g., "f*ck" -> "fuck", "b*tch" -> "bitch")
    wildcard_replaced = re.sub(r"[\*\.\-\_\~]", "", normalized)

    # Strip all non-alphanumeric chars to detect spaced words like "f u c k" or "f_u_c_k"
    alphanumeric_only = re.sub(r"[^a-z0-9]", "", normalized)
    collapsed_single = re.sub(r"(.)\1+", r"\1", alphanumeric_only)

    targets = (raw_lower, normalized, wildcard_replaced, alphanumeric_only, collapsed_single)

    for target in targets:
        if not target:
            continue
        # Check substring matches
        for regex in COMPILED_SUBSTRING_REGEXES:
            if regex.search(target):
                return True
        # Check boundary matches
        for regex in COMPILED_BOUNDARY_REGEXES:
            if regex.search(target):
                return True

    return False




def is_reserved_name(name: str) -> bool:
    """Returns True if the name attempts to impersonate system or admin roles."""
    if not name:
        return False

    normalized = strip_invisible_characters(name).strip().lower()
    clean_alpha = re.sub(r"[^a-z0-9]", "", normalized)

    # Exact match check
    if normalized in RESERVED_EXACT_NAMES or clean_alpha in RESERVED_EXACT_NAMES:
        return True

    # Substring check for official handles
    for reserved in RESERVED_SUBSTRINGS:
        if reserved in normalized or reserved in clean_alpha:
            return True

    return False


def validate_display_name(display_name: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validates a leaderboard display name.

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid.
    """
    if display_name is None:
        return False, "Display name cannot be empty."

    cleaned = strip_invisible_characters(display_name).strip()

    if not cleaned:
        return False, "Display name cannot be empty or solely whitespace."

    if len(cleaned) < 2:
        return False, "Display name must be at least 2 characters long."

    if len(cleaned) > 30:
        return False, "Display name cannot exceed 30 characters."

    # Must contain at least one alphanumeric character
    if not any(c.isalnum() for c in cleaned):
        return False, "Display name must contain at least one letter or number."

    # Reserved name check
    if is_reserved_name(cleaned):
        return False, "This display name is reserved. Please choose a different name."

    # Inappropriate content check
    if is_inappropriate_text(cleaned):
        return False, "This display name contains restricted or inappropriate language."

    return True, None


def validate_username(username: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validates an account username handle.

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid.
    """
    if username is None:
        return False, "Username cannot be empty."

    cleaned = strip_invisible_characters(username).strip()

    if not cleaned:
        return False, "Username cannot be empty."

    if len(cleaned) < 3:
        return False, "Username must be at least 3 characters long."

    if len(cleaned) > 30:
        return False, "Username cannot exceed 30 characters."

    # Usernames must strictly be alphanumeric, hyphens, or underscores
    if not re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
        return False, "Username may only contain letters, numbers, hyphens, and underscores."

    # Reserved handle check
    if is_reserved_name(cleaned):
        return False, "This username is reserved. Please choose a different username."

    # Inappropriate content check
    if is_inappropriate_text(cleaned):
        return False, "This username contains restricted or inappropriate language."

    return True, None


def sanitize_leaderboard_name(name: Optional[str], fallback_index: int = 1) -> str:
    """
    Sanitizes a name for safe rendering on the leaderboard.
    If the name is missing, invalid, or violates content rules, returns a clean fallback.
    """
    if not name:
        return f"Learner {fallback_index}"

    cleaned = strip_invisible_characters(name).strip()
    if not cleaned:
        return f"Learner {fallback_index}"

    # If it fails moderation checks, mask it with the fallback
    if is_inappropriate_text(cleaned) or is_reserved_name(cleaned):
        return f"Learner {fallback_index}"

    # Ensure max display length
    if len(cleaned) > 30:
        cleaned = cleaned[:30].strip()

    return cleaned
