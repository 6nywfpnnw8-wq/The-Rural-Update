"""Offline tests. Production credentials are never used in this suite."""
import io
import json
import sys
import unittest
import urllib.error
import wave
from pathlib import Path
from datetime import datetime, timezone
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

    def test_current_account_limit_codes_are_preserved_without_error_prose(self):
        for code in ("credit_balance_exhausted", "organization_spend_limit_exceeded",
                     "project_spend_limit_exceeded", "organization_usage_limit_exceeded"):
            error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429,
                "private error prose", {}, io.BytesIO(json.dumps({"error":{
                    "code":code,"type":"insufficient_quota","message":"synthetic-private-key"}}).encode()))
            with self.subTest(code=code):
                parsed = access.safe_http_failure(error)
                client = Mock();client.post.side_effect = parsed
                report = access.run_check(client, "gpt-5-mini", include_audio=False)
                check = report["checks"][0]
                self.assertEqual(check["provider_code"], code)
                self.assertEqual(check["provider_type"], "insufficient_quota")
                self.assertFalse(check["retryable"])
                self.assertEqual(client.post.call_count, 1)
                self.assertNotIn("synthetic-private-key", json.dumps(report))

    def test_rate_limit_retains_numeric_server_delay_without_retrying(self):
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429,
            "ignored", {"Retry-After":"56"}, io.BytesIO(
                b'{"error":{"code":"slow_down","type":"rate_limit_error"}}'))
        client = access.Client("synthetic")
        client._opener = Mock();client._opener.open.side_effect = error
        report = access.run_check(client, "gpt-5-mini", include_audio=False)
        check = report["checks"][0]
        self.assertEqual(check["provider_code"], "slow_down")
        self.assertEqual(check["retry_after_seconds"], 56)
        self.assertTrue(check["retryable"])
        self.assertEqual(check["recovery_action"], "wait_and_reduce_request_rate")
        self.assertEqual(client._opener.open.call_count, 1)

    def test_retry_after_http_date_is_reported_as_seconds(self):
        now = datetime(2026,11,1,16,0,tzinfo=timezone.utc)
        self.assertEqual(access.retry_after_seconds("Sun, 01 Nov 2026 16:01:30 GMT", now),90)
        self.assertEqual(access.retry_after_seconds("Sun, 01 Nov 2026 15:59:30 GMT", now),0)

    def test_malformed_retry_headers_are_not_echoed(self):
        for value in (None,"","-1","1.5","synthetic-private-key","9999999999999999"):
            with self.subTest(value=value):self.assertIsNone(access.retry_after_seconds(value))

    def test_unknown_429_is_not_assumed_to_be_a_temporary_rate_limit(self):
        error = access.CheckFailure("provider_http_error",429)
        detail = access.recovery_details(error)
        self.assertIsNone(detail["retryable"])
        self.assertIsNone(detail["provider_code"])
        self.assertEqual(detail["recovery_action"],"inspect_provider_condition")

    def test_quota_type_remains_actionable_when_code_is_unknown(self):
        error = access.CheckFailure("provider_http_error",429,error_type="insufficient_quota")
        detail = access.recovery_details(error)
        self.assertFalse(detail["retryable"])
        self.assertEqual(detail["recovery_action"],"review_api_credits_and_limits")

    def test_quota_condition_does_not_become_retryable_from_a_header(self):
        error = access.CheckFailure("provider_http_error",429,"credit_balance_exhausted",
            error_type="insufficient_quota",retry_after_seconds=60)
        self.assertFalse(access.recovery_details(error)["retryable"])

    def test_unknown_error_types_and_headers_are_not_exposed(self):
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses",429,
            "ignored",{"Retry-After":"synthetic-private-header"},io.BytesIO(
                b'{"error":{"code":"synthetic-private-code","type":"synthetic-private-type"}}'))
        detail = access.recovery_details(access.safe_http_failure(error))
        self.assertNotIn("synthetic-private",json.dumps(detail))
        self.assertNotIn("provider_type",detail)
        self.assertNotIn("retry_after_seconds",detail)

    def test_temporary_overload_is_distinct_from_account_limits(self):
        error = access.CheckFailure("provider_http_error",503,"server_is_overloaded",
            error_type="service_unavailable_error")
        self.assertEqual(access.recovery_details(error)["recovery_action"],"wait_for_provider_capacity")
        self.assertTrue(access.recovery_details(error)["retryable"])

    def test_authentication_errors_remain_distinct_from_limits(self):
        error = access.CheckFailure("provider_http_error",401,"invalid_api_key")
        self.assertEqual(access.recovery_details(error)["recovery_action"],"check_api_credentials")
        self.assertFalse(access.recovery_details(error)["retryable"])


if __name__ == "__main__":
    unittest.main()

