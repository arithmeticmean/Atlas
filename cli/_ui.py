"""Terminal presentation for the interactive commands.

Ported from the standalone ``configure.py`` that used to sit beside the
repository. It kept itself to the standard library because it had to run before
anything was installed; now that it ships inside the package that constraint is
gone, but hand-rolled ANSI is still the right call -- it is a handful of
functions and avoids a rendering dependency for one command.

Colour switches itself off when stdout is not a terminal, and honours
``NO_COLOR``.
"""

import os
import re
import sys
from collections.abc import Sequence

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_ANSI = re.compile(r"\033\[[0-9;]*m")


def c(text: str, *codes: int) -> str:
    if not USE_COLOR or not codes:
        return text
    return "".join(f"\033[{k}m" for k in codes) + text + "\033[0m"


def bold(t: str) -> str:
    return c(t, 1)


def cyan(t: str) -> str:
    return c(t, 36, 1)


def green(t: str) -> str:
    return c(t, 32, 1)


def yellow(t: str) -> str:
    return c(t, 33)


def red(t: str) -> str:
    return c(t, 31, 1)


def gray(t: str) -> str:
    return c(t, 90)


def mag(t: str) -> str:
    return c(t, 35, 1)


def vlen(s: str) -> int:
    """Printable width, ignoring escape sequences."""
    return len(_ANSI.sub("", s))


def banner() -> None:
    art = [
        " █████╗ ████████╗██╗      █████╗ ███████╗",
        "██╔══██╗╚══██╔══╝██║     ██╔══██╗██╔════╝",
        "███████║   ██║   ██║     ███████║███████╗",
        "██╔══██║   ██║   ██║     ██╔══██║╚════██║",
        "██║  ██║   ██║   ███████╗██║  ██║███████║",
        "╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝",
    ]
    print()
    for line in art:
        print("  " + c(line, 36, 1))
    print("  " + gray("self-hosted RAG · setup"))
    print()


def rule(title: str) -> None:
    print(
        "\n"
        + c("── ", 36)
        + bold(title)
        + " "
        + c("─" * max(0, 42 - vlen(title)), 36)
        + "\n"
    )


def panel(title: str, rows: Sequence[str], color: int = 36) -> None:
    width = max([vlen(r) for r in rows] + [vlen(title) + 2])
    print(
        c("┌─ ", color)
        + bold(title)
        + " "
        + c("─" * (width - vlen(title) - 1) + "┐", color)
    )
    for r in rows:
        print(c("│ ", color) + r + " " * (width - vlen(r)) + c(" │", color))
    print(c("└" + "─" * (width + 2) + "┘", color))


def ask(label: str, default: str = "") -> str:
    hint = c(f" ({default})", 90) if default else ""
    try:
        raw = input(f"  {cyan('?')} {label}{hint}: ").strip()
    except EOFError:
        raw = ""
    return raw or default


def ask_secret(label: str) -> str:
    try:
        import getpass

        return getpass.getpass(f"  {cyan('?')} {label} (hidden): ").strip()
    except Exception:
        return ""


def confirm(label: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = ask(f"{label} [{suffix}]").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def menu(
    label: str, options: Sequence[tuple[str, str]], default: str
) -> str:
    """Numbered single-choice menu. Accepts the name or its number."""
    print(f"  {cyan('?')} {bold(label)}")
    for i, (name, desc) in enumerate(options, 1):
        star = green(" ●") if name == default else gray(" ○")
        tail = f"  {gray(desc)}" if desc else ""
        print(f"    {star} {c(str(i), 33, 1)}) {bold(name)}{tail}")
    names = [o[0] for o in options]
    while True:
        raw = ask("choose", default)
        if raw in names:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return names[int(raw) - 1]
        print("    " + red("invalid choice, try again"))
