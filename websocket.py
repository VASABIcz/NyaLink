import aiohttp, asyncio, traceback
from backoff import ExponentialBackoff
from json import dumps
from stats import  Stats


class WebSocket:
    def __init__(self, node, host, port, password, user_id, secure):
        self.node = node
        self.host = host
        self.port = port
        self.password = password
        self.user_id = user_id
        self.secure = secure

        self.task = None
        self.ws = None
        self.closed = False

    @property
    def headers(self):
        return {'Authorization': self.password,
                'User-Id': str(self.user_id)}
                # 'Num-Shards': str(1)} docs show its not needed

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and not self.ws.closed

    async def connect(self):
        try:
            if self.secure is True:
                uri = f'wss://{self.host}:{self.port}'
            else:
                uri = f'ws://{self.host}:{self.port}'

            if not self.is_connected:
                self.ws = await self.node.session.ws_connect(uri, headers=self.headers)
        except Exception:
            return

        if not self.task:
            self.task = self.node.loop.create_task(self.listen())

        self.closed = False
        self.node.available = True
        print("connection established to", self.node.identifier)

    async def listen(self):
        while True:
            msg = await self.ws.receive()
            if msg.type is aiohttp.WSMsgType.CLOSED:
                for _ in range(5):
                    print("trying to reconnect: ", self.node)
                    self.closed = True
                    await asyncio.sleep(2)
                    if not self.is_connected:
                        self.node.loop.create_task(self.connect())
                print(f"destroying node:", self.node)
                await self.node.destroy()
                self.task.close()
            else:
                self.node.loop.create_task(self.process_data(msg.json()))


    async def process_data(self, data):
        op = data.get('op', None)
        if not op:
            return

        if op == 'stats':
            self.node.stats = Stats(self.node, data)
            print(self.node)
        if op == 'event':
            try:
                data['player'] = self.node.players[int(data['guildId'])]
            except KeyError:
                return

            await self.process_event(data['type'], data)

        elif op == 'playerUpdate':
            try:
                await self.node.players[int(data['guildId'])].update_state(data)
            except KeyError:
                pass

    async def process_event(self, name: str, data):
        print("lavalink", name, data)
        if name == 'TrackEndEvent':
            try:
                await data.get('player').on_track_stop()
            except:
                pass
        elif name == 'TrackExceptionEvent':
            if data['exception']['severity'] == 'SUSPICIOUS':  # AMOGUS, ehmmm..., it actaly gets fired when node drops we dont want our song to skip so ignore :)
                return
            try:
                await data.get('player').on_track_stop()
            except:
                pass
        elif name == 'TrackStuckEvent':
            try:
                await data.get('player').on_track_stop()
            except:
                pass
        # elif name == 'TrackStartEvent':
        #     return 'on_track_start', TrackStart(data)
        elif name == 'WebSocketClosedEvent':
            print("CLOSEEEEEEEEEEEEEEEEED", data)

    async def send(self, **data):
        if self.is_connected:
            data_str = dumps(data)
            if isinstance(data_str, bytes):
                data_str = data_str.decode('utf-8')
            await self.ws.send_str(data_str)
