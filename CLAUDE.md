# Garmin MCP Server - Project Guide

## Overview

This is a Model Context Protocol (MCP) server that connects to Garmin Connect and exposes fitness and health data to Claude and other MCP-compatible clients. The server provides 165 tools organized into 16 functional modules.

## Critical: Garmin API Integration

**The integration with Garmin's API is done via the [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library.**

### When Debugging or Implementing New Tools

**ALWAYS reference the python-garminconnect repository and these two files:**

1. **[example.py](https://github.com/cyberjunky/python-garminconnect/blob/master/example.py)** - Contains examples for many available API endpoints
2. **[demo.py](https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py)** - Comprehensive demo with 100+ API methods organized by category

These files are your source of truth for:
- **Available API endpoints** - Check if a method actually exists in the library
- **Correct method signatures** - Verify parameter names and types
- **Expected output formats** - See what data structure each endpoint returns
- **Method names** - Confirm the exact name of Garmin client methods

### Library Version

Currently using: `garminconnect==0.3.20` (see [pyproject.toml](pyproject.toml))

### Important Note

Not all Garmin Connect API endpoints have corresponding methods in python-garminconnect. Before implementing a new tool:
1. Check [example.py](https://github.com/cyberjunky/python-garminconnect/blob/master/example.py)
2. Check [demo.py](https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py)
3. Search the [library source code](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py)

If a method doesn't exist in python-garminconnect, you'll need to either:
- Use an alternative method that provides similar data
- Request the feature in the python-garminconnect repository
- Implement a custom API call if absolutely necessary

## Project Structure

```
src/garmin_mcp/
├── __init__.py                 # Main MCP server entry point
├── __main__.py                 # Module entry point
├── activity_analysis.py        # Activity analysis and FIT file parsing
├── activity_management.py      # Activity CRUD operations
├── auth_cli.py                 # Pre-authentication CLI (garmin-mcp-auth)
├── challenges.py               # Challenges and badges
├── courses.py                  # Course management
├── calendar_events.py          # Calendar events (races) and notes
├── data_management.py          # Data upload/download operations
├── devices.py                  # Device information
├── gear_management.py          # Gear tracking
├── health_wellness.py          # Health metrics (steps, HR, sleep, etc.)
├── http_auth.py                # Bearer-token auth for the HTTP transport
├── nutrition.py                # Nutrition and food logging
├── token_utils.py              # OAuth token management utilities
├── tool_annotations.py         # Read-only/additive/destructive hints per tool
├── tool_profiles.py            # Named tool subsets (profiles)
├── training.py                 # Training and performance metrics
├── user_profile.py             # User account information
├── weight_management.py        # Weight and body composition
├── womens_health.py            # Women's health tracking
├── workout_builders.py         # Programmatic workout creation
├── workout_templates.py        # Workout template helpers
├── workouts.py                 # Workout management
└── write_errors.py             # Structured error results for write tools (WriteTracker)

tests/
├── unit/                       # 450 tests, no Garmin API (helpers, validation, config, auth)
├── integration/                # 880 tests with mocked Garmin API
│   ├── test_activity_analysis_tools.py
│   ├── test_activity_management_tools.py
│   ├── test_calendar_events_tools.py
│   ├── test_challenges_tools.py
│   ├── test_courses_tools.py
│   ├── test_health_wellness_tools.py
│   ├── test_nutrition_tools.py
│   ├── test_other_modules_tools.py
│   ├── test_training_tools.py
│   ├── test_workout_builders_tools.py
│   └── test_workouts_tools.py
└── e2e/                        # 16 end-to-end tests (require real credentials)
    ├── test_server_e2e.py
    └── test_*_live.py          # live write-path checks against a real account
```

## Architecture

### Module Pattern

Each functional module follows this pattern:

```python
# Global client reference (set by main)
garmin_client = None

def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client

def register_tools(app):
    """Register all tools with the MCP server app"""

    @app.tool()
    async def tool_name(param: str) -> str:
        """Tool description"""
        try:
            result = garmin_client.method_name(param)
            if not result:
                return f"No data found."
            return result
        except Exception as e:
            return f"Error: {str(e)}"

    return app
```

### Main Server ([__init__.py](src/garmin_mcp/__init__.py))

The main server:
1. Initializes the Garmin Connect client
2. Configures all modules with the client instance
3. Registers all tools from each module
4. Handles authentication (including MFA)

## Authentication

Garmin credentials are read from environment variables:
- `GARMIN_EMAIL` or `GARMIN_EMAIL_FILE`
- `GARMIN_PASSWORD` or `GARMIN_PASSWORD_FILE`

For accounts with MFA enabled, use the pre-authentication CLI before starting the MCP server:

```bash
garmin-mcp-auth
```

This saves OAuth tokens to `~/.garminconnect` so the MCP server can start without an interactive terminal. Token utilities are in [token_utils.py](src/garmin_mcp/token_utils.py).

## Development Guidelines

### Adding a New Tool

1. **Check python-garminconnect first**: Verify the method exists in [example.py](https://github.com/cyberjunky/python-garminconnect/blob/master/example.py) or [demo.py](https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py)

2. **Choose the correct module**: Add the tool to the appropriate module based on functionality

3. **Follow the pattern**:
   ```python
   @app.tool()
   async def get_something(param: str) -> str:
       """Clear description of what the tool does

       Args:
           param: Description of parameter
       """
       try:
           result = garmin_client.garminconnect_method(param)
           if not result:
               return f"No data found."
           return result
       except Exception as e:
           return f"Error: {str(e)}"
   ```

4. **Add tests**: Create integration tests in `tests/integration/test_[module]_tools.py` (unit tests for helpers go in `tests/unit/`)

5. **Register the tool everywhere it must be listed** (see the checklist below)

#### Tools that write to Garmin

The example in step 3 is the plain *read* pattern. Tools that write follow the pattern below instead.

A tool that creates, changes or deletes data must not retry on its own and must tell the caller whether the write may have landed. Use `WriteTracker` from [write_errors.py](src/garmin_mcp/write_errors.py), validate input *before* `tracker.sending()`, and make destructive tools preview first:

```python
import json

from garmin_mcp.write_errors import WriteTracker


@app.tool()
async def update_thing(thing_id: int, name: str) -> str:
    """What it changes, whether repeating the call is safe, how to get thing_id

    Args:
        thing_id: Id from get_things
        name: New name
    """
    tracker = WriteTracker("update_thing", "Error updating thing")
    try:
        try:
            validated = _validate_name(name)      # ValueError -> plain "Error: ..." text
        except ValueError as e:
            return f"Error: {e}"

        tracker.sending()                          # the request is about to go out
        result = garmin_client.update_thing(thing_id, validated)
        tracker.committed()                        # Garmin accepted it

        return json.dumps({"status": "updated", "thing": result}, indent=2)
    except Exception as e:
        return tracker.error(e)                    # JSON with stage and write_committed
```

- Reads that precede the write (for example fetching the current object to merge into it) go before `tracker.sending()`.
- New tools that delete something irreplaceable (activities, events, courses) take `confirm: bool = False` and return a `needs_confirmation` preview unless `confirm=true`. See `delete_calendar_event`, which combines this with `WriteTracker`; `delete_activity` has the same confirm gate but returns plain error strings. Cheap, easily recreated deletes such as `delete_calendar_note` skip the gate.
- Prefer the `garminconnect` method over a raw `connectapi` call when one exists; fall back to `garmin_client.client.put/post/delete("connectapi", url, json=..., api=True)` otherwise.
- Verify the tool once against a real account with self-cleaning test data (create, change, delete) before opening the PR.

#### Checklist: every new tool

- [ ] **Annotations** - add the tool name to exactly one of `READ_ONLY_TOOLS` (no side effects), `ADDITIVE_TOOLS` (creates something new) or `DESTRUCTIVE_TOOLS` (changes, overwrites or deletes existing data, including every `set_*`/`update_*` tool and file downloads that can overwrite) in [tool_annotations.py](src/garmin_mcp/tool_annotations.py). For a write tool, also add it to `IDEMPOTENT_TOOLS` if repeating the same call is safe, and to `LOCAL_ONLY_TOOLS` if it never contacts Garmin. `test_annotation_registry_is_exhaustive_and_disjoint` fails when the three sets miss a tool or overlap, but it cannot tell you picked the wrong category.
- [ ] **Tool count** - bump the hard-coded `len(names) == N` in `tests/unit/test_tool_annotations.py`.
- [ ] **Profiles** - add the tool to the matching profile(s) in [tool_profiles.py](src/garmin_mcp/tool_profiles.py). A tool that is in no profile is dropped whenever a profile other than `all` is selected, unless the user allowlists it in `GARMIN_ENABLED_TOOLS`; that is allowed but usually not intended. A test checks that every name in a profile is a registered tool.
- [ ] **dxt bundle** - regenerate the manifest tool list and the bundle, then commit both `dxt/manifest.json` and `garmin-mcp.dxt`:
  ```bash
  uv run bash scripts/build_dxt.sh
  ```
  `test_tools_list_matches_registered_tools` and `test_bundled_manifest_matches_source_manifest` fail if either is stale. The manifest also carries each tool's first docstring line, so rebuild after changing that line on an existing tool too. The `.dxt` is a zip, so its bytes differ on every rebuild even when the manifest is unchanged; commit it only when `dxt/manifest.json` changed.
- [ ] **Counts in docs** - update the tool counts that no test checks: "registers N tools" and the per-profile table in [README.md](README.md), the count in the [tool_profiles.py](src/garmin_mcp/tool_profiles.py) docstring, the "Tool Coverage" section in the README (per-module counts and a line per module; it is currently out of date), and the tool/test counts in this file.
- [ ] **New module only** - in [__init__.py](src/garmin_mcp/__init__.py) add the `from garmin_mcp import <module>` import and the `configure()` and `register_tools()` calls, and in `scripts/generate_dxt_tools.py` add the import and an entry in `MODULES`. No test checks that the two lists agree: every coverage test iterates `MODULES`, so a module missing there is silently skipped and the only signal is a runtime warning about unannotated tools. Also add a `tests/integration/test_<module>_tools.py`, a line in the project tree and the module count at the top of this file, and a module line in the README.
- [ ] **Tests and checks** - run `uv run pytest tests/unit tests/integration -q`; for write tools also do the live check described above.

### Error Handling

All tools should:
- Wrap API calls in try/except blocks
- Return user-friendly error messages
- Handle empty/null responses gracefully

## Testing

The project has comprehensive test coverage:

**450 unit tests** and **880 integration tests** - Test helpers and all MCP tools with a mocked Garmin API

```bash
# Run all unit tests
uv run pytest tests/unit -q

# Run all integration tests
uv run pytest tests/integration/ -v

# Run specific module tests
uv run pytest tests/integration/test_health_wellness_tools.py -v
```

**16 end-to-end tests** - Test with real MCP server and Garmin API (requires credentials)

```bash
uv run pytest tests/e2e/ -m e2e -v
```

### Test Structure

Each tool should have at least two tests:
1. **Success case**: Verify the tool works with expected data
2. **Exception case**: Verify error handling when the API fails

Example:
```python
async def test_tool_success(app_with_module, mock_garmin_client):
    """Test tool with valid response"""
    mock_garmin_client.method.return_value = {"data": "value"}
    result = await call_tool(app_with_module, "tool_name", {"param": "value"})
    assert "value" in result

async def test_tool_exception(app_with_module, mock_garmin_client):
    """Test tool when API raises exception"""
    mock_garmin_client.method.side_effect = Exception("API Error")
    result = await call_tool(app_with_module, "tool_name", {"param": "value"})
    assert "Error" in result
```

## Running the Server

### With MCP Inspector (for testing)

```bash
npx @modelcontextprotocol/inspector uv run garmin-mcp
```

### With Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": [
        "--python", "3.12",
        "--from", "git+https://github.com/Taxuspt/garmin_mcp",
        "garmin-mcp"
      ],
      "env": {
        "GARMIN_EMAIL": "YOUR_GARMIN_EMAIL",
        "GARMIN_PASSWORD": "YOUR_GARMIN_PASSWORD"
      }
    }
  }
}
```

## Common Patterns

### Date Parameters

Many tools accept dates in `YYYY-MM-DD` format:
```python
async def get_data(date: str) -> str:
    """Get data for a specific date

    Args:
        date: Date in YYYY-MM-DD format
    """
