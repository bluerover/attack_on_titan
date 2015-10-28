from __future__ import absolute_import, division, print_function, with_statement
import tornado
from tornado.tcpclient import TCPClient
import collections
import re
from tornado.iostream import StreamClosedError
from tornado.concurrent import Future
from tornado.escape import native_str, utf8
from tornado import gen
from tornado import httputil
from tornado import iostream
from tornado.log import gen_log, app_log
from tornado import stack_context
from tornado.util import GzipDecompressor
import socket
from tornado.httpclient import AsyncHTTPClient
from tornado.simple_httpclient import SimpleAsyncHTTPClient
import functools 
from tornado.netutil import Resolver,OverrideResolver
from tornado.http1connection import HTTP1Connection,HTTP1ConnectionParameters,_ExceptionLoggingContext
from tornado.escape import utf8, _unicode
import time

try:
    import urlparse  # py2
except ImportError:
    import urllib.parse as urlparse  # py3

class SimpleAsyncDmtpClient(SimpleAsyncHTTPClient):
    """Non-blocking HTTP client with no external dependencies.
    This class implements an HTTP 1.1 client on top of Tornado's IOStreams.
    Some features found in the curl-based AsyncHTTPClient are not yet
    supported.  In particular, proxies are not supported, connections
    are not reused, and callers cannot select the network interface to be
    used.
    """
    def initialize(self, io_loop, max_clients=10,
                   hostname_mapping=None, max_buffer_size=104857600,
                   resolver=None, defaults=None, max_header_size=None,
                   max_body_size=None):
        """Creates a AsyncHTTPClient.
        Only a single AsyncHTTPClient instance exists per IOLoop
        in order to provide limitations on the number of pending connections.
        ``force_instance=True`` may be used to suppress this behavior.
        Note that because of this implicit reuse, unless ``force_instance``
        is used, only the first call to the constructor actually uses
        its arguments. It is recommended to use the ``configure`` method
        instead of the constructor to ensure that arguments take effect.
        ``max_clients`` is the number of concurrent requests that can be
        in progress; when this limit is reached additional requests will be
        queued. Note that time spent waiting in this queue still counts
        against the ``request_timeout``.
        ``hostname_mapping`` is a dictionary mapping hostnames to IP addresses.
        It can be used to make local DNS changes when modifying system-wide
        settings like ``/etc/hosts`` is not possible or desirable (e.g. in
        unittests).
        ``max_buffer_size`` (default 100MB) is the number of bytes
        that can be read into memory at once. ``max_body_size``
        (defaults to ``max_buffer_size``) is the largest response body
        that the client will accept.  Without a
        ``streaming_callback``, the smaller of these two limits
        applies; with a ``streaming_callback`` only ``max_body_size``
        does.
        .. versionchanged:: 4.2
           Added the ``max_body_size`` argument.
        """
        super(SimpleAsyncHTTPClient, self).initialize(io_loop,
                                                      defaults=defaults)
        self.max_clients = max_clients
        self.queue = collections.deque()
        self.active = {}
        self.waiting = {}
        self.max_buffer_size = max_buffer_size
        self.max_header_size = max_header_size
        self.max_body_size = max_body_size
        # TCPClient could create a Resolver for us, but we have to do it
        # ourselves to support hostname_mapping.
        if resolver:
            self.resolver = resolver
            self.own_resolver = False
        else:
            self.resolver = Resolver(io_loop=io_loop)
            self.own_resolver = True
        if hostname_mapping is not None:
            self.resolver = OverrideResolver(resolver=self.resolver,
                                             mapping=hostname_mapping)
        self.tcp_client = TCPClient(resolver=self.resolver, io_loop=io_loop)

    def close(self):
        super(SimpleAsyncHTTPClient, self).close()
        if self.own_resolver:
            self.resolver.close()
        self.tcp_client.close()
    '''
    request: Dicitonary object which must define 'host', 'port' properties 
    '''
    def fetch_impl(self, request, callback):
        key = object()
        self.queue.append((key, request, callback))
        if not len(self.active) < self.max_clients:
            timeout_handle = self.io_loop.add_timeout(
                self.io_loop.time() + min(request.connect_timeout,
                                          request.request_timeout),
                functools.partial(self._on_timeout, key))
        else:
            timeout_handle = None
        self.waiting[key] = (request, callback, timeout_handle)
        self._process_queue()
        if self.queue:
            gen_log.debug("max_clients limit reached, request queued. "
                          "%d active, %d queued requests." % (
                              len(self.active), len(self.queue)))

    def _process_queue(self):
        with stack_context.NullContext():
            while self.queue and len(self.active) < self.max_clients:
                key, request, callback = self.queue.popleft()
                if key not in self.waiting:
                    continue
                self._remove_timeout(key)
                self.active[key] = (request, callback)
                release_callback = functools.partial(self._release_fetch, key)
                self._handle_request(request, release_callback, callback)

    def _connection_class(self):
        return _DMTPConnection

    def _handle_request(self, request, release_callback, final_callback):
        self._connection_class()(
            self.io_loop, self, request, release_callback,
            final_callback, self.max_buffer_size, self.tcp_client,
            self.max_header_size, self.max_body_size)

    def _release_fetch(self, key):
        del self.active[key]
        self._process_queue()

    def _remove_timeout(self, key):
        if key in self.waiting:
            request, callback, timeout_handle = self.waiting[key]
            if timeout_handle is not None:
                self.io_loop.remove_timeout(timeout_handle)
            del self.waiting[key]

    def _on_timeout(self, key):
        request, callback, timeout_handle = self.waiting[key]
        self.queue.remove((key, request, callback))
        timeout_response = DMTPResponse(
            request, 599, error=Exception(599, "Timeout"),
            request_time=self.io_loop.time() - request.start_time)
        self.io_loop.add_callback(callback, timeout_response)
        del self.waiting[key]

