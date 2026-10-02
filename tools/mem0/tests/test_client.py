from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tools.mem0.client import API_KEY_ENV_VAR, DEFAULT_BASE_URL, Mem0Client, Mem0Error

from .helpers import FakeClock, FakeTransport


class Mem0ClientTests(unittest.TestCase):
	def make_client(self, *responses, api_key: str = "unit-test-key", **kwargs):
		transport = FakeTransport(responses)
		clock = FakeClock()
		client = Mem0Client(
			api_key,
			transport=transport,
			sleep=clock.sleep,
			clock=clock,
			**kwargs,
		)
		return client, transport, clock

	# --- configuration -------------------------------------------------

	def test_missing_api_key_raises_with_environment_hint(self) -> None:
		with patch.dict(os.environ, {API_KEY_ENV_VAR: ""}):
			with self.assertRaises(Mem0Error) as context:
				Mem0Client(transport=FakeTransport())

		self.assertIn(API_KEY_ENV_VAR, str(context.exception))

	def test_api_key_from_environment_uses_token_scheme(self) -> None:
		transport = FakeTransport()
		with patch.dict(os.environ, {API_KEY_ENV_VAR: "env-secret"}):
			client = Mem0Client(transport=transport)

		client.add(text="hello", user_id="alice")

		self.assertEqual(transport.last.headers["Authorization"], "Token env-secret")
		self.assertEqual(transport.last.url, f"{DEFAULT_BASE_URL}/v3/memories/add/")

	# --- add -----------------------------------------------------------

	def test_add_posts_v3_add_payload(self) -> None:
		client, transport, _clock = self.make_client((200, {"event_id": "evt-1", "status": "PENDING"}))

		result = client.add(
			messages=[{"role": "user", "content": "I moved to Austin"}, {"role": "assistant", "content": "Noted"}],
			user_id="alice",
			metadata={"source": "test"},
		)

		self.assertEqual(result["event_id"], "evt-1")
		request = transport.last
		self.assertEqual(request.method, "POST")
		self.assertEqual(request.url, f"{DEFAULT_BASE_URL}/v3/memories/add/")
		self.assertEqual(request.json["messages"][0]["content"], "I moved to Austin")
		self.assertEqual(request.json["user_id"], "alice")
		self.assertEqual(request.json["metadata"], {"source": "test"})
		self.assertNotIn("agent_id", request.json)

	def test_add_accepts_plain_text_as_user_message(self) -> None:
		client, transport, _clock = self.make_client()

		client.add(text="hello", agent_id="guide")

		self.assertEqual(transport.last.json["messages"], [{"role": "user", "content": "hello"}])
		self.assertEqual(transport.last.json["agent_id"], "guide")

	def test_add_requires_an_entity_id(self) -> None:
		client, transport, _clock = self.make_client()

		with self.assertRaises(Mem0Error):
			client.add(text="hello")

		self.assertEqual(transport.requests, [])

	def test_add_rejects_messages_without_role_or_content(self) -> None:
		client, transport, _clock = self.make_client()

		with self.assertRaises(Mem0Error):
			client.add(messages=[{"role": "user"}], user_id="alice")

		with self.assertRaises(Mem0Error):
			client.add(messages=[], user_id="alice")

		self.assertEqual(transport.requests, [])

	def test_add_wait_polls_event_until_succeeded(self) -> None:
		client, transport, clock = self.make_client(
			(200, {"event_id": "evt-1", "status": "PENDING"}),
			(200, {"status": "PENDING"}),
			(200, {"status": "SUCCEEDED"}),
		)

		result = client.add(text="hello", user_id="alice", wait=True, wait_timeout=10)

		self.assertEqual(result["status"], "SUCCEEDED")
		self.assertEqual(len(transport.requests), 3)
		self.assertTrue(transport.requests[1].url.endswith("/v1/event/evt-1/"))
		self.assertEqual(clock.now, 1.0)

	# --- search / get-all ----------------------------------------------

	def test_search_places_entity_ids_inside_filters(self) -> None:
		client, transport, _clock = self.make_client()

		client.search("where does alice live?", user_id="alice", top_k=5, threshold=0.2)

		request = transport.last
		self.assertEqual(request.method, "POST")
		self.assertEqual(request.url, f"{DEFAULT_BASE_URL}/v3/memories/search/")
		self.assertEqual(
			request.json,
			{"query": "where does alice live?", "filters": {"user_id": "alice"}, "top_k": 5, "threshold": 0.2},
		)

	def test_search_merges_explicit_filters(self) -> None:
		client, transport, _clock = self.make_client()

		client.search("hobbies", filters={"AND": [{"user_id": "alice"}]}, user_id="alice")

		self.assertEqual(transport.last.json["filters"]["AND"], [{"user_id": "alice"}])
		self.assertEqual(transport.last.json["filters"]["user_id"], "alice")

	def test_search_rejects_conflicting_entity_ids(self) -> None:
		client, transport, _clock = self.make_client()

		with self.assertRaises(Mem0Error) as context:
			client.search("q", user_id="alice", filters={"user_id": "bob"})

		self.assertIn("conflicting", str(context.exception))
		self.assertEqual(transport.requests, [])

	def test_search_requires_scope(self) -> None:
		client, _transport, _clock = self.make_client()

		with self.assertRaises(Mem0Error):
			client.search("q")

	def test_get_all_sends_pagination_query(self) -> None:
		client, transport, _clock = self.make_client()

		client.get_all(user_id="alice", page=2, page_size=25)

		request = transport.last
		self.assertEqual(request.method, "POST")
		self.assertEqual(request.url, f"{DEFAULT_BASE_URL}/v3/memories/?page=2&page_size=25")
		self.assertEqual(request.json, {"filters": {"user_id": "alice"}})

	# --- update / delete / event ---------------------------------------

	def test_update_uses_put_on_v1_path(self) -> None:
		client, transport, _clock = self.make_client()

		client.update("mem-123", text="updated", metadata={"category": "hobbies"})

		request = transport.last
		self.assertEqual(request.method, "PUT")
		self.assertEqual(request.url, f"{DEFAULT_BASE_URL}/v1/memories/mem-123/")
		self.assertEqual(request.json, {"text": "updated", "metadata": {"category": "hobbies"}})

	def test_update_requires_a_change(self) -> None:
		client, transport, _clock = self.make_client()

		with self.assertRaises(Mem0Error):
			client.update("mem-123")

		self.assertEqual(transport.requests, [])

	def test_delete_uses_delete_on_v1_path(self) -> None:
		client, transport, _clock = self.make_client()

		client.delete("mem-123")

		request = transport.last
		self.assertEqual(request.method, "DELETE")
		self.assertEqual(request.url, f"{DEFAULT_BASE_URL}/v1/memories/mem-123/")
		self.assertIsNone(request.body)

	# --- error handling ------------------------------------------------

	def test_http_error_raises_with_status_and_detail_without_key(self) -> None:
		client, _transport, _clock = self.make_client((401, {"error": "Invalid API key."}))

		with self.assertRaises(Mem0Error) as context:
			client.search("q", user_id="alice")

		self.assertEqual(context.exception.status, 401)
		self.assertIn("Invalid API key", str(context.exception))
		self.assertNotIn("unit-test-key", str(context.exception))

	def test_non_json_success_response_raises(self) -> None:
		client, _transport, _clock = self.make_client((200, "<html>proxy error</html>"))

		with self.assertRaises(Mem0Error) as context:
			client.get_all(user_id="alice")

		self.assertIn("non-JSON", str(context.exception))

	def test_network_failure_is_wrapped(self) -> None:
		client, _transport, _clock = self.make_client((0, OSError("network down")))

		with self.assertRaises(Mem0Error) as context:
			client.delete("mem-1")

		self.assertIn("network down", str(context.exception))

	# --- event polling -------------------------------------------------

	def test_wait_for_event_returns_failed_status(self) -> None:
		client, _transport, _clock = self.make_client((200, {"event_id": "evt-9", "status": "FAILED"}))

		result = client.wait_for_event("evt-9", timeout=5)

		self.assertEqual(result["status"], "FAILED")

	def test_wait_for_event_times_out_while_pending(self) -> None:
		client, transport, clock = self.make_client((200, {"status": "PENDING"}))

		with self.assertRaises(Mem0Error) as context:
			client.wait_for_event("evt-2", timeout=2, interval=1)

		self.assertIn("timed out", str(context.exception))
		self.assertEqual(clock.now, 2.0)
		self.assertEqual(len(transport.requests), 3)

	def test_event_endpoint_reads_status(self) -> None:
		client, transport, _clock = self.make_client((200, {"status": "SUCCEEDED"}))

		result = client.event("evt-3")

		self.assertEqual(result["status"], "SUCCEEDED")
		self.assertEqual(transport.last.method, "GET")
		self.assertEqual(transport.last.url, f"{DEFAULT_BASE_URL}/v1/event/evt-3/")


if __name__ == "__main__":
	unittest.main()
