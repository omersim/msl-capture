"""
Allowlist-based domain validation for msl-capture.
To add a domain: add it to ALLOWED_PATTERNS and commit via SiteOps.
"""
import re
from urllib.parse import urlparse

# Canonical allowlist — only public sites with no PII risk
ALLOWED_PATTERNS = [
    # Israeli government
    r"(^|\.)gov\.il$",
    r"(^|\.)cbs\.gov\.il$",       # Central Bureau of Statistics
    r"(^|\.)boi\.org\.il$",        # Bank of Israel
    r"(^|\.)taxes\.gov\.il$",
    r"(^|\.)nta\.gov\.il$",        # Israeli Tax Authority
    r"(^|\.)moj\.gov\.il$",        # Ministry of Justice
    r"(^|\.)btl\.gov\.il$",        # National Insurance Institute
    r"(^|\.)isa\.gov\.il$",        # Israel Securities Authority
    # Course providers
    r"(^|\.)coursera\.org$",
    r"(^|\.)udemy\.com$",
    # Pricing pages (specific domains added by SiteOps as needed)
    r"(^|\.)plus500\.com$",
    r"(^|\.)etoro\.com$",
    r"(^|\.)trading212\.com$",
    r"(^|\.)tase\.co\.il$",        # Tel Aviv Stock Exchange
]

_compiled = [re.compile(p) for p in ALLOWED_PATTERNS]


def is_allowed(url: str) -> bool:
    """Return True if the URL's hostname is in the allowlist."""
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower()
        return any(pat.search(hostname) for pat in _compiled)
    except Exception:
        return False
