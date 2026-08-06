"""Central registry of this app's own diagnostic codes.

Real HTTP status codes (404, 429, 500...) are used as-is wherever OpenDota
actually gave us one - no point inventing a new number for something that
already has a standard one. The hex codes below are only for failures that
don't come with a status code of their own: DNS, TLS, timeouts, and local
machine/permission problems. Grouped by where in the chain they happen
(machine -> network -> Dota -> OCR/profile-lookup), matching the order
checks run in launcher_checks.py.

These show up appended to user-facing messages (e.g. "...недоступен
[0x2002]") so two people describing "same-looking" errors to each other (or
in a bug report) can tell whether it's actually the same failure.
"""

# 0x1xxx - local machine (missing software/permissions, before any network call)
MISSING_DEPENDENCY = 0x1001
TESSERACT_MISSING = 0x1002
TESSERACT_LANG_MISSING = 0x1003
PORTAL_UNAVAILABLE = 0x1004

# 0x2xxx - network path to OpenDota (no HTTP status code exists yet/at all)
DNS_FAILURE = 0x2001
CONNECTION_ERROR = 0x2002
TLS_ERROR = 0x2003
TIMEOUT = 0x2004
INVALID_JSON = 0x2005
# Not a transport failure - OpenDota answered fine, it just doesn't have
# this match_id indexed yet. Separate code because the fix is "wait", not
# "check your connection" (see last_match_watcher.py's timing caveat).
MATCH_NOT_INDEXED_YET = 0x2006

# 0x3xxx - Dota's own files/config on this machine
DOTA_DIR_MISSING = 0x3001
GSI_CFG_MISSING = 0x3002
GSI_PORT_BUSY = 0x3003
SERVER_LOG_MISSING = 0x3004
STEAM_ACCOUNT_UNKNOWN = 0x3005
LAST_MATCH_FILE_MISSING = 0x3006

# 0x4xxx - OCR / profile-lookup pipeline
REGION_NOT_CALIBRATED = 0x4001
CAPTURE_FAILED = 0x4002
OCR_EMPTY = 0x4003
PROFILE_NOT_FOUND = 0x4004

NAMES = {
    MISSING_DEPENDENCY: "MISSING_DEPENDENCY",
    TESSERACT_MISSING: "TESSERACT_MISSING",
    TESSERACT_LANG_MISSING: "TESSERACT_LANG_MISSING",
    PORTAL_UNAVAILABLE: "PORTAL_UNAVAILABLE",
    DNS_FAILURE: "DNS_FAILURE",
    CONNECTION_ERROR: "CONNECTION_ERROR",
    TLS_ERROR: "TLS_ERROR",
    TIMEOUT: "TIMEOUT",
    INVALID_JSON: "INVALID_JSON",
    MATCH_NOT_INDEXED_YET: "MATCH_NOT_INDEXED_YET",
    DOTA_DIR_MISSING: "DOTA_DIR_MISSING",
    GSI_CFG_MISSING: "GSI_CFG_MISSING",
    GSI_PORT_BUSY: "GSI_PORT_BUSY",
    SERVER_LOG_MISSING: "SERVER_LOG_MISSING",
    STEAM_ACCOUNT_UNKNOWN: "STEAM_ACCOUNT_UNKNOWN",
    LAST_MATCH_FILE_MISSING: "LAST_MATCH_FILE_MISSING",
    REGION_NOT_CALIBRATED: "REGION_NOT_CALIBRATED",
    CAPTURE_FAILED: "CAPTURE_FAILED",
    OCR_EMPTY: "OCR_EMPTY",
    PROFILE_NOT_FOUND: "PROFILE_NOT_FOUND",
}


def tag(code):
    """[0x1001] style suffix for one of this module's own codes."""
    return f"[0x{code:04X}]"


def http_tag(status_code):
    """[HTTP 429] style suffix for a real status code OpenDota returned."""
    return f"[HTTP {status_code}]"
