#!/usr/bin/env python3
"""Generate the dynamic GitHub profile card."""

from __future__ import annotations

import datetime as date
import html
import json
import os
import time
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


def repo_loc(owner: str, name: str) -> tuple[int, int]:
    """Sum USER's additions/deletions in one repo via the contributor stats API."""
    url = f"https://api.github.com/repos/{owner}/{name}/stats/contributors"
    for _ in range(12):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=60) as response:
                if response.status == 202:  # stats cache is warming; retry shortly
                    time.sleep(3)
                    continue
                payload = response.read().decode()
        except Exception:
            return 0, 0
        for entry in json.loads(payload) if payload else []:
            if (entry.get("author") or {}).get("login") == USER:
                weeks = entry.get("weeks", [])
                return sum(week["a"] for week in weeks), sum(week["d"] for week in weeks)
        return 0, 0
    return 0, 0


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
    loc_added = loc_deleted = contributed = 0
    for repo in repos:
        owner, name = repo["full_name"].split("/", 1)
        added, deleted = repo_loc(owner, name)
        loc_added += added
        loc_deleted += deleted
        if added or deleted:  # count repos USER has actually authored code in
            contributed += 1
    return {
        "repos": len(repos),
        "contributed": contributed,
        "stars": sum(repo.get("stargazers_count", 0) for repo in repos),
        "commits": commits,
        "followers": profile.get("followers", 0),
        "loc_added": loc_added,
        "loc_deleted": loc_deleted,
        "loc_net": loc_added - loc_deleted,
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


def svg_escape(item: object) -> str:
    return html.escape(value(item), quote=True)


PANEL_X = 24
VALUE_END = PANEL_X + 715
CANVAS_WIDTH = VALUE_END + 24
CHAR_WIDTH = 9.3


def svg_row(y: int, key: str, item: object) -> str:
    label = f". {key}:"
    label_end = PANEL_X + len(label) * CHAR_WIDTH
    item_text = value(item)
    value_start = VALUE_END - len(item_text) * CHAR_WIDTH
    dots_start = label_end + 8
    dot_count = max(1, round((value_start - dots_start) / CHAR_WIDTH))
    return (
        f'<tspan x="{PANEL_X}" y="{y}" class="andrew-cc">. </tspan>'
        f'<tspan class="andrew-key">{html.escape(key)}</tspan><tspan>:</tspan>'
        f'<tspan x="{dots_start:.1f}" class="andrew-cc">{"." * dot_count}</tspan>'
        f'<tspan x="{value_start:.1f}" class="andrew-value">{svg_escape(item)}</tspan>'
    )


def section_row(y: int, title: str, text_color: str) -> str:
    title_end = PANEL_X + len(f"- {title} ") * CHAR_WIDTH
    dash_count = max(1, round((VALUE_END - title_end) / CHAR_WIDTH))
    return (
        f'<tspan x="{PANEL_X}" y="{y}">- {html.escape(title)} </tspan>'
        f'<tspan class="andrew-cc">{"-" * dash_count}</tspan>'
    )


def render_card(dark: bool, stats: dict, today: date.date) -> str:
    if dark:
        background = "#161b22"
        text = "#c9d1d9"
        key = "#ffa657"
        val = "#a5d6ff"
        cc = "#616e7f"
    else:
        background = "#f6f8fa"
        text = "#24292f"
        key = "#953800"
        val = "#0a3069"
        cc = "#c2cfde"
    prefix = "\n".join([
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="{CANVAS_WIDTH}px" height="500px" font-size="16px">',
        "<style>",
        "@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }",
        f".andrew-key {{fill: {key};}} .andrew-value {{fill: {val};}} .andrew-add {{fill: #3fb950;}} .andrew-del {{fill: #f85149;}} .andrew-cc {{fill: {cc};}} text, tspan {{white-space: pre;}}",
        "</style>",
        f'<rect width="{CANVAS_WIDTH}px" height="500px" fill="{background}" rx="15"/>',
    ])
    rows = [
        svg_row(50, "OS", OS),
        svg_row(70, "Uptime", age(today)),
        svg_row(90, "Host", "Rutgers University"),
        svg_row(130, "IDE", "VSCode 1.125.1"),
        svg_row(170, "Languages.Programming", "Python, JS, TS, Golang, C, C++"),
        svg_row(210, "Languages.Speak", "English, Korean"),
        svg_row(250, "Hobbies.Software", "CV, ML, Web Apps"),
        svg_row(270, "Hobbies.Personal", "Robotics"),
        section_row(310, "Contact", text),
        svg_row(330, "Email.Personal", "sunghoojungg@gmail.com"),
        svg_row(350, "LinkedIn", "sunghoo-jung"),
        svg_row(370, "Discord", "sunny17347"),
        section_row(410, "GitHub Stats", text),
        (f'<tspan x="{PANEL_X}" y="430" class="andrew-cc">. </tspan><tspan class="andrew-key">Repos</tspan><tspan>:</tspan><tspan class="andrew-cc"> ....</tspan>'
         f'<tspan x="{PANEL_X + 200 - len(value(stats["repos"])) * CHAR_WIDTH:.1f}" class="andrew-value">{svg_escape(stats["repos"])}</tspan>'
         f'<tspan x="{PANEL_X + 220}" class="andrew-cc"> &#123;</tspan><tspan class="andrew-key">Contributed</tspan><tspan>: </tspan>'
         f'<tspan x="{PANEL_X + 385 - len(value(stats["contributed"])) * CHAR_WIDTH:.1f}" class="andrew-value">{svg_escape(stats["contributed"])}</tspan>'
         f'<tspan x="{PANEL_X + 400}" class="andrew-cc"> &#125; | </tspan><tspan class="andrew-key">Stars</tspan><tspan>:</tspan>'
         f'<tspan x="{PANEL_X + 400 + len(" } | Stars:") * CHAR_WIDTH:.1f}" class="andrew-cc">{"." * max(1, round((VALUE_END - len(value(stats["stars"])) * CHAR_WIDTH - (PANEL_X + 400 + len(" } | Stars:") * CHAR_WIDTH)) / CHAR_WIDTH))}</tspan>'
         f'<tspan x="{VALUE_END - len(value(stats["stars"])) * CHAR_WIDTH:.1f}" class="andrew-value">{svg_escape(stats["stars"])}</tspan>'),
        (f'<tspan x="{PANEL_X}" y="450" class="andrew-cc">. </tspan><tspan class="andrew-key">Commits</tspan><tspan>: ................</tspan>'
         f'<tspan x="{PANEL_X + 310 - len(value(stats["commits"])) * CHAR_WIDTH:.1f}" class="andrew-value">{svg_escape(stats["commits"])}</tspan>'
         f'<tspan x="{PANEL_X + 330}" class="andrew-cc"> | </tspan><tspan class="andrew-key">Followers</tspan><tspan>:</tspan>'
         f'<tspan x="{PANEL_X + 330 + len(" | Followers:") * CHAR_WIDTH:.1f}" class="andrew-cc">{"." * max(1, round((VALUE_END - len(value(stats["followers"])) * CHAR_WIDTH - (PANEL_X + 330 + len(" | Followers:") * CHAR_WIDTH)) / CHAR_WIDTH))}</tspan>'
         f'<tspan x="{VALUE_END - len(value(stats["followers"])) * CHAR_WIDTH:.1f}" class="andrew-value">{svg_escape(stats["followers"])}</tspan>'),
    ]
    loc_close_x = VALUE_END - 10
    loc_deleted_end = loc_close_x - 10
    loc_deleted_start = loc_deleted_end - (len(value(stats["loc_deleted"])) + 2) * CHAR_WIDTH
    loc_comma_x = loc_deleted_start - 18
    loc_added_end = loc_comma_x - 8
    loc_added_start = loc_added_end - (len(value(stats["loc_added"])) + 2) * CHAR_WIDTH
    loc_open_x = loc_added_start - 20
    loc_net_end = loc_open_x - 8
    loc_net_start = loc_net_end - len(value(stats["loc_net"])) * CHAR_WIDTH
    rows.append(
        f'<tspan x="{PANEL_X}" y="470" class="andrew-cc">. </tspan><tspan class="andrew-key">Lines of Code on GitHub</tspan><tspan>:</tspan>'
        f'<tspan class="andrew-cc"> </tspan><tspan x="{loc_net_start:.1f}" class="andrew-value">{svg_escape(stats["loc_net"])}</tspan>'
        f'<tspan x="{loc_open_x:.1f}" class="andrew-cc"> ( </tspan><tspan x="{loc_added_start:.1f}" class="andrew-add">{svg_escape(stats["loc_added"])}++</tspan>'
        f'<tspan x="{loc_comma_x:.1f}" class="andrew-cc">, </tspan><tspan x="{loc_deleted_start:.1f}" class="andrew-del">{svg_escape(stats["loc_deleted"])}--</tspan><tspan x="{loc_close_x}" class="andrew-cc"> )</tspan>'
    )
    panel = "\n".join([
        '<g font-size="15.5">',
        f'<text x="{PANEL_X}" y="30" fill="{text}"><tspan x="{PANEL_X}" y="30">sunghoo@github</tspan><tspan x="{PANEL_X + len("sunghoo@github") * CHAR_WIDTH + 8:.1f}" class="andrew-cc">{"-" * max(1, round((VALUE_END - (PANEL_X + len("sunghoo@github") * CHAR_WIDTH + 8)) / CHAR_WIDTH))}</tspan>',
        *rows,
        "</text>",
        "</g>",
    ])
    return prefix + panel + "\n</svg>\n"


def main() -> None:
    today = date.date.today()
    try:
        stats = full_stats() if TOKEN else public_stats()
    except Exception as error:
        print(f"Full stats unavailable: {error}")
        stats = public_stats()
    light = ROOT / "light_mode.svg"
    dark = ROOT / "dark_mode.svg"
    light.write_text(render_card(False, stats, today), encoding="utf-8")
    dark.write_text(render_card(True, stats, today), encoding="utf-8")
    print(json.dumps({"date": today.isoformat(), "age": age(today), "stats": stats}, indent=2))


if __name__ == "__main__":
    main()
