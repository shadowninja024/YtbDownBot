import typing
import ffmpeg
import asyncio
from aiohttp import ClientSession, ClientTimeout


class DumbReader(typing.BinaryIO):
    def write(self, s: typing.Union[bytes, bytearray]) -> int:
        pass

    def mode(self) -> str:
        pass

    def name(self) -> str:
        pass

    def close(self) -> None:
        pass

    def closed(self) -> bool:
        pass

    def fileno(self) -> int:
        pass

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        pass

    def readable(self) -> bool:
        pass

    def readline(self, limit: int = -1) -> typing.AnyStr:
        pass

    def readlines(self, hint: int = -1) -> typing.List[typing.AnyStr]:
        pass

    def seek(self, offset: int, whence: int = 0) -> int:
        pass

    def seekable(self) -> bool:
        pass

    def tell(self) -> int:
        pass

    def truncate(self, size: int = None) -> int:
        pass

    def writable(self) -> bool:
        pass

    def write(self, s: typing.AnyStr) -> int:
        pass

    def writelines(self, lines: typing.List[typing.AnyStr]) -> None:
        pass

    def __enter__(self) -> 'typing.IO[typing.AnyStr]':
        pass

    def __exit__(self, type, value, traceback) -> None:
        pass


class FFMpegAV(DumbReader):

    def __init__(self):
        self._buf = b''

    @staticmethod
    async def create(vformat, aformat=None, audio_only=False, headers=''):
        ff = FFMpegAV()
        # _finput = ffmpeg.input(vformat['url'], **{"user-agent": user_agent, "loglevel": "error"})
        _finput = None
        if aformat:
            _finput = ffmpeg.input(vformat['url'], headers="\n".join(headers), i=aformat['url'])
        else:
            _finput = ffmpeg.input(vformat['url'], headers="\n".join(headers))
        _fstream = None
        ff.format = None
        if audio_only:
            ff.format = 'mp3'
            acodec = None
            if 'acodec' in vformat and vformat['acodec'] is not None:
                # if vformat['acodec'].startswith('mp4a'):
                #     acodec = 'm4a'
                if vformat['acodec'].startswith('mp3'):
                    acodec = 'mp3'

                if acodec != None:
                    _fstream = _finput.output('pipe:',
                                              format=acodec,
                                              acodec='copy',
                                              **{'vn': None})
                else:
                    _fstream = _finput.output('pipe:',
                                              format='mp3',
                                              acodec='mp3',
                                              **{'vn': None})
            else:
                _fstream = _finput.output('pipe:',
                                          format='mp3',
                                          acodec='mp3',
                                          **{'vn': None})
        else:
            _fstream = _finput.output('pipe:',
                                      format='mp4',
                                      vcodec='copy',
                                      acodec='mp3',
                                      movflags='frag_keyframe')
        if aformat:
            # args = _fstream.global_args('headers',
            #                             "\n".join(headers),
            #                             '-i',
            #                             aformat['url'],
            #                             '-map',
            #                             '0:v',
            #                             '-map',
            #                             '1:a').compile()
            args = _fstream.compile()
            args = args[:3] + ['-headers', "\n".join(headers)] + args[3:-1] + ['-map', '1:v', '-map', '0:a'] + [args[-1]]
            proc = await asyncio.create_subprocess_exec('ffmpeg',
                                                        *args[1:],
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            ff.stream = proc
        else:
            args = _fstream.compile()
            proc = await asyncio.create_subprocess_exec('ffmpeg',
                                                        *args[1:],
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            ff.stream = proc

        return ff

    async def read(self, n: int = -1):
        buf = b''
        if len(self._buf) != 0:
            buf += self._buf
            self._buf = b''
        if n == -1:
            return await self.stream.stdout.read()

        while len(buf) < n:
            _data = await self.stream.stdout.read(n)
            if len(_data) == 0:
                break
            buf += _data
        if len(buf) > n != -1:
            self._buf = buf[n:]
            return buf[:n]
        else:
            return buf

    def close(self) -> None:
        # print('last data ', len(self.stream.stdout.read()))
        try:
            self.stream.kill()
        except:
            pass


class URLav(DumbReader):
    def __init__(self):
        self._buf = b''

    @staticmethod
    async def create(url, headers=None):
        u = URLav()
        timeout = ClientTimeout(total=7200)
        u.session = await ClientSession(timeout=timeout).__aenter__()
        u.request = await u.session.get(url, headers=headers)
        # u.request = await asks.get(url, headers=headers, stream=True, max_redirects=5)
        # u.body = u.request.body(timeout=14400)
        return u

    async def read(self, n: int = -1):
        buf = b''
        if len(self._buf) != 0:
            buf += self._buf
            self._buf = b''
        if n == -1:
            return await self.request.read()

        while len(buf) < n:
            _data = await self.request.content.read(n)
            if len(_data) == 0:
                break
            buf += _data
        if len(buf) > n != -1:
            self._buf = buf[n:]
            return buf[:n]
        else:
            return buf

    async def close(self) -> None:
        # self.request.release()
        await self.session.__aexit__(exc_type=None, exc_val=None, exc_tb=None)
