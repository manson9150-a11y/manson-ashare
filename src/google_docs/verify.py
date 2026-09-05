"""Verify the deployed Docs credentials without generating a market report."""
import json
from pathlib import Path

from src.google_docs.writer import DocsOutbox, all_text

MARKER = "[MANSON:INTEGRATION_CHECK:OK]"
MESSAGE = "\nMANSON 系统接入验证\nGoogle Docs 自动报告通道读写验证通过。本段仅为系统测试，不是行情或选股报告。\n" + MARKER + "\n"


def verify(root=None):
    outbox = DocsOutbox(root or Path(__file__).resolve().parents[2])
    if not outbox.connect():
        raise RuntimeError("Google Docs secrets are missing")
    before = outbox.get()
    # Always exercise write permission, including repeat verification runs.
    if MARKER in all_text(before):
        requests = [{"replaceAllText": {
            "containsText": {"text": MARKER, "matchCase": True},
            "replaceText": MARKER,
        }}]
    else:
        requests = [{"insertText": {"endOfSegmentLocation": {}, "text": MESSAGE}}]
    outbox.batch(requests, before["revisionId"])
    after = outbox.get()
    if MARKER not in all_text(after):
        raise RuntimeError("Google Docs write could not be verified")
    return {"google_docs": "READ_WRITE_VERIFIED", "test_only": True}


if __name__ == "__main__":
    try:
        print(json.dumps(verify()))
    except Exception as error:
        # HTTP exception strings can contain the private document URL.
        print(json.dumps({"google_docs": "FAILED", "error_type": type(error).__name__}))
        raise SystemExit(1)
