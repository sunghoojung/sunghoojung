#!/usr/bin/env python3
"""Generate the dynamic GitHub profile card."""

from __future__ import annotations

import datetime as date
import html
import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
USER = "sunghoojung"
BIRTHDAY = date.date(2006, 7, 30)
OS = "macOS 26.4"
TOKEN = os.getenv("PROFILE_STATS_TOKEN") or os.getenv("GITHUB_TOKEN", "")
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "sunghoojung-profile"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get_json(url: str, body: dict | None = None) -> dict | list:
    data = None if body is None else json.dumps(body).encode()
    headers = dict(HEADERS)
    if data:
        headers["Content-Type"] = "application/json"
    request = Request(url, headers=headers, data=data, method="POST" if data else "GET")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def graphql(query: str, variables: dict) -> dict:
    result = get_json("https://api.github.com/graphql", {"query": query, "variables": variables})
    if result.get("errors"):
        raise RuntimeError(result["errors"][0]["message"])
    return result["data"]


def age(today: date.date) -> str:
    def add_months(value: date.date, months: int) -> date.date:
        month_index = value.year * 12 + value.month - 1 + months
        year, month = divmod(month_index, 12)
        year, month = year, month + 1
        next_month = (date.date(year, month, 1) + date.timedelta(days=32)).replace(day=1)
        last_day = (next_month - date.timedelta(days=1)).day
        return date.date(year, month, min(value.day, last_day))

    years = today.year - BIRTHDAY.year
    if add_months(BIRTHDAY, years * 12) > today:
        years -= 1
    anchor = add_months(BIRTHDAY, years * 12)
    months = 0
    while add_months(anchor, months + 1) <= today:
        months += 1
    days = (today - add_months(anchor, months)).days
    return f"{years} years, {months} months, {days} days"


