import aiohttp
import asyncio
import aiolimiter

from datetime import datetime, timedelta

from config import Config
from bot.logger import LOGGER

# from orpheusdl-tidal


class TidalApi:
    def __init__(self):
        self.TIDAL_API_BASE = 'https://api.tidal.com/v1/'
        
        self.ratelimit = aiolimiter.AsyncLimiter(30, 60)
        self.session: aiohttp.ClientSession | None = None

        self.tv_session: TvSession | None = None
        self.mobile_hires: MobileSession | None = None
        self.mobile_atmos: MobileSession | None = None

        self.quality = 'LOW'
        self.spatial = 'OFF'
        self.sub_type: str | None = None
        
        self.saved = [] # just for storing opened client session


    async def _get(self, url: str, params: dict | None = None, session=None, refresh=False):
        # if no session is given, use the first one (default)
        if session is None:
            session = self.saved[0]

        params = params or {}
        params.setdefault("countryCode", session.country_code)
        params.setdefault("limit", "9999")


        async with self.ratelimit:
            async with self.session.get(
                self.TIDAL_API_BASE + url,
                headers=session.auth_headers(),
                params=params
            ) as resp:

                # if the request 401s or 403s, try refreshing the TV/Mobile session in case that helps
                if not refresh and (resp.status == 401 or resp.status == 403):
                    await session.refresh()
                    return await self._get(url, params, session, True)

                resp_json = None
                try:
                    resp_json = await resp.json()
                except:  # some tracks seem to return a JSON with leading whitespace
                    raise Exception(f'TIDAL : Response was not valid JSON. HTTP status {resp.status}. {resp.text}')

                if 'status' in resp_json and resp_json['status'] == 404 and \
                        'subStatus' in resp_json and resp_json['subStatus'] == 2001:
                    raise Exception('TIDAL : {}. This might be region-locked.'.format(resp_json['userMessage']))

                if 'status' in resp_json and not resp_json['status'] == 200:
                    raise Exception('TIDAL : ' + str(resp_json))

                return resp_json




    async def get_track(self, track_id):
        return await self._get(f'tracks/{track_id}')


    async def get_album(self, album_id):
        return await self._get('albums/' + str(album_id))
    

    async def get_album_tracks(self, album_id):
        return await self._get('albums/' + str(album_id) + '/tracks')


    async def get_artist(self, artist_id):
        return await self._get('artists/' + str(artist_id))

    async def get_artist_albums(self, artist_id):
        return await self._get('artists/' + str(artist_id) + '/albums')


    async def get_artist_albums_ep_singles(self, artist_id):
        return await self._get('artists/' + str(artist_id) + '/albums', params={'filter': 'EPSANDSINGLES'})


    async def get_stream_url(self, track_id, quality, session):
        return await self._get('tracks/' + str(track_id) + '/playbackinfopostpaywall/v4', {
            'playbackmode': 'STREAM',
            'assetpresentation': 'FULL',
            'audioquality': quality,
            'prefetch': 'false'
        },
        session)



    # call this from bot settings panel only
    async def get_tv_login_url(self):
        self.session = aiohttp.ClientSession()

        if not (Config.TIDAL_TV_TOKEN and Config.TIDAL_TV_SECRET):
            return False, "No Token/Secret added"

        self.tv_session = TvSession(
            Config.TIDAL_TV_TOKEN,
            Config.TIDAL_TV_SECRET,
            self.session
        )

        try:
            auth_url = await self.tv_session.get_device()
            return auth_url, None
        except Exception as e:
            return False, e


    async def login_tv(self):
        try:
            await self.tv_session.auth()
            self.saved.append(self.tv_session)

            self.sub_type = await self.get_subscription()
            LOGGER.info(f"TIDAL : Loaded account - {self.sub_type}")

            await self.refresh_mobile()
            return self.sub_type, None
        except Exception as e: 
            await self.session.close()
            return False, e


    async def login_from_saved(self, data):
        self.session = aiohttp.ClientSession()

        self.tv_session = TvSession(
            Config.TIDAL_TV_TOKEN,
            Config.TIDAL_TV_SECRET,
            self.session
        )

        self.tv_session.refresh_token = data['refresh_token']
        self.tv_session.country_code = data['country_code']
        self.tv_session.user_id = data['user_id']

        try:
            await self.tv_session.refresh()
            self.saved.append(self.tv_session)
        except Exception as e: 
            self.tv_session = None
            LOGGER.error("TIDAL : Coudn't load TV/Auto - " + str(e))

        # even if tv login failes check for mobile (if set to use mobile)
        await self.refresh_mobile()

        if any([self.tv_session, self.mobile_hires, self.mobile_atmos]):
            self.sub_type = await self.get_subscription()
        else:
            self.sub_type = 'UNKNOWN'

        LOGGER.info(f"TIDAL : Loaded account - {self.sub_type}")
    

    async def refresh_mobile(self, data=None):
        if not Config.TIDAL_MOBILE:
            return

        if Config.TIDAL_MOBILE_TOKEN:
            self.mobile_hires = await self._init_mobile_session(Config.TIDAL_MOBILE_TOKEN, 'Hires')


        if Config.TIDAL_ATMOS_MOBILE_TOKEN:
            self.mobile_atmos = await self._init_mobile_session(Config.TIDAL_ATMOS_MOBILE_TOKEN, 'Atmos')


    async def _init_mobile_session(self, token: str, device: str) -> "MobileSession | None":
        session = MobileSession(token, self.session)
        session.copy_from(self.tv_session)
        try:
            await session.refresh()
            self.saved.append(session)
            return session
        except Exception as e:
            LOGGER.error(f"TIDAL: Couldn't load Mobile {device} session - {e}")
            return None



    async def get_subscription(self) -> str:
        if self.saved != []:
            usersess = self.saved[0]
            async with self.session.get(f'https://api.tidal.com/v1/users/{usersess.user_id}/subscription',
                params={'countryCode': usersess.country_code},
                headers=usersess.auth_headers()
            ) as r:
                json_resp = await r.json()
                if r.status != 200:
                    raise Exception(f"TIDAL : {json_resp['userMessage']}")
                return json_resp['subscription']['type']



