import asyncio
import collections
import itertools
import random as r
import time

import async_timeout


class Track:
    __slots__ = ('id',
                 'info',
                 'query',
                 'title',
                 'identifier',
                 'length',
                 'duration',
                 'requester_id')

    def __init__(self, id_, info: dict, requester_id, query: str = None):
        self.id = id_
        self.info = info
        self.query = query
        self.requester_id = requester_id

        self.title = info.get('title')
        self.identifier = info.get('identifier', '')
        self.length = info.get('length')
        self.duration = self.length

    def __str__(self):
        return self.title

    def __repr__(self):
        return f"<{self.__class__}: {str(self)}>"


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
            return

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

    def _wakeup_next(self):
        while self._getters:
            waiter = self._getters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break

    def _wakeup_all(self):
        while self._getters:
            waiter = self._getters.popleft()
            if not waiter.done():
                waiter.set_result(None)

    async def put(self, item):
        return self.put_nowait(item)

    def put_nowait(self, item):
        self._put(item)
        self._wakeup_all()

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
                    self._wakeup_all()
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


class Player:
    def __init__(self, guild_id, node):
        self.node = node
        self.guild_id = guild_id

        self.queue = Que()
        self.next = asyncio.Event()
        self.closed = False
        self.task = asyncio.create_task(self.core())
        self.ignore = False
        self.voice_state = {}

        self.channel_id = None
        self.current = None
        self.paused = False
        self.deaf = None
        self.mute = None
        self.volume = 100

        self.last_update = None
        self.last_position = None

    @property
    def playing(self):
        return self.channel_id and self.current is not None

    @property
    async def connected(self):
        return not not self.channel_id

    @property
    def position(self):
        if not self.playing:
            return 0

        if self.paused:
            return min(self.last_position, self.current.duration)

        difference = (time.time() * 1000) - self.last_update
        position = self.last_position + difference

        if position > self.current.duration:
            return 0

        return min(position, self.current.duration)

    @property
    def json_data(self) -> dict:
        res = {}
        res['queue'] = [{'track': x.info, 'requester': x.requester_id} for x in self.queue]
        res['paused'] = self.paused
        res['loop'] = self.queue.loop
        res['volume'] = self.volume
        res['channel'] = self.channel_id
        res['position'] = self.position
        res['playing'] = self.playing

        return res

    async def dispatch_next(self):
        self.next.set()
        self.next.clear()

    async def core(self):
        while not self.closed:
            # wait for track
            try:
                async with async_timeout.timeout(5 * 60):
                    track = await self.queue.get()
                    print("nuut", self.next)
            except asyncio.TimeoutError:
                await self.destroy()

            await self.play(track)

            # wait for end
            await self.next.wait()
            self.next.clear()

            # consume
            if not self.ignore:
                print("consuming")
                self.queue.consume()
                self.ignore = False

    def on_track_stop(self):
        self.next.set()

    async def on_track_start(self):
        ...

    async def on_voice_state(self, data):
        print("HUH", data)
        self.voice_state.update({
            'sessionId': data['session_id']
        })

        try:
            channel_id = int(data['channel_id'])
        except:
            channel_id = None

        # self.channel_id = channel_id
        # return await self.dispatch_voice()
        # I DONT FUCKING KNOW WHATS HAPPENING JUST WORK PLZ

        if channel_id != self.channel_id:
            print("voice channel change")
            if channel_id and self.channel_id:
                await self.magic_pause()
                await self.dispatch_voice()
            elif self.channel_id and not channel_id:
                await self.destroy()
            else:
                await self.dispatch_voice()
            self.channel_id = channel_id
        elif data['mute'] == self.mute and data['deaf'] == self.deaf:
            print("idk")
            # ignore mute/deaf
            await self.dispatch_voice()
        elif not self.playing:
            print("voice playing change")
            await self.dispatch_voice()
        elif data['session_id'] != self.voice_state['sessionId']:
            print("voice session change")
            # to be sure
            await self.dispatch_voice()
        else:
            print("didnt sent voice state")

        self.deaf = data['deaf']
        self.mute = data['mute']

    async def on_voice_server(self, data):
        self.voice_state.update({
            'event': data
        })

        await self.dispatch_voice()

    async def play_data(self):
        # TODO implement
        ...

    async def play_fetch(self, query, requester_id, cache=True):
        res = await self.node.get_tracks(query, requester_id, cache)
        for track in res:
            await self.queue.put(track)

    def update_state(self, state: dict) -> None:
        state = state['state']

        self.last_update = time.time() * 1000
        self.last_position = state.get('position', 0)

    async def dispatch_voice(self):
        print("before dispatch", self.voice_state)
        if {'sessionId', 'event'} == self.voice_state.keys():
            # print("dispatching", self.voice_state)
            await self.node.send(op='voiceUpdate', guildId=str(self.guild_id), **self.voice_state)

    async def destroy(self):
        await self.stop()

        try:
            del self.node.players[self.guild_id]
        except KeyError:
            pass

        self.closed = True
        self.task.cancel()

    async def stop(self):
        await self.node.send(op='stop', guildId=str(self.guild_id))
        self.current = None

    async def play(self, track):
        self.current = track

        self.last_update = 0
        self.last_position = 0
        self.paused = False

        payload = {'op': 'play',
                   'guildId': str(self.guild_id),
                   'track': track.id,
                   'noReplace': False,
                   'startTime': '0'
                   }

        await self.node.send(**payload)

    async def set_pause(self, pause: bool):
        await self.node.send(op='pause', guildId=str(self.guild_id), pause=pause)
        self.paused = pause

    async def seek(self, position):
        await self.node.send(op='seek', guildId=str(self.guild_id), position=position)

    async def magic_pause(self):
        await self.set_pause(True)
        await asyncio.sleep(0.3)
        await self.set_pause(False)

    async def change_node(self, identifier: str = None) -> None:
        client = self.node.client
        print(f"changing node for:", self.guild_id)
        # looks like it works cant confirm lava.link had some load issues
        # TODO spin up more lavalink instances and test it done

        if identifier:
            node = client.get_node(identifier)
            if not node:
                print("node not found")
                return
            elif node == self.node:
                print("node is is same as current node")
                return
        else:
            self.node.close()
            node = client.get_best_node()
            self.node.open()
            print(node)
            if not node:
                print("no other node to move players")
                return
        old = self.node
        del old.players[self.guild_id]
        await old.send(op='destroy', guildId=str(self.guild_id))
        self.node = node
        self.node.players[self.guild_id] = self
        if self.voice_state:
            await self.dispatch_voice()
        if self.current:
            await self.node.send(op='play', guildId=str(self.guild_id), track=self.current.id,
                                 startTime=int(self.position))
            self.last_update = time.time() * 1000
            if self.paused:
                await self.node.send(op='pause', guildId=str(self.guild_id), pause=self.paused)
        if self.volume != 100:
            await self.node.send(op='volume', guildId=str(self.guild_id), volume=self.volume)
