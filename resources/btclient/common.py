'''
Created on May 3, 2015

@author: ivan
'''
import os
from collections import deque
import logging
import copy
import threading
import traceback
import shutil
import urlparse
from StringIO import StringIO

from hachoir_metadata import extractMetadata
from hachoir_parser import guessParser
import hachoir_core.config as hachoir_config
from hachoir_core.stream.input import InputIOStream

logger = logging.getLogger('common')
hachoir_config.quiet = True


def enum(**enums):
    return type('Enum', (), enums)


TerminalColor = enum(default='\033[39m', green='\033[32m', red='\033[31m', yellow='\033[33m')


def get_duration(fn):
    # We need to provide just begining of file otherwise hachoir might try to read all file
    with open(fn, 'rb') as f:
        s = StringIO(f.read(1024 * 64))
    p = guessParser(InputIOStream(s, filename=unicode(fn), tags=[]))
    m = extractMetadata(p)
    if m:
        return m.getItem('duration', 0) and m.getItem('duration', 0).value


def debug_fn(fn):
    def _fn(*args, **kwargs):
        print "Entering %s, thread %s" % (fn.__name__, threading.current_thread().name)
        traceback.print_stack()
        ret = fn(*args, **kwargs)
        print "Leaving %s, thread %s" % (fn.__name__, threading.current_thread().name)
        return ret

    return _fn


class Hasher(threading.Thread):
    def __init__(self, btfile, hash_cb):
        threading.Thread.__init__(self, name="Hasher")
        if btfile is None:
            raise ValueError('BTFile is None!')
        self._btfile = btfile
        self._hash_cb = hash_cb
        self.hash = None
        self.daemon = True
        self.start()

    def run(self):
        with self._btfile.create_cursor() as c:
            filehash = OpenSubtitles.hash_file(c, self._btfile.size)
            self.hash = filehash
            self._hash_cb(filehash)


class OpenSubtitles(object):
    USER_AGENT = 'BTClient'

    def __init__(self, lang, user='', pwd=''):
        self._lang = lang
        self._token = None
        self._user = user
        self._pwd = pwd

    @staticmethod
    def hash_file(f, filesize):
        import struct

        longlongformat = '<q'  # little-endian long long
        bytesize = struct.calcsize(longlongformat)

        hash = filesize  # @ReservedAssignment
        if filesize < 65536 * 2:
            raise ValueError("SizeError")

        for _x in range(65536 / bytesize):
            buffer = f.read(bytesize)  # @ReservedAssignment
            (l_value,) = struct.unpack(longlongformat, buffer)
            hash += l_value
            hash = hash & 0xFFFFFFFFFFFFFFFF  # to remain as 64bit number  @ReservedAssignment

        f.seek(max(0, filesize - 65536))
        for _x in range(65536 / bytesize):
            buffer = f.read(bytesize)  # @ReservedAssignment
            (l_value,) = struct.unpack(longlongformat, buffer)
            hash += l_value
            hash = hash & 0xFFFFFFFFFFFFFFFF  # @ReservedAssignment
        returnedhash = "%016x" % hash
        return returnedhash

class BaseMonitor(threading.Thread):
    def __init__(self, client, name):
        threading.Thread.__init__(self, name=name)
        self.daemon = True
        self._listeners = []
        self._lock = threading.Lock()
        self._wait_event = threading.Event()
        self._running = True
        self._client = client
        self._ses = None

    def stop(self):
        self._running = False
        self._wait_event.set()

    def add_listener(self, cb):
        with self._lock:
            if not cb in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb):
        with self._lock:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

    def remove_all_listeners(self):
        with self._lock:
            self._listeners = []


