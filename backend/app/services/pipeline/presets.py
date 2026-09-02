"""
Authoring presets.

A preset is a **template applied at write time**, never a stored authority.
`agent_settings.resolve_settings` is the sole arbiter of what a run does; a
preset expanded at read time would add a second resolution layer above it and
reintroduce exactly the drift that module exists to prevent -- the worker, the
API and the UI preview would each be one refactor away from disagreeing about
what a run will do.

So picking a preset in the UI mutates form state and nothing else. Every dial
stays visible and editable below it, `preset_label` is stored for display only,
and the UI renders "Assisted (modified)" by comparing the saved dials against
the preset it names.

One dict, so the API and the UI cannot disagree about what a preset contains.
"""

# Both presets set `auto_merge_on_approval` to False, deliberately.
#
# A preset must never be the thing that enables the only path writing to a
# default branch with no human in the loop. Somebody picking "Autonomous"
# because they want the agent to write code has not thereby said "and land it
# unread"; that stays a separate, deliberate tick.
PRESETS: dict[str, dict] = {
    "assisted": {
        "label": "Assisted",
        "description": (
            "You write the code. Locus analyses every push, runs the review "
            "round trip and the QA thread, and keeps the board and the report "
            "in step. Every model that reads your code runs locally."
        ),
        "values": {
            "authoring_mode": "assisted",
            "autonomous_max_rounds": 2,
            "auto_merge_on_approval": False,
            "project_board_sync": True,
        },
    },
    "autonomous": {
        "label": "Autonomous",
        "description": (
            "Locus writes the first draft. A ticket you hand over is sent to "
            "the configured authoring model, which is remote -- the brief "
            "leaves the machine. Three swings, then it comes back to you."
        ),
        "values": {
            "authoring_mode": "autonomous",
            "autonomous_max_rounds": 2,
            "auto_merge_on_approval": False,
            "project_board_sync": True,
        },
    },
}


def get(name: str) -> dict | None:
    """One preset by name, or None. Unknown names are not an error here."""
    return PRESETS.get((name or "").strip().lower())


def matches(name: str, values: dict) -> bool:
    """
    Whether saved settings still match the preset they name.

    Only the keys the preset states are compared: a preset says nothing about
    a Slack channel, so a repo that set one has not thereby modified the
    preset. This is what lets the UI say "Assisted" rather than
    "Assisted (modified)" for every repo that filled in anything at all.
    """
    preset = get(name)
    if preset is None:
        return False
    return all(values.get(key) == want for key, want in preset["values"].items())
