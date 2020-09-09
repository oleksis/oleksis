import json
import pathlib
import re
import os

import asyncio
from bs4 import BeautifulSoup
from gql import gql, Client, AIOHTTPTransport
import requests


root = pathlib.Path(__file__).parent.resolve()
TOKEN = "bearer " + os.getenv("GH_GQL_API_TOKEN", "")

# Select your transport with a GitHub url endpoint
transport = AIOHTTPTransport(
    url="https://api.github.com/graphql", headers={"Authorization": TOKEN}
)

client = Client(
    transport=transport, fetch_schema_from_transport=True,
)


def replace_chunk(content, marker, chunk, inline=False):
    r = re.compile(
        r"<!\-\- {} starts \-\->.*<!\-\- {} ends \-\->".format(marker, marker),
        re.DOTALL,
    )
    if not inline:
        chunk = "\n{}\n".format(chunk)
    chunk = "<!-- {} starts -->{}<!-- {} ends -->".format(marker, chunk, marker)
    return r.sub(chunk, content)


def make_query(after_cursor=None):
    query_string =  """
query {
  viewer {
    repositories(first: 100, privacy: PUBLIC, after: AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        description
        url
        releases(last: 1) {
          totalCount
          nodes {
            name
            publishedAt
            url
          }
        }
      }
    }
  }
}
""".replace(
        "AFTER", '"{}"'.format(after_cursor) if after_cursor else "null"
    )

    return gql(query_string)


async def fetch_releases():
    repos = []
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    async with client as session:
        while has_next_page:
            try:
                data = await session.execute(make_query(after_cursor))
            except asyncio.exceptions.TimeoutError:
                continue
            # print()
            # print(json.dumps(data, indent=4))
            # print()
            repo_nodes = data["viewer"]["repositories"]["nodes"]

            for repo in repo_nodes:
                if repo["releases"]["totalCount"] and repo["name"] not in repo_names:
                    repos.append(repo)
                    repo_names.add(repo["name"])
                    releases.append(
                        {
                            "repo": repo["name"],
                            "repo_url": repo["url"],
                            "description": repo["description"],
                            "release": repo["releases"]["nodes"][0]["name"]
                            .replace(repo["name"], "")
                            .strip(),
                            "published_at": repo["releases"]["nodes"][0]["publishedAt"],
                            "published_day": repo["releases"]["nodes"][0][
                                "publishedAt"
                            ].split("T")[0],
                            "url": repo["releases"]["nodes"][0]["url"],
                            "total_releases": repo["releases"]["totalCount"],
                        }
                    )
            has_next_page = data["viewer"]["repositories"]["pageInfo"][
                "hasNextPage"
            ]
            after_cursor = data["viewer"]["repositories"]["pageInfo"]["endCursor"]
            await asyncio.sleep(1)
    return releases


def fetch_blog_entries():
    'Get the etries of my blog'
    FEED_URL = 'https://oleksis.github.io/jupyter/feed.xml'
    blog_entries = []

    try:
        page = requests.get(FEED_URL)
        soup = BeautifulSoup(page.content,'html.parser')

        entries = soup.find_all('entry')

        for entry in entries:
            title = entry.find('title')
            link = entry.find('link')
            published = entry.find('published')

            if None in (title, link, published):
                continue

            blog_entries.append(
                {
                    'title': title.text.strip(),
                    'url':  link['href'],
                    'published':  published.text.strip().split("T")[0]
                }
            )

    except requests.ConnectionError:
        print('Error get feed.xml!')
    
    return blog_entries


async def main():
    readme = root / "README.md"
    project_releases = root / "releases.md"
    releases = await fetch_releases()
    # print(json.dumps(releases, indent=4))
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    my_repos = {
        'youtube-dl',
        'youtube-dl-gui',
        'myrich',
        'cubadebate',
        'cubadebatebot',
        'machine-learning-articles',
        'pyinstaller-manylinux',
        'github-cuba',
    }
    releases = [
        release
        for release in releases
        if release['repo'] in my_repos
    ]
    md = "\n\n".join(
        [
            "[{repo} {release}]({url}) - {published_day}".format(**release)
            for release in releases
        ]
    )
    readme_contents = readme.open().read()
    rewritten = replace_chunk(readme_contents, "recent_releases", md)

    # Write out full project-releases.md file
    project_releases_md = "\n".join(
        [
            (
                "* **[{repo}]({repo_url})**: [{release}]({url}) {total_releases_md}- {published_day}\n"
                "<br>{description}"
            ).format(
                total_releases_md="- ([{} releases]({}/releases)) ".format(
                    release["total_releases"], release["repo_url"]
                )
                if release["total_releases"] > 1
                else "",
                **release
            )
            for release in releases
        ]
    )
    project_releases_content = project_releases.open().read()
    project_releases_content = replace_chunk(
        project_releases_content, "recent_releases", project_releases_md
    )
    project_releases_content = replace_chunk(
        project_releases_content, "project_count", str(len(releases)), inline=True
    )
    project_releases_content = replace_chunk(
        project_releases_content,
        "releases_count",
        str(sum(r["total_releases"] for r in releases)),
        inline=True,
    )
    project_releases.open("w").write(project_releases_content)

    entries = fetch_blog_entries()[:10]
    entries_md = "\n\n".join(
        ["[{title}]({url}) - {published}".format(**entry) for entry in entries]
    )
    rewritten = replace_chunk(rewritten, "blog", entries_md)

    readme.open("w").write(rewritten)
    print("README.md updated!")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
