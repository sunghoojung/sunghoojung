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


def svg_escape(item: object) -> str:
    return html.escape(value(item), quote=True)


def svg_row(y: int, key: str, item: object, width: int = 66) -> str:
    item_text = value(item)
    dots = "." * max(5, width - len(f". {key}: ") - len(item_text))
    return (f'<tspan x="436" y="{y}" class="andrew-cc">. </tspan>'
            f'<tspan class="andrew-key">{html.escape(key)}</tspan><tspan class="andrew-cc">: {dots} </tspan>'
            f'<tspan class="andrew-value">{svg_escape(item)}</tspan>')


def render_combined(source: str, dark: bool, stats: dict, today: date.date) -> str:
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
    if '<g font-size="15.5">' in source:
        prefix = source.split('<g font-size="15.5">', 1)[0]
    else:
        prefix = source.split('<text x="436" y="30"', 1)[0]
    prefix = prefix.replace('width="862" height="486" viewBox="0 0 862 486"', 'width="1120" height="530" viewBox="0 0 1120 530"')
    prefix = prefix.replace('width="860" height="484"', 'width="1118" height="528"')
    prefix = prefix.replace('h832', 'h1090').replace('h-860', 'h-1118').replace('x2="861"', 'x2="1119"')
    prefix = prefix.replace("font-family=\"'JetBrains Mono','Fira Code',ui-monospace,'SFMono-Regular',Menlo,monospace\"", 'font-family="ConsolasFallback,Consolas,monospace"')
    prefix = "\n".join(line for line in prefix.splitlines() if "sunghoo@github: ~" not in line)
    if ".andrew-key" not in prefix:
        prefix = prefix.replace(
            "<style>\n",
            "<style>\n@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }\n"
            f".andrew-key {{fill: {key};}} .andrew-value {{fill: {val};}} .andrew-add {{fill: #3fb950;}} .andrew-del {{fill: #f85149;}} .andrew-cc {{fill: {cc};}} text, tspan {{white-space: pre;}}\n",
            1,
        )
    rows = [
        svg_row(70, "OS", OS),
        svg_row(90, "Uptime", age(today)),
        svg_row(110, "Host", "Rutgers University"),
        svg_row(130, "IDE", "Cursor"),
        svg_row(170, "Languages.Programming", "Python, Go Lang"),
        svg_row(190, "Languages.Real", "English"),
        svg_row(230, "Hobbies.Software", "CV, ML, Web Apps"),
        svg_row(250, "Hobbies.Personal", "Robotics"),
        f'<tspan x="436" y="290">- Contact</tspan> -{"-" * 61}',
        svg_row(310, "Email.Personal", "sunghoojungg@gmail.com"),
        svg_row(330, "LinkedIn", "sunghoojung"),
        svg_row(350, "Discord", "sunny17347"),
        f'<tspan x="436" y="390">- GitHub Stats</tspan> -{"-" * 54}',
        (f'<tspan x="436" y="410" class="andrew-cc">. </tspan><tspan class="andrew-key">Repos</tspan>'
         f'<tspan class="andrew-cc">: .... </tspan><tspan class="andrew-value">{svg_escape(stats["repos"])}</tspan>'
         f' &#123;<tspan class="andrew-key">Contributed</tspan>: <tspan class="andrew-value">{svg_escape(stats["contributed"])}</tspan>&#125; | '
         f'<tspan class="andrew-key">Stars</tspan>:<tspan class="andrew-cc"> ............ </tspan><tspan class="andrew-value">{svg_escape(stats["stars"])}</tspan>'),
        (f'<tspan x="436" y="430" class="andrew-cc">. </tspan><tspan class="andrew-key">Commits</tspan>'
         f'<tspan class="andrew-cc">: ................ </tspan><tspan class="andrew-value">{svg_escape(stats["commits"])}</tspan> | '
         f'<tspan class="andrew-key">Followers</tspan>:<tspan class="andrew-cc"> ........ </tspan><tspan class="andrew-value">{svg_escape(stats["followers"])}</tspan>'),
        (f'<tspan x="436" y="450" class="andrew-cc">. </tspan><tspan class="andrew-key">Lines of Code on GitHub</tspan>'
         f'<tspan class="andrew-cc">: </tspan><tspan class="andrew-value">{svg_escape(stats["loc_net"])}</tspan> ( '
         f'<tspan class="andrew-add">{svg_escape(stats["loc_added"])}++</tspan>, '
         f'<tspan class="andrew-del">{svg_escape(stats["loc_deleted"])}--</tspan> )'),
    ]
    panel = "\n".join([
        '<g font-size="15.5">',
        f'<text x="436" y="30" fill="{text}"><tspan x="436" y="30">sunghoo@github</tspan> -{"-" * 59}-</text>',
        f'<text x="436" y="30" fill="{text}">',
        *rows,
        f'<tspan x="436" y="500" class="andrew-cc">Updated {today.isoformat()}</tspan>',
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
    light.write_text(render_combined(light.read_text(encoding="utf-8"), False, stats, today), encoding="utf-8")
    dark.write_text(render_combined(dark.read_text(encoding="utf-8"), True, stats, today), encoding="utf-8")
    print(json.dumps({"date": today.isoformat(), "age": age(today), "stats": stats}, indent=2))


if __name__ == "__main__":
    main()
