import bisect

class Cache:
    """
    Limited cache with weights.
    If limit is exceeded item with least value is replaced with new one
    """
    def __init__(self, limit=10_000):
        self.limit = limit
        self.store = {}
        self.index_key = []
        self.index_value = []

    def __repr__(self):
        return f"{self.store} | {self.index_value} | {self.index_key}"

    def put(self, key, value):
        if key in self.store: # update
            i = self.index_value.index(key)
            # i = sorting position
            if i != len(self.index_key)-1 and self.index_key[i]+1 >= self.index_key[i+1]: # check if is not the biggest and that change woud do something
                n = bisect.bisect_right(self.index_key, self.index_key[i]+1)

                v = self.index_key.pop(i)
                self.index_key.insert(n, v+1)

                v = self.index_value.pop(i)
                self.index_value.insert(n, v)
            else:

                self.index_key[i] += 1
        else: # insert
            if self.limit == len(self.store):
                del self.index_key[0]
                v = self.index_value.pop(0)
                del self.store[v]

            self.store[key] = value

            ie = bisect.bisect_right(self.index_key, 0)
            self.index_key.insert(ie, 0)
            self.index_value.insert(ie, key)


    def get(self, key):
        if key in self.store:
            i = self.index_value.index(key)
            # i = sorting position
            if i != len(self.index_key)-1 and self.index_key[i]+1 >= self.index_key[i+1]: # check if is not the biggest and that change woud do something
                n = bisect.bisect_right(self.index_key, self.index_key[i]+1)

                value = self.index_key.pop(i)
                self.index_key.insert(n, value+1)

                value = self.index_value.pop(i)
                self.index_value.insert(n, value)
            else:
                self.index_key[i] += 1
            return self.store[key]
        return None

