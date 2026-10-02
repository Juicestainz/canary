# Mem0 integration

`tools/mem0` gives the repository a client for [Mem0](https://mem0.ai), the
memory layer for AI agents. It lets any Python tooling in this project store,
search, and manage long-lived memories (user/agent context that survives
across runs) through the Mem0 REST API.

The package uses only the Python standard library — there is nothing to
install.

## Requirements

- Python 3.10+
- A Mem0 API key in the `MEM0_API_KEY` environment variable

## Setup

Create a workspace and API key at [mem0.ai](https://mem0.ai), then add the key
to the project **Keys** tab under the name `MEM0_API_KEY`. Freebuff injects it
into the environment of every terminal command automatically. For local runs
outside Freebuff, export the same variable in your shell.

Never commit the key or pass it on the command line; the tool only reads it
from the environment and never prints it.

## Quick start

Run all commands from the repository root:

```sh
# Store a memory (asynchronous extraction; add --wait to block until done)
python3 -m tools.mem0 add --text "The player prefers retro-pvp rulesets" --user-id player-42 --wait

# Store a conversation
python3 -m tools.mem0 add \
  --message "user:Call me Eldric" \
  --message "assistant:Understood, Eldric" \
  --user-id player-42

# Hybrid search (semantic + keyword + entity matching)
python3 -m tools.mem0 search "what does the player prefer?" --user-id player-42 --top-k 5

# List, update, delete
python3 -m tools.mem0 get-all --user-id player-42 --page-size 25
python3 -m tools.mem0 update <memory-id> --text "The player prefers retro-pvp and open-PvP zones"
python3 -m tools.mem0 delete <memory-id>

# Inspect an asynchronous add event
python3 -m tools.mem0 event <event-id>
```

## CLI reference

| Command | Purpose | Key options |
| --- | --- | --- |
| `add` | Extract and store memories from messages | `--text`, `--message ROLE:CONTENT` (repeatable), `--user-id`/`--agent-id`/`--app-id`/`--run-id`, `--metadata KEY=VALUE`, `--wait`, `--wait-timeout` |
| `search` | Relevance-ranked hybrid search | positional `query`, entity ids, `--filters JSON`, `--top-k`, `--threshold` |
| `get-all` | Paginated list for an entity | entity ids, `--filters JSON`, `--page`, `--page-size` |
| `update` | Change one memory by id | positional `memory_id`, `--text`, `--metadata`, `--expiration-date` |
| `delete` | Remove one memory by id | positional `memory_id` |
| `event` | Read an asynchronous add event | positional `event_id` |

At least one entity id (`--user-id`, `--agent-id`, `--app-id`, `--run-id`) or
an explicit `--filters` object is required for `add`, `search`, and `get-all`;
Mem0 scopes every memory to an entity.

Exit codes: `0` success, `1` API/configuration failure, `2` invalid usage.

## Python API

```python
from tools.mem0 import Mem0Client

client = Mem0Client()  # reads MEM0_API_KEY from the environment

client.add(text="The player prefers retro-pvp rulesets", user_id="player-42", wait=True)
hits = client.search("what does the player prefer?", user_id="player-42", top_k=5)
for item in hits["results"]:
    print(item["score"], item["memory"])

page = client.get_all(user_id="player-42", page_size=25)
client.update(page["results"][0]["id"], text="Updated memory text")
client.delete(page["results"][0]["id"])
```

All methods raise `Mem0Error` (with an optional `.status` HTTP code) when the
API key is missing, the request fails, or the API answers with an error.

## Endpoints used

| Operation | Endpoint |
| --- | --- |
| `add` | `POST /v3/memories/add/` (async; returns `event_id`) |
| `search` | `POST /v3/memories/search/` |
| `get-all` | `POST /v3/memories/?page=&page_size=` |
| `update` | `PUT /v1/memories/{memory_id}/` |
| `delete` | `DELETE /v1/memories/{memory_id}/` |
| `event` | `GET /v1/event/{event_id}/` |

Requests authenticate with `Authorization: Token <MEM0_API_KEY>`. The V3 `add`
endpoint extracts memories asynchronously: poll with `--wait` (or
`Mem0Client.wait_for_event`) until the event reports `SUCCEEDED` or `FAILED`.

## Tests

```sh
python3 -m unittest discover -s tools/mem0/tests -t . -p "test_*.py" -v
```

The tests use a fake transport and never contact the live API.
