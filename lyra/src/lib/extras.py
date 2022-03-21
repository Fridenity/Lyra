import os
import io
import re
import time
import enum as e
import typing as t
import asyncio
import pathlib as pl
import functools as ft
import itertools as it
import urllib.error as urllib_er
import urllib.request as urllib_rq

import scipy.cluster  # type: ignore
import sklearn.cluster  # type: ignore
import attr as a
import lyricsgenius as lg  # type: ignore
import lavasnek_rs as lv


from PIL import Image as pil_img
from ytmusicapi import YTMusic  # type: ignore


_T_co = t.TypeVar('_T_co', covariant=True)
Required = t.Union[_T_co, None]
VoidCoroutine = t.Coroutine[t.Any, t.Any, None]


time_regex: t.Final = re.compile(
    r"^((\d+):)?([0-5][0-9]|[0-9]):([0-5][0-9]|[0-9])(.([0-9]{1,3}))?$"
)
time_regex_2: t.Final = re.compile(
    r"^(?!\s*$)((\d+)h)?(([0-9]|[0-5][0-9])m)?(([0-9]|[0-5][0-9])s)?(([0-9]|[0-9][0-9]|[0-9][0-9][0-9])ms)?$"
)
youtube_regex: t.Final = re.compile(
    r"^(?:https?:)?(?:\/\/)?(?:youtu\.be\/|(?:www\.|m\.)?youtube\.com\/(?:watch|v|embed)(?:\.php)?(?:\?.*v=|\/))([a-zA-Z0-9\_-]{7,15})(?:[\?&][a-zA-Z0-9\_-]+=[a-zA-Z0-9\_-]+)*(?:[&\/\#].*)?$"
)
url_regex: t.Final = re.compile(
    r'^(?:http|ftp)s?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
    r'localhost|'  # localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$',
    re.I,
)
genius_regex: t.Final = re.compile(r'\d*Embed')
genius_regex_2: t.Final = re.compile(r'^.+ Lyrics\n')
# LYRICS_URL = 'https://some-random-api.ml/lyrics?title='

TIMEOUT = 60
RETRIES = 3

ytmusic: t.Final = YTMusic()
genius: t.Final = lg.Genius(
    os.environ['GENIUS_ACCESS_TOKEN'], remove_section_headers=True, retries=3, timeout=8
)
genius.verbose = False
loop = asyncio.get_event_loop()


@a.define(hash=True, init=False, frozen=True)
class NullType(object):
    def __bool__(self) -> t.Literal[False]:
        return False


_S_co = t.TypeVar('_S_co', covariant=True)
NULL = NullType()
NullOr = t.Union[_S_co, NullType]


class LyricsData(t.NamedTuple):
    source: str
    lyrics: str
    title: str
    artist: str
    thumbnail: str
    url: t.Optional[str] = None
    artist_icon: t.Optional[str] = None
    artist_url: t.Optional[str] = None


async def get_lyrics_yt(song: str, /) -> t.Optional[LyricsData]:
    queried = ytmusic.search(song, 'songs') + ytmusic.search(song, 'videos')  # type: ignore
    if not queried:
        return
    track_data_0 = queried[0]['videoId']  # type: ignore
    watches = ytmusic.get_watch_playlist(track_data_0)  # type: ignore
    track_data: dict[str, t.Any] = watches['tracks'][0]
    if watches['lyrics'] is None:
        return

    lyrics_id = watches['lyrics']  # type: ignore
    assert isinstance(lyrics_id, str)
    lyrics: dict[str, str] = ytmusic.get_lyrics(lyrics_id)  # type: ignore
    source: str = lyrics['source'].replace("Source: ", '')

    return LyricsData(
        title=track_data['title'],
        lyrics=lyrics['lyrics'],
        thumbnail=track_data['thumbnail'][-1]['url'],
        artist=" & ".join((a['name'] for a in track_data['artists'])),
        source=source,
    )


async def get_lyrics_ge(song: str, /) -> t.Optional[LyricsData]:
    song_0 = genius.search_song(song, get_full_info=False)  # type: ignore
    if not song_0:
        return

    lyrics = genius.lyrics(song_url=song_0.url)  # type: ignore

    if not lyrics:
        return

    lyrics = genius_regex_2.sub('', genius_regex.sub('', lyrics))  # type: ignore

    artist = song_0.primary_artist  # type: ignore
    return LyricsData(
        title=song_0.title,  # type: ignore
        url=song_0.url,  # type: ignore
        artist=song_0.artist,  # type: ignore
        lyrics=lyrics,
        thumbnail=song_0.song_art_image_url,  # type: ignore
        source="Genius",
        artist_icon=artist.image_url,  # type: ignore
        artist_url=artist.url,  # type: ignore
    )


async def get_lyrics(song: str, /) -> dict[str, LyricsData]:
    from .errors import LyricsNotFound

    # tests = (get_lyrics_ge(song), get_lyrics_yt(song))
    tests = (get_lyrics_yt(song),)
    if not any(lyrics := await asyncio.gather(*tests)):
        raise LyricsNotFound
    return {l.source: l for l in lyrics if l}