class BaseClient(object):
    class Monitor(BaseMonitor):
        def __init__(self, client):
            super(BaseClient.Monitor, self).__init__(client, name="Status Monitor")
            self._client = client

        def run(self):
            while (self._running):
                s = self._client.status
                with self._lock:
                    for cb in self._listeners:
                        cb(s, client=self._client)
                self._wait_event.wait(1.0)

    def __init__(self, path_to_store, args=None):
        self._base_path = path_to_store
        self._ready = False
        self._file = None
        self._on_ready_action = None
        self._monitor = BaseClient.Monitor(self)
        if not args or not args.quiet:
            self.add_monitor_listener(self.print_status)
        self._delete_on_close = True if args and args.delete_on_finish else False

    def _on_file_ready(self, filehash):
        #self._file.filehash = filehash
        self._ready = True
        if self._on_ready_action:
            self._on_ready_action(self._file, self.is_file_complete)

    @property
    def status(self):
        raise NotImplementedError()

    def get_normalized_status(self):
        s = self.status
        return {'source_type': 'base',
                'state': s.state,
                'downloaded': s.downloaded,
                'total_size': s.total_size,
                'download_rate': s.download_rate,
                'desired_rate': s.desired_rate,
                'progress': s.progress,
                'piece_size': self._file.piece_size if self._file else 0
                }

    @property
    def file(self):
        return self._file

    def set_on_file_ready(self, action):
        self._on_ready_action = action

    @property
    def is_file_ready(self):
        return self._ready

    def print_status(self, s, client):
        raise NotImplementedError()

    @property
    def is_file_complete(self):
        raise NotImplementedError()

    def start_url(self, uri):
        raise NotImplementedError()

    def close(self):
        if self._cache:
            self._cache.close()
        if self._delete_on_close and self._file:
            self._file.remove()

    @property
    def unique_file_id(self):
        raise NotImplementedError()

    def update_play_time(self, playtime):
        self._cache.play_position(self.unique_file_id, playtime)

    @property
    def last_play_time(self):
        return self._cache.get_last_position(self.unique_file_id)

    def add_monitor_listener(self, cb):
        self._monitor.add_listener(cb)

    def remove_monitor_listener(self, cb):
        self._monitor.remove_listener(cb)

    def stop(self):
        self._monitor.stop()
        self._monitor.join()


class PieceCache(object):
    TIMEOUT = 30
    size = 5

    def __init__(self, btfile):
        # self._btfile=btfile
        self._cache = [None] * self.size
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._cache_first = btfile.first_piece
        self._piece_size = btfile.piece_size
        self._map_offset = btfile.map_piece
        self._file_size = btfile.size
        self._last_piece = btfile.last_piece
        self._request_piece = btfile.prioritize_piece
        self._btfile = btfile

    def clone(self):
        c = PieceCache(self._btfile)
        with self._lock:
            c._cache = copy.copy(self._cache)
            c._cache_first = self._cache_first
        return c

    def fill_cache(self, first):
        to_request = []
        with self._lock:
            diff = first - self._cache_first
            if diff > 0:
                for i in xrange(self.size):
                    if i + diff < self.size:
                        self._cache[i] = self._cache[i + diff]
                    else:
                        self._cache[i] = None

            elif diff < 0:
                for i in xrange(self.size - 1, -1, -1):
                    if i + diff >= 0:
                        self._cache[i] = self._cache[i + diff]
                    else:
                        self._cache[i] = None

            self._cache_first = first
            self._event.clear()
            for i in xrange(self.size):
                if self._cache[i] is None and (self._cache_first + i) <= self._last_piece:
                    to_request.append((self._cache_first + i, i))
        for args in to_request:
            self._request_piece(*args)

    def add_piece(self, n, data):
        with self._lock:
            i = n - self._cache_first
            if i >= 0 and i < self.size:
                self._cache[i] = data
                if i == 0:
                    self._event.set()

    def has_piece(self, n):
        with self._lock:
            i = n - self._cache_first
            if i >= 0 and i < self.size:
                return not (self._cache[i] is None)

    def _wait_piece(self, pc_no):
        while not self.has_piece(pc_no):
            self.fill_cache(pc_no)
            # self._event.clear()
            logger.debug('Waiting for piece %d' % pc_no)
            self._event.wait(self.TIMEOUT)

    def _get_piece(self, n):
        with self._lock:
            i = n - self._cache_first
            if i < 0 or i > self.size:
                raise ValueError('index of of scope of current cache')
            return self._cache[i]

    def get_piece(self, n):
        self._wait_piece(n)
        return self._get_piece(n)

    def read(self, offset, size):
        size = min(size, self._file_size - offset)
        if not size:
            return

        pc_no, ofs = self._map_offset(offset)
        data = self.get_piece(pc_no)
        pc_size = self._piece_size - ofs
        if pc_size > size:
            return data[ofs: ofs + size]
        else:
            pieces = [data[ofs:self._piece_size]]
            remains = size - pc_size
            new_head = pc_no + 1
            while remains and self.has_piece(new_head):
                sz = min(remains, self._piece_size)
                data = self.get_piece(new_head)
                pieces.append(data[:sz])
                remains -= sz
                if remains:
                    new_head += 1
            self.fill_cache(new_head)
            return ''.join(pieces)


