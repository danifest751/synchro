import re
import unicodedata


def spoken_text(text):
    return text.replace('+', ' плюс ')


def silero_marks(text):
    return re.sub(r'([АЕЁИОУЫЭЮЯаеёиоуыэюя])́', r'+\g<1>', text)


def preserve_stress(spoken, marked):
    if not isinstance(marked, str) or not marked.strip() or len(marked) > 6000:
        raise ValueError('The accent service returned invalid text')
    # Compare words case-insensitively: RUAccent can lowercase sentence initials.
    plain = re.sub(r'\+(?=[АЕЁИОУЫЭЮЯаеёиоуыэюя])', '', marked)
    def normalized(value):
        value = unicodedata.normalize('NFC', value).replace('ё', 'е').replace('Ё', 'Е').replace('\u0301', '')
        return re.findall(r'\w+', value.lower())
    if normalized(plain) != normalized(spoken):
        raise ValueError('The accent service changed the translation text')
    # Transfer stress onto the original characters: the service can drop punctuation.
    annotated = re.sub(r'\+([АЕЁИОУЫЭЮЯаеёиоуыэюя])', lambda match: match[1] + '\u0301', marked)
    stressed, index = set(), 0
    for position, char in enumerate(annotated):
        if char.isalnum() or char == '_':
            if annotated[position + 1:position + 2] == '\u0301':
                stressed.add(index)
            index += 1
    output, index = [], 0
    for position, char in enumerate(spoken):
        output.append(char)
        if char.isalnum() or char == '_':
            if index in stressed and spoken[position + 1:position + 2] != '\u0301':
                output.append('\u0301')
            index += 1
    return ''.join(output)
