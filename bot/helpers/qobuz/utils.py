# From vitiko98/qobuz-dl
import re
import copy
import bot.helpers.translations as lang

from .qopy import qobuz_api
from ..message import send_message, edit_message
from ..utils import format_string
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file

from bot.settings import bot_set
from config import Config



async def get_track_metadata(item_id, r_id, q_meta=None):
    """
    Args:
        item_id : track id
        r_id: reply to message id
        q_meta : raw metadata from qobuz (pre-fetched)
    """
    if q_meta is None:
        raw_meta = await qobuz_api.get_track_url(item_id)
        if "sample" not in raw_meta and raw_meta.get('sampling_rate'):
            q_meta = await qobuz_api.get_track_meta(item_id)
            if not q_meta.get('streamable'):
                return None, lang.s.ERR_QOBUZ_NOT_STREAMABLE
        else:
            return None, lang.s.ERR_QOBUZ_NOT_STREAMABLE
    
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = item_id
    metadata['copyright'] = q_meta['copyright']
    metadata['albumartist'] = q_meta['album']['artist']['name']
    metadata['artist'] = await get_artists_name(q_meta['album'])
    metadata['upc'] = q_meta['album']['upc']
    metadata['album'] = q_meta['album']['title']
    metadata['isrc'] = q_meta['isrc']

    metadata['title'] = q_meta['title']
    if q_meta['version']:
        metadata['title'] += f' ({q_meta["version"]})'

    metadata['duration'] = q_meta['duration']
    metadata['explicit'] = q_meta['parental_warning']
    metadata['tracknumber'] = q_meta['track_number']
    metadata['date'] = q_meta['release_date_original']
    metadata['totaltracks'] = q_meta['album']['tracks_count']
    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'track'

    metadata['cover'] = await create_cover_file(q_meta['album']['image']['large'], metadata)
    metadata['thumbnail'] = await create_cover_file(q_meta['album']['image']['thumbnail'], metadata, True)

    return metadata, None  
        
async def get_album_metadata(item_id, r_id):
    q_meta = await qobuz_api.get_album_meta(item_id)
    if not q_meta.get('streamable'):
        return None, lang.s.ERR_QOBUZ_NOT_STREAMABLE
    
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = item_id
    metadata['albumartist'] = q_meta['artist']['name']
    metadata['upc'] = q_meta['upc']
    metadata['title'] = q_meta['title']
    metadata['album'] = q_meta['title']
    metadata['artist'] = q_meta['artist']['name']
    metadata['date'] = q_meta['release_date_original']
    metadata['totaltracks'] = q_meta['tracks_count']
    metadata['duration'] = q_meta['duration']
    metadata['copyright'] = q_meta['copyright']
    metadata['genre'] = q_meta['genre']['name']
    metadata['explicit'] = q_meta['parental_warning']
    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'album'

    metadata['cover'] = await create_cover_file(q_meta['image']['large'], metadata)
    metadata['thumbnail'] = await create_cover_file(q_meta['image']['thumbnail'], metadata, True)

    metadata['tracks'] = await get_track_meta_from_alb(q_meta, metadata)

    return metadata, None

async def get_track_meta_from_alb(q_meta:dict, alb_meta):
    """
    q_meta : raw metadata from qobuz (album)
    alb_meta : Sorted metadata (album)
    """
    tracks = []
    for track in q_meta['tracks']['items']:
        metadata = copy.deepcopy(alb_meta)
        metadata['itemid'] = track['id']

        metadata['title'] = track['title']
        # add track version if exists
        if track['version']:
            metadata['title'] += f' ({track["version"]})'

        metadata['duration'] = track['duration']
        metadata['isrc'] = track['isrc']
        metadata['tracknumber'] = track['track_number']
        metadata['tracks'] = '' # clear it
        metadata['type'] = 'track'
        tracks.append(metadata)
    return tracks


async def get_playlist_meta(raw_meta, tracks, r_id):
    """
    Args:
        raw_meta : raw metadata of playlist from qobuz
        tracks : list of tracks (raw metadata)
        r_id: reply to message id
    """
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['title'] = raw_meta['name']
    metadata['duration'] = raw_meta['duration']
    metadata['totaltracks'] = raw_meta['tracks_count']
    metadata['itemid'] = raw_meta['id']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Qobuz'
    metadata['cover'] = './project-siesta.png' #cannot get real playlist image
    metadata['thumbnail'] = './project-siesta.png'
    
    for track in tracks:
        track_meta, _ = await get_track_metadata(track['id'], r_id, track)
        metadata['tracks'].append(track_meta)
    return metadata

