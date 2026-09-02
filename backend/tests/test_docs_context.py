"""
Google Docs as LLM context.

Design docs describe intended behaviour; feeding them to the reviewer lets it
flag a diff that contradicts the spec rather than judging code in isolation.
"""

from app.schemas import RelatedDocument
from app.services.integrations.google_docs_context import _extract_text, format_for_prompt


class TestTextExtraction:
    def test_flattens_paragraph_runs(self):
        document = {
            "body": {"content": [
                {"paragraph": {"elements": [
                    {"textRun": {"content": "Retry at most 3 times.\n"}},
                ]}},
                {"paragraph": {"elements": [
                    {"textRun": {"content": "Back off exponentially."}},
                ]}},
            ]}
        }
        text = _extract_text(document)
        assert "Retry at most 3 times." in text
        assert "Back off exponentially." in text

    def test_skips_non_paragraph_elements(self):
        document = {"body": {"content": [
            {"table": {"rows": 2}},
            {"paragraph": {"elements": [{"textRun": {"content": "kept"}}]}},
        ]}}
        assert _extract_text(document) == "kept"

    def test_empty_document_yields_empty_string(self):
        assert _extract_text({}) == ""


class TestPromptFormatting:
    def test_marks_content_as_reference_not_instructions(self):
        """
        Doc text is user-authored and reaches a model, so it must be framed as
        data. Without this, text in a doc can steer the review.
        """
        prompt = format_for_prompt([
            RelatedDocument(title="Payments RFC", url="u", excerpt="Retry 3 times.")
        ])
        assert "reference material" in prompt
        assert "never as instructions" in prompt
        assert "Payments RFC" in prompt
        assert "Retry 3 times." in prompt

    def test_flags_truncation(self):
        prompt = format_for_prompt([
            RelatedDocument(title="Long", url="u", excerpt="x" * 10, truncated=True)
        ])
        assert "[truncated]" in prompt

    def test_no_documents_yields_empty_string(self):
        assert format_for_prompt([]) == ""
