"""
Reminder texts. One entry per variant; the same title and body go to push, Telegram and email.

Adding a variant means appending an entry. IDs are never reused or renumbered, because
notification_template_stats counts sends and conversions per ID: retire a variant by setting
active to False instead of deleting it, so its numbers keep meaning what they meant.

kind:  "daily" (the reminder at the user's chosen hour), "save" (the evening warning when a
       streak or a quiz Chompy would eat is at stake), "welcome_back" (after days away).
case:  which situation the text is written for, see CASES.
style: rough tone, used to compare conversion between groups of texts while there is not
       yet enough data to compare single variants.

Placeholders, filled by render():
  {quizzes}      "1 quiz" / "3 quizzes"
  {title}        the quoted title of the quiz at stake, "and N more" appended when several are
  {streak}       current streak length in days
  {next_streak}  streak + 1
  {eaten}        "1 quiz" / "4 quizzes" that Chompy ate while the user was away
"""
from dataclasses import dataclass

CASES = {
    "daily": ("default",),
    "save": ("both", "chompy", "streak"),
    "welcome_back": ("eaten", "plain"),
}

# Push notifications truncate beyond roughly these lengths on common platforms.
MAX_TITLE_CHARS = 40
MAX_BODY_CHARS = 110
MAX_QUOTED_TITLE_CHARS = 28


@dataclass(frozen=True)
class Template:
    id: str
    kind: str
    case: str
    style: str
    title: str
    body: str
    active: bool = True


TEMPLATES = [
    # Daily reminder: what is due today, nothing else.
    Template("daily_01", "daily", "default", "neutral",
             "Today's review is ready", "{quizzes} due today. A few minutes now keeps them fresh."),
    Template("daily_02", "daily", "default", "progress",
             "Keep it fresh", "{quizzes} ready for review today. Each one makes the memory last longer."),
    Template("daily_03", "daily", "default", "playful",
             "Your brain wants a snack", "{quizzes} waiting for you today. Quick recall, big payoff."),
    Template("daily_04", "daily", "default", "neutral",
             "Time for today's review", "You have {quizzes} due today."),
    Template("daily_05", "daily", "default", "progress",
             "Small step, lasting memory", "{quizzes} due today. Reviewing on the right day is what makes it stick."),
    Template("daily_06", "daily", "default", "playful",
             "Pop quiz time", "{quizzes} ready. Let's see what you remember."),
    Template("daily_07", "daily", "default", "neutral",
             "Reviews due today", "{quizzes} on your list today. Open Studiamo when you have a few minutes."),
    Template("daily_08", "daily", "default", "progress",
             "Remember more with less", "{quizzes} due today. A quick review now saves relearning later."),

    # Evening warning, both a quiz Chompy would eat and the streak are at stake.
    Template("save_both_01", "save", "both", "chompy",
             "Chompy is getting hungry", "One quick quiz saves {title} from Chompy and keeps your {streak}-day streak."),
    Template("save_both_02", "save", "both", "chompy",
             "Last call tonight", "Chompy eats {title} at midnight. One quiz saves it and your {streak}-day streak."),
    Template("save_both_03", "save", "both", "playful",
             "Chompy is sniffing around", "{title} looks tasty to him. A quick quiz keeps it and your {streak}-day streak."),
    Template("save_both_04", "save", "both", "neutral",
             "Save it before midnight", "Finish {title} tonight to keep it and your {streak}-day streak."),

    # Evening warning, only a quiz Chompy would eat is at stake (the streak is already safe).
    Template("save_chompy_01", "save", "chompy", "chompy",
             "Chompy has his eye on something", "Your streak is safe, but Chompy wants {title}. Finish it by midnight."),
    Template("save_chompy_02", "save", "chompy", "chompy",
             "Chompy eats at midnight", "{title} is on his menu tonight. One quiz takes it off."),
    Template("save_chompy_03", "save", "chompy", "playful",
             "Don't feed Chompy", "Finish {title} tonight and it stays on your schedule."),
    Template("save_chompy_04", "save", "chompy", "neutral",
             "Chompy is getting closer", "{title} gets eaten at midnight unless you review it."),

    # Evening warning, only the streak is at stake.
    Template("save_streak_01", "save", "streak", "neutral",
             "Keep your streak going", "Your {streak}-day streak ends at midnight. One answer keeps it alive."),
    Template("save_streak_02", "save", "streak", "progress",
             "{streak} days and counting", "Answer one question before midnight to make it {next_streak}."),
    Template("save_streak_03", "save", "streak", "playful",
             "Quick one before bed?", "One answer is all your {streak}-day streak needs today."),
    Template("save_streak_04", "save", "streak", "neutral",
             "Your streak is waiting", "A single question keeps your {streak}-day streak alive tonight."),

    # Welcome back after days away, Chompy ate something in the meantime.
    Template("welcome_eaten_01", "welcome_back", "eaten", "chompy",
             "Chompy had a feast", "He snacked on {eaten} while you were away. Win them back with a quick quiz."),
    Template("welcome_eaten_02", "welcome_back", "eaten", "neutral",
             "Welcome back", "Chompy ate {eaten}, but nothing is lost. A quick quiz wins each one back."),
    Template("welcome_eaten_03", "welcome_back", "eaten", "playful",
             "Ready for a comeback?", "Chompy paused {eaten} while you were gone. Take them back one quiz at a time."),

    # Welcome back after days away, nothing was eaten.
    Template("welcome_plain_01", "welcome_back", "plain", "neutral",
             "Welcome back", "Your learning goals are right where you left them. Start with one quick quiz."),
    Template("welcome_plain_02", "welcome_back", "plain", "progress",
             "Pick up where you left off", "One short review is all it takes to get back into it."),
    Template("welcome_plain_03", "welcome_back", "plain", "playful",
             "Ready when you are", "Your quizzes are waiting. A few minutes today gets you back on track."),
]


def active_templates(kind: str, case: str) -> list[Template]:
    return [t for t in TEMPLATES if t.active and t.kind == kind and t.case == case]


def _quizzes(n: int) -> str:
    return "1 quiz" if n == 1 else f"{n} quizzes"


def _quoted_title(titles: list[str]) -> str:
    if not titles:
        return "a quiz"
    first = (titles[0] or "a quiz").strip()
    if len(first) > MAX_QUOTED_TITLE_CHARS:
        first = first[:MAX_QUOTED_TITLE_CHARS - 1].rstrip() + "…"
    quoted = f"'{first}'"
    extra = len(titles) - 1
    return f"{quoted} and {extra} more" if extra > 0 else quoted


def render(template: Template, *, count: int = 0, titles=None, streak: int = 0, eaten: int = 0) -> tuple[str, str]:
    """Returns (title, body) with the placeholders filled in."""
    values = {
        "quizzes": _quizzes(count),
        "title": _quoted_title(list(titles or [])),
        "streak": streak,
        "next_streak": streak + 1,
        "eaten": _quizzes(eaten),
    }
    return template.title.format(**values), template.body.format(**values)
