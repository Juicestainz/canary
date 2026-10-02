"""Shared fakes for the Mem0 integration tests."""

from __future__ import annotations

import json


class FakeRequest:
	"""One recorded outgoing request."""

	def __init__(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> None:
		self.method = method
		self.url = url
		self.headers = headers
		self.body = body
		self.timeout = timeout

	@property
	def json(self) -> dict | None:
		return json.loads(self.body.decode("utf-8")) if self.body else None


class FakeTransport:
	"""Records requests and replays queued ``(status, payload)`` responses.

	A queued payload may be a dict (serialized as JSON), a str/bytes body
	(returned verbatim), or an exception instance (raised to simulate a
	network failure). When the queue is empty, an empty 200 response is
	returned.
	"""

	def __init__(self, responses=()) -> None:
		self.requests: list[FakeRequest] = []
		self._responses = list(responses)

	def __call__(self, method: str, url: str, headers, body: bytes | None, timeout: float) -> tuple[int, bytes]:
		self.requests.append(FakeRequest(method, url, dict(headers), body, timeout))
		if not self._responses:
			return 200, b"{}"
		status, payload = self._responses.pop(0)
		if isinstance(payload, BaseException):
			raise payload
		if isinstance(payload, bytes):
			raw = payload
		elif isinstance(payload, str):
			raw = payload.encode("utf-8")
		else:
			raw = json.dumps(payload).encode("utf-8")
		return status, raw

	@property
	def last(self) -> FakeRequest:
		return self.requests[-1]


class FakeClock:
	"""Deterministic clock whose ``sleep`` advances time."""

	def __init__(self) -> None:
		self.now = 0.0

	def __call__(self) -> float:
		return self.now

	def sleep(self, seconds: float) -> None:
		self.now += seconds
