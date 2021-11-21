import asyncio
from websocket import WebSocket
from backoff import ExponentialBackoff
from aiohttp import web
import aiohttp
from urllib.parse import quote
from player import Track

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

        self.players = {}
        self.available = True


    @property
    def is_available(self) -> bool:
        """Return whether the Node is available or not."""
        return self.ws.is_connected and self.available

    def close(self) -> None:
        """Close the node and make it unavailable."""
        self.available = False

    def open(self) -> None:
        """Open the node and make it available."""
        self.available = True

    async def connect(self):
        self.ws = WebSocket(
            node = self,
            host = self.host,
            port = self.port,
            password = self.password,
            user_id = self.user_id,
            secure = self.secure,
        )
        await self.ws.connect()


    async def send(self, **data) -> None:
        await self.ws.send(**data)

    async def destroy(self, *, force: bool = False) -> None:
        # TODO if not force move players to other node
        players = self.players.copy()

        for player in players.values():
            await player.destroy(force=force)

        try:
            self.ws.task.cancel()
        except Exception:
            pass

        del self.client.nodes[self.identifier]


    async def get_tracks(self, query: str, requester_id, *, retry_on_failure: bool = True):
        backoff = ExponentialBackoff(base=1)
        print("querying track", query, requester_id, self.rest_uri)

        for attempt in range(5):
            async with self.session.get(f'{self.rest_uri}/loadtracks?identifier={quote(query)}',
                                        headers={'Authorization': self.password}) as resp:

                print("query track response", resp.status)
                if not resp.status == 200 and retry_on_failure:
                    retry = backoff.delay()

                    await asyncio.sleep(retry)
                    continue

                elif not resp.status == 200 and not retry_on_failure:
                    return

                data = await resp.json()

                if not data['tracks']:
                    continue

                return [Track(id_=track['track'],  info=track['info'], query=query, requester_id=requester_id) for track in data['tracks']]

