from __future__ import annotations

import hashlib
import re
from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from onyx.rss.models import FeedCandidate
from onyx.rss.models import ParsedFeed
from onyx.rss.models import ParsedFeedEntry


def canonicalize_url(url: str | None, base_url: str | None = None) -> str | None:
    if not url:
        return None
    absolute = urljoin(base_url or "", url.strip())
    parsed = urlparse(absolute)
    if not parsed.scheme or not parsed.netloc:
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(query),
            "",
        )
    )


def content_hash(title: str, summary: str | None, full_text: str | None) -> str | None:
    text = full_text or summary
    if not text or len(text.strip()) < 40:
        return None
    normalized = re.sub(r"\s+", " ", f"{title}\n{text}".strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text(" ", strip=True)
    return unescape(re.sub(r"\s+", " ", text)).strip() or None


def discover_feed_candidates(html: str, page_url: str) -> list[FeedCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[FeedCandidate] = []
    seen: set[str] = set()
    for link in soup.find_all("link"):
        rel_values = link.get("rel") or []
        rel = " ".join(str(value).lower() for value in rel_values)
        link_type = str(link.get("type") or "").lower()
        href = str(link.get("href") or "").strip()
        if not href or "alternate" not in rel:
            continue
        if link_type not in {
            "application/rss+xml",
            "application/atom+xml",
            "application/feed+json",
            "text/xml",
            "application/xml",
        }:
            continue
        feed_url = canonicalize_url(href, page_url)
        if feed_url is None or feed_url in seen:
            continue
        seen.add(feed_url)
        title = str(link.get("title") or feed_url)
        candidates.append(
            FeedCandidate(title=title, feed_url=feed_url, site_url=page_url)
        )
    return candidates


def parse_feed(xml_text: str, feed_url: str) -> ParsedFeed:
    root = ElementTree.fromstring(xml_text.lstrip())
    tag = _local_name(root.tag)
    if tag == "rss" or root.find("channel") is not None:
        return _parse_rss(root, feed_url)
    if tag == "feed":
        return _parse_atom(root, feed_url)
    raise ValueError("Unsupported RSS/Atom feed")


def _parse_rss(root: ElementTree.Element, feed_url: str) -> ParsedFeed:
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS feed is missing channel")
    title = _child_text(channel, "title")
    site_url = canonicalize_url(_child_text(channel, "link"), feed_url)
    entries: list[ParsedFeedEntry] = []
    for item in channel.findall("item"):
        item_title = _child_text(item, "title") or "(untitled)"
        link = canonicalize_url(_child_text(item, "link"), feed_url)
        guid = _child_text(item, "guid")
        summary = strip_html(
            _child_text(item, "description")
            or _child_text_ns(item, "encoded")
        )
        content = strip_html(_child_text_ns(item, "encoded"))
        tags = [
            text
            for child in item
            if _local_name(child.tag) == "category"
            for text in [strip_html(child.text)]
            if text
        ]
        entries.append(
            ParsedFeedEntry(
                title=strip_html(item_title) or item_title,
                url=link,
                guid=guid,
                author=_child_text(item, "author") or _child_text_ns(item, "creator"),
                published_at=_parse_date(
                    _child_text(item, "pubDate") or _child_text_ns(item, "date")
                ),
                summary=summary,
                content=content,
                tags=tags,
                category=tags[0] if tags else None,
            )
        )
    return ParsedFeed(title=title, site_url=site_url, entries=entries)


def _parse_atom(root: ElementTree.Element, feed_url: str) -> ParsedFeed:
    title = _child_text(root, "title")
    site_url = _atom_link(root, feed_url, rel_values={"alternate"}) or feed_url
    entries: list[ParsedFeedEntry] = []
    for entry in [child for child in root if _local_name(child.tag) == "entry"]:
        item_title = _child_text(entry, "title") or "(untitled)"
        link = _atom_link(entry, feed_url, rel_values={"alternate"}) or _atom_link(
            entry, feed_url, rel_values={""}
        )
        tags = [
            str(child.attrib.get("term") or child.attrib.get("label") or "").strip()
            for child in entry
            if _local_name(child.tag) == "category"
        ]
        tags = [tag for tag in tags if tag]
        entries.append(
            ParsedFeedEntry(
                title=strip_html(item_title) or item_title,
                url=link,
                guid=_child_text(entry, "id"),
                author=_atom_author(entry),
                published_at=_parse_date(
                    _child_text(entry, "published") or _child_text(entry, "updated")
                ),
                summary=strip_html(
                    _child_text(entry, "summary") or _child_text(entry, "content")
                ),
                content=strip_html(_child_text(entry, "content")),
                tags=tags,
                category=tags[0] if tags else None,
            )
        )
    return ParsedFeed(title=title, site_url=site_url, entries=entries)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            return child.text.strip() if child.text else None
    return None


def _child_text_ns(element: ElementTree.Element, local_name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == local_name:
            return child.text.strip() if child.text else None
    return None


def _atom_link(
    element: ElementTree.Element,
    feed_url: str,
    *,
    rel_values: set[str],
) -> str | None:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        rel = str(child.attrib.get("rel") or "").lower()
        if rel not in rel_values:
            continue
        href = child.attrib.get("href")
        if href:
            return canonicalize_url(str(href), feed_url)
    return None


def _atom_author(element: ElementTree.Element) -> str | None:
    for child in element:
        if _local_name(child.tag) != "author":
            continue
        return _child_text(child, "name")
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
