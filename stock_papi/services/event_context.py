"""Derived announcement labels and conservative correction links, never new facts."""

import copy
import re
from datetime import date, datetime


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def _category(title):
    for label, words in (
        ('營運與風險', ('停工', '火災', '訴訟', '裁罰', '違約')),
        ('人事與治理', ('人事', '任命', '辭任', '辭職', '主管異動', '總經理', '董事改選', '公司名稱', '更名')),
        ('財務與股利', ('財報', '財務報告', '營收', '股利', '除息', '除權', '增資', '減資')),
        ('投資與資產', ('取得', '處分', '投資', '合資', '建廠', '併購')),
        ('營運與風險', ('臨床', '訂單', '契約')),
        ('會議與活動', ('法說', '法人說明會', '股東會', '股東臨時會')),
    ):
        if any(word in title for word in words):
            return label
    return '其他公告'


def _explicit_target(title, candidates):
    match = re.match(r'^更正(?:本公司)?(?:民國)?(\d{2,4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?(.*)$', title)
    if not match:
        return []
    year, month, day = map(int, match.group(1, 2, 3))
    try:
        target_date = date(year + 1911 if year < 1911 else year, month, day)
    except ValueError:
        return []
    text = re.sub(r'[\s。．.]', '', match.group(4))
    # Exact normalized title only: similar announcements are not evidence of identity.
    if len(text) < 6:
        return []
    return [row for row in candidates if _stamp(row.get('published_at'))
            and _stamp(row['published_at']).date() == target_date
            and re.sub(r'[\s。．.]', '', row.get('title', '')) == text]


def annotate_events(events):
    output = []
    for event in events:
        if not isinstance(event, dict):
            continue
        row = copy.deepcopy(event)
        title = str(row.get('title') or '')
        row.update(category=_category(title), correction_notice=bool(row.get('correction_of') or title.startswith('更正')),
                   correction_original=None, correction_changes=[])
        published = _stamp(row.get('published_at'))
        if row['correction_notice'] and published:
            candidates = [item for item in events if isinstance(item, dict)
                          and item.get('id') != row.get('id') and item.get('symbol') == row.get('symbol')
                          and item.get('market', 'TW') == row.get('market', 'TW')
                          and item.get('status') in {'confirmed', 'corrected'}
                          and _stamp(item.get('published_at')) and _stamp(item['published_at']) < published]
            matches = ([item for item in candidates if item.get('source_id') == row['correction_of']]
                       if row.get('correction_of') else _explicit_target(title, candidates))
            if len(matches) == 1:
                original = matches[0]
                row['correction_original'] = {key: original.get(key) for key in
                    ('id', 'title', 'summary', 'published_at', 'source', 'source_locator')}
                row['correction_changes'] = [key for key in ('title', 'summary', 'effective_at')
                                              if row.get(key) != original.get(key)]
        output.append(row)
    return output
