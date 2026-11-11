import re
import unicodedata


CJK = re.compile(r'[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-鿿가-힯豈-﫿]+')
# Russian speech cannot pronounce these: Latin letters, digits, Han, kana and Hangul.
FOREIGN = re.compile(r'[A-Za-z0-9ᄀ-ᇿ぀-ヿ㄰-㆏㐀-鿿가-힯豈-﫿]')


def spoken_text(text):
    return text.replace('+', ' плюс ')


UNITS = ('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать '
         'четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать').split()
TENS = '- - двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split()
HUNDREDS = '- сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split()
SCALES = [('тысяча', 'тысячи', 'тысяч'), ('миллион', 'миллиона', 'миллионов'), ('миллиард', 'миллиарда', 'миллиардов')]
LETTER_NAMES = dict(zip('abcdefghijklmnopqrstuvwxyz', 'эй би си ди и эф джи эйч ай джей кей эл эм эн оу пи кью ар эс ти ю ви '
                        'дабл-ю экс уай зед'.split()))
SOUNDS = [('sch', 'ш'), ('sh', 'ш'), ('ch', 'ч'), ('th', 'т'), ('ph', 'ф'), ('ck', 'к'), ('qu', 'кв'), ('kh', 'х'),
          ('zh', 'ж'), ('ts', 'ц'), ('ee', 'и'), ('oo', 'у'), ('ou', 'ау'), ('ya', 'я'), ('yu', 'ю')] + list(zip(
          'abcdefghijklmnopqrstuvwxyz', 'а б к д е ф г х и дж к л м н о п к р с т у в в кс и з'.split()))


def number_words(number):
    if number == 0:
        return UNITS[0]
    groups, words = [], []
    while number:
        number, group = divmod(number, 1000)
        groups.append(group)
    for scale in reversed(range(len(groups))):
        group = groups[scale]
        if not group:
            continue
        if group >= 100:
            words.append(HUNDREDS[group // 100])
        rest = group % 100
        if rest >= 20:
            words.append(TENS[rest // 10])
            rest %= 10
        if rest:
            # Thousands are feminine: одна тысяча, две тысячи.
            words.append(('одна', 'две')[rest - 1] if scale == 1 and rest < 3 else UNITS[rest])
        if scale:
            last = group % 100
            forms = SCALES[scale - 1]
            words.append(forms[2] if 11 <= last <= 19 else forms[0] if last % 10 == 1 else forms[1] if 2 <= last % 10 <= 4 else forms[2])
    return ' '.join(words)


def latin_word(word):
    lower = word.lower()
    if word.isupper() and len(word) <= 5 or not re.search('[aeiouy]', lower):
        return ' '.join(LETTER_NAMES[char] for char in lower)
    output, index = [], 0
    while index < len(lower):
        latin, cyrillic = next(pair for pair in SOUNDS if lower.startswith(pair[0], index))
        output.append(cyrillic)
        index += len(latin)
    spelled = ''.join(output)
    return spelled.capitalize() if word[0].isupper() else spelled


def cyrillic_spelling(text):
    """Last-resort speech spelling when a model leaves Latin names, digits or source script in Russian text."""
    # shortcut: untranslated Han, kana and Hangul are dropped, not transliterated; add romanization if this appears in logs.
    text = CJK.sub(' ', text)
    text = re.sub(r'[A-Za-z]+', lambda match: f' {latin_word(match[0])} ', text)
    text = re.sub(r'\d+', lambda match: ' ' + (number_words(int(match[0])) if len(match[0]) <= 12 else
                  ' '.join(UNITS[int(digit)] for digit in match[0])) + ' ', text)
    return re.sub(r' +([,.!?;:…])', r'\1', re.sub(r' {2,}', ' ', text)).strip()


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
