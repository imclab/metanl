import pkg_resources
from metanl.general import preprocess_text
from collections import defaultdict
import codecs
import math
import os
CACHE = {}


class lazy_property(object):
    """
    Decorator for properties that you want to compute, lazily, just once.

    From http://stackoverflow.com/a/6849299 and similar code in simplenlp.
    See also http://docs.python.org/2/howto/descriptor.html for reference.
    """
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, cls):
        result = self.func(instance)
        setattr(instance, self.func.__name__, result)
        return result


class Wordlist(object):
    """
    A list mapping words to frequencies, loaded from a .txt file on disk, and
    cached so that it's loaded at most once.
    """
    def __init__(self, worddict):
        self.worddict = worddict
        self._sorted_words = None

    @lazy_property
    def sorted_words(self):
        return sorted(self.worddict.keys(),
                      key=lambda word: (-self.worddict[word], word))

    def __len__(self):
        return len(self.worddict)

    def words(self):
        return list(self.sorted_words)
    keys = words

    def iterwords(self):
        return iter(self.sorted_words)
    iterkeys = iterwords
    __iter__ = iterwords

    def iteritems(self):
        for word in self.sorted_words:
            yield word, self.worddict[word]

    def get(self, word, default=0):
        return self.worddict.get(word, default)

    def __getitem__(self, word):
        return self.get(word)

    def __contains__(self, word):
        return word in self.worddict

    @lazy_property
    def max_freq(self):
        """
        The highest frequency in this wordlist.
        """
        if len(self) == 0:
            raise ValueError("This list is empty.")
        return max(self.worddict.itervalues())

    @classmethod
    def load(cls, filename):
        """
        Load a wordlist stored in metanl's data directory, and cache it so that
        it only has to be loaded once. Note that this will only work on files
        in a standard format (comma-seaprated linear frequency values, text
        already run through ftfy); to load other kinds of files, use "load_new"
        instead.
        """
        if filename in CACHE:
            return CACHE[filename]
        else:
            stream = pkg_resources.resource_stream(
                __name__,
                'data/wordlists/%s' % filename
            )
            wordlist = cls._load_stream(stream)
            CACHE[filename] = wordlist
        return wordlist

    @classmethod
    def _load_stream(cls, stream):
        worddict = {}
        for line in stream:
            word, freq = line.rstrip().split(',')
            freq = float(freq)
            worddict[word] = freq
        return cls(worddict)

    @classmethod
    def load_new(cls, path_and_filename):
        """
        Load a wordlist that is *not* stored in metanl's data directory. Save
        it (in standardized form) in metanl's data directory, and cache it so
        that it only has to be loaded once. The argument of this function must
        """
        filename = os.path.split(path_and_filename)[-1]
        stream = open(path_and_filename, 'r')
        wordlist = cls._load_new_stream(stream)
        CACHE[filename] = wordlist
        wordlist.save(filename)
        return wordlist

    @classmethod
    def _load_new_stream(cls, stream):
        worddict = defaultdict(int)
        mode = None
        # We need to distinguish between two modes, to handle old and new
        # files:
        # 1. comma-separated linear frequency values
        # 2. tab-separated logarithmic values in dB
        for line in stream:
            if mode is None:
                if '\t' in line:
                    mode = 2
                elif ',' in line:
                    mode = 1
                else:
                    raise ValueError(
                        "I don't recognize the format of this wordlist file."
                    )
            if mode == 1:
                word, freq = line.rstrip().split(',')
                freq = float(freq)
            elif mode == 2:
                word, freq = line.rstrip().split('\t')
                freq = 10**(float(freq)/10)
            word = preprocess_text(word).lower()
            worddict[word] += freq
        return cls(dict(worddict))

    def save(self, filename):
        out = codecs.open(filename, 'w', encoding='utf-8')
        for word in self.sorted_words:
            print >> out, "%s,%1.1f" % (word, self.get(word))
        out.close()

    def save_logarithmic(self, filename):
        """
        A format I'm experimenting with, representing the word frequency
        logarithmically.
        """
        out = codecs.open(filename, 'w', encoding='utf-8')
        logmax = math.log10(self.max_freq)
        for word in self.sorted_words:
            logfreq = math.log10(self.get(word))
            db = (logfreq - logmax) * 10
            print >> out, u"%s\t%3.1f" % (word, db)
        out.close()


def merge_lists(weighted_lists):
    """
    Make a list out of the union of multiple wordlists.

    Each entry in `weighted_lists` should be a pair (wordlist, suffix, max).

    `suffix` is a string that should be appended to each item in this list.
    If non-empty, it serves to distinguish which list a word came from.

    `max` indicates what the maximum value in that list should be
    scaled to. If `max` is None, the scaling will not be changed.

    >>> from metanl import english
    >>> from metanl import freeling
    """
    totals = defaultdict(float)
    for sublist, suffix, weight in weighted_lists:
        factor = 1
        if weight is not None and len(sublist) > 0:
            factor = weight / sublist.max_freq
        for word, freq in sublist.iteritems():
            totals[word + suffix] += freq * factor
    return Wordlist(totals)


def get_wordlist(lang):
    """
    Get the preferred frequency list for a language.
    """
    if lang == 'en':
        filename = 'multi-en.txt'
    elif lang == 'en-books':
        filename = 'google-unigrams.txt'
    elif lang == 'en-twitter':
        filename = 'twitter.txt'
    elif lang == 'multi':
        # this pre-combined wordlist is slow, and you're better off
        # loading languages separately
        filename = 'multilingual.txt'
    else:
        filename = 'leeds-internet-%s.txt' % lang
    return Wordlist.load(filename)


def multilingual_wordlist(langs, scale=1e9):
    """
    Get a wordlist that combines wordlists from multiple languages.

    >>> en_fr = multilingual_wordlist(['en', 'fr'])
    >>> int(en_fr['normalisation|fr'])
    52142
    """
    weighted_lists = [(get_wordlist(lang), '|' + lang, scale)
                      for lang in langs]
    return merge_lists(weighted_lists)


def get_frequency(word, lang, default_freq=0, scale=1e9):
    """
    Looks up a word's frequency in our preferred frequency list for the given
    language.

    >>> int(get_frequency('the', 'en', scale=42))
    42
    >>> int(get_frequency('normalization', 'en'))
    19566
    >>> int(get_frequency('Normalization', 'en'))
    19566
    >>> get_frequency('weirdification', 'en', 100.0)
    100.0
    """
    try:
        freqs = get_wordlist(lang)
    except ZeroDivisionError:
        return default_freq
    factor = scale / freqs.max_freq

    if " " in word:
        raise ValueError("get_frequency only can only look up single words, "
                         "but %r contains a space" % word)

    lookup = preprocess_text(word).lower()
    return factor * freqs[lookup] + default_freq

def multilingual_word_frequency(multiword, default_freq=0):
    """
    Splits a token into a word and language at the rightmost vertical bar,
    then looks up that word's frequency in that language.

    >>> int(multilingual_word_frequency('normalization|en'))
    19566
    >>> int(multilingual_word_frequency('normalisation|fr'))
    52142
    """
    word, lang = multiword.rsplit('|', 1)
    return get_frequency(word, lang, default_freq)