import struct

'''    DMTP Packet Structure
    0:2 E051 Packet type 
    2:1 XX Payload length [variable] 
    
    3:2 XXXX Status code:  
    5:4 XXXXXXXX Timestamp [POSIX Epoch time] 
    9:4 XXXXXX Latitude (may be zeroed if client has  no GPS) 
    13:4 XXXXXX Longitude    (may be zeroed if client has no GPS) 
    16:4 
    19:1 XX Reader ID 
    20:2 XXXX Customer Number 
    21:3 XXXXXX Tag Number 
    24:1 XX  RSSI 
    25:1 XX Battery Life indicator 
    26:1 XX Alarm Flags (optional) 
    27:2 XXXX Temperature (optional) 
    29:1      XX Sequence [0 to 255] 
'''

class DMTPTagPacket(object):
    def __init__(self):
        self.packet_header = 20960 #'\xE0\x51'
        
        'The Header is in a different endian format then the packet payload :s'
        '''self.payload_fmt = '=2s4sLL4xbH\
                        xH\
                        3bhb'''
        self.payload_fmt = '>HLLL4xbH\
                        xH\
                        3bhb'
        self.header_fmt = '=Hb'
    def _generate(self,status_code,timestamp,cust_num,tag_num,rssi,reader_id,battery,flags,temperature,latitude=0,longitude=0,seq_num=0,reader_type=0):
        
        '''payload_packet = struct.pack(self.payload_fmt,struct.pack(">H",status_code),struct.pack(">L",timestamp),latitude,longitude,reader_id,cust_num,\
                  tag_num,
                  rssi,battery,flags,temperature,seq_num)'''
        payload_packet = struct.pack(self.payload_fmt,status_code,timestamp,latitude,longitude,reader_id,cust_num,\
                  tag_num,
                  rssi,battery,flags,int(temperature*10),seq_num)
        header_packet = struct.pack(self.header_fmt,self.packet_header,len(payload_packet))
        self.hex_packet = header_packet + payload_packet 
        return self.hex_packet
    
class DMTPTagInRangePacket(DMTPTagPacket):
    def __init__(self,cust_num,tag_num,rssi,reader_id,battery,flags,temperature,*args,**kwargs):
        super(DMTPTagInRangePacket, self).__init__()
        super(DMTPTagInRangePacket,self)._generate(62720,int(time.time()),cust_num,tag_num,rssi,reader_id,battery,flags,temperature)
  

class DMTPRequest(tornado.httpclient.HTTPRequest):
    
    def __init__(self,url,accountid,deviceid,packets=[]):
        super(DMTPRequest,self).__init__(url)
        self.accountid = accountid
        self.deviceid = deviceid
        self.packets= packets
    def start_block(self):
        return '\xe0'
    
    def end_block(self):
        return '\xe0\x00\x00'
    
    def get_account_header(self):
        return '\x12'+struct.pack(">B", len(self.accountid)) + self.accountid
    
    def get_device_header(self):
        return '\x13'+struct.pack(">B", len(self.deviceid)) + self.deviceid
    
    def get_temperature_packets(self):
        pass
    
    def get_write_block(self):
        return self.start_block() + self.get_account_header() +\
            self.start_block() + self.get_device_header() + \
            "".join(map(lambda x:x.hex_packet,self.packets)) +\
            self.end_block()
            
