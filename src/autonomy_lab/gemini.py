"""Gemini REST transport; no tool execution, simulated responses, or request retries."""

import math
import os
import re

import httpx

DEFAULT_MODEL = "gemini-3.8-flash"
_MODEL_ID = re.compile(r"gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_FINISH_REASONS = {
    "MAX_TOKENS", "SAFETY", "RECITATION", "LANGUAGE", "OTHER", "BLOCKLIST",
    "PROHIBITED_CONTENT", "SPII", "MALFORMED_FUNCTION_CALL", "IMAGE_SAFETY",
    "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS", "FINISH_REASON_UNSPECIFIED",
}


class GeminiError(RuntimeError):
    """A sanitized failure, with generation evidence available without logging it.

    ``response`` retains generation payloads, including token usage on incomplete
    generations. HTTP error bodies and request headers are deliberately excluded.
    A transport failure leaves billable request completion unknown; callers must
    not blindly retry it.
    """

    def __init__(self, message: str, *, response: dict | None = None, status_code: int | None = None):
        super().__init__(message)
        self.response = response
        self.status_code = status_code


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60,
        *,
        client: httpx.Client | None = None,
    ):
        key = api_key if api_key is not None else (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        if not isinstance(key, str) or not key.strip():
            raise GeminiError("Set GEMINI_API_KEY or GOOGLE_API_KEY before using Gemini.")
        if not key.isascii() or any(character.isspace() for character in key):
            raise GeminiError("Gemini API key must contain ASCII characters without whitespace.")
        if not isinstance(model, str) or not _MODEL_ID.fullmatch(model):
            raise ValueError("Invalid Gemini model ID; expected a bare gemini- model name.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Gemini timeout must be a finite positive number of seconds.")
        self.model = model
        self._api_key = key
        self._timeout = float(timeout)
        self._client = client

    def generate(
        self,
        contents: list,
        system_instruction: str,
        declarations: list,
        max_output_tokens: int = 2048,
    ) -> dict:
        """Request one complete candidate and retain every returned field.

        Complete content, including opaque thought signatures, must be included
        unchanged in subsequent conversation history. Partial, blocked, or
        malformed generations raise ``GeminiError`` rather than executing tools.
        The caller owns an injected HTTP client; otherwise each call closes its
        own client. No request is automatically retried.
        """
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 65536:
            raise ValueError("Gemini max_output_tokens must be an integer between 1 and 65536.")
        payload = self._input_payload(contents, system_instruction, declarations)
        payload["generationConfig"]["maxOutputTokens"] = max_output_tokens
        result = self._request_json("generateContent", payload)
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise GeminiError("Gemini returned no single usable candidate; inspect response evidence.", response=result)
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        if finish_reason != "STOP":
            # Do not reflect arbitrary provider text into error logs.
            reason = finish_reason if isinstance(finish_reason, str) and finish_reason in _FINISH_REASONS else "UNKNOWN"
            raise GeminiError(f"Gemini generation is incomplete ({reason}); no tool should execute.", response=result)
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts or not all(isinstance(part, dict) and part for part in parts):
            raise GeminiError("Gemini returned no usable content parts.", response=result)
        return result

    def count_tokens(self, contents: list, system_instruction: str, declarations: list) -> int:
        """Return the provider's tokenizer count for the complete supplied input.

        Use generateContentRequest rather than the contents-only shorthand so
        counting receives the same system text, tools, history, and signatures.
        This count is not a guaranteed billable prompt bound: observed responses
        also charge prior thinking carried by preserved signatures. The caller
        must reserve known prior thoughtsTokenCount separately and retain usage.
        Output limits are selected after counting and do not change input tokens.
        """
        request = self._input_payload(contents, system_instruction, declarations)
        request["model"] = f"models/{self.model}"
        result = self._request_json("countTokens", {"generateContentRequest": request})
        count = result.get("totalTokens")
        if type(count) is not int or count < 0:
            raise GeminiError("Gemini countTokens returned no valid nonnegative input token count.")
        return count

    @staticmethod
    def _input_payload(contents: list, system_instruction: str, declarations: list) -> dict:
        if not isinstance(contents, list) or not contents or not all(isinstance(item, dict) for item in contents):
            raise ValueError("Gemini contents must be a nonempty list of content objects.")
        if not isinstance(system_instruction, str):
            raise ValueError("Gemini system instruction must be text.")
        if not isinstance(declarations, list) or not all(isinstance(item, dict) for item in declarations):
            raise ValueError("Gemini declarations must be a list of function declaration objects.")
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 1, "candidateCount": 1},
        }
        if declarations:
            payload["tools"] = [{"functionDeclarations": declarations}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        return payload

    def _request_json(self, method: str, payload: dict) -> dict:
        try:
            if self._client is None:
                with httpx.Client(trust_env=False) as client:
                    response = self._post(client, method, payload)
            else:
                response = self._post(self._client, method, payload)
        except httpx.TimeoutException:
            raise GeminiError(f"Gemini {method} request timed out; completion is unknown. No retry was attempted.") from None
        except httpx.HTTPError:
            raise GeminiError(f"Gemini {method} transport failed; completion is unknown. No retry was attempted.") from None
        except (TypeError, ValueError):
            raise GeminiError("Gemini request could not be encoded or sent. No retry was attempted.") from None
        if not response.is_success:
            raise GeminiError(
                f"Gemini API returned HTTP {response.status_code}. No retry was attempted.",
                status_code=response.status_code,
            )
        try:
            result = response.json()
        except ValueError:
            raise GeminiError(f"Gemini {method} returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise GeminiError(f"Gemini {method} returned a non-object response.")
        return result

    def _post(self, client: httpx.Client, method: str, payload: dict) -> httpx.Response:
        return client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{method}",
            headers={"x-goog-api-key": self._api_key},
            json=payload,
            timeout=self._timeout,
            follow_redirects=False,
        )
