import m3u8
import asyncio
import json
from aiohttp import ClientSession
from http.client import responses
from urllib.parse import urlparse


async def av_info(url, http_headers=''):
    # if use_m3u8:
    #     m3u8_obj = await asyncio.get_event_loop().run_in_executor(None, m3u8.load, url)
    #     url = m3u8_obj.segments[0].absolute_uri  # override for mediainfo call
    #     dur = 0
    #     for s in m3u8_obj.segments:
    #         if hasattr(s, 'duration'):
    #             dur += s.duration

    mediainf_args = None
    # if audio_info:
    #     mediainf_args = '--Inform=Audio;%Duration%'
    # else:
    #     mediainf_args = '--Inform=Video;%Width%\\n%Height%\\n%Duration%'
    ff_proc = await asyncio.create_subprocess_exec('ffprobe',
                                                   '-v',
                                                   'error',
                                                   '-select_streams',
                                                   'v',
                                                   '-show_entries',
                                                   'stream=width,height',
                                                   '-show_entries',
                                                   'format=duration',
                                                   '-of',
                                                   'json',
                                                   '-headers',
                                                   '\n'.join(http_headers),
                                                   url,
                                                   stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.STDOUT)
    # mi_proc = subprocess.Popen(['mediainfo', mediainf_args, '2>', '/dev/null', url],
    #                            stdout=subprocess.PIPE,
    #                            stderr=subprocess.STDOUT)
    out = await ff_proc.stdout.read()
    info = json.loads(out)
    if 'format' in info and 'duration' in info['format']:
        info['format']['duration'] = int(float(info['format']['duration']))
    return info
    # out = out.split(b'\n')
    #
    # w = h = None
    # if not audio_info:
    #     w = int(out[0])
    #     h = int(out[1])
    # if use_m3u8:
    #     dur = int(dur)
    # else:
    #     dur = int(int(float(out[2 if not audio_info else 0]))/1000)
    #
    # if audio_info:
    #     return dur
    # else:
    #     return w, h, dur


async def media_size(url, session=None, http_headers=None):
    _session = None
    if session is None:
        _session = await ClientSession().__aenter__()
    else:
        _session = session
    content_length = 0
    async with _session.head(url, headers=http_headers, allow_redirects=True) as resp:
        if resp.status != 200:
            print('Request to url {} failed: '.format(url) + responses[resp.status])
        else:
            content_length = int(resp.headers['Content-Length'])
    # try GET request when HEAD failed
    if content_length == 0:
        async with _session.get(url, headers=http_headers) as resp:
            if resp.status != 200:
                raise Exception('Request failed: ' + responses[resp.status])
            else:
                content_length = int(resp.headers['Content-Length'])

    if session is None:
        await _session.__aexit__(exc_type=None, exc_val=None, exc_tb=None)

    return content_length
    # head_req = request.Request(url, method='HEAD', headers=http_headers)
    # try:
    #     with request.urlopen(head_req) as resp:
    #         return int(resp.headers['Content-Length'])
    # except:
    #     return None


async def media_mime(url, http_headers=None):
    async with ClientSession() as session:
        async with session.head(url, headers=http_headers, allow_redirects=True) as resp:
            return resp.headers['Content-Type']


def m3u8_parse_url(url):
    _url = urlparse(url)
    if not _url.path.endswith('m3u8'):
        return url
    else:
        return m3u8._parsed_url(url) + '/'


async def m3u8_video_size(url, http_headers=None):
    m3u8_data = None
    m3u8_obj = None
    async with ClientSession() as session:
        async with session.get(url, headers=http_headers) as resp:
            m3u8_data = await resp.read()
            m3u8_obj = m3u8.loads(m3u8_data.decode())
            m3u8_obj.base_uri = m3u8_parse_url(str(resp.url))
        size = 0
        for seg in m3u8_obj.segments:
            size += await media_size(seg.absolute_uri, session=session, http_headers=http_headers)

    return size