class DMTPResponse(tornado.httpclient.HTTPResponse):
    
    def __init__(self,*args,**kwargs):
        super(DMTPResponse,self).__init__(*args,**kwargs)

class DMTPConnection(httputil.HTTPConnection):
    """Implements the HTTP/1.x protocol.

    This class can be on its own for clients, or via `HTTP1ServerConnection`
    for servers.
    """
    def __init__(self, stream, is_client, params=None, context=None):
        """
        :arg stream: an `.IOStream`
        :arg bool is_client: client or server
        :arg params: a `.HTTP1ConnectionParameters` instance or ``None``
        :arg context: an opaque application-defined object that can be accessed
            as ``connection.context``.
        """
        self.is_client = is_client
        self.stream = stream
        if params is None:
            params = HTTP1ConnectionParameters()
        self.params = params
        self.context = context
        self.no_keep_alive = params.no_keep_alive
        # The body limits can be altered by the delegate, so save them
        # here instead of just referencing self.params later.
        self._max_body_size = (self.params.max_body_size or
                               self.stream.max_buffer_size)
        self._body_timeout = self.params.body_timeout
        # _write_finished is set to True when finish() has been called,
        # i.e. there will be no more data sent.  Data may still be in the
        # stream's write buffer.
        self._write_finished = False
        # True when we have read the entire incoming body.
        self._read_finished = False
        # _finish_future resolves when all data has been written and flushed
        # to the IOStream.
        self._finish_future = Future()
        # If true, the connection should be closed after this request
        # (after the response has been written in the server side,
        # and after it has been read in the client)
        self._disconnect_on_finish = False
        self._clear_callbacks()
        # Save the start lines after we read or write them; they
        # affect later processing (e.g. 304 responses and HEAD methods
        # have content-length but no bodies)
        self._request_start_line = None
        self._response_start_line = None
        self._request_headers = None
        # True if we are writing output with chunked encoding.
        self._chunking_output = None
        # While reading a body with a content-length, this is the
        # amount left to read.
        self._expected_content_remaining = None
        # A Future for our outgoing writes, returned by IOStream.write.
        self._pending_write = None

    def read_response(self, delegate):
        """Read a single HTTP response.

        Typical client-mode usage is to write a request using `write_headers`,
        `write`, and `finish`, and then call ``read_response``.

        :arg delegate: a `.HTTPMessageDelegate`

        Returns a `.Future` that resolves to None after the full response has
        been read.
        """
        
        return self._read_message(delegate)

    @gen.coroutine
    def _read_message(self, delegate):
        need_delegate_close = False
        
        try:
           
            '''header_future = self.stream.read_until_regex(
                "\x00",
                max_bytes=3)
            if self.params.header_timeout is None:
                header_data = yield header_future
            else:
                try:
                    header_data = yield gen.with_timeout(
                        self.stream.io_loop.time() + self.params.header_timeout,
                        header_future,
                        io_loop=self.stream.io_loop,
                        quiet_exceptions=iostream.StreamClosedError)
                except gen.TimeoutError:
                    self.close()
                    raise gen.Return(False)'''
            """start_line, headers = self._parse_headers(header_data)
            if self.is_client:
                start_line = httputil.parse_response_start_line(start_line)
                self._response_start_line = start_line
            else:
                start_line = httputil.parse_request_start_line(start_line)
                self._request_start_line = start_line
                self._request_headers = headers
            self._disconnect_on_finish = not self._can_keep_alive(
                start_line, headers)
            """
            yield self._read_body_until_close(delegate)

            need_delegate_close = True
            '''with _ExceptionLoggingContext(app_log):
                header_future = delegate.headers_received(start_line, headers)
                if header_future is not None:
                    yield header_future
            if self.stream is None:
                # We've been detached.
                need_delegate_close = False
                raise gen.Return(False)
            skip_body = False
            if self.is_client:
                if (self._request_start_line is not None and
                        self._request_start_line.method == 'HEAD'):
                    skip_body = True
                code = start_line.code
                if code == 304:
                    # 304 responses may include the content-length header
                    # but do not actually have a body.
                    # http://tools.ietf.org/html/rfc7230#section-3.3
                    skip_body = True
                if code >= 100 and code < 200:
                    # 1xx responses should never indicate the presence of
                    # a body.
                    if ('Content-Length' in headers or
                        'Transfer-Encoding' in headers):
                        raise httputil.HTTPInputError(
                            "Response code %d cannot have body" % code)
                    # TODO: client delegates will get headers_received twice
                    # in the case of a 100-continue.  Document or change?
                    yield self._read_message(delegate)
            else:
                if (headers.get("Expect") == "100-continue" and
                        not self._write_finished):
                    self.stream.write(b"HTTP/1.1 100 (Continue)\r\n\r\n")
            if not skip_body:
                body_future = self._read_body(
                    start_line.code if self.is_client else 0, headers, delegate)
                if body_future is not None:
                    if self._body_timeout is None:
                        yield body_future
                    else:
                        try:
                            yield gen.with_timeout(
                                self.stream.io_loop.time() + self._body_timeout,
                                body_future, self.stream.io_loop,
                                quiet_exceptions=iostream.StreamClosedError)
                        except gen.TimeoutError:
                            gen_log.info("Timeout reading body from %s",
                                         self.context)
                            self.stream.close()
                            raise gen.Return(False)'''
            #self._read_finished = True
            if not self._write_finished or self.is_client:
                need_delegate_close = False
                with _ExceptionLoggingContext(app_log):
                    
                    delegate.finish()
            # If we're waiting for the application to produce an asynchronous
            # response, and we're not detached, register a close callback
            # on the stream (we didn't need one while we were reading)
            if (not self._finish_future.done() and
                    self.stream is not None and
                    not self.stream.closed()):
                self.stream.set_close_callback(self._on_connection_close)
                yield self._finish_future
            if self.is_client and self._disconnect_on_finish:
                self.close()
            if self.stream is None:
                raise gen.Return(False)
        except httputil.HTTPInputError as e:
            gen_log.info("Malformed HTTP message from %s: %s",
                         self.context, e)
            self.close()
            raise gen.Return(False)
        finally:
            if need_delegate_close:
                with _ExceptionLoggingContext(app_log):
                    delegate.on_connection_close()
            self._clear_callbacks()
        raise gen.Return(True)

    def _clear_callbacks(self):
        """Clears the callback attributes.

        This allows the request handler to be garbage collected more
        quickly in CPython by breaking up reference cycles.
        """
        self._write_callback = None
        self._write_future = None
        self._close_callback = None
        if self.stream is not None:
            self.stream.set_close_callback(None)

    def set_close_callback(self, callback):
        """Sets a callback that will be run when the connection is closed.

        .. deprecated:: 4.0
            Use `.HTTPMessageDelegate.on_connection_close` instead.
        """
        self._close_callback = stack_context.wrap(callback)

    def _on_connection_close(self):
        # Note that this callback is only registered on the IOStream
        # when we have finished reading the request and are waiting for
        # the application to produce its response.
        if self._close_callback is not None:
            callback = self._close_callback
            self._close_callback = None
            callback()
        if not self._finish_future.done():
            self._finish_future.set_result(None)
        self._clear_callbacks()

    def close(self):
        if self.stream is not None:
            self.stream.close()
        self._clear_callbacks()
        if not self._finish_future.done():
            self._finish_future.set_result(None)

    def detach(self):
        """Take control of the underlying stream.

        Returns the underlying `.IOStream` object and stops all further
        HTTP processing.  May only be called during
        `.HTTPMessageDelegate.headers_received`.  Intended for implementing
        protocols like websockets that tunnel over an HTTP handshake.
        """
        self._clear_callbacks()
        stream = self.stream
        self.stream = None
        if not self._finish_future.done():
            self._finish_future.set_result(None)
        return stream

    def set_body_timeout(self, timeout):
        """Sets the body timeout for a single request.

        Overrides the value from `.HTTP1ConnectionParameters`.
        """
        self._body_timeout = timeout

    def set_max_body_size(self, max_body_size):
        """Sets the body size limit for a single request.

        Overrides the value from `.HTTP1ConnectionParameters`.
        """
        self._max_body_size = max_body_size


    def write(self, chunk, callback=None):
        """Implements `.HTTPConnection.write`.

        For backwards compatibility is is allowed but deprecated to
        skip `write_headers` and instead call `write()` with a
        pre-encoded header block.
        """
        future = None
        if self.stream.closed():
            future = self._write_future = Future()
            self._write_future.set_exception(iostream.StreamClosedError())
            self._write_future.exception()
        else:
            if callback is not None:
                self._write_callback = stack_context.wrap(callback)
            else:
                future = self._write_future = Future()
            self._pending_write = self.stream.write(chunk)
            self._pending_write.add_done_callback(self._on_write_complete)
        return future

    def finish(self):
        if not self.stream.closed():
                #self._pending_write = self.stream.write("\xe0\x00\x00")
                self._pending_write.add_done_callback(self._on_write_complete)
        self._write_finished = True
        # If the app finished the request while we're still reading,
        # divert any remaining data away from the delegate and
        # close the connection when we're done sending our response.
        # Closing the connection is the only way to avoid reading the
        # whole input body.
        if not self._read_finished:
            self._disconnect_on_finish = True
        # No more data is coming, so instruct TCP to send any remaining
        # data immediately instead of waiting for a full packet or ack.
        self.stream.set_nodelay(True)
        if self._pending_write is None:
            self._finish_request(None)
        else:
            self._pending_write.add_done_callback(self._finish_request)

    def _on_write_complete(self, future):
        exc = future.exception()
        if exc is not None and not isinstance(exc, iostream.StreamClosedError):
            future.result()
        if self._write_callback is not None:
            callback = self._write_callback
            self._write_callback = None
            self.stream.io_loop.add_callback(callback)
        if self._write_future is not None:
            future = self._write_future
            self._write_future = None
            future.set_result(None)

    
    def _finish_request(self, future):
        self._clear_callbacks()
        if not self.is_client and self._disconnect_on_finish:
            self.close()
            return
        # Turn Nagle's algorithm back on, leaving the stream in its
        # default state for the next request.
        self.stream.set_nodelay(False)
        if not self._finish_future.done():
            self._finish_future.set_result(None)


    @gen.coroutine
    def _read_body_until_close(self, delegate):
        body = yield self.stream.read_until_close()
        self._read_finished = True
        if not self._write_finished or self.is_client:
            with _ExceptionLoggingContext(app_log):
                delegate.data_received(body)


        
