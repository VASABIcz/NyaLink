import asyncio
import sys
from json import loads, dumps

import aiohttp
from aiohttp import web

from cache import Cache
from node import Node
from player import Player

# TODO rest api done
# TODO add node for all cients bad idea
# TODO fix small lag after reconnect impossible
# TODO weighted track cache done
# it is posible that when nya link adn doesnt recive voice server update it wont play any audio until move to other chnnnel
# TODO add api that will ask our client for voice server update
# or just dont allow connecting while client isn't connected
# TODO fix server/state isnt handelded/better voice state
# TODO on player dc/stop stop track fetching or ignore it
# TODO playing spotify somehow skips itself done
# next.set issue

clients = {}


class Unbuffered:
    """
    Used for stdout and stderr.
    """

    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


class NyaLink:
    def __init__(self, ws, user_id, cache):
        self.session = aiohttp.ClientSession()
        self.loop = asyncio.get_event_loop()
        self.ws: web.WebSocketResponse = ws
        self.user_id = user_id  # int(self.ws.headers['user_id'])
        self.cache: Cache = cache

        self.closed = False

        self.nodes = {}

        self.listener = self.loop.create_task(self.listen())

    def _get_players(self) -> dict:
        players = []

        for node in self.nodes.values():
            players.extend(node.players.values())

        return {player.guild_id: player for player in players}

    @property
    def players(self):
        return self._get_players()

    def get_best_node(self):
        nodes = [n for n in self.nodes.values() if n.is_available]
        if not nodes:
            return None

        return sorted(nodes, key=lambda n: len(n.players))[0]

    def get_best_stats_node(self):
        nodes = [n for n in self.nodes.values() if n.is_available]
        if not nodes:
            return None

        return sorted(nodes, key=lambda n: n.penalty)[0]

    def get_node(self, identifier: str):
        return self.nodes.get(identifier, None)

    async def update_handler(self, data) -> None:
        if not data or 't' not in data:
            return

        # TODO implement move resume done
        # TODO implement dc teardown done

        if data['t'] == 'VOICE_SERVER_UPDATE':
            guild_id = int(data['d']['guild_id'])

            try:
                player = self.get_player(guild_id)
            except Exception:
                pass
            else:
                print("player vs", player.voice_state)
                await player.on_voice_server(data['d'])

        elif data['t'] == 'VOICE_STATE_UPDATE':
            if int(data['d']['user_id']) != int(self.user_id):
                return

            guild_id = int(data['d']['guild_id'])
            try:
                player = self.get_player(guild_id)
            except KeyError:
                pass
            else:
                print("player vs", player.voice_state)
                await player.on_voice_state(data['d'])

    def get_player(self, guild_id: int, **kwargs):
        players = self.players

        try:
            player = players[guild_id]
        except KeyError:
            pass
        else:
            return player

        node = self.get_best_node()

        player = Player(guild_id, node)
        print(f"node players: {node.players}")
        node.players[guild_id] = player

        return player

    async def add_node(self, data):
        print("adding node: ", data['identifier'])
        identifier = data['identifier']
        if identifier in self.nodes:
            return
        host = data['host']
        port = int(data['port'])
        user_id = self.user_id
        client = self
        session = self.session
        rest_uri = data['rest_uri']
        password = data['password']
        region = data.get('region')
        shard_id = data.get('shard_id', None)
        secure = data.get('secure', False)

        n = Node(host=host, port=port, user_id=user_id, client=client, session=session, rest_uri=rest_uri,
                 password=password, region=region, identifier=identifier, shard_id=shard_id, secure=secure)
        await n.connect()
        self.nodes[identifier] = n

    async def remove_node(self, **data):
        identifier = data['identifier']
        force = data.get("force", False)
        await self.nodes[identifier].destroy(force)

    async def process_data(self, msg):
        print(f"procesing: {msg.data}")
        data = loads(msg.data)
        # client
        if data['op'] == "fetch_track":
            ...
        # node
        elif data['op'] == "add_node":
            await self.add_node(data['data'])
        elif data['op'] == "remov_node":
            await self.remove_node(**data)
        # player
        elif data['op'] == "play":
            guild_id = int(data['guild_id'])
            query = data['query']
            requester = data['requester']
            await self.get_player(guild_id).play_fetch(query, requester)
        elif data['op'] == "skip":
            guild_id = int(data['guild_id'])

            await self.get_player(guild_id).stop()
        elif data['op'] == "skip_to":
            guild_id = int(data['guild_id'])
            index = int(data['index'])

            p = self.get_player(guild_id)
            p.queue.skip_to(index)

            p.ignore = True
            await p.stop()
        elif data['op'] == "stop":
            guild_id = int(data['guild_id'])

            p = self.get_player(guild_id)
            p.queue._queue.clear()
            await p.stop()

        elif data['op'] == 'destroy':
            guild_id = int(data['guild_id'])

            p = self.get_player(guild_id)
            p.queue.clear()
            await p.teardown()

        elif data['op'] == "loop":
            guild_id = int(data['guild_id'])
            loop = int(data['loop'])

            if loop not in (0, 1, 2):
                return
            self.get_player(guild_id).queue.loop = loop
        elif data['op'] == "seek":
            guild_id = int(data['guild_id'])
            seek = int(data['time'])

            await self.get_player(guild_id).seek(seek)
        elif data['op'] == "revind":
            guild_id = int(data['guild_id'])

            p = self.get_player(guild_id)

            p.queue.revert()
            p.ignore = True
            await p.stop()
        elif data['op'] == "remove":
            guild_id = int(data['guild_id'])
            index = int(data['index'])

            await self.get_player(guild_id).queue.remove(index)
        elif data['op'] == "pause":
            guild_id = int(data['guild_id'])
            pause = data['pause']

            await self.get_player(guild_id).set_pause(pause)
        elif data['op'] == "shuffle":
            guild_id = int(data['guild_id'])

            await self.get_player(guild_id).queue.shuffle()

        elif data['op'] == 'voice_update':
            d = data['data']
            await self.update_handler(d)

        # elif data['op'] == 'status':
        #     guild_id = int(data['guild_id'])
        #     p = self.get_player(guild_id)
        #     d = {}
        #     d['op'] = 'status'
        #     d['playing'] = p.is_playing
        #     d['current'] = True if p.current else False
        #     d['connected'] = p.is_connected
        #     d['paused'] = p.paused
        #     d['loop'] = p.queue.loop
        #     try:
        #         d['queue'] = len(p.queue)
        #     except Exception:
        #         d['queue'] = []
        #     d['node'] = {}
        #     d['node']['players'] = len(p.node.players)
        #     await self.ws.send_str(dumps(d))

        elif data['op'] == "move":
            guild_id = int(data['guild_id'])
            identifier = data.get('node', None)
            await self.get_player(guild_id).change_node(identifier)

    def close(self):
        self.closed = True
        self.listener.cancel()

    def resume(self, ws):
        self.ws = ws
        self.closed = False
        self.listener = asyncio.create_task(self.listen())

    async def listen(self):
        while not self.closed:
            msg = await self.ws.receive()
            if msg.type is aiohttp.WSMsgType.CLOSED:
                self.close()
            else:
                self.loop.create_task(self.process_data(msg))


