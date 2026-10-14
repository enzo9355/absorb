"""Small, allowlisted public feeds. Content is always a private review candidate."""

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import requests
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException


SOURCES = {
    'aswath-damodaran': {'url': 'https://aswathdamodaran.blogspot.com/feeds/posts/default?alt=rss',
        'site': 'https://aswathdamodaran.blogspot.com/', 'title': 'Musings on Markets', 'name': 'Aswath Damodaran'},
    'ben-carlson': {'url': 'https://awealthofcommonsense.com/feed/',
        'site': 'https://awealthofcommonsense.com/', 'title': 'A Wealth of Common Sense', 'name': 'Ben Carlson'},
    'meb-faber': {'url': 'https://mebfaber.com/feed/',
        'site': 'https://mebfaber.com/', 'title': 'Meb Faber Research', 'name': 'Meb Faber'},
    'nick-maggiulli': {'url': 'https://ofdollarsanddata.com/feed/',
        'site': 'https://ofdollarsanddata.com/', 'title': 'Of Dollars And Data', 'name': 'Nick Maggiulli'},
    'barry-ritholtz': {'url': 'https://ritholtz.com/feed/',
        'site': 'https://ritholtz.com/', 'title': 'The Big Picture', 'name': 'Barry Ritholtz'},
    'alpha-architect': {'url': 'https://alphaarchitect.com/feed/',
        'site': 'https://alphaarchitect.com/', 'title': 'Alpha Architect', 'name': 'Alpha Architect', 'multiple_authors': True},
    'stock-nobleman': {'url': 'https://www.youtube.com/feeds/videos.xml?channel_id=UCZn9BeImRq3SDLC8WVrVmUw',
        'site': 'https://www.youtube.com/@WE178', 'name': '股市貴公子／鍾崑禎',
        'channel_id': 'UCZn9BeImRq3SDLC8WVrVmUw'},
}
MAX_BYTES = 2_000_000
MAX_ITEMS = 25
ATOM = '{http://www.w3.org/2005/Atom}'
YT = '{http://www.youtube.com/xml/schemas/2015}'


def is_source_url(creator_id, url):
    source = SOURCES.get(creator_id)
    if not source or not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.fragment:
            return False
        if 'channel_id' in source:
            return (parsed.hostname == 'www.youtube.com' and parsed.path == '/watch'
                    and re.fullmatch(r'[A-Za-z0-9_-]{11}', parse_qs(parsed.query).get('v', [''])[0]) is not None)
        return parsed.hostname == urlsplit(source['site']).hostname and parsed.path not in {'', '/'} and not parsed.query
    except ValueError:
        return False


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    parser = _PlainText()
    parser.feed(value or '')
    return ' '.join(' '.join(parser.parts).split())


def parse_feed(creator_id, raw, *, now=None):
    source = SOURCES[creator_id]
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or len(raw) > MAX_BYTES:
        raise ValueError('invalid feed capture')
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError('invalid feed XML') from exc
    video = 'channel_id' in source
    if video:
        if root.tag != ATOM+'feed' or root.findtext(YT+'channelId') not in {source['channel_id'], source['channel_id'][2:]}:
            raise ValueError('feed channel identity changed')
        entries = root.findall(ATOM+'entry')
    else:
        if root.tag != 'rss' or not (root.findtext('channel/title') or '').startswith(source['title']):
            raise ValueError('feed site identity changed')
        entries = root.findall('channel/item')
    rows, seen = [], set()
    for entry in entries[:MAX_ITEMS]:
        title = _plain(entry.findtext(ATOM+'title' if video else 'title'))
        if video:
            if entry.findtext(YT+'channelId') != source['channel_id']:
                raise ValueError('entry channel identity changed')
            video_id = entry.findtext(YT+'videoId') or ''
            url = 'https://www.youtube.com/watch?v=' + video_id
            stamp = entry.findtext(ATOM+'published') or ''
            published = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            excerpt = entry.findtext('{http://search.yahoo.com/mrss/}group/{http://search.yahoo.com/mrss/}description')
            author = entry.findtext(ATOM+'author/'+ATOM+'name') or source['name']
            if source.get('title_contains') and source['title_contains'] not in title:
                continue
        else:
            url = (entry.findtext('link') or '').strip()
            author = entry.findtext('{http://purl.org/dc/elements/1.1/}creator') or entry.findtext('author') or ''
            if author and not source.get('multiple_authors') and author not in {source['name'], 'noreply@blogger.com ('+source['name']+')'}:
                raise ValueError('entry author identity changed')
            published = parsedate_to_datetime(entry.findtext('pubDate') or '')
            excerpt = entry.findtext('description')
        if not title or not is_source_url(creator_id, url) or published.tzinfo is None or published > now:
            raise ValueError('invalid feed entry URL, title or date')
        if url in seen:
            continue
        seen.add(url)
        key = 'feed:' + hashlib.sha256(url.encode()).hexdigest()
        rows.append({'id': key.replace(':', '-'), 'opinion_id': key, 'creator_id': creator_id,
            'source_url': url, 'source_kind': 'youtube_video' if video else 'article',
            'source_platform': 'YouTube' if video else 'RSS', 'acquisition_method': 'public_feed',
            'origin_group_id': key, 'market': '', 'symbol': '', 'security_status': 'unmapped',
            'published_at': published.astimezone(timezone.utc).isoformat(), 'first_seen_at': now.isoformat(),
            'reviewed_at': '', 'review_status': 'pending_review', 'source_status': 'available',
            'content_type': 'original_opinion', 'stance': 'unclear', 'recommendation_kind': 'mention',
            'direction': 'hold', 'source_author': _plain(author)[:200],
            'text': title[:500] + ('\n作者：'+_plain(author)[:200] if source.get('multiple_authors') else '')
                    + ('\n'+_plain(excerpt)[:4000] if excerpt else '')})
    if not rows:
        raise ValueError('empty feed; retain previous candidates')
    return {'schema_version': 2, 'catalog_id': 'public-opinions-feed-candidate',
            'fetch_meta': {'creator_id': creator_id, 'feed_url': source['url'],
                           'provider': 'YouTube' if video else 'RSS', 'fetched_at': now.isoformat(),
                           'has_more': len(entries) >= MAX_ITEMS}, 'opinions': rows}


def fetch_candidates(creator_id, *, now=None):
    with requests.get(SOURCES[creator_id]['url'], headers={'User-Agent': 'ABSORB-research/1.0'},
                      timeout=(10, 20), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError('feed HTTP ' + str(response.status_code))
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError('feed exceeds size limit')
    return parse_feed(creator_id, bytes(raw), now=now)