class _DMTPConnection(httputil.HTTPMessageDelegate):
    _SUPPORTED_METHODS = set(["ACCOUNT", "DEVICE", "TAG_IN_RANGE"])

    def __init__(self, io_loop, client, request, release_callback,
                 final_callback, max_buffer_size, tcp_client,
                 max_header_size, max_body_size):
        self.start_time = io_loop.time()
        self.io_loop = io_loop
        self.client = client
        self.request = request
        self.release_callback = release_callback
        self.final_callback = final_callback
        self.max_buffer_size = max_buffer_size
        self.tcp_client = tcp_client
        self.max_header_size = max_header_size
        self.max_body_size = max_body_size
        self.code = None
        self.headers = None
        self.chunks = []
        self._decompressor = None
        # Timeout handle returned by IOLoop.add_timeout
        self._timeout = None
        self._sockaddr = None
        with stack_context.ExceptionStackContext(self._handle_exception):
            self.parsed = urlparse.urlsplit(_unicode(self.request.url))
            af = socket.AF_UNSPEC
            netloc = self.parsed.netloc
            
            host, port = httputil.split_host_and_port(netloc)
            timeout = min(self.request.connect_timeout, self.request.request_timeout)
            if timeout:
                self._timeout = self.io_loop.add_timeout(
                    self.start_time + timeout,
                    stack_context.wrap(self._on_timeout))
            self.tcp_client.connect(host,port, af=af,
                                    max_buffer_size=self.max_buffer_size,
                                    callback=self._on_connect)

    def _on_timeout(self):
        self._timeout = None
        if self.final_callback is not None:
            raise Exception(599, "Timeout")

    def _remove_timeout(self):
        if self._timeout is not None:
            self.io_loop.remove_timeout(self._timeout)
            self._timeout = None

    def _on_connect(self, stream):
        if self.final_callback is None:
            # final_callback is cleared if we've hit our timeout.
            stream.close()
            return
        self.stream = stream
        self.stream.set_close_callback(self.on_connection_close)
        self._remove_timeout()
        if self.final_callback is None:
            return
        
        
        self.connection = self._create_connection(stream)
        self.connection.write(self.request.get_write_block())
        #self.connection.write_packets(self.request.packets)
        '''start_line = httputil.RequestStartLine(self.request.method,
                                               req_path, '')
        self.connection.write_headers(start_line, self.request.headers)
        if self.request.expect_100_continue:
            self._read_response()
        else:
            self._write_body(True)'''
        self.connection.finish()
        self._read_response()
        
    def _create_connection(self, stream):
        stream.set_nodelay(True)
        connection = DMTPConnection(
            stream, True,
            HTTP1ConnectionParameters(
                no_keep_alive=True,
                max_header_size=self.max_header_size,
                max_body_size=self.max_body_size,
                decompress=self.request.decompress_response),
            self._sockaddr)
        return connection

    
    def _read_response(self):
        # Ensure that any exception raised in read_response ends up in our
        # stack context.
        self.io_loop.add_future(
            self.connection.read_response(self),
            lambda f: f.result())

    def _release(self):
        if self.release_callback is not None:
            release_callback = self.release_callback
            self.release_callback = None
            release_callback()

    def _run_callback(self, response):
        self._release()
        if self.final_callback is not None:
            final_callback = self.final_callback
            self.final_callback = None
            self.io_loop.add_callback(final_callback, response)

    def _handle_exception(self, typ, value, tb):
        if self.final_callback:
            self._remove_timeout()
            if isinstance(value, StreamClosedError):
                value = HTTPError(599, "Stream closed")
            self._run_callback(DMTPResponse(self.request, 599, error=value,
                                            request_time=self.io_loop.time() - self.start_time,
                                            ))

            if hasattr(self, "stream"):
                # TODO: this may cause a StreamClosedError to be raised
                # by the connection's Future.  Should we cancel the
                # connection more gracefully?
                self.stream.close()
            return True
        else:
            # If our callback has already been called, we are probably
            # catching an exception that is not caused by us but rather
            # some child of our callback. Rather than drop it on the floor,
            # pass it along, unless it's just the stream being closed.
            return isinstance(value, StreamClosedError)

    def on_connection_close(self):
        if self.final_callback is not None:
            message = "Connection closed"
            if self.stream.error:
                raise self.stream.error
            try:
                raise HTTPError(599, message)
            except HTTPError:
                self._handle_exception(*sys.exc_info())

    def headers_received(self, first_line, headers):
        if self.request.expect_100_continue and first_line.code == 100:
            self._write_body(False)
            return
        self.headers = headers
        self.code = first_line.code
        self.reason = first_line.reason

        if self.request.header_callback is not None:
            # Reassemble the start line.
            self.request.header_callback('%s %s %s\r\n' % first_line)
            for k, v in self.headers.get_all():
                self.request.header_callback("%s: %s\r\n" % (k, v))
            self.request.header_callback('\r\n')

    def finish(self):
        data = b''.join(self.chunks)
        self._remove_timeout()
        original_request = getattr(self.request, "original_request",
                                   self.request)
        
        '''if self.request.streaming_callback:
            buffer = BytesIO()
        else:
            buffer = BytesIO(data)  # TODO: don't require one big string?'''
        response = DMTPResponse(original_request,
                                200, reason="we the best",
                                headers=self.headers,
                                request_time=self.io_loop.time() - self.start_time,
                                buffer=data,
                                effective_url=self.request.url)
        self._run_callback(response)
        self._on_end_request()

    def _on_end_request(self):
        self.stream.close()

    def data_received(self, chunk):
        print(chunk)
        if self.request.streaming_callback is not None:
            self.request.streaming_callback(chunk)
        else:
            self.chunks.append(chunk)