async def get_artist_meta(artist_raw):
    """
    Args:
        artist_raw : raw metadata of artist from qobuz
    """
    metadata = copy.deepcopy(base_meta)
    metadata['title'] = artist_raw['name']
    metadata['type'] = 'artist'
    metadata['provider'] = 'Qobuz'
    return metadata

async def get_artists_name(meta):
    artists = []
    try:
        for a in meta['artists']:
            artists.append(a['name'])
    except:
        artists.append(meta['artist']['name'])
    return ', '.join([str(artist) for artist in artists])


async def check_type(url):
    possibles = {
            "playlist": {
                "func": qobuz_api.get_plist_meta,
                "iterable_key": "tracks",
            },
            "artist": {
                "func": qobuz_api.get_artist_meta,
                "iterable_key": "albums",
            },
            "interpreter": {
                "func": qobuz_api.get_artist_meta,
                "iterable_key": "albums",
            },
            "label": {
                "func": qobuz_api.get_label_meta,
                "iterable_key": "albums",
            },
            "album": {"album": True, "func": None, "iterable_key": None},
            "track": {"album": False, "func": None, "iterable_key": None},
        }
    try:
        url_type, item_id = await get_url_info(url)
        type_dict = possibles[url_type]
    except (KeyError, IndexError, ValueError):
        return

    content = None
    if type_dict["func"]:
        res = await type_dict["func"](item_id)
        content = [item for item in res]

        smart_discography = True
        if smart_discography and url_type == "artist":
            items = smart_discography_filter(
                content,
                save_space=True,
                skip_extras=True,
            )
        else:
            items = [item[type_dict["iterable_key"]]["items"] for item in content][0]
            
        return items, None, type_dict, content
    else:
        return None, item_id, type_dict, content


async def get_url_info(url):
    """
    Extract the type and ID from a Qobuz URL.
    Supports both classic URLs and the new playlist URL format.
    """
    # Try the classic pattern first
    r = re.search(
        r"(?:https:\/\/(?:w{3}|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})?"
        r"\/(album|artist|track|playlist|label|interpreter)(?:\/[-\w\d]+)?\/([\w\d]+)",
        url,
    )
    
    # If not matched, try the new playlist URL format (e.g. /playlists/deftones/33105005)
    if not r:
        r = re.search(
            r"https:\/\/(?:w{3}|open|play)\.qobuz\.com(?:\/[a-z]{2}-[a-z]{2})?\/playlists\/[-\w]+\/(\d+)",
            url,
        )
        if r:
            return ("playlist", r.group(1))
        else:
            raise ValueError(f"URL does not match any known Qobuz format: {url}")

    return r.groups()


def smart_discography_filter(
    contents: list, save_space: bool = False, skip_extras: bool = False
) -> list:

    TYPE_REGEXES = {
        "remaster": r"(?i)(re)?master(ed)?",
        "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)",
    }

    def is_type(album_t: str, album: dict) -> bool:
        version = album.get("version", "")
        title = album.get("title", "")
        regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None

    def essence(album: dict) -> str:
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album)
        if not r:
            return album.lower()
        return r.group(1).strip().lower()

    requested_artist = contents[0]["name"]
    items = [item["albums"]["items"] for item in contents][0]

    title_grouped = dict()
    for item in items:
        title_ = essence(item["title"])
        if title_ not in title_grouped:
            title_grouped[title_] = []
        title_grouped[title_].append(item)

    items = []
    for albums in title_grouped.values():
        best_bit_depth = max(a["maximum_bit_depth"] for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a["maximum_sampling_rate"]
            for a in albums
            if a["maximum_bit_depth"] == best_bit_depth
        )
        remaster_exists = any(is_type("remaster", a) for a in albums)

        def is_valid(album: dict) -> bool:
            return (
                album["maximum_bit_depth"] == best_bit_depth
                and album["maximum_sampling_rate"] == best_sampling_rate
                and album["artist"]["name"] == requested_artist
                and not (
                    (remaster_exists and not is_type("remaster", album))
                    or (skip_extras and is_type("extra", album))
                )
            )

        filtered = tuple(filter(is_valid, albums))
        if len(filtered) >= 1:
            items.append(filtered[0])

    return items

    
async def get_quality(meta:dict):
    """
    Args
        meta : track url metadata dict
    Returns
        extention, quality
    """
    if qobuz_api.quality == 5:
        return 'mp3', '320K'
    else:
        return 'flac', f'{meta["bit_depth"]}B - {meta["sampling_rate"]}k'
