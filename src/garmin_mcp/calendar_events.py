"""
Calendar event (race) functions for Garmin Connect MCP Server
"""
import json
import math
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, List, Optional

from garminconnect import GarminConnectNotFoundError

from garmin_mcp.write_errors import WriteTracker

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The garmin_client will be set by the main file
garmin_client = None

# Garmin's calendar-service groups every calendar entry under an itemType.
# Races the user added or subscribed to arrive as "event"; workouts, weigh-ins
# and badges share the same feed and are ignored here.
EVENT_ITEM_TYPE = "event"

# Garmin's calendar-service sends completionTarget.unit as one of these
# strings (Connect's custom-event picker: meter, kilometer, yard, mile).
# Always report meters; unknown units become None.
_DISTANCE_UNIT_TO_METERS = {
    "meter": 1.0,
    "kilometer": 1000.0,
    "yard": 0.9144,
    "mile": 1609.344,
}


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def _validate_date(value: str, field: str = "date") -> date:
    if not _DATE_RE.fullmatch(value):
        raise ValueError(f"Invalid {field} '{value}': expected YYYY-MM-DD")
    return date.fromisoformat(value)


def _month_range(start: date, end: date):
    """Yield (year, month) pairs covering start..end inclusive."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _fetch_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Return the raw calendar items for one month.

    Despite its name, the library's get_scheduled_workouts returns the whole
    calendar feed for a month, events included. It takes a 1-indexed month and
    converts it to the 0-indexed month Garmin's calendar-service expects.
    """
    data = garmin_client.get_scheduled_workouts(year, month)
    if not isinstance(data, dict):
        return []
    items = data.get("calendarItems")
    return items if isinstance(items, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    """Return a dict for Garmin fields that may be null or another shape."""
    return value if isinstance(value, dict) else {}


def _target_distance_meters(item: Dict[str, Any]) -> Optional[float]:
    """Return the event's distance goal, if it is expressed as a distance."""
    target = _as_dict(item.get("completionTarget"))
    if target.get("unitType") != "distance":
        return None
    value = target.get("value")
    scale = _DISTANCE_UNIT_TO_METERS.get(target.get("unit"))
    if not isinstance(value, (int, float)) or isinstance(value, bool) or scale is None:
        return None
    return float(value) * scale


def _fetch_event_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the event detail payload, which contains the custom goal."""
    event_id = item.get("id")
    event_uuid = _clean_str(item.get("shareableEventUuid"))
    if isinstance(event_id, (int, str)) and not isinstance(event_id, bool):
        path = f"/calendar-service/event/{event_id}"
    elif event_uuid:
        path = f"/calendar-service/event/{event_uuid}/shareable"
    else:
        return {}

    try:
        return _as_dict(garmin_client.connectapi(path))
    except Exception:
        # Event-detail availability must not make the calendar list unusable.
        return {}


def _goal_time_seconds(detail: Dict[str, Any]) -> Optional[float]:
    """Return the user's custom event goal when Garmin stores it as time."""
    customization = _as_dict(detail.get("eventCustomization"))
    goal = _as_dict(customization.get("customGoal"))
    value = goal.get("value")
    if (
        goal.get("unitType") != "time"
        or goal.get("unit") != "second"
        or not isinstance(value, (int, float))
        or isinstance(value, bool)
    ):
        return None
    return float(value)


def _clean_str(value: Any) -> Optional[str]:
    """Return a trimmed string, or None for the blanks Garmin sends."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _curate_event(
    item: Dict[str, Any], detail: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Curate one raw calendar event into a compact shape."""
    event_time = _as_dict(item.get("eventTimeLocal"))
    return {
        "event_id": item.get("id"),
        "title": item.get("title"),
        "date": item.get("date"),
        "is_race": bool(item.get("isRace")),
        "primary_event": bool(item.get("primaryEvent")),
        "subscribed": bool(item.get("subscribed")),
        "distance_meters": _target_distance_meters(item),
        "goal_time_seconds": _goal_time_seconds(detail or {}),
        "start_time_local": event_time.get("startTimeHhMm"),
        "time_zone": event_time.get("timeZoneId"),
        "location": _clean_str(item.get("location")),
        "url": item.get("url"),
        "event_uuid": item.get("shareableEventUuid"),
    }


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _build_event_fields(
    *,
    name: Optional[str],
    event_date: Optional[str],
    event_type: Optional[str],
    is_race: Optional[bool],
    distance_km: Optional[float],
    start_time: Optional[str],
    time_zone: Optional[str],
    location: Optional[str],
    url: Optional[str],
    notes: Optional[str],
    goal_time_seconds: Optional[int],
) -> Dict[str, Any]:
    """Validate the given arguments and map them onto Garmin's event fields.

    Only arguments that are not None are returned, so the result can be
    merged into an existing event (update) or used as a new one (create).
    Raises ValueError with a user-facing message on invalid input.
    """
    fields: Dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise ValueError("name must not be empty.")
        fields["eventName"] = name.strip()
    if event_date is not None:
        fields["date"] = _validate_date(event_date, "date").isoformat()
    if event_type is not None:
        if not event_type.strip():
            raise ValueError("event_type must not be empty.")
        fields["eventType"] = event_type.strip()
    if is_race is not None:
        fields["race"] = bool(is_race)
    if distance_km is not None:
        if not math.isfinite(distance_km) or distance_km <= 0:
            raise ValueError("distance_km must be a finite number greater than 0.")
        fields["completionTarget"] = {
            "value": float(distance_km),
            "unit": "kilometer",
            "unitType": "distance",
        }
    if start_time is not None:
        if not _TIME_RE.fullmatch(start_time):
            raise ValueError("start_time must be in HH:MM (24-hour) format.")
        fields["_start_time"] = start_time
    if time_zone is not None:
        zone = time_zone.strip()
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"Unknown time_zone {time_zone!r}; use an IANA name such as Europe/Paris."
            )
        fields["_time_zone"] = zone
    if location is not None:
        fields["location"] = location.strip()
    if url is not None:
        fields["url"] = url.strip()
    if notes is not None:
        fields["note"] = notes
    if goal_time_seconds is not None:
        if goal_time_seconds <= 0:
            raise ValueError("goal_time_seconds must be greater than 0.")
        fields["_goal_time_seconds"] = int(goal_time_seconds)
    return fields


