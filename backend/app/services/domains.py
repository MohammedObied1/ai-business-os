"""Custom domain verification (white-label). A company must prove it controls a domain — by publishing a TXT
record we give them — before we ever treat requests for that host as belonging to them; otherwise any company
could type in a domain it doesn't own and pick up another company's traffic if that domain is ever misconfigured.

TXT lookups go over DNS-over-HTTPS (a plain HTTPS GET to a public resolver) instead of a DNS library, since
`httpx` is already a dependency and this needs nothing else installed.
"""
import re
import secrets

import httpx

DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


def clean_domain(domain: str) -> str:
    d = domain.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].split(":")[0]
    if not DOMAIN_RE.match(d) or d.endswith((".local", ".internal")):
        raise ValueError("That doesn't look like a valid domain, e.g. erp.yourcompany.com")
    return d


def new_token() -> str:
    return "bizos-verify-" + secrets.token_hex(16)


def verify_txt(domain: str, token: str) -> bool:
    """True if `_bizos-verify.<domain>` has a TXT record containing `token`. Tries two public DoH resolvers so one
    being unreachable doesn't block verification."""
    name = f"_bizos-verify.{domain}"
    for url in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        try:
            r = httpx.get(url, params={"name": name, "type": "TXT"}, headers={"accept": "application/dns-json"}, timeout=6)
            if r.status_code != 200:
                continue
            answers = r.json().get("Answer", [])
            if any(token in a.get("data", "") for a in answers):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False
