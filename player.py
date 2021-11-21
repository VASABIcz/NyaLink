import time, re
#from node import Node
import asyncio
import collections
import itertools
import async_timeout
import random as r

URL_REG = re.compile(r'https?://(?:www\.)?.+')

class Old:
    def __init__(self, len):
        self.len = len
        self._queue = []

    def put(self, item):
        if len(self._queue) == self.len:
            del self._queue[-1]

        self._queue.insert(0, item)

    def get(self):
        return self._queue.pop(0)

class Que:
    """This custom queue is specifically made for wavelink so u shouldn't use it anywhere else"""

    def __init__(self):
        self._queue = []
        self._old = Old(5)

        self._loop = asyncio.get_event_loop()
        self.loop = 0  # 0 = no loop, 1 = loop one, 2 = loop

        self._getters = collections.deque()


    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return len(self._queue)

    @property
    def loop_emoji(self):
        if self.loop == 0:
            return ""
        elif self.loop == 1:
            return "🔂"
        else:
            return "🔁"

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        x1 = self._queue.pop(0)
        r.shuffle(self._queue)
        self._queue.insert(0, x1)


    def remove(self, index: int):
        del self._queue[index]

    def skip_to(self, index):
        self._queue = self._queue[index:] + self._queue[:index]

    def revert(self):
        try:
            self._queue.insert(0, self._old.get())
        except IndexError:
            ... # TODO smthing


    def _put(self, item):
        self._queue.append(item)

    def _get(self):
        return self._queue[0]

    def _consume(self):
        if self._queue:
            item = self._queue.pop(0)
            self._old.put(item)
            return item

    def empty(self):
        return not self._queue

    def _wakeup_next(self, waiters):
        while waiters:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break


    async def put(self, item):
        return self.put_nowait(item)


    def put_nowait(self, item):
        self._put(item)
        self._wakeup_next(self._getters)

    def get_nowait(self):
        if self.empty():
            raise Exception("random exc in que")
        return self._get()


    async def get(self):
        while self.empty():
            getter = self._loop.create_future()
            self._getters.append(getter)
            try:
                await getter
            except:
                getter.cancel()
                try:
                    self._getters.remove(getter)
                except ValueError:
                    pass
                if not self.empty() and not getter.cancelled():
                    self._wakeup_next(self._getters)
                raise

        return self.get_nowait()

    def consume(self):
        if self.loop == 0:
            self._consume()
        elif self.loop == 1:
            ...
        elif self.loop == 2:
            if self._queue:
                self._put(self._queue.pop(0))

class Track:
    __slots__ = ('id',
                 'info',
                 'query',
                 'title',
                 'identifier',
                 'ytid',
                 'length',
                 'duration',
                 'uri',
                 'author',
                 'is_stream',
                 'dead',
                 'thumb',
                 'requester_id')

    def __init__(self, id_, info: dict,requester_id, query: str = None):
        self.id = id_
        self.info = info
        self.query = query
        self.requester_id = requester_id

        self.title = info.get('title')
        self.identifier = info.get('identifier', '')
        self.ytid = self.identifier if re.match(r"^[a-zA-Z0-9_-]{11}$", self.identifier) else None
        self.length = info.get('length')
        self.duration = self.length
        self.uri = info.get('uri')
        self.author = info.get('author')

        self.is_stream = info.get('isStream')
        self.dead = False

        if self.ytid:
            self.thumb = f"https://img.youtube.com/vi/{self.ytid}/hqdefault.jpg"
        else:
            self.thumb = None

    def __str__(self):
        return self.title

    @property
    def is_dead(self):
        return self.dead

