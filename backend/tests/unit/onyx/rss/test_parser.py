from __future__ import annotations

from onyx.rss.parser import canonicalize_url
from onyx.rss.parser import content_hash
from onyx.rss.parser import discover_feed_candidates
from onyx.rss.parser import parse_feed


def test_discover_feed_candidates_from_html() -> None:
    html = """
    <html>
      <head>
        <link rel="alternate" type="application/rss+xml" title="Posts" href="/feed.xml" />
        <link
          rel="alternate"
          type="application/atom+xml"
          title="Atom"
          href="https://example.com/atom.xml"
        />
      </head>
    </html>
    """

    candidates = discover_feed_candidates(html, "https://example.com/blog")

    assert [(candidate.title, candidate.feed_url) for candidate in candidates] == [
        ("Posts", "https://example.com/feed.xml"),
        ("Atom", "https://example.com/atom.xml"),
    ]


def test_discover_feed_candidates_ignores_unsupported_json_feed() -> None:
    html = """
    <html>
      <head>
        <link
          rel="alternate"
          type="application/feed+json"
          title="JSON Feed"
          href="/feed.json"
        />
      </head>
    </html>
    """

    assert discover_feed_candidates(html, "https://example.com/blog") == []


def test_parse_rss_feed_handles_basic_entry() -> None:
    feed = """
    <rss version="2.0">
      <channel>
        <title>Example Feed</title>
        <link>https://example.com</link>
        <item>
          <title>Hello RSS</title>
          <link>https://example.com/posts/hello?utm_source=x</link>
          <guid>guid-1</guid>
          <pubDate>Wed, 08 Jul 2026 10:00:00 GMT</pubDate>
          <description><![CDATA[<p>Short summary</p>]]></description>
          <category>ai</category>
        </item>
      </channel>
    </rss>
    """

    parsed = parse_feed(feed, "https://example.com/feed.xml")

    assert parsed.title == "Example Feed"
    assert parsed.site_url == "https://example.com/"
    assert len(parsed.entries) == 1
    entry = parsed.entries[0]
    assert entry.title == "Hello RSS"
    assert entry.url == "https://example.com/posts/hello"
    assert entry.guid == "guid-1"
    assert entry.summary == "Short summary"
    assert entry.tags == ["ai"]


def test_content_hash_requires_real_content() -> None:
    assert content_hash("Title", "short", None) is None
    assert content_hash("Title", "Long enough content " * 5, None) == content_hash(
        "Title",
        "Long enough content " * 5,
        None,
    )


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    assert (
        canonicalize_url("https://Example.com/a/?utm_source=x&b=1#frag")
        == "https://example.com/a?b=1"
    )
