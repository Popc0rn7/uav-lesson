"""BERT uncased WordPiece for the supplied DINO tokenizer, standard library only."""
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unicodedata


def chinese(code):
    return any(a <= code <= b for a, b in ((0x4e00, 0x9fff), (0x3400, 0x4dbf),
        (0x20000, 0x2a6df), (0x2a700, 0x2b73f), (0x2b740, 0x2b81f),
        (0x2b820, 0x2ceaf), (0xf900, 0xfaff), (0x2f800, 0x2fa1f)))


class BertTokenizer:
    def __init__(self, directory, context):
        path = Path(directory)
        config = json.loads((path/'tokenizer.json' if path.is_dir() else path).read_text())
        normalizer = config['normalizer']
        if (config['model']['type'] != 'WordPiece' or normalizer != {
                'type': 'BertNormalizer', 'clean_text': True, 'handle_chinese_chars': True,
                'strip_accents': None, 'lowercase': True}
                or config['pre_tokenizer'] != {'type': 'BertPreTokenizer'}):
            raise ValueError('Unsupported tokenizer configuration')
        self.vocab = config['model']['vocab']
        self.inverse = {v: k for k, v in self.vocab.items()}
        self.context = context
        self.max_chars = config['model']['max_input_chars_per_word']
        self.added = {t['content']: t['id'] for t in config['added_tokens']}
        self.pattern = re.compile('('+'|'.join(re.escape(t) for t in self.added)+')')
        self.special = {self.vocab[t] for t in ('[CLS]', '[SEP]', '.', '?')}
        if [self.vocab[t] for t in ('[PAD]', '[UNK]', '[CLS]', '[SEP]')] != [0, 100, 101, 102]:
            raise ValueError('Unexpected BERT special token IDs')

    def pieces(self, text):
        clean = []
        for char in text:
            category = unicodedata.category(char)
            if char in ('\t', '\n', '\r') or category == 'Zs':
                clean.append(' ')
            elif ord(char) in (0, 0xfffd) or category in ('Cc', 'Cf'):
                continue
            elif chinese(ord(char)):
                clean.extend((' ', char, ' '))
            else:
                clean.append(char)
        text = ''.join(c for c in unicodedata.normalize('NFD', ''.join(clean).lower())
                       if unicodedata.category(c) != 'Mn')
        basic, current = [], ''
        for char in text:
            code = ord(char)
            punctuation = (33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96
                           or 123 <= code <= 126 or unicodedata.category(char).startswith('P'))
            if char.isspace() or punctuation:
                if current:
                    basic.append(current)
                    current = ''
                if punctuation:
                    basic.append(char)
            else:
                current += char
        if current:
            basic.append(current)
        result = []
        for word in basic:
            if len(word) > self.max_chars:
                result.append(100)
                continue
            start, tokens = 0, []
            while start < len(word):
                end = len(word)
                while end > start:
                    piece = ('##' if start else '') + word[start:end]
                    if piece in self.vocab:
                        tokens.append(self.vocab[piece])
                        break
                    end -= 1
                if end == start:
                    tokens = [100]
                    break
                start = end
            result.extend(tokens)
        return result

    def encode(self, prompt):
        prompt = prompt.lower().strip()
        if not prompt:
            raise ValueError('Prompt must not be empty')
        if not prompt.endswith('.'):
            prompt += '.'
        ids = [101]
        for part in self.pattern.split(prompt):
            ids.extend([self.added[part]] if part in self.added else self.pieces(part))
        ids.append(102)
        if len(ids) > self.context:
            raise ValueError(f'Prompt exceeds {self.context} tokens')
        valid = len(ids)
        ids += [0]*(self.context-valid)
        return SimpleNamespace(ids=ids, type_ids=[0]*self.context,
                               attention_mask=[1]*valid+[0]*(self.context-valid))

    def decode(self, ids):
        tokens = [self.inverse[i] for i in ids if i not in self.added.values()]
        text = ' '.join(tokens).replace(' ##', '')
        for before, after in [(' .', '.'), (' ?', '?'), (' !', '!'), (' ,', ','),
                              (" ' ", "'"), (" n't", "n't"), (" 'm", "'m"),
                              (" 's", "'s"), (" 've", "'ve"), (" 're", "'re")]:
            text = text.replace(before, after)
        return text
