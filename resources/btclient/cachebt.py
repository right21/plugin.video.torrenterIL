'''
Created on Apr 28, 2015

@author: ivan
'''
import os.path
import shelve
import re
import logging
import base64

logger = logging.getLogger('cache')


class CacheBT(object):
    CACHE_DIR = '.cache'

    def __init__(self, path, lt):
        if not os.path.isdir(path):
            raise ValueError('Invalid base directory')
        self.path = os.path.join(path, CacheBT.CACHE_DIR)
        if not os.path.isdir(self.path):
            os.mkdir(self.path)
        self._index_path = os.path.join(self.path, 'index')
        self._index = shelve.open(self._index_path)
        self._last_pos_path = os.path.join(self.path, 'last_position')
        self._last_pos = shelve.open(self._last_pos_path)
        self.lt=lt

    def save(self, url, info_hash):
        self._index[url] = info_hash
        self._index.sync()

    def close(self):
        self._index.close()
        self._last_pos.close()

    def _tname(self, info_hash):
        return os.path.join(self.path, info_hash.upper() + '.torrent')

    def _rname(self, info_hash):
        return os.path.join(self.path, info_hash.upper() + '.resume')

    def save_resume(self, info_hash, data):
        with open(self._rname(info_hash), 'wb') as f:
            f.write(data)

    def get_resume(self, url=None, info_hash=None):
        if url:
            info_hash = self._index.get(url)
        if not info_hash:
            return
        rname = self._rname(info_hash)
        if os.access(rname, os.R_OK):
            with open(rname, 'rb') as f:
                return f.read()

    def file_complete(self, torrent, url=None):
        info_hash = str(torrent.info_hash())
        nt = self.lt.create_torrent(torrent)
        tname = self._tname(info_hash)
        with open(tname, 'wb') as f:
            f.write(self.lt.bencode(nt.generate()))
        if url:
            self.save(url, info_hash)

    def get_torrent(self, url=None, info_hash=None):
        if url:
            info_hash = self._index.get(url)
        if not info_hash:
            return
        tname = self._tname(info_hash)
        if os.access(tname, os.R_OK):
            logger.debug('Torrent is cached')
            return tname

    magnet_re = re.compile('xt=urn:btih:([0-9A-Za-z]+)')
    hexa_chars = re.compile('^[0-9A-F]+$')

    @staticmethod
    def hash_from_magnet(m):
        res = CacheBT.magnet_re.search(m)
        if res:
            ih = res.group(1).upper()
            if len(ih) == 40 and CacheBT.hexa_chars.match(ih):
                return res.group(1).upper()
            elif len(ih) == 32:
                s = base64.b32decode(ih)
                return "".join("{:02X}".format(ord(c)) for c in s)
            else:
                raise ValueError('Not BT magnet link')

        else:
            raise ValueError('Not BT magnet link')

    def play_position(self, info_hash, secs):
        self._last_pos[info_hash] = secs

    def get_last_position(self, info_hash):
        return self._last_pos.get(info_hash) or 0