class Player:
    def __init__(self, guild_id, node):
        self.guild_id = guild_id
        self.node = node

        self.last_update = None
        self.last_position = None
        self.position_timestamp = None

        self._voice_state = {}
        self.voice_server = None

        self.volume = 100
        self.paused = False
        self.current = None
        self.channel_id = None

        self._new_track = False

        self.queue = Que()
        self.waiting = False
        self.ignore = False

    async def do_next(self) -> None:
        if self.is_playing or self.waiting:
            print("waiting")
            self.ignore = False
            return

        if not self.ignore:
            self.queue.consume()

        self.ignore = False
        try:
            self.waiting = True
            with async_timeout.timeout(5 * 60):
                track = await self.queue.get()
        except asyncio.TimeoutError:
            return await self.teardown()

        await self.play(track)
        self.waiting = False

    async def teardown(self):
        try:
            await self.destroy()
        except KeyError:
            pass

    async def magic_pause(self, pause=0.3):
        # this pause will magically make bot play again after moving to new channel
        await asyncio.sleep(pause)
        await self.set_pause(True)
        await asyncio.sleep(pause)
        await self.set_pause(False)

    async def on_track_stop(self):
        self.current = None
        await self.do_next()

    async def play_fetch(self, query, requester):
        if URL_REG.match(query):
            query = query
        else:
            query = f"ytsearch:{query}"
        tracks = await self.node.get_tracks(query, requester)
        print("get_tracks res:", tracks)
        if tracks:
            for track in tracks:
                await self.queue.put(track)
        else:
            ... # send error
        if not self.is_playing:
            print("do_next")
            self.ignore = True
            await self.do_next()

    async def play_data(self, query, requester, *tracks):
        if tracks:
            for track in tracks:
                await self.queue.put(Track(track['id'], track['data'], requester, query))#
        else:
            ... # send error

        if not self.is_playing:
            await self.do_next()

    @property
    def is_connected(self) -> bool:
        return self.channel_id is not None

    @property
    def is_playing(self) -> bool:
        return self.is_connected and self.current is not None

    @property
    def is_paused(self) -> bool:
        return self.paused

    @property
    def position(self):
        if not self.is_playing:
            return 0

        if not self.current:
            return 0

        if self.paused:
            return min(self.last_position, self.current.duration)

        difference = (time.time() * 1000) - self.last_update
        position = self.last_position + difference

        if position > self.current.duration:
            return 0

        return min(position, self.current.duration)

    async def update_state(self, state: dict) -> None:
        state = state['state']  #
        self.last_update = time.time() * 1000
        self.last_position = state.get('position', 0)
        self.position_timestamp = state.get('time', 0)

    async def play(self, track, *, replace: bool = True, start: int = 0, end: int = 0) -> None:
        if replace or not self.is_playing:
            self.last_update = 0
            self.last_position = 0
            self.position_timestamp = 0
            self.paused = False
        else:
            return

        no_replace = not replace

        if self.current:
            self._new_track = True

        self.current = track

        payload = {'op': 'play',
                   'guildId': str(self.guild_id),
                   'track': track.id,
                   'noReplace': no_replace,
                   'startTime': str(start)
                   }
        if end > 0:
            payload['endTime'] = str(end)

        await self.node.send(**payload)

    async def stop(self) -> None:
        await self.node.send(op='stop', guildId=str(self.guild_id))
        self.current = None

    async def destroy(self, *, force: bool = False) -> None:
        await self.stop()

        await self.node.send(op='destroy', guildId=str(self.guild_id))

        try:
            del self.node.players[self.guild_id]
        except KeyError:
            pass

    async def set_pause(self, pause: bool) -> None:
        await self.node.send(op='pause', guildId=str(self.guild_id), pause=pause)
        self.paused = pause

    async def set_volume(self, vol: int) -> None:
        self.volume = max(min(vol, 1000), 0)
        await self.node.send(op='volume', guildId=str(self.guild_id), volume=self.volume)

    async def seek(self, position: int = 0) -> None:
        await self.node.send(op='seek', guildId=str(self.guild_id), position=position)

    async def _dispatch_voice_update(self) -> None:
        if {'sessionId', 'event'} == self._voice_state.keys():
            await self.node.send(op='voiceUpdate', guildId=str(self.guild_id), **self._voice_state)

    async def _voice_server_update(self, data) -> None:
        self._voice_state.update({
            'event': data
        })

        # await self._dispatch_voice_update()
        if data != self.voice_server:
            print("voice server changed")
            await self._dispatch_voice_update()
            self.voice_server = data

    async def _voice_state_update(self, data) -> None:
        try:
            channel_id = int(data['channel_id'])
        except:
            channel_id = None

        if self.channel_id != channel_id:
            self._voice_state.update({
                'sessionId': data['session_id']
            })
            if self.channel_id and channel_id:
                print("MOVE")
                self.channel_id = channel_id
                await self._dispatch_voice_update()

                await self.magic_pause(0.5)
            elif self.channel_id and not channel_id:
                print("DISCONNECT")
                self._voice_state.clear()
                self.queue.clear()
                await self.teardown()

                self.channel_id = channel_id
                await self._dispatch_voice_update()
            else:
                print("JOIN")
                await self._dispatch_voice_update()
            self.channel_id = channel_id

        elif self._voice_state['sessionId'] != data['session_id']:
            print("VOICE SESSION CHANGE")
            self._voice_state.update({
                'sessionId': data['session_id']
            })
            await self._dispatch_voice_update()




        # if not channel_id:  # We're disconnecting
        #     print("disconnecting")
        #     self.channel_id = None
        #     self._voice_state.clear()
        #     self.queue.clear()
        #     await self.teardown()
        #     return
