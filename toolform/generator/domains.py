"""Domain library for the synthetic tool generator.

Each domain describes a small, self-consistent world: an entity, its typed
fields with concrete value pools, and the operations you can perform on it.
From that the generator builds tools, a deterministic simulator state, and
natural-language requests whose answer is known by construction.

Why generate rather than scrape: scraped APIs are contaminated (models have
seen them), uncontrolled (you cannot dial complexity), and unverifiable (you
cannot execute them). A generator gives fresh, parametric, executable
instances forever. The study's real-tool arm shows
the laws are not an artefact of this choice.

Adding a domain is pure data — no new code.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ..ir import TypeKind


@dataclass(frozen=True)
class FieldSpec:
    """One attribute of a domain entity."""

    name: str
    kind: TypeKind
    values: tuple[Any, ...] = ()  # sample pool for scalars
    enum: tuple[str, ...] = ()  # if set, the field is an enum
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""

    @property
    def is_enum(self) -> bool:
        return bool(self.enum)


@dataclass(frozen=True)
class OpSpec:
    """One operation the domain supports.

    ``kernel`` names an executable function in
    :mod:`toolform.generator.kernels`. ``roles`` maps kernel argument roles to
    domain field names, which is how a generic kernel becomes a specific tool.
    """

    verb: str  # "create", "find", "cancel", ...
    kernel: str  # executable semantics
    roles: dict[str, str] = field(default_factory=dict)
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    description: str = ""
    request_templates: tuple[str, ...] = ()
    returns: str = "a result record"


@dataclass(frozen=True)
class DomainSpec:
    name: str
    entity: str
    entity_plural: str
    fields: tuple[FieldSpec, ...]
    ops: tuple[OpSpec, ...]
    blurb: str = ""

    def field(self, name: str) -> FieldSpec | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


S, I, N, B = TypeKind.STRING, TypeKind.INTEGER, TypeKind.NUMBER, TypeKind.BOOLEAN  # noqa: E741 (the kinds read as type letters)


# --------------------------------------------------------------------------- #
# helper builders keep the domain table readable
# --------------------------------------------------------------------------- #


def _f(name, kind, values=(), *, enum=(), desc="", lo=None, hi=None, unit=""):
    return FieldSpec(name, kind, tuple(values), tuple(enum), desc, lo, hi, unit)


def _op(verb, kernel, *, roles=None, req=(), opt=(), desc="", templates=(), returns="a result record"):
    return OpSpec(verb, kernel, roles or {}, tuple(req), tuple(opt), desc, tuple(templates), returns)


# --------------------------------------------------------------------------- #
# the domains
# --------------------------------------------------------------------------- #

DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec(
        name="calendar",
        entity="meeting",
        entity_plural="meetings",
        blurb="scheduling and calendars",
        fields=(
            _f(
                "title",
                S,
                ["Budget review", "Design sync", "One-on-one", "Sprint demo", "Client call"],
                desc="Name of the meeting.",
            ),
            _f(
                "day",
                S,
                ["2027-03-04", "2027-03-11", "2027-04-02", "2027-05-19"],
                desc="Calendar date in YYYY-MM-DD form.",
            ),
            _f("start_hour", I, [9, 10, 13, 15, 16], desc="Hour the meeting starts, 0-23.", lo=0, hi=23),
            _f(
                "duration_minutes",
                I,
                [15, 30, 45, 60, 90],
                desc="How long the meeting runs.",
                lo=5,
                hi=480,
                unit="minutes",
            ),
            _f("room", S, ["Aspen", "Birch", "Cedar", "Dogwood"], desc="Room to book."),
            _f("attendee", S, ["nina", "omar", "priya", "quentin", "rosa"], desc="Username of an attendee."),
            _f("visibility", S, enum=["public", "private", "confidential"], desc="Who can see the entry."),
            _f("recurring", B, desc="Whether the meeting repeats weekly."),
        ),
        ops=(
            _op(
                "schedule",
                "create",
                req=("title", "day", "start_hour"),
                opt=("duration_minutes", "room", "visibility", "recurring"),
                desc="Put a new meeting on the calendar.",
                templates=(
                    "Put {title} on the calendar for {day} starting at {start_hour}.",
                    "Book a meeting called {title} on {day} at {start_hour}.",
                ),
                returns="the id of the new meeting",
            ),
            _op(
                "find",
                "search",
                req=("day",),
                opt=("room", "attendee", "visibility"),
                desc="List meetings that match a day and optional filters.",
                templates=("What is on the calendar for {day}?", "Show me the meetings on {day}."),
                returns="a list of matching meetings",
            ),
            _op(
                "cancel",
                "delete",
                req=("record_id",),
                desc="Remove a meeting from the calendar.",
                templates=("Cancel meeting {record_id}.", "Drop the meeting with id {record_id}."),
                returns="whether the meeting was removed",
            ),
            _op(
                "move",
                "update",
                roles={"field": "start_hour"},
                req=("record_id", "start_hour"),
                desc="Change the start time of an existing meeting.",
                templates=("Move meeting {record_id} to start at {start_hour}.",),
                returns="the updated meeting",
            ),
            _op(
                "count",
                "count",
                req=("day",),
                opt=("room",),
                desc="Count how many meetings fall on a day.",
                templates=("How many meetings are there on {day}?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="inventory",
        entity="item",
        entity_plural="items",
        blurb="warehouse stock",
        fields=(
            _f("sku", S, ["SKU-1180", "SKU-2245", "SKU-3390", "SKU-4471"], desc="Stock keeping unit code."),
            _f("warehouse", S, enum=["north", "south", "east", "west"], desc="Which warehouse holds the stock."),
            _f("quantity", I, [4, 12, 40, 175, 900], desc="Number of units.", lo=0, hi=100000),
            _f("unit_price", N, [3.5, 12.99, 48.0, 210.75], desc="Price per unit in dollars.", lo=0),
            _f("category", S, enum=["tools", "fasteners", "electrical", "safety"], desc="Product category."),
            _f("reorder_level", I, [5, 25, 100], desc="Level at which restocking is triggered.", lo=0),
            _f("discontinued", B, desc="Whether the item is no longer stocked."),
        ),
        ops=(
            _op(
                "add_stock",
                "create",
                req=("sku", "warehouse", "quantity"),
                opt=("unit_price", "category"),
                desc="Record new stock arriving at a warehouse.",
                templates=("Log {quantity} units of {sku} arriving at the {warehouse} warehouse.",),
                returns="the id of the stock record",
            ),
            _op(
                "check",
                "search",
                req=("sku",),
                opt=("warehouse", "category"),
                desc="Look up current stock for an item.",
                templates=("How much {sku} do we have?", "Check stock for {sku}."),
                returns="matching stock records",
            ),
            _op(
                "adjust",
                "update",
                roles={"field": "quantity"},
                req=("record_id", "quantity"),
                desc="Set the quantity on an existing stock record.",
                templates=("Set the quantity on record {record_id} to {quantity}.",),
                returns="the updated record",
            ),
            _op(
                "value",
                "aggregate",
                roles={"field": "quantity", "agg": "sum"},
                req=("warehouse",),
                opt=("category",),
                desc="Total the units held in a warehouse.",
                templates=("What is the total stock in the {warehouse} warehouse?",),
                returns="a total",
            ),
            _op(
                "low_stock",
                "rank",
                roles={"field": "quantity", "order": "asc"},
                req=("warehouse",),
                opt=("limit",),
                desc="List the items with the least stock first.",
                templates=("Which items are running low in {warehouse}?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="geo",
        entity="place",
        entity_plural="places",
        blurb="places and distances",
        fields=(
            _f("place", S, ["Nairobi", "Lisbon", "Osaka", "Bogota", "Helsinki"], desc="Name of a city."),
            _f("country", S, ["Kenya", "Portugal", "Japan", "Colombia", "Finland"], desc="Country the city is in."),
            _f("latitude", N, [-1.29, 38.72, 34.69, 4.71, 60.17], desc="Latitude in degrees.", lo=-90, hi=90),
            _f("longitude", N, [36.82, -9.14, 135.5, -74.07, 24.94], desc="Longitude in degrees.", lo=-180, hi=180),
            _f("units", S, enum=["km", "miles"], desc="Distance unit to answer in."),
            _f("radius", I, [5, 25, 100, 500], desc="Search radius.", lo=1, hi=20000),
            _f("mode", S, enum=["driving", "walking", "cycling", "transit"], desc="Travel mode."),
        ),
        ops=(
            _op(
                "locate",
                "lookup",
                req=("place",),
                desc="Get the coordinates of a named place.",
                templates=("Where is {place}?", "Get the coordinates for {place}."),
                returns="coordinates and country",
            ),
            _op(
                "distance",
                "compute",
                roles={"op": "distance"},
                req=("place", "country"),
                opt=("units", "mode"),
                desc="Measure the distance between two places.",
                templates=("How far is it from {place} to somewhere in {country}?",),
                returns="a distance",
            ),
            _op(
                "nearby",
                "search",
                req=("place", "radius"),
                opt=("units",),
                desc="Find places within a radius of a starting point.",
                templates=("What is within {radius} of {place}?",),
                returns="a list of nearby places",
            ),
        ),
    ),
    DomainSpec(
        name="finance",
        entity="transaction",
        entity_plural="transactions",
        blurb="accounts and payments",
        fields=(
            _f("account", S, ["ACC-4410", "ACC-5521", "ACC-6632"], desc="Account number."),
            _f("amount", N, [12.5, 250.0, 1499.99, 20000.0], desc="Amount of money.", lo=0),
            _f("currency", S, enum=["USD", "EUR", "JPY", "GBP"], desc="Currency code."),
            _f(
                "counterparty",
                S,
                ["Ridgeway Ltd", "Kessler Foods", "Vantage Media"],
                desc="Who the money goes to or comes from.",
            ),
            _f("category", S, enum=["payroll", "supplies", "travel", "utilities"], desc="Spending category."),
            _f("posted_on", S, ["2027-01-08", "2027-02-14", "2027-03-30"], desc="Date the transaction posted."),
            _f("cleared", B, desc="Whether the transaction has cleared."),
        ),
        ops=(
            _op(
                "transfer",
                "create",
                req=("account", "amount", "currency"),
                opt=("counterparty", "category"),
                desc="Move money out of an account.",
                templates=("Send {amount} {currency} from {account}.",),
                returns="the id of the new transaction",
            ),
            _op(
                "history",
                "search",
                req=("account",),
                opt=("category", "currency", "cleared"),
                desc="List transactions on an account.",
                templates=("Show the transactions on {account}.",),
                returns="a list of transactions",
            ),
            _op(
                "balance",
                "aggregate",
                roles={"field": "amount", "agg": "sum"},
                req=("account",),
                opt=("category",),
                desc="Total the amounts on an account.",
                templates=("What is the balance on {account}?",),
                returns="a total amount",
            ),
            _op(
                "convert",
                "convert",
                roles={"from": "currency"},
                req=("amount", "currency"),
                opt=("category",),
                desc="Convert an amount between currencies.",
                templates=("Convert {amount} {currency} to another currency.",),
                returns="the converted amount",
            ),
            _op(
                "largest",
                "rank",
                roles={"field": "amount", "order": "desc"},
                req=("account",),
                opt=("limit",),
                desc="List the biggest transactions first.",
                templates=("What were the biggest charges on {account}?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="messaging",
        entity="message",
        entity_plural="messages",
        blurb="chat and email",
        fields=(
            _f("recipient", S, ["dana", "elias", "farrah", "gideon"], desc="Who receives the message."),
            _f("channel", S, enum=["email", "sms", "chat", "push"], desc="How to deliver it."),
            _f("subject", S, ["Weekly update", "Invoice attached", "Door code"], desc="Subject line."),
            _f(
                "body",
                S,
                ["Numbers look good.", "Please review by Friday.", "Rescheduled to Tuesday."],
                desc="Message text.",
            ),
            _f("priority", S, enum=["low", "normal", "high", "urgent"], desc="Delivery priority."),
            _f("attachments", TypeKind.ARRAY, ["report.pdf", "photo.jpg", "notes.txt"], desc="Files to attach."),
            _f("read_receipt", B, desc="Ask for a read receipt."),
        ),
        ops=(
            _op(
                "send",
                "create",
                req=("recipient", "channel", "body"),
                opt=("subject", "priority", "attachments", "read_receipt"),
                desc="Send a message to someone.",
                templates=("Send {recipient} a {channel} saying {body}.",),
                returns="the id of the sent message",
            ),
            _op(
                "search",
                "search",
                req=("recipient",),
                opt=("channel", "priority"),
                desc="Find messages to or from a person.",
                templates=("Find the messages I sent to {recipient}.",),
                returns="a list of messages",
            ),
            _op(
                "unread_count",
                "count",
                req=("recipient",),
                opt=("channel",),
                desc="Count messages waiting for someone.",
                templates=("How many messages is {recipient} waiting on?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="devices",
        entity="device",
        entity_plural="devices",
        blurb="smart home and IoT",
        fields=(
            _f("device_id", S, ["thermo-01", "lamp-04", "lock-02", "cam-07"], desc="Identifier of the device."),
            _f("room", S, enum=["kitchen", "garage", "study", "hallway"], desc="Where the device is."),
            _f("state", S, enum=["on", "off", "standby"], desc="Power state."),
            _f("target_value", N, [16.5, 20.0, 22.5, 68.0], desc="Setpoint for the device.", lo=-40, hi=200),
            _f("brightness", I, [10, 40, 75, 100], desc="Brightness percentage.", lo=0, hi=100),
            _f("locked", B, desc="Whether the device is locked."),
        ),
        ops=(
            _op(
                "set_state",
                "update",
                roles={"field": "state"},
                req=("device_id", "state"),
                opt=("room",),
                desc="Turn a device on or off.",
                templates=("Turn the {device_id} {state}.",),
                returns="the new device state",
            ),
            _op(
                "set_target",
                "update",
                roles={"field": "target_value"},
                req=("device_id", "target_value"),
                desc="Set a device's target value.",
                templates=("Set {device_id} to {target_value}.",),
                returns="the new setpoint",
            ),
            _op(
                "status",
                "lookup",
                req=("device_id",),
                desc="Read the current state of a device.",
                templates=("What is {device_id} doing right now?",),
                returns="the device record",
            ),
            _op(
                "list_room",
                "search",
                req=("room",),
                opt=("state",),
                desc="List the devices in a room.",
                templates=("What devices are in the {room}?",),
                returns="a list of devices",
            ),
        ),
    ),
    DomainSpec(
        name="travel",
        entity="booking",
        entity_plural="bookings",
        blurb="flights and hotels",
        fields=(
            _f("origin", S, ["Denver", "Seville", "Kyoto", "Perth"], desc="Where the trip starts."),
            _f("destination", S, ["Reykjavik", "Cusco", "Hanoi", "Tallinn"], desc="Where the trip ends."),
            _f("depart_on", S, ["2027-06-03", "2027-07-21", "2027-09-09"], desc="Departure date."),
            _f("cabin", S, enum=["economy", "premium", "business", "first"], desc="Cabin class."),
            _f("passengers", I, [1, 2, 4], desc="Number of travellers.", lo=1, hi=9),
            _f("max_price", N, [350.0, 900.0, 2400.0], desc="Highest acceptable price.", lo=0),
            _f("refundable", B, desc="Whether the fare must be refundable."),
        ),
        ops=(
            _op(
                "book",
                "create",
                req=("origin", "destination", "depart_on"),
                opt=("cabin", "passengers", "refundable"),
                desc="Book travel between two places.",
                templates=("Book me from {origin} to {destination} on {depart_on}.",),
                returns="the booking id",
            ),
            _op(
                "search",
                "search",
                req=("origin", "destination"),
                opt=("cabin", "max_price"),
                desc="Search for available trips.",
                templates=("Find trips from {origin} to {destination}.",),
                returns="a list of options",
            ),
            _op(
                "cancel",
                "delete",
                req=("record_id",),
                desc="Cancel an existing booking.",
                templates=("Cancel booking {record_id}.",),
                returns="whether it was cancelled",
            ),
            _op(
                "cheapest",
                "rank",
                roles={"field": "max_price", "order": "asc"},
                req=("destination",),
                opt=("limit",),
                desc="Rank trips by price, cheapest first.",
                templates=("What is the cheapest way to get to {destination}?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="library",
        entity="book",
        entity_plural="books",
        blurb="library catalogue",
        fields=(
            _f("title", S, ["Tidal Grammar", "The Copper Almanac", "Hollow Signals"], desc="Book title."),
            _f("author", S, ["Vela Sunder", "Marek Ostrow", "Ines Baptiste"], desc="Author name."),
            _f("shelf", S, enum=["fiction", "reference", "archive", "children"], desc="Which section it lives in."),
            _f("year", I, [1974, 1998, 2011, 2024], desc="Year of publication.", lo=1400, hi=2100),
            _f("copies", I, [1, 3, 8], desc="Copies held.", lo=0, hi=500),
            _f("borrower", S, ["hal", "iris", "jonah"], desc="Who has it out."),
            _f("overdue", B, desc="Whether the loan is overdue."),
        ),
        ops=(
            _op(
                "borrow",
                "create",
                req=("title", "borrower"),
                opt=("shelf",),
                desc="Check a book out to someone.",
                templates=("Check out {title} for {borrower}.",),
                returns="the loan id",
            ),
            _op(
                "find",
                "search",
                req=("author",),
                opt=("shelf", "year"),
                desc="Search the catalogue.",
                templates=("What do we have by {author}?",),
                returns="matching books",
            ),
            _op(
                "return_book",
                "delete",
                req=("record_id",),
                desc="Close out a loan.",
                templates=("Return loan {record_id}.",),
                returns="whether the loan closed",
            ),
            _op(
                "count_shelf",
                "count",
                req=("shelf",),
                opt=("year",),
                desc="Count the books on a shelf.",
                templates=("How many books are on the {shelf} shelf?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="health",
        entity="record",
        entity_plural="records",
        blurb="appointments and vitals",
        fields=(
            _f("patient", S, ["p-2201", "p-3312", "p-4423"], desc="Patient identifier."),
            _f("clinic", S, enum=["general", "dental", "optical", "physio"], desc="Which clinic."),
            _f("metric", S, enum=["weight", "heart_rate", "steps", "sleep_hours"], desc="Which measurement."),
            _f("value", N, [62.4, 71.0, 8400.0, 6.5], desc="Recorded value."),
            _f("taken_on", S, ["2027-02-02", "2027-02-16", "2027-03-01"], desc="Date of the reading."),
            _f("notes", S, ["Feeling well.", "Slight headache.", "No change."], desc="Free-text note."),
        ),
        ops=(
            _op(
                "log",
                "create",
                req=("patient", "metric", "value"),
                opt=("taken_on", "notes"),
                desc="Record a health measurement.",
                templates=("Log a {metric} of {value} for {patient}.",),
                returns="the record id",
            ),
            _op(
                "history",
                "search",
                req=("patient",),
                opt=("metric", "clinic"),
                desc="Pull a patient's past readings.",
                templates=("Show {patient}'s readings.",),
                returns="a list of readings",
            ),
            _op(
                "average",
                "aggregate",
                roles={"field": "value", "agg": "mean"},
                req=("patient", "metric"),
                desc="Average a patient's readings for one metric.",
                templates=("What is {patient}'s average {metric}?",),
                returns="an average",
            ),
        ),
    ),
    DomainSpec(
        name="tickets",
        entity="ticket",
        entity_plural="tickets",
        blurb="support desk",
        fields=(
            _f("ticket_id", S, ["T-9001", "T-9002", "T-9003"], desc="Ticket number."),
            _f("requester", S, ["kai", "lena", "milo"], desc="Who opened it."),
            _f("severity", S, enum=["s1", "s2", "s3", "s4"], desc="How urgent it is."),
            _f("queue", S, enum=["billing", "network", "hardware", "accounts"], desc="Which queue owns it."),
            _f("summary", S, ["Printer offline", "Cannot log in", "Double charged"], desc="One-line summary."),
            _f("age_days", I, [0, 2, 9, 40], desc="How long it has been open.", lo=0),
            _f("escalated", B, desc="Whether it has been escalated."),
        ),
        ops=(
            _op(
                "open",
                "create",
                req=("requester", "summary", "queue"),
                opt=("severity", "escalated"),
                desc="Open a new support ticket.",
                templates=("Open a {queue} ticket for {requester} about {summary}.",),
                returns="the ticket id",
            ),
            _op(
                "triage",
                "update",
                roles={"field": "severity"},
                req=("record_id", "severity"),
                desc="Change a ticket's severity.",
                templates=("Set ticket {record_id} to {severity}.",),
                returns="the updated ticket",
            ),
            _op(
                "queue_list",
                "search",
                req=("queue",),
                opt=("severity", "escalated"),
                desc="List the tickets in a queue.",
                templates=("What is open in the {queue} queue?",),
                returns="a list of tickets",
            ),
            _op(
                "oldest",
                "rank",
                roles={"field": "age_days", "order": "desc"},
                req=("queue",),
                opt=("limit",),
                desc="List the longest-open tickets first.",
                templates=("Which {queue} tickets have been open longest?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="media",
        entity="track",
        entity_plural="tracks",
        blurb="music and video",
        fields=(
            _f("track", S, ["Anvil Light", "Second Harbour", "Paper Radio"], desc="Track name."),
            _f("artist", S, ["Cold Meridian", "Nube", "The Falter"], desc="Performer."),
            _f("genre", S, enum=["ambient", "folk", "techno", "jazz"], desc="Genre label."),
            _f("length_seconds", I, [143, 214, 388], desc="Track length.", lo=1, unit="seconds"),
            _f("rating", I, [1, 3, 5], desc="Star rating.", lo=1, hi=5),
            _f("playlist", S, ["Morning", "Focus", "Late"], desc="Playlist name."),
        ),
        ops=(
            _op(
                "play",
                "lookup",
                req=("track",),
                opt=("artist",),
                desc="Start playing a track.",
                templates=("Play {track}.",),
                returns="the now-playing record",
            ),
            _op(
                "add_to_playlist",
                "create",
                req=("track", "playlist"),
                opt=("rating",),
                desc="Add a track to a playlist.",
                templates=("Add {track} to my {playlist} playlist.",),
                returns="the playlist entry id",
            ),
            _op(
                "browse",
                "search",
                req=("genre",),
                opt=("artist", "rating"),
                desc="Browse tracks by genre.",
                templates=("Show me some {genre}.",),
                returns="a list of tracks",
            ),
            _op(
                "top_rated",
                "rank",
                roles={"field": "rating", "order": "desc"},
                req=("genre",),
                opt=("limit",),
                desc="Rank tracks by rating.",
                templates=("What is the best {genre} we have?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="weather",
        entity="reading",
        entity_plural="readings",
        blurb="weather and forecasts",
        fields=(
            _f("city", S, ["Wrocław", "Windhoek", "Rotorua", "Salta"], desc="City to report on."),
            _f("unit", S, enum=["celsius", "fahrenheit", "kelvin"], desc="Temperature unit."),
            _f("days_ahead", I, [0, 1, 3, 7], desc="How far ahead to forecast.", lo=0, hi=14),
            _f("temperature", N, [-4.0, 11.5, 23.0, 35.5], desc="Temperature reading."),
            _f("conditions", S, enum=["clear", "cloudy", "rain", "snow"], desc="Sky conditions."),
            _f("include_hourly", B, desc="Whether to include an hourly breakdown."),
        ),
        ops=(
            _op(
                "current",
                "lookup",
                req=("city",),
                opt=("unit",),
                desc="Get the current weather for a city.",
                templates=("What is the weather in {city}?",),
                returns="a weather reading",
            ),
            _op(
                "forecast",
                "compute",
                roles={"op": "forecast"},
                req=("city", "days_ahead"),
                opt=("unit", "include_hourly"),
                desc="Forecast the weather a number of days ahead.",
                templates=("What will it be like in {city} in {days_ahead} days?",),
                returns="a forecast",
            ),
            _op(
                "convert_temp",
                "convert",
                roles={"from": "unit"},
                req=("temperature", "unit"),
                desc="Convert a temperature between units.",
                templates=("Convert {temperature} to another unit.",),
                returns="the converted temperature",
            ),
        ),
    ),
    DomainSpec(
        name="hr",
        entity="employee",
        entity_plural="employees",
        blurb="people operations",
        fields=(
            _f("employee_id", S, ["E-1102", "E-1207", "E-1355"], desc="Employee number."),
            _f("department", S, enum=["engineering", "sales", "support", "legal"], desc="Which department."),
            _f("leave_type", S, enum=["annual", "sick", "unpaid", "parental"], desc="Type of leave."),
            _f("days", I, [1, 3, 10, 20], desc="Number of days.", lo=0, hi=365),
            _f("start_date", S, ["2027-04-05", "2027-08-17"], desc="First day of leave."),
            _f("approved", B, desc="Whether it is approved."),
            _f("salary_band", I, [2, 4, 6, 8], desc="Pay band.", lo=1, hi=12),
        ),
        ops=(
            _op(
                "request_leave",
                "create",
                req=("employee_id", "leave_type", "days"),
                opt=("start_date", "approved"),
                desc="File a leave request.",
                templates=("Request {days} days of {leave_type} leave for {employee_id}.",),
                returns="the request id",
            ),
            _op(
                "directory",
                "search",
                req=("department",),
                opt=("salary_band",),
                desc="List people in a department.",
                templates=("Who is in {department}?",),
                returns="a list of employees",
            ),
            _op(
                "headcount",
                "count",
                req=("department",),
                desc="Count the people in a department.",
                templates=("How many people are in {department}?",),
                returns="a count",
            ),
            _op(
                "approve",
                "update",
                roles={"field": "approved"},
                req=("record_id", "approved"),
                desc="Approve or reject a pending request.",
                templates=("Approve request {record_id}.",),
                returns="the updated request",
            ),
        ),
    ),
    DomainSpec(
        name="ecommerce",
        entity="order",
        entity_plural="orders",
        blurb="online shopping",
        fields=(
            _f("order_id", S, ["ORD-7781", "ORD-8892", "ORD-9903"], desc="Order number."),
            _f("product", S, ["kettle", "desk lamp", "running shoes"], desc="Product name."),
            _f("quantity", I, [1, 2, 6], desc="How many.", lo=1, hi=999),
            _f("shipping", S, enum=["standard", "express", "overnight", "pickup"], desc="Shipping method."),
            _f("address", S, ["12 Rowan Way", "4 Kiln Street", "88 Marsh Lane"], desc="Delivery address."),
            _f("gift_wrap", B, desc="Whether to gift wrap it."),
            _f("total", N, [19.99, 84.5, 302.0], desc="Order total.", lo=0),
        ),
        ops=(
            _op(
                "place",
                "create",
                req=("product", "quantity", "address"),
                opt=("shipping", "gift_wrap"),
                desc="Place a new order.",
                templates=("Order {quantity} {product} to {address}.",),
                returns="the order id",
            ),
            _op(
                "track",
                "lookup",
                req=("order_id",),
                desc="Check where an order is.",
                templates=("Where is order {order_id}?",),
                returns="the order record",
            ),
            _op(
                "refund",
                "delete",
                req=("record_id",),
                desc="Refund and close an order.",
                templates=("Refund order {record_id}.",),
                returns="whether it was refunded",
            ),
            _op(
                "spend",
                "aggregate",
                roles={"field": "total", "agg": "sum"},
                req=("address",),
                opt=("shipping",),
                desc="Total spending for an address.",
                templates=("How much has been spent shipping to {address}?",),
                returns="a total",
            ),
        ),
    ),
    DomainSpec(
        name="devops",
        entity="deployment",
        entity_plural="deployments",
        blurb="services and deploys",
        fields=(
            _f("service", S, ["auth-api", "billing-worker", "search-index"], desc="Service name."),
            _f("environment", S, enum=["dev", "staging", "prod"], desc="Which environment."),
            _f("version", S, ["1.4.2", "2.0.0", "2.1.7"], desc="Version tag to deploy."),
            _f("replicas", I, [1, 3, 8, 20], desc="How many replicas.", lo=0, hi=500),
            _f("canary_percent", I, [5, 25, 50], desc="Share of traffic on the new version.", lo=0, hi=100),
            _f("auto_rollback", B, desc="Roll back automatically on failure."),
        ),
        ops=(
            _op(
                "deploy",
                "create",
                req=("service", "environment", "version"),
                opt=("replicas", "canary_percent", "auto_rollback"),
                desc="Deploy a version of a service.",
                templates=("Deploy {service} {version} to {environment}.",),
                returns="the deployment id",
            ),
            _op(
                "scale",
                "update",
                roles={"field": "replicas"},
                req=("record_id", "replicas"),
                desc="Change the replica count of a deployment.",
                templates=("Scale deployment {record_id} to {replicas} replicas.",),
                returns="the updated deployment",
            ),
            _op(
                "status",
                "lookup",
                req=("service",),
                opt=("environment",),
                desc="Check the state of a service.",
                templates=("Is {service} healthy?",),
                returns="a status record",
            ),
            _op(
                "rollback",
                "delete",
                req=("record_id",),
                desc="Roll a deployment back.",
                templates=("Roll back deployment {record_id}.",),
                returns="whether it rolled back",
            ),
        ),
    ),
    DomainSpec(
        name="documents",
        entity="document",
        entity_plural="documents",
        blurb="files and folders",
        fields=(
            _f("path", S, ["/reports/q1.md", "/legal/nda.pdf", "/photos/trip.zip"], desc="Path to the file."),
            _f("folder", S, enum=["reports", "legal", "photos", "archive"], desc="Which folder."),
            _f("format", S, enum=["md", "pdf", "zip", "csv"], desc="File format."),
            _f("size_kb", I, [12, 480, 9600], desc="Size in kilobytes.", lo=0),
            _f("shared_with", S, ["tomas", "ursula", "vik"], desc="Who it is shared with."),
            _f("read_only", B, desc="Whether it is read only."),
        ),
        ops=(
            _op(
                "upload",
                "create",
                req=("path", "folder"),
                opt=("format", "read_only"),
                desc="Add a document to a folder.",
                templates=("Put {path} in the {folder} folder.",),
                returns="the document id",
            ),
            _op(
                "find",
                "search",
                req=("folder",),
                opt=("format", "shared_with"),
                desc="Search a folder for documents.",
                templates=("What is in the {folder} folder?",),
                returns="a list of documents",
            ),
            _op(
                "share",
                "update",
                roles={"field": "shared_with"},
                req=("record_id", "shared_with"),
                desc="Share a document with someone.",
                templates=("Share document {record_id} with {shared_with}.",),
                returns="the updated document",
            ),
            _op(
                "total_size",
                "aggregate",
                roles={"field": "size_kb", "agg": "sum"},
                req=("folder",),
                desc="Total the size of a folder.",
                templates=("How big is the {folder} folder?",),
                returns="a total size",
            ),
        ),
    ),
    DomainSpec(
        name="education",
        entity="course",
        entity_plural="courses",
        blurb="classes and grades",
        fields=(
            _f("course_code", S, ["BIO-210", "MAT-118", "HIS-330"], desc="Course code."),
            _f("student", S, ["ada", "boris", "clea"], desc="Student username."),
            _f("term", S, enum=["fall", "spring", "summer"], desc="Which term."),
            _f("grade", I, [55, 72, 88, 95], desc="Percentage grade.", lo=0, hi=100),
            _f("credits", I, [1, 3, 4], desc="Credit hours.", lo=0, hi=12),
            _f("audit", B, desc="Whether the student is auditing."),
        ),
        ops=(
            _op(
                "enrol",
                "create",
                req=("student", "course_code", "term"),
                opt=("credits", "audit"),
                desc="Enrol a student in a course.",
                templates=("Enrol {student} in {course_code} for {term}.",),
                returns="the enrolment id",
            ),
            _op(
                "transcript",
                "search",
                req=("student",),
                opt=("term",),
                desc="List a student's courses.",
                templates=("What has {student} taken?",),
                returns="a list of enrolments",
            ),
            _op(
                "gpa",
                "aggregate",
                roles={"field": "grade", "agg": "mean"},
                req=("student",),
                opt=("term",),
                desc="Average a student's grades.",
                templates=("What is {student}'s average grade?",),
                returns="an average",
            ),
            _op(
                "set_grade",
                "update",
                roles={"field": "grade"},
                req=("record_id", "grade"),
                desc="Record a grade on an enrolment.",
                templates=("Give enrolment {record_id} a grade of {grade}.",),
                returns="the updated enrolment",
            ),
        ),
    ),
    DomainSpec(
        name="restaurant",
        entity="reservation",
        entity_plural="reservations",
        blurb="dining and reservations",
        fields=(
            _f("venue", S, ["Saltbox", "Ember & Ash", "Fig House"], desc="Restaurant name."),
            _f("party_size", I, [2, 4, 8], desc="How many people.", lo=1, hi=40),
            _f("seating", S, enum=["indoor", "patio", "bar", "private"], desc="Seating preference."),
            _f("dietary", S, enum=["none", "vegetarian", "vegan", "gluten_free"], desc="Dietary requirement."),
            _f("at_time", S, ["18:30", "19:45", "21:00"], desc="Time of the booking."),
            _f("on_date", S, ["2027-05-02", "2027-05-16"], desc="Date of the booking."),
        ),
        ops=(
            _op(
                "reserve",
                "create",
                req=("venue", "party_size", "on_date", "at_time"),
                opt=("seating", "dietary"),
                desc="Reserve a table.",
                templates=("Book a table for {party_size} at {venue} on {on_date} at {at_time}.",),
                returns="the reservation id",
            ),
            _op(
                "availability",
                "search",
                req=("venue", "on_date"),
                opt=("party_size", "seating"),
                desc="Check what is free at a venue.",
                templates=("What is free at {venue} on {on_date}?",),
                returns="a list of slots",
            ),
            _op(
                "cancel",
                "delete",
                req=("record_id",),
                desc="Cancel a reservation.",
                templates=("Cancel reservation {record_id}.",),
                returns="whether it was cancelled",
            ),
        ),
    ),
    DomainSpec(
        name="fleet",
        entity="vehicle",
        entity_plural="vehicles",
        blurb="vehicles and routes",
        fields=(
            _f("plate", S, ["KR-4821", "TL-9930", "MN-1145"], desc="Number plate."),
            _f("depot", S, enum=["central", "harbour", "airport"], desc="Home depot."),
            _f("fuel_percent", I, [12, 55, 90], desc="Fuel level.", lo=0, hi=100),
            _f("driver", S, ["sam", "tessa", "ugo"], desc="Assigned driver."),
            _f("odometer_km", I, [12000, 88000, 250000], desc="Distance travelled.", lo=0),
            _f("in_service", B, desc="Whether the vehicle is available."),
        ),
        ops=(
            _op(
                "assign",
                "update",
                roles={"field": "driver"},
                req=("record_id", "driver"),
                desc="Assign a driver to a vehicle.",
                templates=("Give vehicle {record_id} to {driver}.",),
                returns="the updated vehicle",
            ),
            _op(
                "locate",
                "lookup",
                req=("plate",),
                desc="Find out where a vehicle is.",
                templates=("Where is {plate}?",),
                returns="the vehicle record",
            ),
            _op(
                "depot_list",
                "search",
                req=("depot",),
                opt=("in_service",),
                desc="List vehicles at a depot.",
                templates=("What is parked at {depot}?",),
                returns="a list of vehicles",
            ),
            _op(
                "lowest_fuel",
                "rank",
                roles={"field": "fuel_percent", "order": "asc"},
                req=("depot",),
                opt=("limit",),
                desc="Rank vehicles by fuel, emptiest first.",
                templates=("Which vehicles at {depot} need fuel?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="security",
        entity="alert",
        entity_plural="alerts",
        blurb="access and alerts",
        fields=(
            _f("alert_id", S, ["AL-330", "AL-441", "AL-552"], desc="Alert identifier."),
            _f("source", S, enum=["firewall", "endpoint", "identity", "cloud"], desc="Where it came from."),
            _f("risk", S, enum=["low", "medium", "high", "critical"], desc="Risk level."),
            _f("user", S, ["wren", "xavi", "yuki"], desc="User involved."),
            _f("count", I, [1, 12, 240], desc="How many times it fired.", lo=1),
            _f("acknowledged", B, desc="Whether someone has acknowledged it."),
        ),
        ops=(
            _op(
                "raise",
                "create",
                req=("source", "risk", "user"),
                opt=("count", "acknowledged"),
                desc="Raise a new security alert.",
                templates=("Raise a {risk} {source} alert for {user}.",),
                returns="the alert id",
            ),
            _op(
                "acknowledge",
                "update",
                roles={"field": "acknowledged"},
                req=("record_id", "acknowledged"),
                desc="Acknowledge an alert.",
                templates=("Acknowledge alert {record_id}.",),
                returns="the updated alert",
            ),
            _op(
                "by_source",
                "search",
                req=("source",),
                opt=("risk", "acknowledged"),
                desc="List alerts from a source.",
                templates=("What has {source} reported?",),
                returns="a list of alerts",
            ),
            _op(
                "noisiest",
                "rank",
                roles={"field": "count", "order": "desc"},
                req=("source",),
                opt=("limit",),
                desc="Rank alerts by how often they fired.",
                templates=("Which {source} alerts fire most?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="agriculture",
        entity="plot",
        entity_plural="plots",
        blurb="fields and crops",
        fields=(
            _f("plot_id", S, ["PL-08", "PL-14", "PL-22"], desc="Plot identifier."),
            _f("crop", S, enum=["barley", "sorghum", "lentils", "canola"], desc="What is planted."),
            _f("hectares", N, [2.5, 18.0, 44.5], desc="Area of the plot.", lo=0),
            _f("moisture_percent", I, [8, 22, 40], desc="Soil moisture.", lo=0, hi=100),
            _f("irrigated", B, desc="Whether the plot is irrigated."),
            _f("yield_tonnes", N, [1.2, 15.8, 60.0], desc="Harvest yield.", lo=0),
        ),
        ops=(
            _op(
                "plant",
                "create",
                req=("plot_id", "crop", "hectares"),
                opt=("irrigated",),
                desc="Record a planting on a plot.",
                templates=("Plant {crop} on {hectares} hectares of {plot_id}.",),
                returns="the planting id",
            ),
            _op(
                "readings",
                "search",
                req=("crop",),
                opt=("irrigated",),
                desc="List plots growing a crop.",
                templates=("Which plots have {crop}?",),
                returns="a list of plots",
            ),
            _op(
                "total_yield",
                "aggregate",
                roles={"field": "yield_tonnes", "agg": "sum"},
                req=("crop",),
                desc="Total the harvest for a crop.",
                templates=("How much {crop} did we harvest?",),
                returns="a total",
            ),
            _op(
                "driest",
                "rank",
                roles={"field": "moisture_percent", "order": "asc"},
                req=("crop",),
                opt=("limit",),
                desc="Rank plots by soil moisture, driest first.",
                templates=("Which {crop} plots are driest?",),
                returns="a ranked list",
            ),
        ),
    ),
    DomainSpec(
        name="research",
        entity="paper",
        entity_plural="papers",
        blurb="papers and citations",
        fields=(
            _f("paper_id", S, ["arx-4410", "arx-5521", "arx-6632"], desc="Paper identifier."),
            _f("topic", S, enum=["optics", "genomics", "seismology", "logic"], desc="Research area."),
            _f("year", I, [2019, 2022, 2026], desc="Publication year.", lo=1900, hi=2100),
            _f("citations", I, [0, 14, 320], desc="Citation count.", lo=0),
            _f("author", S, ["h. brantley", "s. oduya", "l. karvonen"], desc="Author name."),
            _f("open_access", B, desc="Whether it is open access."),
        ),
        ops=(
            _op(
                "fetch",
                "lookup",
                req=("paper_id",),
                desc="Fetch the record for a paper.",
                templates=("Pull up {paper_id}.",),
                returns="the paper record",
            ),
            _op(
                "search",
                "search",
                req=("topic",),
                opt=("year", "open_access"),
                desc="Search papers by topic.",
                templates=("Find papers on {topic}.",),
                returns="a list of papers",
            ),
            _op(
                "most_cited",
                "rank",
                roles={"field": "citations", "order": "desc"},
                req=("topic",),
                opt=("limit",),
                desc="Rank papers by citations.",
                templates=("What are the most cited {topic} papers?",),
                returns="a ranked list",
            ),
            _op(
                "count_by_year",
                "count",
                req=("topic",),
                opt=("year",),
                desc="Count papers in an area.",
                templates=("How many {topic} papers are there?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="energy",
        entity="meter",
        entity_plural="meters",
        blurb="energy usage",
        fields=(
            _f("meter_id", S, ["M-1001", "M-1002", "M-1003"], desc="Meter identifier."),
            _f("site", S, enum=["plant_a", "plant_b", "office", "depot"], desc="Which site."),
            _f("kwh", N, [120.5, 4400.0, 98000.0], desc="Energy used.", lo=0, unit="kWh"),
            _f("tariff", S, enum=["peak", "offpeak", "flat"], desc="Tariff band."),
            _f("month", S, ["2027-01", "2027-02", "2027-03"], desc="Billing month."),
            _f("estimated", B, desc="Whether the reading is estimated."),
        ),
        ops=(
            _op(
                "submit_reading",
                "create",
                req=("meter_id", "kwh", "month"),
                opt=("tariff", "estimated"),
                desc="Submit a meter reading.",
                templates=("Record {kwh} kWh on {meter_id} for {month}.",),
                returns="the reading id",
            ),
            _op(
                "usage",
                "search",
                req=("site",),
                opt=("tariff", "month"),
                desc="List readings for a site.",
                templates=("Show energy use at {site}.",),
                returns="a list of readings",
            ),
            _op(
                "total_usage",
                "aggregate",
                roles={"field": "kwh", "agg": "sum"},
                req=("site",),
                opt=("month",),
                desc="Total energy used at a site.",
                templates=("How much energy did {site} use?",),
                returns="a total",
            ),
        ),
    ),
    DomainSpec(
        name="legal",
        entity="contract",
        entity_plural="contracts",
        blurb="contracts and clauses",
        fields=(
            _f("contract_id", S, ["C-2201", "C-3312", "C-4423"], desc="Contract number."),
            _f("counterparty", S, ["Holt & Vane", "Northmoor Trust", "Aster Group"], desc="Other party."),
            _f("status", S, enum=["draft", "review", "signed", "expired"], desc="Where it stands."),
            _f("value", N, [15000.0, 240000.0, 1800000.0], desc="Contract value.", lo=0),
            _f("term_months", I, [6, 12, 36], desc="Length of the term.", lo=1, hi=600),
            _f("auto_renew", B, desc="Whether it renews automatically."),
        ),
        ops=(
            _op(
                "draft",
                "create",
                req=("counterparty", "value", "term_months"),
                opt=("auto_renew",),
                desc="Draft a new contract.",
                templates=("Draft a {term_months} month contract with {counterparty} worth {value}.",),
                returns="the contract id",
            ),
            _op(
                "status_of",
                "lookup",
                req=("contract_id",),
                desc="Check a contract's status.",
                templates=("Where is contract {contract_id}?",),
                returns="the contract record",
            ),
            _op(
                "by_status",
                "search",
                req=("status",),
                opt=("auto_renew",),
                desc="List contracts by status.",
                templates=("Which contracts are in {status}?",),
                returns="a list of contracts",
            ),
            _op(
                "advance",
                "update",
                roles={"field": "status"},
                req=("record_id", "status"),
                desc="Move a contract to a new status.",
                templates=("Move contract {record_id} to {status}.",),
                returns="the updated contract",
            ),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# the held-out domains
# --------------------------------------------------------------------------- #
#
# Four held-out domains, written after the study's main runs. They live in their own pool
# so that nothing in DOMAINS changes:
# a universe built from the base pool is byte-for-byte what it was, and a cell
# that says ``domain_pool: heldout`` builds its universe from these four
# alone. The laws fitted on the 24 base domains either predict these or they
# do not; that is the generator's own held-out test.

HELDOUT_DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec(
        name="logistics",
        entity="shipment",
        entity_plural="shipments",
        blurb="freight and parcel shipments",
        fields=(
            _f(
                "tracking_code",
                S,
                ["SHP-1042", "SHP-2210", "SHP-3377", "SHP-4501"],
                desc="Tracking code printed on the label.",
            ),
            _f("origin", S, ["Lisbon", "Oslo", "Denver", "Osaka"], desc="City the shipment leaves from."),
            _f("destination", S, ["Madrid", "Bergen", "Austin", "Nagoya"], desc="City the shipment is going to."),
            _f("weight_kg", N, [2.5, 12.0, 48.5, 120.0], desc="Gross weight.", lo=0, unit="kg"),
            _f("carrier", S, enum=["road", "rail", "air", "sea"], desc="How the shipment travels."),
            _f(
                "status",
                S,
                enum=["booked", "in_transit", "delivered", "held"],
                desc="Where the shipment is in its journey.",
            ),
            _f("priority", I, [1, 2, 3], desc="Delivery priority, 1 is the most urgent.", lo=1, hi=5),
            _f("fragile", B, desc="Whether the contents need careful handling."),
        ),
        ops=(
            _op(
                "book",
                "create",
                req=("origin", "destination", "weight_kg"),
                opt=("carrier", "priority", "fragile"),
                desc="Book a new shipment.",
                templates=(
                    "Book a shipment from {origin} to {destination} weighing {weight_kg} kg.",
                    "Send {weight_kg} kg from {origin} to {destination}.",
                ),
                returns="the id of the new shipment",
            ),
            _op(
                "track",
                "lookup",
                req=("tracking_code",),
                desc="Look up one shipment by its tracking code.",
                templates=("Where is shipment {tracking_code}?", "Track {tracking_code}."),
                returns="the shipment record",
            ),
            _op(
                "in_status",
                "search",
                req=("status",),
                opt=("carrier", "destination"),
                desc="List shipments in a given status.",
                templates=("Which shipments are {status}?", "Show me every shipment that is {status}."),
                returns="a list of shipments",
            ),
            _op(
                "reroute",
                "update",
                roles={"field": "destination"},
                req=("record_id", "destination"),
                desc="Change where a shipment is going.",
                templates=("Reroute shipment {record_id} to {destination}.",),
                returns="the updated shipment",
            ),
            _op(
                "heaviest",
                "rank",
                roles={"field": "weight_kg", "order": "desc"},
                req=("carrier",),
                opt=("limit",),
                desc="Rank a carrier's shipments by weight, heaviest first.",
                templates=("What are the heaviest shipments going by {carrier}?",),
                returns="a ranked list",
            ),
            _op(
                "total_weight",
                "aggregate",
                roles={"field": "weight_kg", "agg": "sum"},
                req=("carrier",),
                opt=("status",),
                desc="Total weight carried by one carrier.",
                templates=("How much weight is going by {carrier} in total?",),
                returns="a total in kg",
            ),
        ),
    ),
    DomainSpec(
        name="realestate",
        entity="listing",
        entity_plural="listings",
        blurb="property listings",
        fields=(
            _f(
                "address",
                S,
                ["12 Elm Street", "400 Harbour Road", "7 Kings Lane", "88 Mill Court"],
                desc="Street address of the property.",
            ),
            _f("city", S, ["Leeds", "Porto", "Tampa", "Adelaide"], desc="City the property is in."),
            _f("price", I, [180000, 245000, 410000, 780000], desc="Asking price.", lo=0, unit="dollars"),
            _f("bedrooms", I, [1, 2, 3, 4, 5], desc="Number of bedrooms.", lo=0, hi=12),
            _f("listing_type", S, enum=["sale", "rent"], desc="Whether the property is for sale or for rent."),
            _f("status", S, enum=["active", "under_offer", "sold", "withdrawn"], desc="Where the listing stands."),
            _f("furnished", B, desc="Whether the property comes furnished."),
            _f("agent", S, ["hana", "ivan", "joel", "kira"], desc="Username of the agent handling it."),
        ),
        ops=(
            _op(
                "list_property",
                "create",
                req=("address", "city", "price"),
                opt=("bedrooms", "listing_type", "furnished", "agent"),
                desc="Put a property on the market.",
                templates=(
                    "List {address} in {city} at {price}.",
                    "Add a listing for {address}, {city}, asking {price}.",
                ),
                returns="the id of the new listing",
            ),
            _op(
                "search_listings",
                "search",
                req=("city",),
                opt=("bedrooms", "listing_type", "status"),
                desc="Find listings in a city with optional filters.",
                templates=("What is on the market in {city}?", "Show me listings in {city}."),
                returns="a list of listings",
            ),
            _op(
                "reprice",
                "update",
                roles={"field": "price"},
                req=("record_id", "price"),
                desc="Change the asking price of a listing.",
                templates=("Change the price of listing {record_id} to {price}.",),
                returns="the updated listing",
            ),
            _op(
                "withdraw",
                "delete",
                req=("record_id",),
                desc="Take a listing off the market.",
                templates=("Withdraw listing {record_id}.", "Take listing {record_id} off the market."),
                returns="whether the listing was removed",
            ),
            _op(
                "cheapest",
                "rank",
                roles={"field": "price", "order": "asc"},
                req=("city",),
                opt=("limit",),
                desc="Rank a city's listings by price, cheapest first.",
                templates=("What are the cheapest listings in {city}?",),
                returns="a ranked list",
            ),
            _op(
                "count_listings",
                "count",
                req=("city",),
                opt=("status",),
                desc="Count the listings in a city.",
                templates=("How many listings are there in {city}?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="sports",
        entity="fixture",
        entity_plural="fixtures",
        blurb="matches and fixtures",
        fields=(
            _f("home_team", S, ["Falcons", "Tigers", "Rovers", "Comets"], desc="Team playing at home."),
            _f("away_team", S, ["Wolves", "Sharks", "Kings", "Pirates"], desc="Visiting team."),
            _f("league", S, enum=["premier", "cup", "youth"], desc="Competition the match belongs to."),
            _f(
                "match_day",
                S,
                ["2027-08-14", "2027-08-21", "2027-09-04", "2027-09-18"],
                desc="Date of the match in YYYY-MM-DD form.",
            ),
            _f("venue", S, ["North Park", "City Arena", "Riverside"], desc="Ground the match is played at."),
            _f("home_score", I, [0, 1, 2, 3], desc="Goals scored by the home team.", lo=0),
            _f("away_score", I, [0, 1, 2, 4], desc="Goals scored by the away team.", lo=0),
            _f("televised", B, desc="Whether the match is broadcast."),
        ),
        ops=(
            _op(
                "schedule_match",
                "create",
                req=("home_team", "away_team", "match_day"),
                opt=("league", "venue", "televised"),
                desc="Add a fixture to the calendar.",
                templates=(
                    "Schedule {home_team} against {away_team} on {match_day}.",
                    "Add a match between {home_team} and {away_team} for {match_day}.",
                ),
                returns="the id of the new fixture",
            ),
            _op(
                "fixtures_on",
                "search",
                req=("match_day",),
                opt=("league", "venue"),
                desc="List the fixtures on a day.",
                templates=("What matches are on {match_day}?", "Show me the fixtures for {match_day}."),
                returns="a list of fixtures",
            ),
            _op(
                "record_home_score",
                "update",
                roles={"field": "home_score"},
                req=("record_id", "home_score"),
                desc="Record the home team's score for a fixture.",
                templates=("Set the home score of fixture {record_id} to {home_score}.",),
                returns="the updated fixture",
            ),
            _op(
                "call_off",
                "delete",
                req=("record_id",),
                desc="Remove a fixture from the calendar.",
                templates=("Call off fixture {record_id}.", "Cancel match {record_id}."),
                returns="whether the fixture was removed",
            ),
            _op(
                "highest_scoring",
                "rank",
                roles={"field": "home_score", "order": "desc"},
                req=("league",),
                opt=("limit",),
                desc="Rank a league's fixtures by home goals, most first.",
                templates=("Which {league} matches had the most home goals?",),
                returns="a ranked list",
            ),
            _op(
                "count_fixtures",
                "count",
                req=("league",),
                opt=("venue",),
                desc="Count the fixtures in a league.",
                templates=("How many {league} fixtures are there?",),
                returns="a count",
            ),
        ),
    ),
    DomainSpec(
        name="veterinary",
        entity="patient",
        entity_plural="patients",
        blurb="a veterinary clinic's patients",
        fields=(
            _f("pet_name", S, ["Biscuit", "Luna", "Max", "Pepper"], desc="The animal's name."),
            _f("species", S, enum=["dog", "cat", "rabbit", "bird"], desc="Kind of animal."),
            _f("owner", S, ["yara", "zed", "alma", "bram"], desc="Username of the owner."),
            _f("weight_kg", N, [0.4, 3.2, 8.5, 24.0], desc="Weight at the last visit.", lo=0, unit="kg"),
            _f("age_years", I, [1, 3, 7, 12], desc="Age in whole years.", lo=0, hi=40),
            _f("clinic", S, ["Westside", "Harbour", "Hilltop"], desc="Clinic the patient is registered at."),
            _f(
                "visit_reason",
                S,
                enum=["vaccination", "check_up", "dental", "injury"],
                desc="Why the patient last came in.",
            ),
            _f("vaccinated", B, desc="Whether the vaccinations are up to date."),
        ),
        ops=(
            _op(
                "register",
                "create",
                req=("pet_name", "species", "owner"),
                opt=("weight_kg", "age_years", "clinic", "vaccinated"),
                desc="Register a new patient.",
                templates=(
                    "Register a {species} called {pet_name} for {owner}.",
                    "Add {owner}'s {species} {pet_name} as a patient.",
                ),
                returns="the id of the new patient",
            ),
            _op(
                "patients_of",
                "search",
                req=("owner",),
                opt=("species", "clinic"),
                desc="List the patients an owner has registered.",
                templates=("Which animals does {owner} have with us?", "Show me {owner}'s patients."),
                returns="a list of patients",
            ),
            _op(
                "weigh",
                "update",
                roles={"field": "weight_kg"},
                req=("record_id", "weight_kg"),
                desc="Record a new weight for a patient.",
                templates=("Record that patient {record_id} now weighs {weight_kg} kg.",),
                returns="the updated patient",
            ),
            _op(
                "discharge",
                "delete",
                req=("record_id",),
                desc="Remove a patient from the register.",
                templates=("Discharge patient {record_id}.", "Remove patient {record_id} from the register."),
                returns="whether the patient was removed",
            ),
            _op(
                "oldest",
                "rank",
                roles={"field": "age_years", "order": "desc"},
                req=("clinic",),
                opt=("limit",),
                desc="Rank a clinic's patients by age, oldest first.",
                templates=("Who are the oldest patients at {clinic}?",),
                returns="a ranked list",
            ),
            _op(
                "average_weight",
                "aggregate",
                roles={"field": "weight_kg", "agg": "mean"},
                req=("clinic",),
                opt=("species",),
                desc="Average weight of the patients at a clinic.",
                templates=("What is the average patient weight at {clinic}?",),
                returns="a mean weight in kg",
            ),
        ),
    ),
)

DOMAIN_POOLS: dict[str, tuple[DomainSpec, ...]] = {
    "base": DOMAINS,
    "heldout": HELDOUT_DOMAINS,
    "all": DOMAINS + HELDOUT_DOMAINS,
}

# The pool the universe builder reads. A plain module global rather than a
# context variable: generation is synchronous and single-threaded, and the
# runner sets the pool for exactly the time it builds a cell's instances.
_ACTIVE_POOL = "base"


def active_domains() -> tuple[DomainSpec, ...]:
    """The domains a universe is built from right now (see ``use_domain_pool``)."""
    return DOMAIN_POOLS[_ACTIVE_POOL]


@contextmanager
def use_domain_pool(name: str = "base"):
    """Build universes from one pool for the length of the block.

    ``base`` is the study's 24 domains and the default everywhere, so an
    existing cell is unchanged; ``heldout`` is the four held-out domains; ``all``
    is both.
    """
    global _ACTIVE_POOL
    if name not in DOMAIN_POOLS:
        raise KeyError(f"unknown domain pool {name!r}. Known: {', '.join(DOMAIN_POOLS)}")
    before = _ACTIVE_POOL
    _ACTIVE_POOL = name
    try:
        yield DOMAIN_POOLS[name]
    finally:
        _ACTIVE_POOL = before


DOMAIN_BY_NAME = {d.name: d for d in DOMAINS + HELDOUT_DOMAINS}


def get_domain(name: str) -> DomainSpec:
    if name not in DOMAIN_BY_NAME:
        raise KeyError(f"unknown domain {name!r}. Known: {', '.join(DOMAIN_BY_NAME)}")
    return DOMAIN_BY_NAME[name]


def domain_names() -> list[str]:
    return [d.name for d in active_domains()]


def total_base_tools() -> int:
    """How many distinct (domain, op) pairs the library can produce."""
    return sum(len(d.ops) for d in active_domains())
