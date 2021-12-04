import asyncio
import re
from urllib.parse import quote

from backoff import ExponentialBackoff
from player import Track
from websocket import WebSocket

URL_REG = re.compile(r'https?://(?:www\.)?.+')


class Node:
    def __init__(self, host: str,
                 port: int,
                 user_id: int,
                 *,
                 client,
                 session,
                 rest_uri: str,
                 password: str,
                 region: str,
                 identifier: str,
                 shard_id: int = None,
                 secure: bool = False,
                 ):
        self.host = host
        self.port = port
        self.user_id = user_id
        self.client = client
        self.session = session
        self.rest_uri = rest_uri
        self.password = password
        self.region = region
        self.identifier = identifier
        self.shard_id = shard_id
        self.secure = secure
        self.available = True
        self.loop = asyncio.get_event_loop()

        self.ws = None
        self.stats = None

        self.players = {}

    def __repr__(self):
        return f"<user: {self.user_id}, players: {len(self.players)}, identifier: {self.identifier}, stats: {self.stats}>"


    @property
    def is_available(self) -> bool:
        """Return whether the Node is available or not."""
        return self.ws.is_connected and self.available

    @property
    def penalty(self) -> float:
        """Returns the load-balancing penalty for this node."""
        if not self.is_available or not self.stats:
            return 9e30

        return self.stats.penalty.total

    def close(self) -> None:
        """Close the node and make it unavailable."""
        self.available = False

    def open(self) -> None:
        """Open the node and make it available."""
        self.available = True

    async def connect(self):
        self.ws = WebSocket(
            node=self,
            host=self.host,
            port=self.port,
            password=self.password,
            user_id=self.user_id,
            secure=self.secure,
        )
        await self.ws.connect()


    async def send(self, **data) -> None:
        await self.ws.send(**data)

    async def destroy(self, *, force: bool = False) -> None:
        # TODO if not force move players to other node done
        players = self.players.copy()

        for player in players.values():
            if force:
                try:
                    await player.destroy(force=force)
                except Exception:
                    pass
            else:
                await player.change_node()

        try:
            self.ws.task.cancel()
        except Exception:
            pass

        del self.client.nodes[self.identifier]


    async def _get_tracks(self, query: str, cache=True):
        backoff = ExponentialBackoff(base=1)
        print("querying track", query, self.rest_uri)

        if cache:
            res = await self.client.cache.get(query)
            if res:
                print("cached")
                return res

        if URL_REG.match(query):
            lava_query = query
        else:
            lava_query = f"ytsearch:{query}"
        for attempt in range(5):
            async with self.session.get(f'{self.rest_uri}/loadtracks?identifier={quote(lava_query)}',
                                        headers={'Authorization': self.password}) as resp:

                print("query track response", resp.status)
                if not resp.status == 200:
                    retry = backoff.delay()

                    await asyncio.sleep(retry)
                    continue

                data = await resp.json()

                if not data['tracks']:
                    retry = backoff.delay()
                    await asyncio.sleep(retry)
                    continue

                # TODO implement caching done
                print("fetched")
                if data['playlistInfo']:
                    for track in data['tracks']:
                        await self.client.cache.put(track['info']['title'], [track])
                    await self.client.cache.put(query, data['tracks'])

                    return data['tracks']

                for track in data['tracks']:
                    await self.client.cache.put(track['info']['title'], [track])
                await self.client.cache.put(query, [data['tracks'][0]])

                return [data['tracks'][0]]

    async def get_tracks(self, query: str, requester_id, cache=True):
        tracks = await self._get_tracks(query, cache=cache)

        return [Track(id_=track['track'], info=track['info'], query=query,
                      requester_id=requester_id) for track in tracks]

    async def get_raw_track(self, query: str, cache=True):
        return await self._get_tracks(query, cache=cache)

