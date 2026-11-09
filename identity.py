"""Who a person is, as far as Bob is concerned.

A person is identified by a NAME, compared without regard to upper or lower case:

  * the account Bob runs as is the OWNER, the head admin;
  * any other real login on the Pi is a Pi person (they can use the shared console, so they already have an identity);
  * a name that matches no login is an APP-ONLY person. That is allowed, because not everyone has a Pi login, but a login is
    better: it is checked by the operating system instead of being just a word someone typed.

Nobody can claim a real login by typing it. A name that belongs to a real account can only be paired with an invite from
that same person or from the owner (`/pair NAME`). App-only names can only be invited by the owner.
Claude has no part in any of this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NAME_OK = re.compile(r"^[\w][\w .'\-]{0,31}$", re.UNICODE)


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    key: str        # the comparison form: lower case, one space between words
    display: str    # how to show them: the real account name for logins, as typed for app-only people
    kind: str       # "owner", "pi" or "app"

    @property
    def label(self) -> str:
        return {"owner": f"{self.display} (owner)", "pi": f"{self.display} (Pi login)"}.get(self.kind, f"{self.display} (app only)")

    def as_dict(self) -> dict:
        return {"key": self.key, "display": self.display, "kind": self.kind}

    @staticmethod
    def from_dict(d) -> "Principal | None":
        try:
            if d["kind"] in ("owner", "pi", "app") and d["key"] and d["display"]:
                return Principal(str(d["key"]), str(d["display"]), str(d["kind"]))
        except (KeyError, TypeError):
            pass
        return None


def system_accounts() -> list[str]:
    """The people-type logins on this machine: ordinary users, not services (uid 1000 and up, with a real shell)."""
    try:
        import pwd
        return [p.pw_name for p in pwd.getpwall()
                if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false"))]
    except Exception:
        return []


def tidy(text) -> str:
    return " ".join(str(text or "").split())


class Identity:
    def __init__(self, owner: str, accounts=system_accounts):
        self.owner = tidy(owner)
        self._accounts = accounts

    def logins(self) -> list[str]:
        names = {self.owner.casefold(): self.owner}
        for a in self._accounts():
            names.setdefault(a.casefold(), a)
        return sorted(names.values(), key=str.casefold)

    def resolve(self, text) -> Principal:
        """The person this name is. Raises IdentityError for a name that can't be used."""
        name = tidy(text)
        if not name:
            raise IdentityError("I need a name")
        if not NAME_OK.match(name):
            raise IdentityError("names can use letters, numbers, spaces and . _ - ' and be up to 32 long")
        key = name.casefold()
        if key == self.owner.casefold():
            return Principal(key, self.owner, "owner")
        for login in self._accounts():
            if login.casefold() == key:
                return Principal(key, login, "pi")
        return Principal(key, name, "app")

    def invite_problem(self, issuer: Principal, target: Principal) -> str | None:
        """Why `issuer` may not invite `target`, or None when they may."""
        if issuer.kind == "owner":
            return None
        if issuer.key == target.key:
            return None
        who = self.owner
        if target.kind == "app":
            return f"only {who} (the owner) can invite someone who has no login on this Pi"
        return f"only {who} (the owner) or {target.display} can invite {target.display}"

    def advice(self, target: Principal) -> str:
        if target.kind == "app":
            return (f"{target.display} has no login on this Pi, so they will be an app-only person. That works, but a Pi login is "
                    "better: it is checked by the system, and lets them use the shared console too (manual 20).")
        return ""