```

### Activity IDs

Activity IDs are typically large integers (e.g., `12345678901`):
```python
async def get_activity_detail(activity_id: int) -> str:
```

### Return Types

All tools return `str` (MCP requirement). Complex objects are returned as JSON strings.

## Troubleshooting

### Method doesn't exist in garminconnect

**Always check [example.py](https://github.com/cyberjunky/python-garminconnect/blob/master/example.py) and [demo.py](https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py) first!**

If the method you're trying to use isn't documented there, it likely doesn't exist in the library.

### Unexpected output format

Check the example files to see what the actual API returns. The Garmin API can return different structures than expected.

### Authentication issues

For MFA accounts, run `garmin-mcp-auth` first to pre-authenticate and save tokens.

Check logs at:
- macOS: `~/Library/Logs/Claude/mcp-server-garmin.log`
- Windows: `%APPDATA%\Claude\logs\mcp-server-garmin.log`

## Key Dependencies

- `garminconnect==0.3.20` - Garmin Connect API wrapper
- `mcp>=1.28.1,<2` - Model Context Protocol SDK (2.x renamed FastMCP; capped until ported)
- `fitparse>=1.2.0` - FIT file parsing for activity analysis
- `python-dotenv==1.2.2` - Environment variable management
- `requests==2.33.0` - HTTP client

## Resources

- [python-garminconnect GitHub](https://github.com/cyberjunky/python-garminconnect)
- [example.py - API examples](https://github.com/cyberjunky/python-garminconnect/blob/master/example.py)
- [demo.py - Comprehensive API demo](https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py)
- [MCP Documentation](https://modelcontextprotocol.io/)
