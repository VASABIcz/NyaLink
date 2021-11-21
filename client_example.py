import asyncio

from discord.ext import commands
import aiohttp
import discord
from json import dumps


class NyaLink:
    def __init__(self, bot, uri, session=None, loop=None):
        self.bot = bot
        self.uri = uri
        self.session = session or aiohttp.ClientSession()
        self.loop = loop or asyncio.get_event_loop()

        self.closed = False

        self.loop.create_task(self.connect())
        self.task = None

    async def setup(self):
        data = {'host': 'lavalink',
                'port': 2333,
                'rest_uri': 'http://lavalink:2333',
                'password': 'youshallnotpass',
                'identifier': 'MAIN',
                'region': 'europe'}
        print("adding node")
        await self.add_node(data)

    @property
    def headers(self):
        return {"user_id": str(self.bot.user.id)}

    @property
    def is_connected(self) -> bool:
        return self.ws is not None and not self.ws.closed

    async def connect(self):
        await self.bot.wait_until_ready()
        print(self.headers)
        self.ws = await self.session.ws_connect(self.uri, headers=self.headers)
        self.bot.add_listener(self.voice_update, 'on_socket_response')
        print("connected")
        self.closed = False

        if not self.task:
            self.task = self.loop.create_task(self.listener())
        self.loop.create_task(self.setup())

    async def listener(self):
        while True:
            msg = await self.ws.receive()
            if msg.type is aiohttp.WSMsgType.CLOSED:
                self.closed = True
                await asyncio.sleep(5)
                if not self.is_connected:
                    self.loop.create_task(self.connect())
            else:
                print(msg.data)
                ...
                # TODO implement

    async def send(self, **data):
        if self.is_connected:
            data['user_id'] = self.bot.user.id
            data_str = dumps(data)
            if isinstance(data_str, bytes):
                data_str = data_str.decode('utf-8')
            await self.ws.send_str(data_str)


    async def play(self, guild_id, query, requester):
        await self.send(op='play', guild_id=guild_id, query=query, requester=requester)

    async def skip(self, guild_id):
        await self.send(op='skip', guild_id=guild_id)

    async def skip_to(self, guild_id, index):
        await self.send(op='skip_to', guild_id=guild_id, index=index)

    async def stop(self, guild_id):
        await self.send(op='stop', guild_id=guild_id)

    async def loop(self,guild_id, loop):
        await self.send(op='loop', guild_id=guild_id, loop=loop)

    async def seek(self, guild_id, time):
        await self.send(op='seek', guild_id=guild_id, time=time)

    async def revind(self, guild_id):
        await self.send(op='revind', guild_id=guild_id)

    async def remove(self, guild_id, index):
        await self.send(op='remove', guild_id=guild_id, index=index)

    async def pause(self, guild_id, pause):
        await self.send(op='pause', guild_id=guild_id, pause=pause)

    async def shuffle(self, guild_id):
        await self.send(op='shuffle', guild_id=guild_id)

    async def status(self, guild_id):
        await self.send(op='status', guild_id=guild_id)

    async def destroy(self, guild_id):
        await self.send(op='destroy', guild_id=guild_id)

    async def voice_update(self, data):
        # TODO ignore mute/def client and server side
        if not data or 't' not in data:
            return

        if data['t'] in ('VOICE_SERVER_UPDATE', 'VOICE_STATE_UPDATE'):
            await self.send(op='voice_update', data=data)

    async def add_node(self, data):
        await self.send(op='add_node', data=data)

    async def magic_pause(self, guild_id):
        await self.pause(guild_id, True)
        await asyncio.sleep(0.3)
        await self.pause(guild_id, False)



class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.link = NyaLink(self.bot, uri='ws://nya_link:8080', session=self.bot.session, loop=self.bot.loop)


    def _get_shard_socket(self, shard_id: int):
        if isinstance(self.bot, commands.AutoShardedBot):
            try:
                return self.bot.shards[shard_id].ws
            except AttributeError:
                return self.bot.shards[shard_id]._parent.ws

        if self.bot.shard_id is None or self.bot.shard_id == shard_id:
            return self.bot.ws


    @commands.command()
    async def play(self, ctx, query):
        await self.link.play(ctx.guild.id, query, ctx.author.id)

    @commands.command()
    async def skip(self, ctx):
        await self.link.skip(ctx.guild.id)

    @commands.command()
    async def loop(self, ctx):
        await self.link.loop(ctx.guild.id, 2)

    @commands.command()
    async def noloop(self, ctx):
        await self.link.loop(ctx.guild.id, 0)

    @commands.command()
    async def loopone(self, ctx):
        await self.link.loop(ctx.guild.id, 1)

    @commands.command()
    async def resume(self, ctx):
        await self.link.pause(ctx.guild.id, False)

    @commands.command()
    async def pause(self, ctx):
        await self.link.pause(ctx.guild.id, True)

    @commands.command()
    async def disconnect(self, ctx):
        await self._get_shard_socket(ctx.guild.shard_id).voice_state(ctx.guild.id, None)
        await self.link.stop(ctx.guild.id)

    @commands.command()
    async def stop(self, ctx):
        await self.link.stop(ctx.guild.id)

    @commands.command()
    async def status(self, ctx):
        await self.link.status(ctx.guild.id)

    @play.before_invoke
    async def _connect(self, ctx):
        try:
            await ctx.invoke(self.connect_)
        except:
            pass

    @commands.command(name='connect', aliases=['join', 'c'])
    async def connect_(self, ctx, *, channel: discord.VoiceChannel = None):
        if not channel:
            try:
                channel = ctx.author.voice.channel
            except AttributeError:
                raise commands.CommandError

        await ctx.send(f'Connecting to **`{channel.name}`**')
        await self._get_shard_socket(ctx.guild.shard_id).voice_state(ctx.guild.id, str(channel.id), self_deaf=False)

def setup(bot):
    bot.add_cog(Link(bot))