def public_stats() -> dict:
    profile = get_json(f"https://api.github.com/users/{USER}")
    repos = []
    for page in range(1, 11):
        page_repos = get_json(f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100&page={page}")
        if not page_repos:
            break
        repos.extend(page_repos)
        if len(page_repos) < 100:
            break
    try:
        commits = get_json(f"https://api.github.com/search/commits?q={quote(f'author:{USER}')}&per_page=1")["total_count"]
    except Exception:
        commits = "n/a"
    return {
        "repos": len(repos),
        "contributed": "add token",
        "stars": sum(repo.get("stargazers_count", 0) for repo in repos),
        "commits": commits,
        "followers": profile.get("followers", 0),
        "loc_added": "add token",
        "loc_deleted": "add token",
        "loc_net": "add token",
    }


def calculate_loc(user_id: str, repo_edges: list[dict]) -> tuple[int, int]:
    query = """
    query($owner:String!, $name:String!, $cursor:String, $authorId:ID!) {
      repository(owner:$owner, name:$name) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first:100, after:$cursor, author:{id:$authorId}) {
                edges { node { additions deletions } }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
      }
    }
    """
    additions = 0
    deletions = 0
    for edge in repo_edges:
        owner, name = edge["node"]["nameWithOwner"].split("/", 1)
        cursor = None
        while True:
            data = graphql(query, {"owner": owner, "name": name, "cursor": cursor, "authorId": user_id})
            branch = data["repository"]["defaultBranchRef"]
            if not branch:
                break
            history = branch["target"]["history"]
            for commit in history["edges"]:
                additions += commit["node"]["additions"]
                deletions += commit["node"]["deletions"]
            if not history["pageInfo"]["hasNextPage"]:
                break
            cursor = history["pageInfo"]["endCursor"]
    return additions, deletions


def full_stats() -> dict:
    query = """
    query($login:String!) {
      user(login:$login) {
        id
        followers { totalCount }
        repositories(first:100, ownerAffiliations:OWNER) {
          totalCount
          edges { node { nameWithOwner stargazers { totalCount } } }
        }
        contributed: repositories(first:100, ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]) { totalCount }
        contributionsCollection { contributionCalendar { totalContributions } }
      }
    }
    """
    user = graphql(query, {"login": USER})["user"]
    repos = user["repositories"]
    loc_added, loc_deleted = calculate_loc(user["id"], repos["edges"])
    return {
        "repos": repos["totalCount"],
        "contributed": user["contributed"]["totalCount"],
        "stars": sum(edge["node"]["stargazers"]["totalCount"] for edge in repos["edges"]),
        "commits": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "followers": user["followers"]["totalCount"],
        "loc_added": loc_added,
        "loc_deleted": loc_deleted,
        "loc_net": loc_added - loc_deleted,
    }


def value(item: object) -> str:
    return f"{item:,}" if isinstance(item, int) else str(item)


def esc(item: object) -> str:
    return html.escape(value(item), quote=True)


def leader_row(y: int, key: str, item: object, key_color: str, muted: str, value_color: str) -> str:
    value_text = value(item)
    prefix_length = len(f". {key}: ")
    dots = "." * max(5, 92 - prefix_length - len(value_text))
    return (f'<text x="40" y="{y}" font-family="monospace" font-size="16">'
            f'<tspan fill="{muted}">. </tspan>'
            f'<tspan fill="{key_color}" font-weight="700">{html.escape(key)}</tspan>'
            f'<tspan fill="{muted}">: {dots} </tspan>'
            f'<tspan fill="{value_color}">{esc(item)}</tspan></text>')


def section_row(y: int, title: str, green: str, muted: str) -> str:
    return (f'<text x="40" y="{y}" font-family="monospace" font-size="16">'
            f'<tspan fill="{green}" font-weight="700">- {html.escape(title)} </tspan>'
            f'<tspan fill="{muted}">{"-" * 82}</tspan></text>')


def stats_row(y: int, stats: dict, muted: str, green: str, value_color: str) -> str:
    repos = esc(stats["repos"])
    contributed = esc(stats["contributed"])
    stars = esc(stats["stars"])
    commits = esc(stats["commits"])
    followers = esc(stats["followers"])
    added = esc(stats["loc_added"])
    deleted = esc(stats["loc_deleted"])
    net = esc(stats["loc_net"])
    if y == 568:
        return (f'<text x="40" y="{y}" font-family="monospace" font-size="16">'
                f'<tspan fill="{muted}">. </tspan><tspan fill="{green}" font-weight="700">Repos</tspan>'
                f'<tspan fill="{muted}">: .... </tspan><tspan fill="{value_color}">{repos}</tspan>'
                f'<tspan fill="{muted}"> &#123;</tspan><tspan fill="{green}" font-weight="700">Contributed</tspan>'
                f'<tspan fill="{muted}">: </tspan><tspan fill="{value_color}">{contributed}</tspan>'
                f'<tspan fill="{muted}">&#125; | </tspan><tspan fill="{green}" font-weight="700">Stars</tspan>'
                f'<tspan fill="{muted}">: ............ </tspan><tspan fill="{value_color}">{stars}</tspan></text>')
    if y == 599:
        return (f'<text x="40" y="{y}" font-family="monospace" font-size="16">'
                f'<tspan fill="{muted}">. </tspan><tspan fill="{green}" font-weight="700">Commits</tspan>'
                f'<tspan fill="{muted}">: ................ </tspan><tspan fill="{value_color}">{commits}</tspan>'
                f'<tspan fill="{muted}"> | </tspan><tspan fill="{green}" font-weight="700">Followers</tspan>'
                f'<tspan fill="{muted}">: ........ </tspan><tspan fill="{value_color}">{followers}</tspan></text>')
    return (f'<text x="40" y="{y}" font-family="monospace" font-size="16">'
            f'<tspan fill="{muted}">. </tspan><tspan fill="{green}" font-weight="700">Lines of Code on GitHub</tspan>'
            f'<tspan fill="{muted}">: </tspan><tspan fill="{value_color}">{net}</tspan>'
            f'<tspan fill="{muted}"> ( </tspan><tspan fill="#3fb950">{added}++</tspan>'
            f'<tspan fill="{muted}">, </tspan><tspan fill="#f85149">{deleted}--</tspan>'
            f'<tspan fill="{muted}"> )</tspan></text>')


def render(dark: bool, stats: dict, today: date.date) -> str:
    bg = "#0d1117" if dark else "#f6f8fa"
    panel = "#161b22" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    text = "#c9d1d9" if dark else "#24292f"
    muted = "#8b949e" if dark else "#57606a"
    green = "#7ee787" if dark else "#1a7f37"
    rows = [
        leader_row(72, "OS", OS, green, muted, green),
        leader_row(103, "Uptime", age(today), green, muted, green),
        leader_row(134, "Host", "Rutgers University", green, muted, green),
        leader_row(165, "IDE", "Cursor", green, muted, green),
        leader_row(227, "Languages.Real", "English", green, muted, green),
        leader_row(289, "Hobbies.Software", "CV, ML, Web Apps", green, muted, green),
        leader_row(320, "Hobbies.Personal", "Robotics", green, muted, green),
        section_row(382, "Contact", green, muted),
        leader_row(413, "Email.Personal", "sunghoojungg@gmail.com", green, muted, green),
        leader_row(444, "LinkedIn", "sunghoojung", green, muted, green),
        leader_row(475, "Discord", "sunny17347", green, muted, green),
        section_row(537, "GitHub Stats", green, muted),
        stats_row(568, stats, muted, green, green),
        stats_row(599, stats, muted, green, green),
        stats_row(630, stats, muted, green, green),
    ]
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="700" viewBox="0 0 1120 700">',
        f'<rect x="1" y="1" width="1118" height="698" rx="14" fill="{panel}" stroke="{border}" stroke-width="2"/>',
        f'<path d="M1 15a14 14 0 0 1 14-14h1090a14 14 0 0 1 14 14v35H1z" fill="{bg}"/>',
        f'<line x1="1" y1="50" x2="1119" y2="50" stroke="{border}"/>',
        '<circle cx="25" cy="26" r="6" fill="#ff5f56"/><circle cx="46" cy="26" r="6" fill="#ffbd2e"/><circle cx="67" cy="26" r="6" fill="#27c93f"/>',
        f'<text x="40" y="31" font-family="monospace" font-size="16" fill="{green}" font-weight="700">Sunghoo at GitHub</text>',
        f'<text x="250" y="31" font-family="monospace" font-size="16" fill="{muted}">{"-" * 78}</text>',
        *rows,
        f'<text x="40" y="670" font-family="monospace" font-size="12" fill="{muted}">Updated {today.isoformat()} | Add PROFILE_STATS_TOKEN for full contributed and LOC data</text>',
        '</svg>',
        '',
    ])


def main() -> None:
    today = date.date.today()
    try:
        stats = full_stats() if TOKEN else public_stats()
    except Exception as error:
        print(f"Full stats unavailable: {error}")
        stats = public_stats()
    (ROOT / "stats_light.svg").write_text(render(False, stats, today), encoding="utf-8")
    (ROOT / "stats_dark.svg").write_text(render(True, stats, today), encoding="utf-8")
    print(json.dumps({"date": today.isoformat(), "age": age(today), "stats": stats}, indent=2))


if __name__ == "__main__":
    main()