class BaseSession:
    AUTH_BASE = "https://auth.tidal.com/v1/"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.user_id: str | None = None
        self.country_code: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires: datetime | None = None

    def copy_from(self, other: "BaseSession"):
        self.country_code = other.country_code
        self.refresh_token = other.refresh_token
        self.user_id = other.user_id

    def auth_headers(self) -> dict:
        raise NotImplementedError

    async def refresh(self):
            raise NotImplementedError

        

class MobileSession(BaseSession):
    def __init__(self, token: str, session: aiohttp.ClientSession):
        super().__init__(session)
        self.client_id = token


    async def refresh(self):
        if not self.refresh_token:
            raise Exception("TIDAL: Missing refresh token for MobileSession")

        async with self.session.post(
            self.AUTH_BASE + 'oauth2/token', 
            data={
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'grant_type': 'refresh_token'
            }
        ) as r:
            json_resp = await r.json()
            if r.status == 200:
                # get user_id in case of direct refresh token login
                self.user_id = self.user_id or data["user_id"]
                self.access_token = json_resp['access_token']
                self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])
                self.refresh_token = json_resp.get("refresh_token", self.refresh_token)
            elif r.status == 401:
                raise Exception('TIDAL : ' + json_resp['userMessage'])


    def auth_headers(self):
        return {
            'Host': 'api.tidal.com',
            'X-Tidal-Token': self.client_id,
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'User-Agent': 'TIDAL_ANDROID/1039 okhttp/3.14.9'
        }


class TvSession(BaseSession):
    def __init__(self, token: str, secret: str, session: aiohttp.ClientSession):
        super().__init__(session)
        self.client_id = token
        self.client_secret = secret
        self.temp_data: dict | None = None


    async def get_device(self):
        async with self.session.post(
            self.AUTH_BASE + 'oauth2/device_authorization', 
            data={'client_id': self.client_id, 'scope': 'r_usr w_usr'}
        ) as r:
            if r.status != 200:
                raise Exception("TIDAL : Invalid TV Client ID or Token")

            json_resp = await r.json()
            auth_link = f"https://link.tidal.com/{json_resp['userCode']}"

            self.temp_data = {
                'client_id': self.client_id,
                'device_code': json_resp['deviceCode'],
                'client_secret': self.client_secret,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'scope': 'r_usr w_usr'
            }

            return auth_link


    async def auth(self):
        # keep a timer - not causing infinite wait
        #expiry = datetime.now() + timedelta(seconds=self.login_timeout)
        status_code = 400
        i = 1
        while status_code == 400:
            """if datetime.now() > expiry:
                raise Exception('TIDAL : Authorization Timedout')"""
            r = await self.session.post(self.TIDAL_AUTH_BASE + 'oauth2/token', data=self.temp_data)
            status_code = r.status
            await asyncio.sleep(i)
            i+=1

        json_resp = await r.json()

        if status_code != 200:
            raise Exception(f"TIDAL : Auth error - {json_resp['error']}")

        self.access_token = json_resp['access_token']
        self.refresh_token = json_resp['refresh_token']
        self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])

        async with self.session.get('https://api.tidal.com/v1/sessions', headers=self.auth_headers()) as r:
            assert (r.status == 200)
            json_resp = await r.json()
            self.user_id = json_resp['userId']
            self.country_code = json_resp['countryCode']

        async with self.session.get(
            f'https://api.tidal.com/v1/users/{self.user_id}?countryCode={self.country_code}',
            headers=self.auth_headers()) as r:
            assert (r.status == 200)


    async def refresh(self):
        if not self.refresh_token:
            raise Exception("TIDAL: Missing refresh token for TvSession")

        async with self.session.post(
            self.AUTH_BASE + 'oauth2/token', 
            data={
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token'
            }
        ) as r:
            json_resp = await r.json()
            if r.status != 200:
                raise Exception(f"TIDAL: TV refresh failed - {json_resp.get('userMessage')}")

            # get user_id in case of direct refresh token login
            self.user_id = self.user_id or json_resp["user_id"]
            self.access_token = json_resp['access_token']
            self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])
            self.refresh_token = json_resp.get("refresh_token", self.refresh_token)


    def auth_headers(self):
        return {
            'X-Tidal-Token': self.client_id,
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'User-Agent': 'TIDAL_ANDROID/1039 okhttp/3.14.9'
        }


tidalapi = TidalApi()