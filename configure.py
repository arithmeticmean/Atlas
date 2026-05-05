#!/usr/bin/env python3
"""Atlas — configuration generator.

A colourful setup UI that writes the project's ``.env``. It only needs a
Python 3 interpreter on the host — it does not touch Docker. You start the
stack yourself afterwards:

    python3 configure.py       # pick providers/models -> writes .env
    docker compose up -d       # reads .env and runs everything

Standard library only.
"""

import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

# Only models I'm confident are current/correct are listed; every menu also has
# an "enter name" entry for anything else. Embedding options are deliberately
# few (hosted embedding APIs are scarce; Anthropic offers none).
EMBEDDING_PROVIDERS = {
    "ollama": {
        "backend": "ollama", "desc": "local, no API key",
        "models": ["nomic-embed-text", "mxbai-embed-large", "bge-m3"],
    },
    "openai": {
        "backend": "openai", "desc": "hosted, bring your own key",
        "key": "OPENAI_API_KEY",
        "models": ["text-embedding-3-small", "text-embedding-3-large"],
    },
}

# Well-known LLM providers with their own factory branch.
LLM_NATIVE = {
    "ollama": {
        "backend": "ollama", "desc": "local, no API key",
        "models": ["llama3.1", "llama3.2", "qwen2.5", "mistral"],
    },
    "openai": {
        "backend": "openai", "desc": "GPT", "key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
    "anthropic": {
        "backend": "anthropic", "desc": "Claude", "key": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-5", "claude-opus-5",
                   "claude-haiku-4-5-20251001"],
    },
}

# Everything else that speaks the OpenAI API: pick the endpoint, then type the
# model name (their catalogs change too fast to hardcode). name -> base_url;
# "" means enter your own URL.
COMPATIBLE_ENDPOINTS = [
    ("Moonshot / Kimi", "https://api.moonshot.ai/v1"),
    ("Groq", "https://api.groq.com/openai/v1"),
    ("DeepSeek", "https://api.deepseek.com/v1"),
    ("Together", "https://api.together.xyz/v1"),
    ("other (enter URL)", ""),
]

# --- colour + drawing -------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_ANSI = re.compile(r"\033\[[0-9;]*m")


def c(text, *codes):
    if not USE_COLOR or not codes:
        return text
    return "".join(f"\033[{k}m" for k in codes) + text + "\033[0m"


def bold(t): return c(t, 1)
def cyan(t): return c(t, 36, 1)
def green(t): return c(t, 32, 1)
def yellow(t): return c(t, 33)
def red(t): return c(t, 31, 1)
def gray(t): return c(t, 90)
def mag(t): return c(t, 35, 1)


def vlen(s):
    return len(_ANSI.sub("", s))


def banner():
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
    print("  " + gray("self-hosted RAG · configuration"))
    print()


def rule(title):
    print("\n" + c("── ", 36) + bold(title) + " "
          + c("─" * max(0, 42 - vlen(title)), 36) + "\n")


def panel(title, rows, color=36):
    width = max([vlen(r) for r in rows] + [vlen(title) + 2])
    print(c("┌─ ", color) + bold(title) + " "
          + c("─" * (width - vlen(title) - 1) + "┐", color))
    for r in rows:
        print(c("│ ", color) + r + " " * (width - vlen(r)) + c(" │", color))
    print(c("└" + "─" * (width + 2) + "┘", color))


# --- prompts ----------------------------------------------------------------

def ask(label, default=""):
    hint = c(f" ({default})", 90) if default else ""
    try:
        raw = input(f"  {cyan('?')} {label}{hint}: ").strip()
    except EOFError:
        raw = ""
    return raw or default


def ask_secret(label):
    try:
        import getpass
        return getpass.getpass(f"  {cyan('?')} {label} (hidden): ").strip()
    except Exception:
        return ""


def menu(label, options, default):
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


def pick_model(label, models):
    options = [(m, "") for m in models] + [("custom…", "type any model name")]
    choice = menu(label, options, models[0])
    if choice == "custom…":
        return ask(f"{label} — enter model name", models[0])
    return choice


# --- config -----------------------------------------------------------------

def gather():
    env = {}

    rule("Embedding model")
    ekey = menu(
        "Embedding provider",
        [(k, v["desc"]) for k, v in EMBEDDING_PROVIDERS.items()],
        "ollama",
    )
    espec = EMBEDDING_PROVIDERS[ekey]
    env["EMBEDDING_PROVIDER"] = espec["backend"]
    env["EMBEDDING_MODEL"] = pick_model("Embedding model", espec["models"])
    if espec.get("key"):
        env[espec["key"]] = ask_secret("OpenAI API key")

    rule("Answering model (LLM)")
    providers = [(k, v["desc"]) for k, v in LLM_NATIVE.items()]
    providers.append(
        ("openai-compatible", "Kimi, Groq, DeepSeek, … (enter model name)")
    )
    lkey = menu("LLM provider", providers, "ollama")

    if lkey == "openai-compatible":
        env["LLM_PROVIDER"] = "openai"
        endpoint = menu(
            "Endpoint",
            [(name, url or "enter your own") for name, url in
             COMPATIBLE_ENDPOINTS],
            COMPATIBLE_ENDPOINTS[0][0],
        )
        url = dict(COMPATIBLE_ENDPOINTS)[endpoint]
        env["LLM_BASE_URL"] = url or ask("Base URL", "https://…/v1")
        env["LLM_MODEL"] = ask("Model name (as the provider names it)")
        env["LLM_API_KEY"] = ask_secret(f"{endpoint} API key")
    else:
        spec = LLM_NATIVE[lkey]
        env["LLM_PROVIDER"] = spec["backend"]
        env["LLM_MODEL"] = pick_model("LLM model", spec["models"])
        key_var = spec.get("key")
        if key_var and not env.get(key_var):  # reuse OpenAI key across roles
            env[key_var] = ask_secret(f"{lkey} API key")

    rule("Owner account")
    print("  " + gray("the single admin who can create projects & invite users"))
    env["OWNER_EMAIL"] = ask("Owner email", "owner@atlas.local")
    env["OWNER_PASSWORD"] = ask_secret("Owner password")

    # Ollama runs as its own container (a compose profile), reached by service
    # name — only started when the config actually uses it. Record its models.
    pull = []
    if espec["backend"] == "ollama":
        pull.append(env["EMBEDDING_MODEL"])
    if env["LLM_PROVIDER"] == "ollama":
        pull.append(env["LLM_MODEL"])
    if pull:
        env["OLLAMA_BASE_URL"] = "http://ollama:11434"
        env["OLLAMA_PULL_MODELS"] = " ".join(dict.fromkeys(pull))
        env["COMPOSE_PROFILES"] = "ollama"

    env["JWT_SECRET"] = secrets.token_urlsafe(48)
    return env


def summarize(env):
    hidden = {"JWT_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "LLM_API_KEY", "OWNER_PASSWORD"}
    rows = [
        f"{gray(k):<32} {(mag('••••••••') if k in hidden and v else green(str(v)))}"
        for k, v in env.items()
    ]
    panel("Configuration", rows)


def write_env(env):
    ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in env.items()))


def main():
    banner()
    env = gather()
    print()
    summarize(env)
    write_env(env)
    print("  " + green("✓") + f" wrote {bold(str(ENV_FILE))}")
    print("\n  start it with:  " + bold("docker compose up -d")
          + gray("   → http://localhost:8000"))


if __name__ == "__main__":
    main()
