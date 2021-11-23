import asyncio

from aiohttp import web
import aiohttp
from node import Node
from player import Player
import sys
from json import loads, dumps

# TODO rest api (get_tracks, stats, player)
# TODO add node for all cients
# TODO fix small lag after reconnect prop. impossible without modifing lavalink/lavaplayer
# TODO weighted track cache
# TODO nodes var should be global so all clientscan acces all nodes
# TODO make better load ballancing prop. use stats
# TODO on node failure transfer players to new nodes

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
    def __init__(self, ws, user_id):
        self.sesion = aiohttp.ClientSession()
        self.loop = asyncio.get_event_loop()
        self.ws: web.WebSocketResponse = ws
        self.user_id = user_id

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
                player = self.players[guild_id]
            except KeyError:
                pass
            else:
                print("player vs", player._voice_state)
                await player._voice_server_update(data['d'])

        elif data['t'] == 'VOICE_STATE_UPDATE':
            if int(data['d']['user_id']) != int(self.user_id):
                return

            guild_id = int(data['d']['guild_id'])
            try:
                player = self.players[guild_id]
            except KeyError:
                pass
            else:
                print("player vs", player._voice_state)
                await player._voice_state_update(data['d'])

    def get_player(self, guild_id: int, *, cls=None, node_id=None, **kwargs):
        players = self.players

        try:
            player = players[guild_id]
        except KeyError:
            pass
        else:
            return player

        if not cls:
            cls = Player

        if node_id:
            node = self.get_node(identifier=node_id)

            player = cls(node, **kwargs)
            node.players[guild_id] = player

            return player

        node = self.get_best_node()

        player = cls(guild_id, node)
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
        session = self.sesion
        rest_uri = data['rest_uri']
        password = data['password']
        region = data.get('region')
        shard_id = data.get('shard_id', None)
        secure = data.get('secure', False)

        n = Node(host=host, port=port, user_id=user_id, client=client, session=session, rest_uri=rest_uri, password=password, region=region, identifier=identifier, shard_id=shard_id, secure=secure)
        await n.connect()
        self.nodes[identifier] = n

    async def remove_node(self, **data):
        identifier = data['identifier']
        force = data.get("force", False)
        self.nodes[identifier].destroy(force)

    async def process_data(self, msg):
        print(f"procesing: {msg.data}")
        data = loads(msg.data)
        # client
        if data['op'] == "fetch_track":
            ...
        # node
        elif data['op'] == "add_node":
            # TODO for clients add node
            await self.add_node(data['data'])
        elif data['op'] == "remov_node":
            ...
        # player
        elif data['op'] == "play":
            guild_id= int(data['guild_id'])
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

            if not loop in (0, 1, 2):
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

        elif data['op'] == 'status':
            guild_id = int(data['guild_id'])

            p = self.get_player(guild_id)
            d = {}
            d['op'] = 'status'
            d['playing'] = p.is_playing
            d['current'] = True if p.current else False
            d['connected'] = p.is_connected
            d['paused'] = p.paused
            d['loop'] = p.queue.loop
            try:
                d['queue'] = len(p.queue)
            except Exception:
                d['queue'] = []
            d['node'] = {}
            d['node']['players'] = len(p.node.players)

            await self.ws.send_str(dumps(d))

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


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    user_id = int(request.headers['user_id'])
    try:
        print("resuming client connection from:", user_id)
        c = clients[user_id]
        c.resume(ws)
    except Exception:
        print("creating client connection from:", user_id)
        clients[user_id] = NyaLink(ws, user_id)
    await asyncio.Future()

app = web.Application()
app.add_routes([web.get('/', websocket_handler)])
# e

sys.stdout, sys.stderr, sys.stdin = Unbuffered(sys.stdout), Unbuffered(sys.stderr), Unbuffered(sys.stdin)

web.run_app(app)
