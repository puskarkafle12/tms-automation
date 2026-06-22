import unittest
from unittest.mock import patch

from utils.llm_chat import (
    LlmChatError,
    call_llm_chat,
    is_auth_llm_error,
    is_retryable_llm_error,
    should_fallback_llm_error,
    summarize_llm_providers,
)


class LlmChatTest(unittest.TestCase):
    def test_is_retryable_llm_error_detects_429(self):
        self.assertTrue(is_retryable_llm_error(Exception("Error code: 429 - Too Many Requests")))
        self.assertTrue(is_retryable_llm_error(Exception("nvidia AI request failed: model request failed")))
        self.assertTrue(is_retryable_llm_error(Exception("Error code: 413 - Request too large")))
        self.assertTrue(is_retryable_llm_error(Exception("Limit 12000, Requested 17720 tokens per minute")))
        self.assertTrue(is_retryable_llm_error(Exception("Error code: 404 - model not found")))
        self.assertFalse(is_retryable_llm_error(Exception("invalid api key")))

    def test_is_auth_llm_error_detects_401(self):
        self.assertTrue(is_auth_llm_error(Exception("Error code: 401 - Unauthorized")))
        self.assertTrue(is_auth_llm_error(Exception("Authentication failed")))
        self.assertTrue(should_fallback_llm_error(LlmChatError("Error code: 401 - Unauthorized")))

    @patch("utils.llm_chat._provider_chain", return_value=["groq", "nvidia"])
    @patch("utils.llm_chat._call_provider_chat")
    def test_call_llm_chat_falls_back_on_rate_limit(self, mock_call, _chain):
        mock_call.side_effect = [
            LlmChatError("groq AI request failed: Error code: 429 - Too Many Requests"),
            "STATUS: OK",
        ]
        content, provider = call_llm_chat("system", "hello")
        self.assertEqual(content, "STATUS: OK")
        self.assertEqual(provider, "nvidia")
        self.assertEqual(mock_call.call_count, 2)

    @patch("utils.llm_chat._provider_chain", return_value=["nvidia", "groq"])
    @patch("utils.llm_chat._call_provider_chat")
    def test_call_llm_chat_falls_back_on_auth_error(self, mock_call, _chain):
        mock_call.side_effect = [
            LlmChatError("nvidia AI request failed: Error code: 401 - Unauthorized"),
            "STATUS: OK",
        ]
        content, provider = call_llm_chat("full prompt", "hello", compact_system_prompt="compact prompt")
        self.assertEqual(content, "STATUS: OK")
        self.assertEqual(provider, "groq")
        self.assertEqual(mock_call.call_args_list[1].args[1], "compact prompt")

    @patch("utils.llm_chat._provider_chain", return_value=["gemini", "cohere", "groq"])
    @patch("utils.llm_chat._call_provider_chat")
    def test_call_llm_chat_falls_back_to_cohere_second(self, mock_call, _chain):
        mock_call.side_effect = [
            LlmChatError("gemini AI request failed: quota exceeded"),
            "STATUS: OK",
        ]
        content, provider = call_llm_chat("full prompt", "hello")
        self.assertEqual(content, "STATUS: OK")
        self.assertEqual(provider, "cohere")
        self.assertEqual(mock_call.call_count, 2)

    @patch("utils.llm_chat._provider_chain", return_value=["gemini", "groq"])
    @patch("utils.llm_chat._call_provider_chat")
    def test_call_llm_chat_uses_full_prompt_for_gemini(self, mock_call, _chain):
        mock_call.return_value = "STATUS: OK"
        call_llm_chat("full prompt", "hello", compact_system_prompt="compact prompt")
        self.assertEqual(mock_call.call_args.args[1], "full prompt")

    @patch("utils.llm_chat.test_llm_connection", return_value={"response_preview": "OK"})
    @patch("utils.llm_chat._provider_chain", return_value=["gemini", "cohere", "groq"])
    @patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "gemini-key",
            "COHERE_API_KEY": "cohere-key",
            "GROQ_API_KEY": "groq-key",
            "NVIDIA_API_KEY": "",
        },
        clear=False,
    )
    def test_summarize_llm_providers_marks_missing_nvidia_key(self, _chain, _probe):
        summary = summarize_llm_providers(probe=False)
        by_name = {item["provider"]: item for item in summary["providers"]}
        self.assertEqual(by_name["gemini"]["status"], "configured")
        self.assertEqual(by_name["nvidia"]["status"], "missing_key")
        self.assertFalse(by_name["nvidia"]["configured"])
        self.assertIn("gemini", summary["provider_chain"])


if __name__ == "__main__":
    unittest.main()