#
        # if self.channel_id != channel_id:
        #     print(self.channel_id, channel_id)
        #     print("DISPATCHEEEEEEEEEEEEEE")
        #     await self._dispatch_voice_update()
#
        # if self.channel_id and self.channel_id != channel_id:
        #     await self.set_pause(True)
        #     await asyncio.sleep(0.3)
        #     await self.set_pause(False)
#
        # self.channel_id = channel_id



    # @property
    # def equalizer(self):
    #     return self._equalizer

    # @property
    # def eq(self):
    #     return self.equalizer
    # async def hook(self, event) -> None:
    #     if isinstance(event, TrackEnd) and not self._new_track:
    #         self.current = None
    #     self._new_track = False

    # async def _voice_server_update(self, data) -> None:
    #   self._voice_state.update({
    #       'event': data
    #   })
    #   await self._dispatch_voice_update()
    #   async def _voice_state_update(self, data) -> None:
    #     self._voice_state.update({
    #         'sessionId': data['session_id']
    #     })
    #     channel_id = data['channel_id']
    #     if not channel_id:  # We're disconnecting
    #         self.channel_id = None
    #         self._voice_state.clear()
    #         return
    #     self.channel_id = int(channel_id)
    #     await self._dispatch_voice_update()
    #     async def _dispatch_voice_update(self) -> None:
    #       if {'sessionId', 'event'} == self._voice_state.keys():
    #           await self.node.send(op='voiceUpdate', guildId=str(self.guild_id), **self._voice_state)

    # async def set_eq(self, equalizer: Equalizer) -> None:
    #     await self.node.send(op='equalizer', guildId=str(self.guild_id), bands=equalizer.eq)
    #     self._equalizer = equalizer

    # TODO implement
    # async def change_node(self, identifier: str = None) -> None:
    #     client = self.node._client  #
    #     if identifier:
    #         node = client.get_node(identifier)  #
    #         if not node:
    #             raise WavelinkException(f'No Nodes matching identifier:: {identifier}')
    #         elif node == self.node:
    #             raise WavelinkException('Node identifiers must not be the same while changing.')
    #     else:
    #         self.node.close()
    #         node = None #
    #         if self.node.region:
    #             node = client.get_node_by_region(self.node.region)  #
    #         if not node and self.node.shard_id:
    #             node = client.get_node_by_shard(self.node.shard_id) #
    #         if not node:
    #             node = client.get_best_node()   #
    #         if not node:
    #             self.node.open()
    #             raise WavelinkException('No Nodes available for changeover.')   #
    #     self.node.open()    #
    #     old = self.node
    #     del old.players[self.guild_id]
    #     await old.send(op='destroy', guildId=str(self.guild_id))   #
    #     self.node = node
    #     self.node.players[int(self.guild_id)] = self    #
    #     if self._voice_state:
    #         await self._dispatch_voice_update() #
    #     if self.current:
    #         await self.node.send(op='play', guildId=str(self.guild_id), track=self.current.id, startTime=int(self.position))
    #         self.last_update = time.time() * 1000   #
    #         if self.paused:
    #             await self.node.send(op='pause', guildId=str(self.guild_id), pause=self.paused)    #
    #     if self.volume != 100:
    #         await self.node.send(op='volume', guildId=str(self.guild_id), volume=self.volume)