import time
import uuid
from builtins import (bytes, chr, str, int, object)

from contextlib import contextmanager

from diesel.core import until_eol, receive, fire, send, first, fork, sleep
from diesel.transports.common import protocol
from diesel.transports.tcp import TCPClient
from diesel.util.queue import Queue, QueueTimeout

def flatten_arg_pairs(l):
    o = []
    for i in l:
        o.extend(i)
    return o

REDIS_PORT = 6379

class RedisError(Exception): pass

class RedisClient(TCPClient):
    def __init__(self, host='localhost', port=REDIS_PORT, password=None,
                 encoding='utf-8', encoding_errors='strict',
                 decode_responses=False, **kw):
        """
        :param host: host of the redis server
        :param port: port of the redis server
        :param password: password of the redis server
        :param decode_responses: If true, the incomming socket bytes will be
        decoded using the `encoding` charset
        :param encoding: Encoding to use to encode/decode data given the
        socket level communication must be done with bytes
        :param encoding_errors: errors handling when encoding unicode
        """
        super(RedisClient, self).__init__(host, port, **kw)
        self.password = password
        self.encoding = encoding
        self.encoding_errors = encoding_errors
        self.decode_responses = decode_responses

    def _decode_response(self, resp):
        """If requested, convert response into unicode"""
        if isinstance(resp, bytes) and self.decode_responses:
            return resp.decode(self.encoding)
        # TODO : remove me, for sanity check during py3k porting
        elif not isinstance(resp, (str, bytes)) and resp != None:
            import pdb; pdb.set_trace()
        else:
            return resp

    def _encode(self, value):
        "Return a bytestring representation of the value"
        if isinstance(value, bytes):
            return value
        elif isinstance(value, int):
            value = str(value)
        elif isinstance(value, float):
            value = repr(value)
        elif not isinstance(value, str):
            value = str(value)
        if isinstance(value, str):
            value = value.encode(self.encoding, self.encoding_errors)
        return value

    ##################################################
    ### GENERAL OPERATIONS
    @protocol
    def auth(self):
        self._send('AUTH', self.password)
        resp = self._get_response()
        return bool(resp)
    @protocol
    def exists(self, k):
        self._send('EXISTS', k)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def delete(self, k):
        self._send('DEL', k)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def type(self, k):
        self._send('TYPE', k)
        resp = self._get_response()
        return resp

    @protocol
    def keys(self, pat):
        self._send('KEYS', pat)
        resp = self._get_response()
        return set(resp)

    @protocol
    def randomkey(self):
        self._send('RANDOMKEY')
        resp = self._get_response()
        return resp

    @protocol
    def rename(self, old, new):
        self._send('RENAME', old, new)
        resp = self._get_response()
        return resp

    @protocol
    def renamenx(self, old, new):
        self._send('RENAMENX', old, new)
        resp = self._get_response()
        return resp

    @protocol
    def dbsize(self):
        self._send('DBSIZE')
        resp = self._get_response()
        return resp

    @protocol
    def expire(self, key, seconds):
        self._send('EXPIRE', key, seconds)
        resp = self._get_response()
        return resp

    @protocol
    def expireat(self, key, when):
        unix_time = time.mktime(when.timetuple())
        self._send('EXPIREAT', key, unix_time)
        resp = self._get_response()
        return resp

    @protocol
    def ttl(self, key):
        self._send('TTL', key)
        resp = self._get_response()
        resp = None if resp == -1 else int(resp)
        return resp

    @protocol
    def select(self, idx):
        self._send('SELECT', idx)
        resp = self._get_response()
        return resp

    @protocol
    def move(self, key, idx):
        self._send('MOVE', key, idx)

    @protocol
    def flushdb(self):
        self._send('FLUSHDB')
        resp = self._get_response()
        return resp

    @protocol
    def flushall(self):
        self._send('FLUSHALL')
        resp = self._get_response()
        return resp

    ##################################################
    ### TRANSACTION OPERATIONS
    ### http://redis.io/topics/transactions
    @protocol
    def multi(self):
        """Starts a transaction."""
        self._send('MULTI')
        return self._get_response()

    @protocol
    def exec_(self):
        """Atomically executes queued commands in a transaction."""
        self._send('EXEC')
        return self._get_response()

    @protocol
    def discard(self):
        """Discards any queued commands and aborts a transaction."""
        self._send('DISCARD')
        return self._get_response()

    @protocol
    def watch(self, keys):
        """Sets up keys to be watched in preparation for a transaction."""
        self._send('WATCH', list=keys)
        return self._get_response()

    def transaction(self, watch=None):
        """Returns a RedisTransaction context manager.

        If watch is supplied, it should be a list of keys to be watched for
        changes. The transaction will be aborted if the value of any of the
        keys is changed outside of the transaction.

        A transaction can be invoked with Python's ``with`` statement for
        atomically executing a series of commands.

        >>> transaction = client.transaction(watch=['dependent_var_1'])
        >>> dv1 = client.get('dependent_var_1')
        >>> with transaction as t:
        ...     composite_val = compute(dv1)
        ...     t.set('dependent_var_2', composite_val)
        >>> print t.value

        """
        return RedisTransaction(self, watch or [])

    ##################################################
    ### STRING OPERATIONS
    @protocol
    def set(self, k, v):
        self._send('SET', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def get(self, k):
        self._send('GET', k)
        resp = self._get_response()
        return resp

    @protocol
    def getset(self, k, v):
        self._send('GETSET', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def mget(self, keylist):
        self._send('MGET', list=keylist)
        resp = self._get_response()
        return resp

    @protocol
    def setnx(self, k, v):
        self._send('SETNX', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def setex(self, k, tm, v):
        self._send('SETEX', k, tm, v)
        resp = self._get_response()
        return resp

    @protocol
    def mset(self, d):
        self._send('MSET', list=flatten_arg_pairs(iter(d.items())))
        resp = self._get_response()
        return resp

    @protocol
    def msetnx(self, d):
        self._send('MSETNX', list=flatten_arg_pairs(iter(d.items())))
        resp = self._get_response()
        return resp

    @protocol
    def incr(self, k):
        self._send('INCR', k)
        resp = self._get_response()
        return resp

    @protocol
    def incrby(self, k, amt):
        self._send('INCRBY', k, amt)
        resp = self._get_response()
        return resp

    @protocol
    def decr(self, k):
        self._send('DECR', k)
        resp = self._get_response()
        return resp

    @protocol
    def decrby(self, k, amt):
        self._send('DECRBY', k, amt)
        resp = self._get_response()
        return resp

    @protocol
    def append(self, k, value):
        self._send('APPEND', k, value)
        resp = self._get_response()
        return resp

    @protocol
    def substr(self, k, start, end):
        self._send('SUBSTR', k, start, end)
        resp = self._get_response()
        return resp

    @protocol
    def getbit(self, k, offset):
        self._send('GETBIT', k, offset)
        resp = self._get_response()
        return int(resp)

    @protocol
    def setbit(self, k, offset, value):
        self._send('SETBIT', k, offset, value)
        resp = self._get_response()
        return resp

    @protocol
    def strlen(self, k):
        self._send('STRLEN', k)
        resp = self._get_response()
        return int(resp)


    ##################################################
    ### LIST OPERATIONS
    @protocol
    def rpush(self, k, v):
        self._send('RPUSH', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def lpush(self, k, v):
        self._send('LPUSH', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def llen(self, k):
        self._send('LLEN', k)
        resp = self._get_response()
        return resp

    @protocol
    def lrange(self, k, start, end):
        self._send('LRANGE', k, start, end)
        resp = self._get_response()
        return resp

    @protocol
    def ltrim(self, k, start, end):
        self._send('LTRIM', k, start, end)
        resp = self._get_response()
        return resp

    @protocol
    def lindex(self, k, idx):
        self._send('LINDEX', k, idx)
        resp = self._get_response()
        return resp

    @protocol
    def lset(self, k, idx, v):
        self._send('LSET', k, idx,  v)
        resp = self._get_response()
        return resp

    @protocol
    def lrem(self, k, v, count=0):
        self._send('LREM', k, count, v)
        resp = self._get_response()
        return resp

    @protocol
    def lpop(self, k):
        self._send('LPOP', k)
        resp = self._get_response()
        return resp

    @protocol
    def rpop(self, k):
        self._send('RPOP', k)
        resp = self._get_response()
        return resp

    @protocol
    def blpop(self, keylist, timeout=0):
        self._send('BLPOP', list=list(keylist) + [timeout])
        resp = self._get_response()
        if resp:
            assert len(resp) == 2
            resp = tuple(resp)
        else:
            resp = None
        return resp

    @protocol
    def brpop(self, keylist, timeout=0):
        self._send('BRPOP', list=list(keylist) + [timeout])
        resp = self._get_response()
        if resp:
            assert len(resp) == 2
            resp = tuple(resp)
        else:
            resp = None
        return resp

    @protocol
    def rpoplpush(self, src, dest):
        self._send('RPOPLPUSH', src, dest)
        resp = self._get_response()
        return resp

    ##################################################
    ### SET OPERATIONS
    @protocol
    def sadd(self, k, v):
        self._send('SADD', k, v)
        resp = self._get_response()
        return resp

    @protocol
    def srem(self, k, v):
        self._send('SREM', k, v)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def spop(self, k):
        self._send('SPOP', k)
        resp = self._get_response()
        return resp

    @protocol
    def smove(self, src, dst, v):
        self._send('SMOVE', src, dst, v)
        resp = self._get_response()
        return resp

    @protocol
    def scard(self, k):
        self._send('SCARD', k)
        resp = self._get_response()
        return resp

    @protocol
    def sismember(self, k, v):
        self._send('SISMEMBER', k, v)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def sinter(self, keylist):
        self._send('SINTER', list=keylist)
        resp = self._get_response()
        return set(resp)

    @protocol
    def sinterstore(self, dst, keylist):
        flist = [dst] + list(keylist)
        self._send('SINTERSTORE', list=flist)
        resp = self._get_response()
        return resp

    @protocol
    def sunion(self, keylist):
        self._send('SUNION', list=keylist)
        resp = self._get_response()
        return set(resp)

    @protocol
    def sunionstore(self, dst, keylist):
        flist = [dst] + list(keylist)
        self._send('SUNIONSTORE', list=flist)
        resp = self._get_response()
        return resp

    @protocol
    def sdiff(self, keylist):
        self._send('SDIFF', list=keylist)
        resp = self._get_response()
        return set(resp)

    @protocol
    def sdiffstore(self, dst, keylist):
        flist = [dst] + list(keylist)
        self._send('SDIFFSTORE', list=flist)
        resp = self._get_response()
        return resp

    @protocol
    def smembers(self, key):
        self._send('SMEMBERS', key)
        resp = self._get_response()
        return set(resp)

    @protocol
    def srandmember(self, key):
        self._send('SRANDMEMBER', key)
        resp = self._get_response()
        return resp

    ##################################################
    ### ZSET OPERATIONS

    def __pair_with_scores(self, resp):
        return [(resp[x], float(resp[x+1]))
                for x in range(0, len(resp), 2)]

    @protocol
    def zadd(self, key, score, member):
        self._send('ZADD', key, score, member)
        resp = self._get_response()
        return resp

    @protocol
    def zrem(self, key, member):
        self._send('ZREM', key, member)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def zrange(self, key, start, end, with_scores=False):
        args = 'ZRANGE', key, start, end
        if with_scores:
            args += 'WITHSCORES',
        self._send(*args)
        resp = self._get_response()
        if with_scores:
            return self.__pair_with_scores(resp)
        return resp

    @protocol
    def zrevrange(self, key, start, end, with_scores=False):
        args = 'ZREVRANGE', key, start, end
        if with_scores:
            args += 'WITHSCORES',
        self._send(*args)
        resp = self._get_response()
        if with_scores:
            return self.__pair_with_scores(resp)
        return resp

    @protocol
    def zcard(self, key):
        self._send('ZCARD', key)
        resp = self._get_response()
        return int(resp)

    @protocol
    def zscore(self, key, member):
        self._send('ZSCORE', key, member)
        resp = self._get_response()
        return float(resp) if resp is not None else None

    @protocol
    def zincrby(self, key, increment, member):
        self._send('ZINCRBY', key, increment, member)
        resp = self._get_response()
        return float(resp)

    @protocol
    def zrank(self, key, member):
        self._send('ZRANK', key, member)
        resp = self._get_response()
        return resp

    @protocol
    def zrevrank(self, key, member):
        self._send('ZREVRANK', key, member)
        resp = self._get_response()
        return resp

    @protocol
    def zrangebyscore(self, key, min, max, offset=None, count=None, with_scores=False):
        args = 'ZRANGEBYSCORE', key, min, max
        if offset:
            assert count is not None, "if offset specified, count must be as well"
            args += 'LIMIT', offset, count
        if with_scores:
            args += 'WITHSCORES',

        self._send(*args)
        resp = self._get_response()

        if with_scores:
            return self.__pair_with_scores(resp)

        return resp

    @protocol
    def zcount(self, key, min, max):
        self._send('ZCOUNT', key, min, max)
        resp = self._get_response()
        return resp

    @protocol
    def zremrangebyrank(self, key, min, max):
        self._send('ZREMRANGEBYRANK', key, min, max)
        resp = self._get_response()
        return resp

    @protocol
    def zremrangebyscore(self, key, min, max):
        self._send('ZREMRANGEBYSCORE', key, min, max)
        resp = self._get_response()
        return resp

    ##################################################
    ### HASH OPERATIONS
    @protocol
    def hset(self, key, field, value):
        self._send('HSET', key, field, value)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def hget(self, key, field):
        self._send('HGET', key, field)
        resp = self._get_response()
        return resp


    @protocol
    def hmset(self, key, d):
        if not d:
            return True
        args = [key] + flatten_arg_pairs(iter(d.items()))

        self._send('HMSET', list=args)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def hmget(self, key, l):
        if not l:
            return {}
        args = [key] + l
        self._send('HMGET', list=args)
        resp = self._get_response()
        return dict(list(zip(l, resp)))

    @protocol
    def hincrby(self, key, field, amt):
        self._send('HINCRBY', key, field, amt)
        resp = self._get_response()
        return resp

    @protocol
    def hexists(self, key, field):
        self._send('HEXISTS', key, field)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def hdel(self, key, field):
        self._send('HDEL', key, field)
        resp = self._get_response()
        return bool(resp)

    @protocol
    def hlen(self, key):
        self._send('HLEN', key)
        resp = self._get_response()
        return resp

    @protocol
    def hkeys(self, key):
        self._send('HKEYS', key)
        resp = self._get_response()
        return set(resp)

    @protocol
    def hvals(self, key):
        self._send('HVALS', key)
        resp = self._get_response()
        return resp

    @protocol
    def hgetall(self, key):
        self._send('HGETALL', key)
        resp = self._get_response()
        return dict(resp[x:x+2] for x in range(0, len(resp), 2))

    @protocol
    def hsetnx(self, key, field, value):
        self._send('HSETNX', key, field, value)
        resp = self._get_response()
        return bool(resp)

    ##################################################
    ### Sorting...
    @protocol
    def sort(self, key, pattern=None, limit=None,
    get=None, order='ASC', alpha=False, store=None):

        args = [key]
        if pattern:
            args += ['BY', pattern]

        if limit:
            args += ['LIMIT'] + list(limit)

        if get:
            args += ['GET', get]

        args += [order]

        if alpha:
            args += 'ALPHA'

        if store:
            args += ['STORE', store]

        self._send('SORT', *args)
        resp = self._get_response()
        return resp

    @protocol
    def subscribe(self, *channels):
        '''Subscribe to the given channels.

        Note: assumes subscriptions succeed
        '''
        self._send('SUBSCRIBE', *channels)
        return None

    @protocol
    def unsubscribe(self, *channels):
        '''Unsubscribe from the given channels, or all of them if none are given.

        Note: assumes subscriptions don't succeed
        '''
        self._send('UNSUBSCRIBE', *channels)
        return None

    @protocol
    def psubscribe(self, *channels):
        '''Subscribe to the given glob pattern-matched channels.

        Note: assumes subscriptions succeed
        '''
        self._send('PSUBSCRIBE', *channels)
        return None

    @protocol
    def punsubscribe(self, *channels):
        '''Unsubscribe from the given glob pattern-matched channels, or all of them if none are given.

        Note: assumes subscriptions don't succeed
        '''
        self._send('PUNSUBSCRIBE', *channels)
        return None

    @protocol
    def get_from_subscriptions(self, wake_sig=None):
        '''Wait for a published message on a subscribed channel.

        Returns a tuple consisting of:

            * The subscription pattern which matched
                (the same as the channel for non-glob subscriptions)
            * The channel the message was received from.
            * The message itself.

        -- OR -- None, if wake_sig was fired

        NOTE: The message will always be of bytes type.  Handle this as you see fit.
        NOTE: subscribe/unsubscribe acks are ignored here
        '''
        while True:
            r = self._get_response(wake_sig)
            if r:
                if r[0] == b'message':
                    return [r[1]] + r[1:]
                elif r[0] == b'pmessage':
                    return r[1:]
            else:
                return None


    @protocol
    def publish(self, channel, message):
        '''Publish a message on the given channel.

        Returns the number of clients that received the message.
        '''
        self._send('PUBLISH', channel, message)
        resp = self._get_response()
        return resp

    @protocol
    def send_raw_command(self, arguments):
        cmd, rest = arguments[0], arguments[1:]
        self._send(cmd, list=rest)

        line_one = until_eol()
        c = chr(bytes(line_one)[0])
        if c in ('+', '-', ':'):
            return line_one
        if c == '$':
            amt = int(line_one[1:])
            if amt == -1:
                return line_one
            return line_one + receive(amt) + until_eol()
        if c == '*':
            nargs = int(line_one[1:])
            if nargs == -1:
                return line_one
            out = line_one
            for x in range(nargs):
                head = until_eol()
                out += head
                out += receive(int(head[1:])) + until_eol()
            return out

    def _send(self, cmd, *args, **kwargs):
        if 'list' in kwargs:
            args = tuple(kwargs['list'])
        all = tuple(map(self._encode, (cmd,) + args))
        send(('*%s\r\n' % len(all)).encode())
        for i in all:
            send(('$%s\r\n' % len(i)).encode() + i + b'\r\n')

    def _get_response(self, wake_sig=None):
        if wake_sig:
            ev, val = first(until_eol=True, waits=[wake_sig])
            if ev != 'until_eol':
                return None
            fl = val.strip()
        else:
            fl = until_eol().strip()

        c = chr(bytes(fl)[0])
        if c == '+':
            return self._decode_response(fl[1:])
        elif c == '$':
            l = int(fl[1:])
            if l == -1:
                resp = None
            else:
                resp = receive(l)
                until_eol() # noop
            return self._decode_response(resp)
        elif c == '*':
            count = int(fl[1:])
            resp = []
            if count == -1:
                return None
            for x in range(count):
                hl = until_eol()
                c_hl = chr(bytes(hl)[0])
                assert c_hl in ['$', ':', '+'], c_hl
                if c_hl == '$':
                    l = int(hl[1:])
                    if l == -1:
                        resp.append(None)
                    else:
                        resp.append(self._decode_response(receive(l)))
                        until_eol() # noop
                elif c_hl == ':':
                    resp.append(int(hl[1:]))
                elif c_hl == '+':
                    resp.append(self._decode_response(hl[1:].strip()))
            return resp
        elif c == ':':
            return int(fl[1:])
        elif c == '-':
            e_message = fl[1:]
            raise RedisError(e_message)

class RedisTransaction(object):
    """A context manager for doing transactions with a RedisClient."""

    def __init__(self, client, watch_keys):
        """Returns a new RedisTransaction instance.

        The client argument should be a RedisClient instance and watch_keys
        should be a list of keys to watch.

        Handles calling the Redis WATCH, MULTI, EXEC and DISCARD commands to
        manage transactions. Calls WATCH to watch keys for changes, MULTI to
        start the transaction, EXEC to complete it or DISCARD to abort if there
        was an exception.

        Instances proxy method calls to the client instance. If the transaction
        is successful, the value attribute will contain the results.

        See http://redis.io/topics/transactions for more details.

        """
        self.client = client
        self.value = None
        self.watching = watch_keys
        self.aborted = False
        if watch_keys:
            self.client.watch(watch_keys)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def __enter__(self):
        # Begin the transaction.
        self.client.multi()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if any([exc_type, exc_val, exc_tb]):
            # There was an error. Abort the transaction.
            self.client.discard()
            self.aborted = True
        else:
            # Try and execute the transaction.
            self.value = self.client.exec_()
            if self.value is None:
                self.aborted = True
                msg = 'A watched key changed before the transaction completed.'
                raise RedisTransactionError(msg)

        # Instruct Python not to swallow exceptions generated in the
        # transaction block.
        return False

class RedisTransactionError(Exception): pass


class LockNotAcquired(Exception):
    pass

class RedisLock(object):
    def __init__(self, client, key, timeout=30):
        assert timeout >= 2, 'Timeout must be greater than 2 to guarantee the transaction'
        self.client = client
        assert isinstance(key, (str, bytes))
        self.key = key if isinstance(key, bytes) else key.encode()
        self.timeout = timeout
        self.me = uuid.uuid4().bytes

    def __enter__(self):
        trans = self.client.transaction(watch=[self.key])
        v = self.client.get(self.key)
        if v:
            raise LockNotAcquired()
        else:
            try:
                with trans as t:
                    t.setex(self.key, self.timeout, self.me)

                def touch():
                    with RedisClient(self.client.addr, self.client.port) as c:
                        while self.in_block:
                            c.expire(self.key, self.timeout)
                            sleep(self.timeout / 2)
                self.in_block = True
                fork(touch)
            except RedisTransactionError:
                raise LockNotAcquired()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.in_block = False
        val = self.client.get(self.key)
        assert val == self.me, 'Someone else took the lock, panic (val=%s, expected=%s, wha=%s)' % (val, self.me, self.client.get(self.key))
        self.client.delete(self.key)


#########################################
## Hub, an abstraction of sub behavior, etc
class RedisSubHub(object):
    def __init__(self, host='127.0.0.1', port=REDIS_PORT, password=None,
                 encoding='utf-8', encoding_errors='strict',
                 decode_responses=False):
        """
        :param host: host of the redis server
        :param port: port of the redis server
        :param password: password of the redis server
        :param decode_responses: If true, the incomming socket bytes will be
        decoded using the `encoding` charset
        :param encoding: Encoding to use to encode/decode data given the
        socket level communication must be done with bytes
        :param encoding_errors: errors handling when encoding unicode
        """
        self.encoding = encoding
        self.encoding_errors = encoding_errors
        self.decode_responses = decode_responses
        self.host = host
        self.port = port
        self.password= password
        self.sub_wake_signal = uuid.uuid4().hex
        self.sub_adds = []
        self.sub_rms = []
        self.subs = {}

    def _encode(self, value):
        "Return a bytestring representation of the value"
        if isinstance(value, bytes):
            return value
        elif isinstance(value, int):
            value = str(value)
        elif isinstance(value, float):
            value = repr(value)
        elif not isinstance(value, str):
            value = str(value)
        if isinstance(value, str):
            value = value.encode(self.encoding, self.encoding_errors)
        return value

    def make_client(self):
        client = RedisClient(self.host, self.port, self.password,
                             encoding=self.encoding,
                             encoding_errors=self.encoding_errors,
                             decode_responses=self.decode_responses)
        if self.password != None:
            client.auth()
        return  client

    def __isglob(self, glob):
        return b'*' in glob or b'?' in glob or (b'[' in glob and b']' and glob)

    def __call__(self):
        with self.make_client() as conn:
            subs = self.subs
            for sub in subs:
                if self.__isglob(sub):
                    conn.psubscribe(sub)
                else:
                    conn.subscribe(sub)
            while True:
                new = rm = None
                if self.sub_adds:
                    sa = self.sub_adds[:]
                    self.sub_adds = []
                    new_subs, new_glob_subs = set(), set()
                    for k, q in sa:
                        new = new_glob_subs if self.__isglob(k) else new_subs

                        if k not in subs:
                            new.add(k)
                            subs[k] = set([q])
                        else:
                            subs[k].add(q)

                    if new_subs:
                        conn.subscribe(*new_subs)
                    if new_glob_subs:
                        conn.psubscribe(*new_glob_subs)

                if self.sub_rms:
                    sr = self.sub_rms[:]
                    self.sub_rms = []
                    rm_subs, rm_glob_subs = set(), set()
                    for k, q in sr:
                        rm = rm_glob_subs if self.__isglob(k) else rm_subs

                        subs[k].remove(q)
                        if not subs[k]:
                            del subs[k]
                            rm.add(k)

                    if rm_subs:
                        conn.unsubscribe(*rm_subs)
                    if rm_glob_subs:
                        conn.punsubscribe(*rm_glob_subs)

                if not self.sub_rms and not self.sub_adds:
                    r = conn.get_from_subscriptions(self.sub_wake_signal)
                    if r:
                        cls, key, msg = r
                        if cls in subs:
                            for q in subs[cls]:
                                q.put((key, msg))

    @contextmanager
    def subq(self, classes):
        if type(classes) not in (set, list, tuple):
            classes = [classes]
        classes = [self._encode(classe) for classe in classes]

        q = Queue()

        for cls in classes:
            self.sub_adds.append((cls, q))

        fire(self.sub_wake_signal)

        try:
            yield q
        finally:
            for cls in classes:
                self.sub_rms.append((cls, q))


    @contextmanager
    def sub(self, classes):
        if type(classes) not in (set, list, tuple):
            classes = [classes]
        classes = [self._encode(classe) for classe in classes]

        hb = self
        q = Queue()
        class Poller(object):
            def __init__(self):
                for cls in classes:
                    hb.sub_adds.append((cls, q))

                fire(hb.sub_wake_signal)

            def fetch(self, timeout=None):
                try:
                    qn, msg = q.get(timeout=timeout)
                except QueueTimeout:
                    return (None, None)
                else:
                    return (qn, msg)

            def close(self):
                for cls in classes:
                    hb.sub_rms.append((cls, q))

        pl = Poller()
        try:
            yield pl
        finally:
            pl.close()