if __name__ == '__main__':
    sys.stdout, sys.stderr, sys.stdin = Unbuffered(sys.stdout), Unbuffered(sys.stderr), Unbuffered(sys.stdin)
    routes = web.RouteTableDef()
    cache = Cache()


    @routes.get('/')
    async def handle_websocket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        user_id = int(request.headers['user_id'])
        try:
            print("resuming client connection from:", user_id)
            c = clients[user_id]
            c.resume(ws)
        except Exception:
            print("creating client connection from:", user_id)
            clients[user_id] = NyaLink(ws, user_id, cache)

        await asyncio.Future()


    @routes.get('/get_tracks')
    async def get_tracks(request):
        d = request.query
        user_id = int(d['user'])
        query = d.get('query', '')
        try:
            data = await request.json()
        except Exception:
            data = None

        node = clients[user_id].get_best_node()

        if query:
            res = (await node.get_raw_tracks(query))
        else:
            res = await asyncio.gather(*[node.get_raw_tracks(query) for query in data])

        return web.Response(text=dumps(res, indent=4))


    @routes.get('/data')
    async def return_player_data(request: aiohttp.web.Request):
        # TODO implement error messages
        try:
            d = request.query
            user_id = int(d['user'])
            guild_id = int(d['guild'])

            user: NyaLink = clients[user_id]

            player: Player = user.players[guild_id]
            return web.Response(text=dumps(player.json_data, indent=4))
        except Exception:
            return web.Response(text="{}")


    @routes.get('/status')
    async def status(request: aiohttp.web.Request):
        d = {}
        for client in clients.values():
            user_id = str(client.user_id)
            d[user_id] = {}
            d[user_id]['connected'] = not client.closed
            d[user_id]['nodes'] = {}
            for node in client.nodes.values():
                identifier = str(node.identifier)
                d[user_id]['nodes'][identifier] = {}
                d[user_id]['nodes'][identifier]['penalty'] = node.penalty
                d[user_id]['nodes'][identifier]['players'] = {}
                for player in node.players.values():
                    guild_id = str(player.guild_id)
                    d[user_id]['nodes'][identifier]['players'][guild_id] = {}
                    d[user_id]['nodes'][identifier]['players'][guild_id]['queue'] = len(player.queue)
                    d[user_id]['nodes'][identifier]['players'][guild_id]['playing'] = player.playing
                    d[user_id]['nodes'][identifier]['players'][guild_id]['loop'] = player.queue.loop

        return web.Response(text=dumps(d, indent=4))


    @routes.post('/play_fetch')
    async def play_fetch(request):
        d = request.query
        user_id = int(d['user'])
        guild_id = int(d['guild'])
        requester = int(d['requester'])
        query = d.get('query', None)
        data = await request.json()

        client: NyaLink = clients[user_id]
        player = client.get_player(guild_id)

        async def fetch_task():
            if query:
                await player.play_fetch(query, requester)
            else:
                n = 4
                chunks = [data[i * n:(i + 1) * n] for i in range((len(data) + n - 1) // n)]
                for chunk in chunks:
                    await asyncio.gather(*[player.play_fetch(query, requester) for query in chunk])

        asyncio.create_task(fetch_task())  # fetch all tracks in background so we can send fast response

        print("waiting for track")
        await player.queue.get()  # we wait for the first song and immanently send response
        return web.Response(text=dumps(player.json_data, indent=4))


    @routes.post('/play_data')
    async def play_data(request: aiohttp.web.Request):
        d = request.query
        user_id = int(d['user'])
        guild_id = int(d['guild'])
        requester = int(d['requester'])
        query = d.get('query', '')
        data = await request.json()

        client: NyaLink = clients[user_id]
        player = client.get_player(guild_id)

        for d in data:
            await player.play_data(query, requester, d)

        return web.Response(text=dumps(player.json_data, indent=4))


    @routes.get('/players')
    async def players(request: aiohttp.web.Request):
        d = request.query
        user_id = int(d['user'])

        client: NyaLink = clients[user_id]
        # {guild_id: playing}
        res = {}

        for p in client.players.values():
            res[p.guild_id] = p.channel_id

        print(res)
        return web.Response(text=dumps(res, indent=4))


    app = web.Application()
    app.router.add_routes(routes)

    web.run_app(app)
