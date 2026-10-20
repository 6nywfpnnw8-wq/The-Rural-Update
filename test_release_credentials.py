"""Offline tests. Production credentials are never used in this suite."""
import io
import json
import sys
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import check_openai_access as access


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 16000)
    return output.getvalue()


def research():
    return json.dumps({
        "status": "completed",
        "output": [{"type": "web_search_call", "status": "completed"},
                   {"type": "message", "content": [
                       {"type": "output_text", "text": "https://www.cms.gov/"}]}],
    }).encode()


class CredentialAccessTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.post.side_effect = [
            research(), wav_bytes(), json.dumps({"text": access.PHRASE}).encode()]
        return client

    def test_three_capabilities_pass_without_publication(self):
        client = self.client()
        report = access.run_check(client, "gpt-5-mini")
        self.assertTrue(report["passed"])
        self.assertEqual(client.post.call_count, 3)
        self.assertFalse(report["publication_attempted"])
        self.assertFalse(report["research_budget_modified"])

    def test_first_auth_rejection_stops_without_retry(self):
        client = Mock()
        client.post.side_effect = access.CheckFailure(
            "provider_http_error", 401, "invalid_api_key")
        report = access.run_check(client, "gpt-5-mini")
        self.assertFalse(report["passed"])
        self.assertEqual(client.post.call_count, 1)
        self.assertEqual(report["checks"][0]["http_status"], 401)

    def test_speech_permissions_fail_separately(self):
        client = self.client()
        client.post.side_effect = [research(), access.CheckFailure("provider_http_error", 403)]
        report = access.run_check(client, "gpt-5-mini")
        self.assertEqual(report["checks"][-1]["stage"], "speech")
        self.assertFalse(report["passed"])

    def test_transcription_permissions_fail_separately(self):
        client = self.client()
        client.post.side_effect = [research(), wav_bytes(),
                                  access.CheckFailure("provider_http_error", 403)]
        report = access.run_check(client, "gpt-5-mini")
        self.assertEqual(report["checks"][-1]["stage"], "transcription")
        self.assertFalse(report["passed"])

    def test_no_web_search_does_not_pass(self):
        client = Mock()
        client.post.return_value = b'{"status":"completed","output":[]}'
        report = access.run_check(client, "gpt-5-mini")
        self.assertEqual(report["checks"][-1]["reason"], "web_search_not_completed")
        self.assertEqual(client.post.call_count, 1)

    def test_incomplete_model_response_blocked(self):
        client = Mock()
        client.post.return_value = b'{"status":"incomplete","output":[]}'
        report = access.run_check(client, "gpt-5-mini")
        self.assertFalse(report["passed"])
        self.assertEqual(client.post.call_count, 1)

    def test_arbitrary_exception_message_never_reported(self):
        client = Mock()
        client.post.side_effect = RuntimeError("private key secret-example")
        report = access.run_check(client, "gpt-5-mini")
        self.assertNotIn("secret-example", json.dumps(report))

    def test_error_body_is_not_echoed(self):
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 401,
                "bad private key", {}, io.BytesIO(
                    b'{"error":{"code":"invalid_api_key","message":"private key secret-example"}}'))
        result = access.safe_http_failure(error)
        self.assertEqual(result.code, "invalid_api_key")
        self.assertNotIn("secret-example", str(result))
        self.assertNotIn("private key", str(result))

    def test_unknown_error_code_not_echoed(self):
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 400,
                "ignored", {}, io.BytesIO(b'{"error":{"code":"secret-example"}}'))
        self.assertIsNone(access.safe_http_failure(error).code)

    def test_missing_or_whitespace_key_rejected(self):
        for key in ("", " key", "key ", "key\nsuffix"):
            with self.subTest(key=key):
                with self.assertRaises(access.CheckFailure):
                    access.Client(key)

    def test_transcription_does_not_receive_reference_text(self):
        data, content_type = access.multipart(wav_bytes())
        self.assertNotIn(access.PHRASE.encode(), data)
        self.assertNotIn(b'name="prompt"', data)
        self.assertIn("multipart/form-data", content_type)

    def test_incomplete_test_narration_is_not_a_pass(self):
        client = self.client()
        client.post.side_effect = [research(), wav_bytes(),
                                  b'{"text":"The Rural Update"}']
        self.assertFalse(access.run_check(client, "gpt-5-mini")["passed"])

    def test_redirect_rejected(self):
        with self.assertRaises(access.CheckFailure):
            access.NoRedirect().redirect_request(
                None, None, 302, "ignored", {}, "https://example.invalid/")

    def test_foreign_endpoint_never_sent(self):
        with self.assertRaises(access.CheckFailure):
            access.Client("synthetic").post("https://example.invalid/", {})


if __name__ == "__main__":
    unittest.main()