def _apply_time(event: Dict[str, Any], fields: Dict[str, Any]) -> None:
    """Resolve start time and zone from ``fields`` and the event's current values.

    Either may be omitted when the event already has it. Raises ValueError
    when a start time ends up without a zone (or the reverse).
    """
    start = fields.pop("_start_time", None)
    zone = fields.pop("_time_zone", None)
    if start is None and zone is None:
        return
    current = _as_dict(event.get("eventTimeLocal"))
    start = start or current.get("startTimeHhMm")
    zone = zone or current.get("timeZoneId")
    if not start or not zone:
        raise ValueError(
            "start_time and time_zone (IANA name, e.g. Europe/Paris) are needed together."
        )
    event["eventTimeLocal"] = {
        **current,
        "startTimeHhMm": start,
        "timeZoneId": zone,
    }


def _apply_goal_time(event: Dict[str, Any], fields: Dict[str, Any]) -> None:
    """Move the goal time from ``fields`` into the event's customization."""
    seconds = fields.pop("_goal_time_seconds", None)
    if seconds is None:
        return
    customization = dict(_as_dict(event.get("eventCustomization")))
    customization["customGoal"] = {
        "value": float(seconds),
        "unit": "second",
        "unitType": "time",
    }
    event["eventCustomization"] = customization


def _parse_event_id(event_id: Any) -> int:
    try:
        value = int(event_id)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid event_id: {event_id}")
    if value <= 0:
        raise ValueError(f"Invalid event_id: {event_id}")
    return value


def _get_event(event_id: int) -> Dict[str, Any]:
    """Fetch one event; returns {} when it does not exist."""
    try:
        return _as_dict(garmin_client.get_calendar_event(event_id))
    except GarminConnectNotFoundError:
        return {}


