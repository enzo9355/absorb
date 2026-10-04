"""Private, Taipei-day digest over already validated public research."""

from datetime import datetime, timedelta, timezone

from stock_papi.services.event_context import annotate_events
from stock_papi.services.opinion_consensus import query_opinions

TAIPEI = timezone(timedelta(hours=8))


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp if stamp.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def build_daily_digest(watchlist, events, catalog, *, now, event_status='available'):
    if now.tzinfo is None:
        raise ValueError('digest cutoff must include timezone')
    start = now.astimezone(TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
    watched = {(str(row.get('market') or 'TW'), str(row.get('code') or '').upper())
               for row in watchlist if isinstance(row, dict) and row.get('code')}
    announcements = []
    for row in annotate_events(events):
        published = _stamp(row.get('published_at'))
        checked = _stamp(row.get('source_checked_at'))
        if ((row.get('market', 'TW'), row.get('symbol')) in watched
                and row.get('status') in {'confirmed', 'corrected', 'cancelled'}
                and row.get('source_status') == 'available' and published and checked
                and start <= published <= now and checked <= now):
            announcements.append(row)
    announcements.sort(key=lambda row: _stamp(row['published_at']), reverse=True)
    opinions = []
    for row in query_opinions(catalog or {}, cutoff_at=now):
        if (row.get('market'), row.get('symbol')) in watched and _stamp(row['reviewed_at']) >= start:
            opinions.append(row)
    opinions.sort(key=lambda row: _stamp(row['reviewed_at']), reverse=True)
    return {'date': start.date().isoformat(), 'announcements': announcements,
            'opinions': opinions, 'event_status': event_status,
            'opinion_status': 'available' if catalog and catalog.get('catalog_version') else 'unavailable',
            'watched_count': len(watched)}
