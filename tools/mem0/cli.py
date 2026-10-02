"""Command-line interface for the Mem0 memory integration."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from .client import API_KEY_ENV_VAR, DEFAULT_WAIT_TIMEOUT_SECONDS, Mem0Client, Mem0Error

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

ENTITY_OPTIONS = ("user_id", "agent_id", "app_id", "run_id")
MESSAGE_ROLES = ("user", "assistant", "system", "tool")


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog="python -m tools.mem0",
		description="Store, search, and manage memories through the Mem0 API.",
		epilog=f"requires the {API_KEY_ENV_VAR} environment variable (project Keys tab)",
	)
	subcommands = parser.add_subparsers(dest="command", required=True)

	add = subcommands.add_parser("add", help="extract and store memories from conversation messages")
	add.add_argument("--text", help="single user message to store")
	add.add_argument("--message", action="append", default=[], metavar="ROLE:CONTENT", help="conversation message; repeatable")
	_entity_options(add)
	add.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE", help="metadata entry; repeatable")
	add.add_argument("--wait", action="store_true", help="poll until asynchronous extraction finishes")
	add.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT_SECONDS, metavar="SECONDS")

	search = subcommands.add_parser("search", help="search memories with hybrid retrieval")
	search.add_argument("query")
	_entity_options(search)
	search.add_argument("--filters", metavar="JSON", help="additional JSON filter object")
	search.add_argument("--top-k", type=int, default=10, help="maximum results (1-1000, default 10)")
	search.add_argument("--threshold", type=float, help="minimum score (0.0 disables the threshold)")

	get_all = subcommands.add_parser("get-all", help="list memories for an entity")
	_entity_options(get_all)
	get_all.add_argument("--filters", metavar="JSON", help="additional JSON filter object")
	get_all.add_argument("--page", type=int, default=1)
	get_all.add_argument("--page-size", type=int, default=50)

	update = subcommands.add_parser("update", help="update a memory by id")
	update.add_argument("memory_id")
	update.add_argument("--text", help="replacement memory text")
	update.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE", help="metadata entry; repeatable")
	update.add_argument("--expiration-date", metavar="YYYY-MM-DD", help="new expiration date")

	delete = subcommands.add_parser("delete", help="delete a memory by id")
	delete.add_argument("memory_id")

	event = subcommands.add_parser("event", help="read the status of an asynchronous add event")
	event.add_argument("event_id")

	return parser


def _entity_options(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--user-id", help="Mem0 user entity id")
	parser.add_argument("--agent-id", help="Mem0 agent entity id")
	parser.add_argument("--app-id", help="Mem0 app entity id")
	parser.add_argument("--run-id", help="Mem0 run entity id")


def _entity_values(args: argparse.Namespace) -> dict[str, str]:
	return {name: value for name in ENTITY_OPTIONS if (value := getattr(args, name, None)) is not None}


def _parse_metadata(entries: list[str], parser: argparse.ArgumentParser) -> dict[str, str]:
	metadata: dict[str, str] = {}
	for entry in entries:
		key, separator, value = entry.partition("=")
		if not separator or not key:
			parser.error(f"invalid metadata {entry!r}; expected KEY=VALUE")
		metadata[key] = value
	return metadata


def _parse_filters(raw: str | None, parser: argparse.ArgumentParser) -> dict[str, Any] | None:
	if raw is None:
		return None
	try:
		filters = json.loads(raw)
	except json.JSONDecodeError as error:
		parser.error(f"invalid --filters JSON: {error}")
	if not isinstance(filters, dict):
		parser.error("--filters must be a JSON object")
	return filters


def _parse_messages(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[dict[str, str]]:
	messages: list[dict[str, str]] = []
	for entry in args.message:
		role, separator, content = entry.partition(":")
		if not separator or not role or not content:
			parser.error(f"invalid --message {entry!r}; expected ROLE:CONTENT")
		if role not in MESSAGE_ROLES:
			parser.error(f"invalid role {role!r} in --message; expected one of {', '.join(MESSAGE_ROLES)}")
		messages.append({"role": role, "content": content})
	if messages:
		if args.text is not None:
			parser.error("--text cannot be combined with --message")
		return messages
	if args.text is None or not args.text.strip():
		parser.error("add requires --text or at least one --message ROLE:CONTENT")
	return [{"role": "user", "content": args.text}]


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
	args.metadata_map = _parse_metadata(args.metadata, parser) if hasattr(args, "metadata") else {}
	if args.command == "add":
		args.messages = _parse_messages(args, parser)
		args.filters = None
		if args.wait_timeout < 0:
			parser.error("--wait-timeout must not be negative")
	elif args.command == "search":
		if not args.query.strip():
			parser.error("query must not be empty")
		if not 1 <= args.top_k <= 1000:
			parser.error("--top-k must be between 1 and 1000")
		args.filters = _parse_filters(args.filters, parser)
		if not _entity_values(args) and not args.filters:
			parser.error("search requires an entity id (--user-id and friends) or --filters")
	elif args.command == "get-all":
		args.filters = _parse_filters(args.filters, parser)
		if not _entity_values(args) and not args.filters:
			parser.error("get-all requires an entity id (--user-id and friends) or --filters")
		if args.page < 1 or args.page_size < 1:
			parser.error("--page and --page-size must be at least 1")
	elif args.command == "update":
		if args.text is None and not args.metadata_map and args.expiration_date is None:
			parser.error("update requires --text, --metadata, or --expiration-date")


def _dispatch(args: argparse.Namespace, client: Mem0Client) -> Any:
	entities = _entity_values(args)
	if args.command == "add":
		result = client.add(
			messages=args.messages,
			metadata=args.metadata_map or None,
			wait=args.wait,
			wait_timeout=args.wait_timeout,
			**entities,
		)
		if args.wait and isinstance(result, Mapping) and result.get("status") == "FAILED":
			raise Mem0Error(f"mem0 add event failed: {json.dumps(result, ensure_ascii=False)}")
		return result
	if args.command == "search":
		return client.search(
			args.query,
			filters=args.filters,
			top_k=args.top_k,
			threshold=args.threshold,
			**entities,
		)
	if args.command == "get-all":
		return client.get_all(
			filters=args.filters,
			page=args.page,
			page_size=args.page_size,
			**entities,
		)
	if args.command == "update":
		return client.update(
			args.memory_id,
			text=args.text,
			metadata=args.metadata_map or None,
			expiration_date=args.expiration_date,
		)
	if args.command == "delete":
		return client.delete(args.memory_id)
	return client.event(args.event_id)


def main(argv: Sequence[str] | None = None) -> int:
	parser = _parser()
	args = parser.parse_args(argv)
	_validate(args, parser)
	try:
		client = Mem0Client()
		result = _dispatch(args, client)
	except Mem0Error as error:
		print(f"error: {error}", file=sys.stderr)
		return EXIT_FAILURE
	print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
	return EXIT_SUCCESS