'''Utility funcitons to generate request packets
use this function to send credentials etc.'''
def hex_from_string(str):
    return map(hex, map(ord, str))

def start_block():
    return '\xE0'

def end_block():
    return '\x00'

def main():
    import time
    ioloop = tornado.ioloop.IOLoop.current()
    client = SimpleAsyncDmtpClient(ioloop)


    def on_response(response):
        print(response)
        if response.error:
            print("DONT CLEAR BUFFER")
        else:
            print("CLEAR BUFFER")
            
    def cb():
        #cust_num,tag_num,rssi,reader_id,battery,flags,temperature):
        packet = DMTPTagInRangePacket(6,4302,77,0,2,3,-21.35)
        print(packet.hex_packet)
        dmtp_request = DMTPRequest('dmtp://54.84.59.135:21000',"foodsafety","amittest",packets=[packet])
        client.fetch(dmtp_request,on_response)
    def cb2():
        print("timer:%d"%int(time.time()))
    periodic_callback = tornado.ioloop.PeriodicCallback(cb,5000, io_loop=ioloop)
    periodic_callback2 = tornado.ioloop.PeriodicCallback(cb2,100, io_loop=ioloop)
    
    periodic_callback.start()
    #periodic_callback2.start()
    cb()
    ioloop.start()
    
if __name__ == '__main__':
    main()
    
