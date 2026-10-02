from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tools.mem0 import cli
from tools.mem0.client import API_KEY_ENV_VAR, Mem0Error


class StubClient:
	"""Records CLI dispatches and returns canned results."""

	def __init__(self) -> None:
		self.calls: list[tuple] = []

	def add(self, **kwargs):
		self.calls.append(("add", kwargs))
		return {"event_id": "evt-1", "status": "PENDING"}

	def search(self, query, **kwargs):
		self.calls.append(("search", query, kwargs))
		return {"results": [{"id": "mem-1", "memory": "Likes cricket"}]}

	def get_all(self, **kwargs):
		self.calls.append(("get_all", kwargs))
		return {"count": 1, "results": [{"id": "mem-1"}]}

	def update(self, memory_id, **kwargs):
		self.calls.append(("update", memory_id, kwargs))
		return {"id": memory_id}

	def delete(self, memory_id):
		self.calls.append(("delete", memory_id))
		return {"message": "Memory deleted successfully!"}

	def event(self, event_id):
		self.calls.append(("event", event_id))
		return {"status": "SUCCEEDED"}


class FailingAddClient(StubClient):
	def add(self, **kwargs):
		raise Mem0Error("mem0 exploded")


class FailedEventClient(StubClient):
	def add(self, **kwargs):
		self.calls.append(("add", kwargs))
		return {"event_id": "evt-9", "status": "FAILED"}


class CliTests(unittest.TestCase):
	def run_cli(self, argv, client=None):
		stub = client if client is not None else StubClient()
		stdout = io.StringIO()
		stderr = io.StringIO()
		with patch.object(cli, "Mem0Client", return_value=stub):
			with redirect_stdout(stdout), redirect_stderr(stderr):
				status = cli.main(argv)
		return status, stdout.getvalue(), stderr.getvalue(), stub

	def run_usage_error(self, argv) -> str:
		stderr = io.StringIO()
		with patch.object(cli, "Mem0Client", return_value=StubClient()):
			with redirect_stderr(stderr):
				with self.assertRaises(SystemExit) as context:
					cli.main(argv)
		self.assertEqual(context.exception.code, cli.EXIT_USAGE)
		return stderr.getvalue()

	# --- success paths -------------------------------------------------

	def test_add_prints_json_and_exits_zero(self) -> None:
		status, stdout, stderr, stub = self.run_cli(
			["add", "--text", "I moved to Austin", "--user-id", "alice", "--metadata", "source=cli"]
		)

		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertEqual(stderr, "")
		self.assertEqual(json.loads(stdout), {"event_id": "evt-1", "status": "PENDING"})
		kind, kwargs = stub.calls[0]
		self.assertEqual(kind, "add")
		self.assertEqual(kwargs["messages"], [{"role": "user", "content": "I moved to Austin"}])
		self.assertEqual(kwargs["user_id"], "alice")
		self.assertEqual(kwargs["metadata"], {"source": "cli"})

	def test_add_accepts_repeated_messages(self) -> None:
		status, _stdout, _stderr, stub = self.run_cli(
			["add", "--message", "user:hi", "--message", "assistant:hello", "--agent-id", "guide"]
		)

		self.assertEqual(status, cli.EXIT_SUCCESS)
		kwargs = stub.calls[0][1]
		self.assertEqual(
			kwargs["messages"],
			[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
		)
		self.assertEqual(kwargs["agent_id"], "guide")

	def test_search_dispatches_query_and_scope(self) -> None:
		status, stdout, _stderr, stub = self.run_cli(
			["search", "hobbies", "--user-id", "alice", "--top-k", "3"]
		)

		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertIn("cricket", json.loads(stdout)["results"][0]["memory"])
		kind, query, kwargs = stub.calls[0]
		self.assertEqual((kind, query), ("search", "hobbies"))
		self.assertEqual(kwargs["user_id"], "alice")
		self.assertEqual(kwargs["top_k"], 3)

	def test_get_all_update_delete_event_dispatch(self) -> None:
		status, _stdout, _stderr, stub = self.run_cli(["get-all", "--user-id", "alice"])
		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertEqual(stub.calls[-1][0], "get_all")

		status, _stdout, _stderr, stub = self.run_cli(["update", "mem-1", "--text", "new text"])
		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertEqual(stub.calls[-1], ("update", "mem-1", {"text": "new text", "metadata": None, "expiration_date": None}))

		status, _stdout, _stderr, stub = self.run_cli(["delete", "mem-9"])
		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertEqual(stub.calls[-1], ("delete", "mem-9"))

		status, _stdout, _stderr, stub = self.run_cli(["event", "evt-3"])
		self.assertEqual(status, cli.EXIT_SUCCESS)
		self.assertEqual(stub.calls[-1], ("event", "evt-3"))

	# --- failure paths -------------------------------------------------

	def test_api_failure_exits_one(self) -> None:
		status, stdout, stderr, _stub = self.run_cli(
			["add", "--text", "hi", "--user-id", "alice"], client=FailingAddClient()
		)

		self.assertEqual(status, cli.EXIT_FAILURE)
		self.assertEqual(stdout, "")
		self.assertIn("mem0 exploded", stderr)

	def test_missing_api_key_exits_one_with_hint(self) -> None:
		stdout = io.StringIO()
		stderr = io.StringIO()
		with patch.dict(os.environ, {API_KEY_ENV_VAR: ""}):
			with redirect_stdout(stdout), redirect_stderr(stderr):
				status = cli.main(["event", "evt-1"])

		self.assertEqual(status, cli.EXIT_FAILURE)
		self.assertIn(API_KEY_ENV_VAR, stderr.getvalue())

	def test_failed_wait_event_exits_one(self) -> None:
		status, _stdout, stderr, _stub = self.run_cli(
			["add", "--text", "hi", "--user-id", "alice", "--wait"], client=FailedEventClient()
		)

		self.assertEqual(status, cli.EXIT_FAILURE)
		self.assertIn("FAILED", stderr)

	# --- usage errors --------------------------------------------------

	def test_add_without_content_is_usage_error(self) -> None:
		message = self.run_usage_error(["add", "--user-id", "alice"])

		self.assertIn("add requires --text", message)

	def test_add_rejects_malformed_message(self) -> None:
		message = self.run_usage_error(["add", "--message", "just-text", "--user-id", "alice"])

		self.assertIn("ROLE:CONTENT", message)

	def test_search_without_scope_is_usage_error(self) -> None:
		message = self.run_usage_error(["search", "hobbies"])

		self.assertIn("entity id", message)

	def test_search_rejects_out_of_range_top_k(self) -> None:
		message = self.run_usage_error(["search", "q", "--user-id", "alice", "--top-k", "0"])

		self.assertIn("--top-k", message)

	def test_update_without_change_is_usage_error(self) -> None:
		message = self.run_usage_error(["update", "mem-1"])

		self.assertIn("--text", message)

	def test_invalid_filters_json_is_usage_error(self) -> None:
		message = self.run_usage_error(["search", "q", "--user-id", "alice", "--filters", "{not json"])

		self.assertIn("--filters", message)


if __name__ == "__main__":
	unittest.main()