def _event_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    """Compact view of a raw event (from the detail endpoint)."""
    return _curate_event(
        {
            "id": event.get("id"),
            "title": event.get("eventName"),
            "date": event.get("date"),
            "isRace": event.get("race"),
            "primaryEvent": _as_dict(event.get("eventCustomization")).get(
                "isPrimaryEvent"
            ),
            "subscribed": event.get("subscribed"),
            "completionTarget": event.get("completionTarget"),
            "eventTimeLocal": event.get("eventTimeLocal"),
            "location": event.get("location"),
            "url": event.get("url"),
            "shareableEventUuid": event.get("shareableEventUuid"),
        },
        event,
    )


def register_tools(app):
    """Register all calendar event tools with the MCP server app"""

    @app.tool()
    async def get_calendar_events(start_date: str, end_date: str) -> str:
        """Get races and events on the Garmin Connect calendar between two dates

        Returns calendar entries the user added or subscribed to in Garmin
        Connect, such as upcoming races. Use this to answer questions about
        which events or races are scheduled.

        These entries are not returned by get_scheduled_workouts, which covers
        only workouts, nor by get_goals. This is the only tool that exposes
        them.

        Each event reports its distance in meters when Garmin stores one,
        the user's custom goal time in seconds when set, the local start
        time when the organiser published it, and two flags: is_race marks
        the entry as a race rather than a general event, and primary_event
        marks the goal race that an active training plan targets. Goal time
        comes from a per-event detail request.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
        """
        try:
            start = _validate_date(start_date, "start_date")
            end = _validate_date(end_date, "end_date")
            if start > end:
                return "start_date must be on or before end_date."

            events: List[Dict[str, Any]] = []
            seen = set()
            for year, month in _month_range(start, end):
                for item in _fetch_month(year, month):
                    if not isinstance(item, dict):
                        continue
                    if item.get("itemType") != EVENT_ITEM_TYPE:
                        continue
                    # The first and last month of the range extend past it.
                    day = item.get("date")
                    if not isinstance(day, str) or not start_date <= day <= end_date:
                        continue
                    # Multi-month responses can repeat an event at the seams.
                    key = (item.get("shareableEventUuid"), item.get("title"), day)
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append(_curate_event(item, _fetch_event_detail(item)))

            events.sort(key=lambda event: (event["date"], event["title"] or ""))

            curated = {
                "count": len(events),
                "date_range": {"start": start_date, "end": end_date},
                "events": events,
            }
            return json.dumps(curated, indent=2, ensure_ascii=False)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error retrieving calendar events: {str(e)}"

    @app.tool()
    async def create_calendar_event(
        name: str,
        date: str,
        distance_km: Optional[float] = None,
        event_type: str = "running",
        is_race: bool = True,
        start_time: Optional[str] = None,
        time_zone: Optional[str] = None,
        location: Optional[str] = None,
        url: Optional[str] = None,
        notes: Optional[str] = None,
        goal_time_seconds: Optional[int] = None,
    ) -> str:
        """Add a race or event to the Garmin Connect calendar

        Creates a calendar entry such as a race. It then shows up in
        get_calendar_events (use that to find its event_id). Not idempotent:
        calling twice creates two events. If a write fails with
        write_committed="unknown", check get_calendar_events before retrying.

        Args:
            name: Event name
            date: Event date in YYYY-MM-DD format
            distance_km: Target distance in kilometers
            event_type: Garmin event type key (default "running")
            is_race: Mark the entry as a race (default true)
            start_time: Local start time in HH:MM (requires time_zone)
            time_zone: IANA time zone for start_time, e.g. Europe/Paris
            location: Free-text location, e.g. a city
            url: Event web page
            notes: Free-text notes
            goal_time_seconds: Your goal finishing time in seconds
        """
        tracker = WriteTracker("create_calendar_event", "Error creating calendar event")
        try:
            try:
                fields = _build_event_fields(
                    name=name,
                    event_date=date,
                    event_type=event_type,
                    is_race=is_race,
                    distance_km=distance_km,
                    start_time=start_time,
                    time_zone=time_zone,
                    location=location,
                    url=url,
                    notes=notes,
                    goal_time_seconds=goal_time_seconds,
                )
            except ValueError as e:
                return f"Error: {e}"
            event: Dict[str, Any] = dict(fields)
            try:
                _apply_time(event, event)
            except ValueError as e:
                return f"Error: {e}"
            _apply_goal_time(event, event)

            tracker.sending()
            result = garmin_client.create_calendar_event(event)
            tracker.committed()

            return json.dumps(
                {"status": "created", "event": result}, indent=2, ensure_ascii=False
            )
        except Exception as e:
            return tracker.error(e)

    @app.tool()
    async def update_calendar_event(
        event_id: int,
        name: Optional[str] = None,
        date: Optional[str] = None,
        distance_km: Optional[float] = None,
        event_type: Optional[str] = None,
        is_race: Optional[bool] = None,
        start_time: Optional[str] = None,
        time_zone: Optional[str] = None,
        location: Optional[str] = None,
        url: Optional[str] = None,
        notes: Optional[str] = None,
        goal_time_seconds: Optional[int] = None,
    ) -> str:
        """Change fields of an event on the Garmin Connect calendar

        Only the arguments you pass are changed; everything else keeps its
        value. Get event_id from get_calendar_events. Repeating the same
        call is safe. Pass "" to clear notes, location or url. Distance,
        start time and goal time can be changed but not cleared. start_time
        and time_zone may be passed on their own; the event's current value
        is used for the other.

        Args:
            event_id: Event id from get_calendar_events ("event_id")
            name: New event name
            date: New date in YYYY-MM-DD format
            distance_km: New target distance in kilometers
            event_type: New Garmin event type key
            is_race: Whether the entry is a race
            start_time: New local start time in HH:MM
            time_zone: IANA time zone, e.g. Europe/Paris
            location: New free-text location
            url: New event web page
            notes: New free-text notes
            goal_time_seconds: New goal finishing time in seconds
        """
        tracker = WriteTracker("update_calendar_event", "Error updating calendar event")
        try:
            try:
                eid = _parse_event_id(event_id)
                fields = _build_event_fields(
                    name=name,
                    event_date=date,
                    event_type=event_type,
                    is_race=is_race,
                    distance_km=distance_km,
                    start_time=start_time,
                    time_zone=time_zone,
                    location=location,
                    url=url,
                    notes=notes,
                    goal_time_seconds=goal_time_seconds,
                )
            except ValueError as e:
                return f"Error: {e}"
            if not fields:
                return "Error: pass at least one field to change."

            # Garmin's PUT replaces the whole event, so merge into the current one.
            event = dict(_get_event(eid))
            if not event:
                return f"Error: event {eid} not found."
            try:
                _apply_time(event, fields)
            except ValueError as e:
                return f"Error: {e}"
            _apply_goal_time(event, fields)
            if "completionTarget" in fields:
                fields["completionTarget"] = {
                    **_as_dict(event.get("completionTarget")),
                    **fields["completionTarget"],
                }
            event.update(fields)

            tracker.sending()
            response = garmin_client.update_calendar_event(eid, event)
            tracker.committed()

            saved = response if isinstance(response, dict) and response else event
            return json.dumps(
                {"status": "updated", "event": _event_summary(saved)},
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            return tracker.error(e)

    @app.tool()
    async def delete_calendar_event(event_id: int, confirm: bool = False) -> str:
        """Delete an event from the Garmin Connect calendar

        This cannot be undone. Call once with confirm=false (the default) to
        preview the event, then call again with confirm=true to delete it.

        Args:
            event_id: Event id from get_calendar_events ("event_id")
            confirm: Must be true to actually delete. Default false returns a preview.
        """
        tracker = WriteTracker("delete_calendar_event", "Error deleting calendar event")
        try:
            try:
                eid = _parse_event_id(event_id)
            except ValueError as e:
                return f"Error: {e}"

            event = _get_event(eid)
            if not event:
                return f"Error: event {eid} not found."
            summary = _event_summary(event)
            if not confirm:
                return json.dumps(
                    {
                        "status": "needs_confirmation",
                        "event": summary,
                        "message": (
                            "This permanently deletes the event from the Garmin "
                            "Connect calendar. Call again with confirm=true to proceed."
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                )

            tracker.sending()
            garmin_client.delete_calendar_event(eid)
            tracker.committed()
            return json.dumps(
                {
                    "status": "deleted",
                    "event": summary,
                    "message": f"Event {eid} deleted.",
                },
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            return tracker.error(e)

    return app
