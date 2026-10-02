"""Synchronous Mem0 platform client for repository tooling.

Uses only the Python standard library so it runs anywhere the rest of the
repository tooling runs. The API key is read from ``MEM0_API_KEY`` and is
never included in error messages.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

DEFAULT_BASE_URL = "https://api.mem0.ai"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
API_KEY_ENV_VAR = "MEM0_API_KEY"

ENTITY_FIELDS = ("user_id", "agent_id", "app_id", "run_id")
TERMINAL_EVENT_STATUSES = frozenset({"SUCCEEDED", "FAILED"})

Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


class Mem0Error(RuntimeError):
	"""Raised when the Mem0 API is misconfigured, unreachable, or answers with an error."""

	def __init__(self, message: str, *, status: int | None = None) -> None:
		super().__init__(message)
		self.status = status


def _urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
	request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			return response.status, response.read()
	except urllib.error.HTTPError as error:
		return error.code, error.read()


def _error_detail(data: Any) -> str | None:
	if isinstance(data, str):
		return data or None
	if isinstance(data, Mapping):
		for key in ("error", "detail", "message"):
			value = data.get(key)
			if isinstance(value, str) and value:
				return value
			if value is not None:
				return json.dumps(value, ensure_ascii=False)
	return None


def _require_text(value: str | None, name: str) -> str:
	if value is None or not value.strip():
		raise Mem0Error(f"{name} is required")
	return value.strip()


def _entity_values(user_id: str | None, agent_id: str | None, app_id: str | None, run_id: str | None) -> dict[str, str]:
	values = (user_id, agent_id, app_id, run_id)
	return {name: value for name, value in zip(ENTITY_FIELDS, values) if value is not None}


def _merged_filters(
	user_id: str | None,
	agent_id: str | None,
	app_id: str | None,
	run_id: str | None,
	filters: Mapping[str, Any] | None,
) -> dict[str, Any]:
	combined: dict[str, Any] = dict(filters or {})
	for name, value in _entity_values(user_id, agent_id, app_id, run_id).items():
		previous = combined.get(name)
		if previous is not None and previous != value:
			raise Mem0Error(f"conflicting values for {name} in filters")
		combined[name] = value
	if not combined:
		raise Mem0Error("at least one entity id (user_id, agent_id, app_id, run_id) or explicit filters is required")
	return combined


class Mem0Client:
	"""Client for the Mem0 REST API (V3 memory endpoints, V1 management endpoints)."""

	def __init__(
		self,
		api_key: str | None = None,
		*,
		base_url: str = DEFAULT_BASE_URL,
		timeout: float = DEFAULT_TIMEOUT_SECONDS,
		transport: Transport | None = None,
		sleep: Callable[[float], None] = time.sleep,
		clock: Callable[[], float] = time.monotonic,
	) -> None:
		key = api_key if api_key is not None else os.environ.get(API_KEY_ENV_VAR, "").strip()
		if not key:
			raise Mem0Error(f"{API_KEY_ENV_VAR} is not set; add it to the project Keys/environment before using Mem0")
		self._api_key = key
		self._base_url = base_url.rstrip("/")
		self._timeout = timeout
		self._transport = transport if transport is not None else _urllib_transport
		self._sleep = sleep
		self._clock = clock

	def _request(
		self,
		method: str,
		path: str,
		*,
		payload: Mapping[str, Any] | None = None,
		params: Mapping[str, Any] | None = None,
	) -> Any:
		url = f"{self._base_url}{path}"
		if params:
			url = f"{url}?{urllib.parse.urlencode(params)}"
		headers = {"Authorization": f"Token {self._api_key}", "Accept": "application/json"}
		body = None
		if payload is not None:
			headers["Content-Type"] = "application/json"
			body = json.dumps(payload).encode("utf-8")
		try:
			status, raw = self._transport(method, url, headers, body, self._timeout)
		except OSError as error:
			raise Mem0Error(f"mem0 {method} {path} request failed: {error}") from error

		text = raw.decode("utf-8", errors="replace")
		data: Any = None
		if text.strip():
			try:
				data = json.loads(text)
			except json.JSONDecodeError:
				data = None

		if status >= 400:
			detail = _error_detail(data) or text.strip() or f"HTTP {status}"
			raise Mem0Error(f"mem0 {method} {path} returned {status}: {detail}", status=status)
		if data is None:
			if text.strip():
				raise Mem0Error(f"mem0 {method} {path} returned a non-JSON response", status=status)
			return {}
		return data

	def add(
		self,
		*,
		messages: Sequence[Mapping[str, Any]] | None = None,
		text: str | None = None,
		user_id: str | None = None,
		agent_id: str | None = None,
		app_id: str | None = None,
		run_id: str | None = None,
		metadata: Mapping[str, Any] | None = None,
		wait: bool = False,
		wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
	) -> Any:
		"""Extract and store memories from conversation messages (POST /v3/memories/add/)."""
		if messages is None:
			if text is None:
				raise Mem0Error("add() requires messages or text")
			messages = ({"role": "user", "content": text},)
		normalized = [dict(message) for message in messages]
		if not normalized:
			raise Mem0Error("add() requires at least one message")
		for message in normalized:
			if not message.get("role") or not message.get("content"):
				raise Mem0Error("each message requires a role and content")

		payload: dict[str, Any] = {"messages": normalized}
		entities = _entity_values(user_id, agent_id, app_id, run_id)
		if not entities:
			raise Mem0Error("add() requires at least one entity id (user_id, agent_id, app_id, run_id)")
		payload.update(entities)
		if metadata is not None:
			payload["metadata"] = dict(metadata)

		result = self._request("POST", "/v3/memories/add/", payload=payload)
		if wait and isinstance(result, Mapping) and result.get("event_id"):
			return self.wait_for_event(str(result["event_id"]), timeout=wait_timeout)
		return result

	def search(
		self,
		query: str,
		*,
		user_id: str | None = None,
		agent_id: str | None = None,
		app_id: str | None = None,
		run_id: str | None = None,
		filters: Mapping[str, Any] | None = None,
		top_k: int = 10,
		threshold: float | None = None,
	) -> Any:
		"""Relevance-ranked hybrid search (POST /v3/memories/search/)."""
		_require_text(query, "query")
		if top_k < 1:
			raise Mem0Error("top_k must be at least 1")
		payload: dict[str, Any] = {
			"query": query.strip(),
			"filters": _merged_filters(user_id, agent_id, app_id, run_id, filters),
			"top_k": top_k,
		}
		if threshold is not None:
			payload["threshold"] = threshold
		return self._request("POST", "/v3/memories/search/", payload=payload)

	def get_all(
		self,
		*,
		user_id: str | None = None,
		agent_id: str | None = None,
		app_id: str | None = None,
		run_id: str | None = None,
		filters: Mapping[str, Any] | None = None,
		page: int = 1,
		page_size: int = 50,
	) -> Any:
		"""List memories for an entity (POST /v3/memories/?page=&page_size=)."""
		if page < 1 or page_size < 1:
			raise Mem0Error("page and page_size must be at least 1")
		payload = {"filters": _merged_filters(user_id, agent_id, app_id, run_id, filters)}
		return self._request(
			"POST",
			"/v3/memories/",
			payload=payload,
			params={"page": page, "page_size": page_size},
		)

	def update(
		self,
		memory_id: str,
		*,
		text: str | None = None,
		metadata: Mapping[str, Any] | None = None,
		expiration_date: str | None = None,
	) -> Any:
		"""Update one memory (PUT /v1/memories/{memory_id}/)."""
		memory_id = _require_text(memory_id, "memory_id")
		payload: dict[str, Any] = {}
		if text is not None:
			payload["text"] = text
		if metadata is not None:
			payload["metadata"] = dict(metadata)
		if expiration_date is not None:
			payload["expiration_date"] = expiration_date
		if not payload:
			raise Mem0Error("update() requires text, metadata, or expiration_date")
		return self._request("PUT", f"/v1/memories/{urllib.parse.quote(memory_id, safe='')}/", payload=payload)

	def delete(self, memory_id: str) -> Any:
		"""Delete one memory (DELETE /v1/memories/{memory_id}/)."""
		memory_id = _require_text(memory_id, "memory_id")
		return self._request("DELETE", f"/v1/memories/{urllib.parse.quote(memory_id, safe='')}/")

	def event(self, event_id: str) -> Any:
		"""Read an asynchronous add event (GET /v1/event/{event_id}/)."""
		event_id = _require_text(event_id, "event_id")
		return self._request("GET", f"/v1/event/{urllib.parse.quote(event_id, safe='')}/")

	def wait_for_event(
		self,
		event_id: str,
		*,
		timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
		interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
	) -> Any:
		"""Poll an add event until it reaches SUCCEEDED or FAILED, or the timeout expires."""
		event_id = _require_text(event_id, "event_id")
		if timeout < 0 or interval <= 0:
			raise Mem0Error("timeout must not be negative and interval must be positive")
		deadline = self._clock() + timeout
		while True:
			event = self.event(event_id)
			status = event.get("status") if isinstance(event, Mapping) else None
			if status in TERMINAL_EVENT_STATUSES:
				return event
			if self._clock() >= deadline:
				raise Mem0Error(
					f"timed out after {timeout:g}s waiting for mem0 event {event_id} (last status: {status})"
				)
			self._sleep(interval)