class BTCursor(object):
    def __init__(self, btfile):
        self._btfile = btfile
        self._pos = 0
        self._cache = PieceCache(btfile)

    def clone(self):
        c = BTCursor(self._btfile)
        c._cache = self._cache.clone()
        return c

    def close(self):
        self._btfile.remove_cursor(self)

    def read(self, n=None):
        sz = self._btfile.size - self._pos
        if not n:
            n = sz
        else:
            n = min(n, sz)
        res = self._cache.read(self._pos, n)
        if res:
            self._pos += len(res)
        return res

    def seek(self, n):
        if n > self._btfile.size:
            n = self._btfile.size
            # raise ValueError('Seeking beyond file size')
        elif n < 0:
            raise ValueError('Seeking negative')
        self._pos = n

    def tell(self):
        return self._pos

    def update_piece(self, n, data):
        self._cache.add_piece(n, data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class AbstractFile(object):
    def __init__(self, path, base, size, piece_size):
        self._base = base
        self.size = size
        self.path = path
        self.piece_size = piece_size
        self.offset = 0
        self._full_path = os.path.join(base, path)
        self._cursors = []
        self._cursors_history = deque(maxlen=3)
        self._lock = threading.Lock()
        self.first_piece = 0
        self.last_piece = self.first_piece + (max(size - 1, 0)) // piece_size

        self._rate = None
        self._piece_duration = None

    def add_cursor(self, c):
        with self._lock:
            self._cursors.append(c)

    def remove_cursor(self, c):
        with self._lock:
            self._cursors.remove(c)
            self._cursors_history.appendleft(c)

    def create_cursor(self, offset=None):
        c = None
        if offset is not None:
            with self._lock:
                for e in reversed(self._cursors):
                    if abs(e.tell() - offset) < self.piece_size:
                        c = e.clone()
                        logger.debug('Cloning existing cursor')
                        break
            if not c:
                with self._lock:
                    for e in reversed(self._cursors_history):
                        if abs(e.tell() - offset) < self.piece_size:
                            c = e
                            logger.debug('Reusing previous cursor')
        if not c:
            c = BTCursor(self)
        self.add_cursor(c)
        if offset:
            c.seek(offset)
        return c

    def map_piece(self, ofs):
        return self.first_piece + (ofs + self.offset) // self.piece_size, \
               (ofs + self.offset) % self.piece_size

    def prioritize_piece(self, piece, idx):
        raise NotImplementedError()

    @property
    def full_path(self):
        return self._full_path

    def close(self):
        pass

    def remove(self):
        dirs = self.path.split(os.sep)
        if len(dirs) > 1:
            shutil.rmtree(os.path.join(self._base, dirs[0]), ignore_errors=True)
        else:
            os.unlink(self._full_path)

    def update_piece(self, n, data):
        for c in self._cursors:
            c.update_piece(n, data)

    @property
    def duration(self):
        if not hasattr(self, '_duration'):
            self._duration = get_duration(self._full_path) if os.path.exists(self._full_path) else 0
        return self._duration or 0

    @property
    def piece_duration_ms(self):
        if not self._piece_duration:
            if self.byte_rate:
                self._piece_duration = self.piece_size / self.byte_rate / 1000

        return self._piece_duration

    @property
    def byte_rate(self):
        if not self._rate:
            d = self.duration
            if d:
                if hasattr(d, 'total_seconds'):
                    total_seconds=d.total_seconds()
                else:
                    total_seconds=(d.microseconds + (d.seconds + d.days * 24 * 3600) * 10**6) / 10**6
                self._rate = self.size / total_seconds
        return self._rate

    def __str__(self):
        return self.path


class Resolver(object):
    URL_PATTERN = None
    SPEED_LIMIT = None  # kB/s
    THREADS = 4

    def __init__(self, loader):
        self._client = loader

    def resolve(self, url):
        return url

    @staticmethod
    def url_to_file(uri):
        path = urlparse.urlsplit(uri)[2]
        if path.startswith('/'):
            path = path[1:]
        return path
