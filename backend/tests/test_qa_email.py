"""
Gmail polling for QA replies.

The parsing is where this breaks in practice: a reply quotes the original, and
without stripping that the classifier reads our own "reply if broken"
boilerplate instead of the tester's answer.
"""

import base64

from app.services.qa_email_poller import _header, _plain_text, strip_quoted_reply


def encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class TestQuoteStripping:
    def test_removes_gmail_attribution_and_quote(self):
        reply = (
            "Still failing on staging.\n"
            "\n"
            "On Tue, Aug 12, 2026 at 3:00 PM Locus <bot@x.com> wrote:\n"
            "> Ready to test\n"
            "> Reply to this email if something does not work\n"
        )
        assert strip_quoted_reply(reply) == "Still failing on staging."

    def test_removes_quoted_lines_without_attribution(self):
        reply = "Works fine.\n> original message\n> more quoted"
        assert strip_quoted_reply(reply) == "Works fine."

    def test_stops_at_signature_separator(self):
        reply = "Looks good.\n--\nPriya\nQA Lead"
        assert strip_quoted_reply(reply) == "Looks good."

    def test_stops_at_outlook_separator(self):
        reply = "Broken.\n-----Original Message-----\nFrom: bot"
        assert strip_quoted_reply(reply) == "Broken."

    def test_preserves_multiline_feedback(self):
        reply = "Two problems:\n1. Timeout still 30s\n2. Retry count wrong"
        assert strip_quoted_reply(reply) == reply

    def test_empty_input(self):
        assert strip_quoted_reply("") == ""


class TestHeaderReading:
    def test_reads_header_case_insensitively(self):
        message = {"payload": {"headers": [
            {"name": "In-Reply-To", "value": "<abc@x>"},
            {"name": "SUBJECT", "value": "Re: test"},
        ]}}
        assert _header(message, "in-reply-to") == "<abc@x>"
        assert _header(message, "Subject") == "Re: test"

    def test_missing_header_yields_empty_string(self):
        assert _header({"payload": {"headers": []}}, "In-Reply-To") == ""


class TestBodyExtraction:
    def test_reads_flat_plain_text(self):
        message = {"payload": {
            "mimeType": "text/plain",
            "body": {"data": encode("still broken")},
        }}
        assert _plain_text(message) == "still broken"

    def test_prefers_plain_text_over_html_in_multipart(self):
        message = {"payload": {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encode("plain version")}},
                {"mimeType": "text/html", "body": {"data": encode("<p>html</p>")}},
            ],
        }}
        assert _plain_text(message) == "plain version"

    def test_finds_nested_plain_text(self):
        message = {"payload": {
            "mimeType": "multipart/mixed",
            "parts": [{
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encode("nested")}},
                ],
            }],
        }}
        assert _plain_text(message) == "nested"

    def test_html_only_message_yields_empty(self):
        message = {"payload": {
            "mimeType": "text/html",
            "body": {"data": encode("<p>hi</p>")},
        }}
        assert _plain_text(message) == ""
