"""Unit tests for the calendar event write tools."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import calendar_events


@pytest.fixture
def client():
    mock = MagicMock()
    calendar_events.configure(mock)
    return mock


@pytest.fixture
def tools():
    app = FastMCP("test")
    calendar_events.register_tools(app)

    def call(tool_name, /, **kwargs):
        return asyncio.run(app.call_tool(tool_name, kwargs))

    return call


def _text(result):
    # FastMCP returns (content_blocks, structured) or a block list.
    blocks = result[0] if isinstance(result, tuple) else result
    return blocks[0].text


EXISTING = {
    "id": 42,
    "eventName": "Old name",
    "date": "2026-12-01",
    "race": True,
    "completionTarget": {"value": 10.0, "unit": "kilometer", "unitType": "distance"},
    "eventCustomization": {"isPrimaryEvent": False, "customGoal": None},
    "shareableEventUuid": "abc",
}


def test_create_builds_payload(client, tools):
    client.create_calendar_event.return_value = {"id": 7}
    out = json.loads(
        _text(
            tools(
                "create_calendar_event",
                name="  Spring 10K ",
                date="2027-04-10",
                distance_km=10,
                start_time="09:30",
                time_zone="Europe/Paris",
                location="Barcelona",
                goal_time_seconds=3000,
            )
        )
    )
    assert out["status"] == "created"
    payload = client.create_calendar_event.call_args.args[0]
    assert payload["eventName"] == "Spring 10K"
    assert payload["date"] == "2027-04-10"
    assert payload["eventType"] == "running"
    assert payload["race"] is True
    assert payload["completionTarget"] == {
        "value": 10.0,
        "unit": "kilometer",
        "unitType": "distance",
    }
    assert payload["eventTimeLocal"] == {
        "startTimeHhMm": "09:30",
        "timeZoneId": "Europe/Paris",
    }
    assert payload["eventCustomization"]["customGoal"] == {
        "value": 3000.0,
        "unit": "second",
        "unitType": "time",
    }
    assert "_goal_time_seconds" not in payload


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"date": "2027-13-40"}, "month"),
        ({"distance_km": 0}, "distance_km"),
        ({"start_time": "9:30", "time_zone": "Europe/Paris"}, "HH:MM"),
        ({"start_time": "09:30"}, "time_zone"),
        ({"time_zone": "Europe/Paris"}, "time_zone"),
        ({"goal_time_seconds": 0}, "goal_time_seconds"),
        ({"name": "  "}, "name"),
    ],
)
def test_create_rejects_invalid_input(client, tools, kwargs, message):
    args = {"name": "Race", "date": "2027-04-10", **kwargs}
    out = _text(tools("create_calendar_event", **args))
    assert out.startswith("Error:")
    assert message in out
    client.create_calendar_event.assert_not_called()


def test_create_failure_reports_write_state(client, tools):
    client.create_calendar_event.side_effect = RuntimeError("boom")
    out = json.loads(
        _text(tools("create_calendar_event", name="Race", date="2027-04-10"))
    )
    assert out["write_committed"] == "unknown"


def test_update_merges_into_existing_event(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING)
    out = json.loads(
        _text(
            tools(
                "update_calendar_event",
                event_id=42,
                name="New name",
                goal_time_seconds=2900,
            )
        )
    )
    assert out["status"] == "updated"
    event_id, payload = client.update_calendar_event.call_args.args
    assert event_id == 42
    assert payload["eventName"] == "New name"
    # Untouched fields survive the full-object PUT.
    assert payload["date"] == "2026-12-01"
    assert payload["completionTarget"]["value"] == 10.0
    assert payload["shareableEventUuid"] == "abc"
    assert payload["eventCustomization"]["isPrimaryEvent"] is False
    assert payload["eventCustomization"]["customGoal"]["value"] == 2900.0
    assert out["event"]["goal_time_seconds"] == 2900.0


def test_update_requires_a_field(client, tools):
    out = _text(tools("update_calendar_event", event_id=42))
    assert out.startswith("Error:")
    client.update_calendar_event.assert_not_called()


def test_update_unknown_event(client, tools):
    client.get_calendar_event.return_value = {}
    out = _text(tools("update_calendar_event", event_id=42, name="X"))
    assert "not found" in out
    client.update_calendar_event.assert_not_called()


def test_delete_previews_without_confirm(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING)
    out = json.loads(_text(tools("delete_calendar_event", event_id=42)))
    assert out["status"] == "needs_confirmation"
    assert out["event"]["title"] == "Old name"
    client.delete_calendar_event.assert_not_called()


def test_delete_with_confirm(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING)
    out = json.loads(
        _text(tools("delete_calendar_event", event_id=42, confirm=True))
    )
    assert out["status"] == "deleted"
    client.delete_calendar_event.assert_called_once_with(42)


def test_get_calendar_events_includes_event_id():
    item = {"id": 5, "title": "Race", "date": "2026-12-01", "itemType": "event"}
    assert calendar_events._curate_event(item)["event_id"] == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_time": "09:30\n", "time_zone": "Europe/Paris"},
        {"distance_km": float("nan")},
        {"distance_km": float("inf")},
        {"start_time": "09:30", "time_zone": "Not/AZone"},
        {"start_time": "09:30", "time_zone": "  "},
    ],
)
def test_create_rejects_edge_case_input(client, tools, kwargs):
    args = {"name": "Race", "date": "2027-04-10", **kwargs}
    out = _text(tools("create_calendar_event", **args))
    assert out.startswith("Error:")
    client.create_calendar_event.assert_not_called()


def test_update_start_time_only_reuses_existing_zone(client, tools):
    event = dict(EXISTING, eventTimeLocal={"startTimeHhMm": "08:00", "timeZoneId": "Europe/Paris"})
    client.get_calendar_event.return_value = event
    client.update_calendar_event.return_value = None
    out = json.loads(_text(tools("update_calendar_event", event_id=42, start_time="10:15")))
    payload = client.update_calendar_event.call_args.args[1]
    assert payload["eventTimeLocal"] == {"startTimeHhMm": "10:15", "timeZoneId": "Europe/Paris"}
    assert out["event"]["start_time_local"] == "10:15"


def test_update_zone_only_keeps_start_time(client, tools):
    event = dict(EXISTING, eventTimeLocal={"startTimeHhMm": "08:00", "timeZoneId": "Europe/Paris"})
    client.get_calendar_event.return_value = event
    tools("update_calendar_event", event_id=42, time_zone="Europe/London")
    payload = client.update_calendar_event.call_args.args[1]
    assert payload["eventTimeLocal"] == {"startTimeHhMm": "08:00", "timeZoneId": "Europe/London"}


def test_update_start_time_without_any_zone_is_rejected(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING)
    out = _text(tools("update_calendar_event", event_id=42, start_time="10:15"))
    assert out.startswith("Error:")
    client.update_calendar_event.assert_not_called()


def test_update_can_clear_notes_location_url(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING, note="x", location="y", url="z")
    tools("update_calendar_event", event_id=42, notes="", location="", url="")
    payload = client.update_calendar_event.call_args.args[1]
    assert (payload["note"], payload["location"], payload["url"]) == ("", "", "")


def test_update_goal_time_when_customization_missing(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING, eventCustomization=None)
    tools("update_calendar_event", event_id=42, goal_time_seconds=2500)
    payload = client.update_calendar_event.call_args.args[1]
    assert payload["eventCustomization"]["customGoal"]["value"] == 2500.0


def test_update_uses_garmin_response_when_present(client, tools):
    client.get_calendar_event.return_value = dict(EXISTING)
    client.update_calendar_event.return_value = dict(EXISTING, eventName="From Garmin")
    out = json.loads(_text(tools("update_calendar_event", event_id=42, name="Mine")))
    assert out["event"]["title"] == "From Garmin"


def test_not_found_from_garmin_is_reported_cleanly(client, tools):
    from garminconnect import GarminConnectNotFoundError

    client.get_calendar_event.side_effect = GarminConnectNotFoundError("API Error 404")
    for tool, kwargs in [
        ("update_calendar_event", {"name": "X"}),
        ("delete_calendar_event", {"confirm": True}),
    ]:
        out = _text(tools(tool, event_id=42, **kwargs))
        assert "not found" in out
    client.update_calendar_event.assert_not_called()
    client.delete_calendar_event.assert_not_called()


def test_update_put_5xx_is_unknown_commit_state(client, tools):
    from garminconnect import GarminConnectConnectionError

    client.get_calendar_event.return_value = dict(EXISTING)
    client.update_calendar_event.side_effect = GarminConnectConnectionError(
        "API Error 502 - bad gateway"
    )
    out = json.loads(_text(tools("update_calendar_event", event_id=42, name="X")))
    assert out["write_committed"] == "unknown"


def test_update_read_failure_is_not_committed(client, tools):
    from garminconnect import GarminConnectConnectionError

    client.get_calendar_event.side_effect = GarminConnectConnectionError(
        "API Error 500 - boom"
    )
    out = json.loads(_text(tools("update_calendar_event", event_id=42, name="X")))
    assert out["write_committed"] is False


def test_delete_failure_after_send_is_unknown_on_5xx(client, tools):
    from garminconnect import GarminConnectConnectionError

    client.get_calendar_event.return_value = dict(EXISTING)
    client.delete_calendar_event.side_effect = GarminConnectConnectionError(
        "API Error 503 - unavailable"
    )
    out = json.loads(_text(tools("delete_calendar_event", event_id=42, confirm=True)))
    assert out["write_committed"] == "unknown"


def test_create_note_passes_validated_fields(client, tools):
    client.create_calendar_note.return_value = {"id": 9, "noteName": "Rest day"}
    out = json.loads(
        _text(tools("create_calendar_note", date="2027-01-05", name=" Rest day ", content="easy"))
    )
    assert out["status"] == "created"
    assert out["note"]["id"] == 9
    client.create_calendar_note.assert_called_once_with("2027-01-05", "Rest day", "easy")


@pytest.mark.parametrize(
    "kwargs", [{"date": "2027-13-01", "name": "x"}, {"date": "2027-01-05", "name": "  "}]
)
def test_create_note_rejects_invalid_input(client, tools, kwargs):
    out = _text(tools("create_calendar_note", **kwargs))
    assert out.startswith("Error:")
    client.create_calendar_note.assert_not_called()


def test_create_note_failure_reports_write_state(client, tools):
    client.create_calendar_note.side_effect = RuntimeError("boom")
    out = json.loads(_text(tools("create_calendar_note", date="2027-01-05", name="x")))
    assert out["write_committed"] == "unknown"


def test_update_note_replaces_all_fields(client, tools):
    client.update_calendar_note.return_value = None
    out = json.loads(
        _text(tools("update_calendar_note", note_id=9, date="2027-01-06", name="New", content=""))
    )
    client.update_calendar_note.assert_called_once_with(9, "2027-01-06", "New", "")
    assert out["status"] == "updated"
    assert out["note"] == {"id": 9, "noteName": "New", "content": "", "date": "2027-01-06"}


def test_update_note_rejects_bad_id(client, tools):
    out = _text(tools("update_calendar_note", note_id=0, date="2027-01-06", name="x"))
    assert out.startswith("Error:") and "note_id" in out
    client.update_calendar_note.assert_not_called()


def test_delete_note(client, tools):
    out = json.loads(_text(tools("delete_calendar_note", note_id=9)))
    assert out["status"] == "deleted"
    client.delete_calendar_note.assert_called_once_with(9)


def test_delete_note_5xx_is_unknown_commit_state(client, tools):
    from garminconnect import GarminConnectConnectionError

    client.delete_calendar_note.side_effect = GarminConnectConnectionError("API Error 502 - x")
    out = json.loads(_text(tools("delete_calendar_note", note_id=9)))
    assert out["write_committed"] == "unknown"


def test_get_calendar_notes_filters_and_sorts(client, tools):
    client.get_scheduled_workouts.return_value = {
        "calendarItems": [
            {"id": 2, "itemType": "note", "title": "B", "date": "2027-06-18"},
            {"id": 1, "itemType": "note", "title": "A", "date": "2027-06-17"},
            {"id": 3, "itemType": "event", "title": "Race", "date": "2027-06-17"},
            {"id": 4, "itemType": "note", "title": "Out of range", "date": "2027-06-30"},
            {"id": 1, "itemType": "note", "title": "A", "date": "2027-06-17"},
        ]
    }
    out = json.loads(
        _text(tools("get_calendar_notes", start_date="2027-06-01", end_date="2027-06-20"))
    )
    assert out["count"] == 2
    assert [n["note_id"] for n in out["notes"]] == [1, 2]


def test_get_calendar_notes_rejects_reversed_range(client, tools):
    out = _text(tools("get_calendar_notes", start_date="2027-06-20", end_date="2027-06-01"))
    assert "on or before" in out


@pytest.mark.parametrize("item_type", ["event", "note", " Note "])
def test_move_calendar_item(client, tools, item_type):
    out = json.loads(
        _text(tools("move_calendar_item", item_type=item_type, item_id=7, date="2027-06-21"))
    )
    assert out == {
        "status": "moved",
        "item_type": item_type.strip().lower(),
        "item_id": 7,
        "date": "2027-06-21",
    }
    client.move_calendar_item.assert_called_once_with(item_type.strip().lower(), 7, "2027-06-21")


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"item_type": "workout"}, "reschedule_workout"),
        ({"item_type": ""}, "item_type"),
        ({"item_id": 0}, "item_id"),
        ({"date": "2027-13-01"}, "month"),
    ],
)
def test_move_calendar_item_rejects_invalid_input(client, tools, kwargs, message):
    args = {"item_type": "note", "item_id": 7, "date": "2027-06-21", **kwargs}
    out = _text(tools("move_calendar_item", **args))
    assert out.startswith("Error:") and message in out
    client.move_calendar_item.assert_not_called()


def test_move_calendar_item_5xx_is_unknown_commit_state(client, tools):
    from garminconnect import GarminConnectConnectionError

    client.move_calendar_item.side_effect = GarminConnectConnectionError("API Error 502 - x")
    out = json.loads(
        _text(tools("move_calendar_item", item_type="note", item_id=7, date="2027-06-21"))
    )
    assert out["write_committed"] == "unknown"
