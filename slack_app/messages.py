"""All user-facing copy lives here, so wording changes never touch logic."""

HELP_TEXT = (
    "*Down Memory Lane* — I generate imagined childhood photos of you.\n\n"
    "Mention me with an age and a scene, for example:\n"
    "• `@memorylane my 2-year-old self in my house's backyard`\n"
    "• `@memorylane my 5-year-old self on a beach`\n"
    "• `@memorylane my 10-year-old self in a classroom`\n\n"
    "I reply in the same thread. Generation usually takes 30-60 seconds."
)


def acknowledgement_text(age_in_years: int, scene: str, age_was_specified: bool) -> str:
    age_note = "" if age_was_specified else " _(no age given — assuming young child)_"
    return (
        f":camera_with_flash: Working on it — *you at {age_in_years}*, "
        f"{scene}.{age_note}\nThis usually takes 30-60 seconds."
    )


def success_caption(age_in_years: int, scene: str, seconds_elapsed: float) -> str:
    return (
        f":sparkles: *You at {age_in_years}* — {scene}\n"
        f"_Generated in {seconds_elapsed:.0f}s_"
    )


def unparseable_text(reason: str) -> str:
    return (
        f":thinking_face: {reason}\n\n"
        "Try something like `my 5-year-old self on a beach`."
    )


def thread_already_busy_text(job_id: str) -> str:
    """Shown when a thread already has a request in flight.

    We reject rather than queue: see README, 'Judgment calls'.
    """
    return (
        ":hourglass_flowing_sand: I'm still working on your last request in "
        "this thread. I'll post it here as soon as it's done — then send the "
        "next one.\n"
        f"_If you'd rather not wait, start a new thread and I'll run them in "
        f"parallel. (Job `{job_id}`)_"
    )


def replicate_rate_limited_text() -> str:
    return (
        ":traffic_light: The image service is busy right now and asked me to "
        "slow down. Nothing was generated — please try again in a minute."
    )


def rate_limited_text(active_job_count: int) -> str:
    return (
        f":hourglass: You already have {active_job_count} image(s) generating. "
        "I'll get to this one once those finish — or wait a moment and ask again."
    )


def generation_failed_text(job_id: str, detail: str) -> str:
    return (
        f":warning: I couldn't generate that image.\n"
        f"```{detail}```\n"
        f"_Job `{job_id}` — try rephrasing, or ask again in a moment._"
    )


def generation_timed_out_text(job_id: str, timeout_seconds: int) -> str:
    return (
        f":alarm_clock: That image took longer than {timeout_seconds}s and I "
        f"stopped waiting. The model may be cold-starting — please try again.\n"
        f"_Job `{job_id}`_"
    )