def curr_time_ms() -> int:
    return time.time_ns() // 1_000_000


def to_stamp(ms: int, /) -> str:
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return (
        (f'{h:02}:' if h else '')
        + f'{m:02}:{s:02}'
        + (f'.{ms:03}' if not (h or m or s) else '')
    )


def to_ms(str_: str, /) -> int:
    VALID_FORMAT = "00:00.204 1:57 2:00:09 400ms 7m51s 5h2s99ms".split()
    singl_z = ['0']
    if match := time_regex.fullmatch(str_):
        match_ = singl_z + [*match.groups('0')]
        match_ += singl_z * (7 - len(match.groups()))
        ms = int(match_[6])
        s = int(match_[4])
        m = int(match_[3])
        h = int(match_[2])
    elif match := time_regex_2.fullmatch(str_):
        match_ = singl_z + list(match.groups('0'))
        match_ += singl_z * (9 - len(match.groups()))
        ms = int(match_[8])
        s = int(match_[6])
        m = int(match_[4])
        h = int(match_[2])
    else:
        raise ValueError(
            f"Invalid timestamp format given. Must be in the following format:\n> {fmt_str(VALID_FORMAT)}"
        )
    return (((h * 60 + m) * 60 + s)) * 1000 + ms


def wr(
    str_: str,
    limit: int = 60,
    replace_with: str = '…',
    /,
    *,
    block_friendly: bool = True,
) -> str:
    str_ = str_.replace("'", '′').replace('"', '″') if block_friendly else str_
    return (
        str_ if len(str_) <= limit else str_[: limit - len(replace_with)] + replace_with
    )


def format_flags(flags: e.Flag, /) -> str:
    return ' & '.join(f.replace('_', ' ').title() for f in str(flags).split('|'))


_E = t.TypeVar('_E')


def chunk(seq: t.Sequence[_E], n: int, /) -> t.Generator[t.Sequence[_E], None, None]:
    """Yield successive `n`-sized chunks from `seq`."""
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def chunk_b(seq: t.Sequence[_E], n: int, /) -> t.Generator[t.Sequence[_E], None, None]:
    """Yield successive `n`-sized chunks from `seq`, backwards."""
    start = 0
    for end in range(len(seq) % n, len(seq) + 1, n):
        yield seq[start:end]
        start = end


def inj_glob(pattern: str, /):
    if os.environ.get('IN_DOCKER', False):
        p = pl.Path('.') / 'shared'
    else:
        p = pl.Path('.') / '..'
    return p.glob(pattern)


@ft.cache
def get_img_pallete(
    img_url: str, /, *, n: int = 10, resize: tuple[int, int] = (150, 150)
):
    import numpy as np

    img_b = io.BytesIO(urllib_rq.urlopen(img_url).read())
    img = pil_img.open(img_b).resize(resize)  # optional, to reduce time
    ar = np.asarray(img)  # type: ignore
    shape = ar.shape
    ar = ar.reshape(np.product(shape[:2]), shape[2]).astype(float)  # type: ignore

    kmeans = sklearn.cluster.MiniBatchKMeans(  # type: ignore
        n_clusters=n, init="k-means++", max_iter=20, random_state=1000
    ).fit(ar)
    codes = kmeans.cluster_centers_  # type: ignore

    # assign codes
    vecs, _dist = scipy.cluster.vq.vq(ar, codes)  # type: ignore
    # count occurrences
    counts, _bins = np.histogram(vecs, len(codes))  # type: ignore

    return (
        *((*(int(code) for code in codes[i]),) for i in np.argsort(counts)[::-1]),  # type: ignore
    )  # returns colors in order of dominance


@ft.cache
def get_thumbnail(t_info: lv.Info, /) -> str | t.NoReturn:
    id_ = t_info.identifier

    # TODO: Make this support not just Youtube
    res = ('maxresdefault', 'sddefault', 'mqdefault', 'hqdefault', 'default')

    for x in res:
        url = f'https://img.youtube.com/vi/{id_}/{x}.jpg'
        try:
            if (urllib_rq.urlopen(url)).getcode() == 200:
                return url
        except urllib_er.HTTPError:
            continue

    raise NotImplementedError


_CE = t.TypeVar('_CE')


def uniquify(iter_: t.Iterable[_CE], /) -> t.Iterable[_CE]:
    return (*(k for k, _ in it.groupby(iter_)),)


def join_and(
    str_iter: t.Iterable[str], /, *, sep: str = ', ', and_: str = ' and '
) -> str:
    l = (*filter(lambda e: e, str_iter),)
    return sep.join((*l[:-2], *[and_.join(l[-2:])]))


_FE = t.TypeVar('_FE')


def flatten(iter_iters: t.Iterable[t.Iterable[_FE]], /) -> t.Iterable[_FE]:
    return (*(val for sublist in iter_iters for val in sublist),)


def split_preset(str_: str, /, *, sep_1: str = ',', sep_2: str = '|'):
    return tuple(frozenset(v.split(sep_2)) for v in str_.split(sep_1))


def fmt_str(iter_strs: t.Iterable[str], /, *, sep: str = ', ') -> str:
    return sep.join('\"%s\"' % s for s in iter_strs)
