"""Phrase boundaries from source timestamps; translated text is never discarded."""
import re

ALIGNMENT_SCHEMA = {'type': 'object', 'properties': {'ends': {'type': 'array', 'items': {'type': 'integer'}}},
                    'required': ['ends'], 'additionalProperties': False}


def source_phrases(words, cutoff):
    groups, current = [], []
    for word in words:
        if current:
            gap = float(word['start']) - float(current[-1]['end'])
            span = float(current[-1]['end']) - float(current[0]['start'])
            if gap >= .45 or span >= 6 or span >= 1 and re.search(r'[.!?…]["\')\]]*$', current[-1]['word']):
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    phrases = []
    for index, group in enumerate(groups):
        start = float(group[0]['start'])
        next_start = float(groups[index + 1][0]['start']) if index + 1 < len(groups) else cutoff
        end = min(next_start, cutoff, max(float(word['end']) for word in group) + .08)
        phrases.append({'start': start, 'end': max(start + .12, end),
                        'source': ''.join(word['word'] for word in group).strip()})
    return phrases


def split_translation(text, ends, count):
    tokens = text.split()
    if not isinstance(ends, list) or len(ends) != count or any(type(end) is not int for end in ends):
        raise ValueError('Invalid phrase alignment')
    previous, parts = 0, []
    for end in ends:
        if not previous <= end <= len(tokens):
            raise ValueError('Invalid phrase alignment boundary')
        parts.append(' '.join(tokens[previous:end]))
        previous = end
    if previous != len(tokens):
        raise ValueError('Phrase alignment did not cover the complete translation')
    return parts
