#!/bin/python3

import sys, os
from telethon import TelegramClient, Button, functions
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio
from telethon.sessions import StringSession
import traceback
import asyncio
import logging
import logaugment
import youtube_dl
from aiohttp import web
from urlextract import URLExtract
import re
import av_utils
import av_source
import users
import cut_time
import tgaction
import thumb
import io
import inspect
import mimetypes
from datetime import time
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from urllib.error import HTTPError
import signal
import functools


def get_client_session():
    if 'CLIENT_SESSION' in os.environ:
        return os.environ['CLIENT_SESSION']

    try:
        from cloudant import cloudant
        from cloudant.adapters import Replay429Adapter
    except:
        raise Exception('Couldn\'t find client session nor in os.environ or cloudant db')

    with cloudant(os.environ['CLOUDANT_USERNAME'],
                  os.environ['CLOUDANT_PASSWORD'],
                  url=os.environ['CLOUDANT_URL'],
                  adapter=Replay429Adapter(retries=10),
                  connect=True) as client:
        db = client['ytbdownbot']
        instance_id = '0'
        # in case of multi instance architecture
        if 'INSTANCE_INDEX' in os.environ:
            instance_id = os.environ['INSTANCE_INDEX']
        return db['session' + instance_id]['session']


def new_logger(user_id, msg_id):
    logger = logging.Logger('')
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(levelname)s <%(id)s> [%(msgid)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logaugment.set(logger, id=str(user_id), msgid=str(msg_id))

    return logger


async def on_callback(callback):
    from_id = callback['from']['id']
    msg_id = callback['message']['message_id']
    data = callback['data']
    user = await users.User.init(from_id)
    log = new_logger(from_id, msg_id)
    # retry in case of update conflict
    for _ in range(15):
        try:
            await _on_callback(from_id, msg_id, data, user, log)
        except HTTPError as e:
            if e.response.status_code == 409:
                log.warning('document update conflict, trying sync with db...')
                try:
                    await user.sync_with_db()
                except HTTPError as e:
                    if e.response.status_code == 404:
                        user = await users.User.init(from_id, force_create=True)
                continue
            else:
                log.exception(e)
                break
        except Exception as e:
            log.exception(e)
            break
        break


async def _on_callback(from_id, msg_id, data, user, log):
    key, value = data.split(':')
    if key == 'default_media_type':
        if int(value) == users.DefaultMediaType.Video.value:
            log.info('set default media type to {}'.format(users.DefaultMediaType.Audio))
            await user.set_default_media_type(users.DefaultMediaType.Audio)
        else:
            log.info('set default media type to {}'.format(users.DefaultMediaType.Video))
            await user.set_default_media_type(users.DefaultMediaType.Video)
    elif key == 'video_format':
        value = int(value)
        if value == users.VideoFormat.LOW.value:
            log.info('set video format to {}'.format(users.VideoFormat.MED))
            await user.set_video_format(users.VideoFormat.MED)
        elif value == users.VideoFormat.MED.value:
            log.info('set video format to {}'.format(users.VideoFormat.HIGH))
            await user.set_video_format(users.VideoFormat.HIGH)
        elif value == users.VideoFormat.HIGH.value:
            log.info('set video format to {}'.format(users.VideoFormat.LOW))
            await user.set_video_format(users.VideoFormat.LOW)
    elif key == 'audio_caption':
        value = not (1 if value == 'True' else 0)
        log.info('set audio captions to {}'.format(value))
        await user.set_audio_caption(value)
    elif key == 'video_caption':
        value = not (1 if value == 'True' else 0)
        log.info('set video captions to {}'.format(value))
        await user.set_video_caption(value)
    elif key == '':
        global bot_entity
        log.info('delete settings menu')
        await _bot.delete_message(from_id, msg_id)
        # await bot.delete_messages(bot_entity, msg_id)
        return

    await send_settings(user, from_id, msg_id)


async def on_message(request):
    try:
        req_data = await request.json()

        if 'callback_query' in req_data:
            asyncio.get_event_loop().create_task(on_callback(req_data['callback_query']))
            return web.Response(status=200)

        message = req_data['message']
        if message['from']['id'] == BOT_AGENT_CHAT_ID:
            try:
                await share_content_with_user(message)
            except Exception as e:
                if 'Reply message not found' in str(e):
                    await share_content_with_user(message, with_reply=False)
                else:
                    print(e)
                    traceback.print_exc()
            return web.Response(status=200)

        asyncio.get_event_loop().create_task(_on_message_task(message))
    except Exception as e:
        print(e)
        traceback.print_exc()

    return web.Response(status=200)


# share uploaded by client api file to user
async def share_content_with_user(message, with_reply=True):
    _user_id, _reply_msg_id, user_caption = message['caption'].split(':', maxsplit=2)
    user_id = int(_user_id)
    reply_msg_id = int(_reply_msg_id) if with_reply else None
    caption = user_caption if user_caption != '' else None
    if 'video' in message:
        await _bot.send_video(user_id, message['video']['file_id'], reply_to_message_id=reply_msg_id, caption=caption)
    elif 'audio' in message:
        await _bot.send_audio(user_id, message['audio']['file_id'], reply_to_message_id=reply_msg_id, caption=caption)
    elif 'document' in message:
        await _bot.send_document(user_id, message['document']['file_id'], reply_to_message_id=reply_msg_id,
                                 caption=caption)


async def _on_message_task(message):
    try:
        # async with bot.action(message['chat']['id'], 'file'):
        chat_id = message['from']['id']
        msg_id = message['message_id']
        log = new_logger(chat_id, msg_id)
        try:
            await _on_message(message, log)
        except HTTPError as e:
            # crashing to try change ip
            # otherwise youtube.com will not allow us
            # to download any video for some time
            if e.code == 429:
                log.critical(e)
                await abort()
            else:
                log.exception(e)
                await _bot.send_message(chat_id, e.__str__(), reply_to_message_id=msg_id)
                # await bot.send_message(chat_id, e.__str__(), reply_to=msg_id)
        except youtube_dl.DownloadError as e:
            # crashing to try change ip
            # otherwise youtube.com will not allow us
            # to download any video for some time
            if e.exc_info[0] is HTTPError:
                if e.exc_info[1].file.code == 429:
                    log.critical(e)
                    await abort()

            log.exception(e)
            await _bot.send_message(chat_id, str(e), reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, e.__str__(), reply_to=msg_id)
        except Exception as e:
            log.exception(e)
            await _bot.send_message(chat_id, str(e), reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, e.__str__(), reply_to=msg_id)
    except Exception as e:
        logging.error(e)


# extract telegram command from message
def cmd_from_message(message):
    cmd = None
    if 'entities' in message:
        for e in message['entities']:
            if e['type'] == 'bot_command':
                cmd = message['text'][e['offset'] + 1:e['length']]

    return cmd


async def extract_url_info(ydl, url):
    # data = {
    #     "url": url,
    #     **params
    # }
    # headers = {
    #     "x-ibm-client-id": YTDL_LAMBDA_SECRET
    # }
    # async with ClientSession() as session:
    #     async with session.post(YTDL_LAMBDA_URL, json=data, headers=headers, timeout=14400) as req:
    #         return await req.json()
    return await asyncio.get_event_loop().run_in_executor(None,
                                                          functools.partial(ydl.extract_info,
                                                                            download=False,
                                                                            force_generic_extractor=ydl.params.get(
                                                                                'force_generic_extractor', False)),
                                                          url)


async def send_settings(user, user_id, edit_id=None):
    buttons = None
    keyboard = InlineKeyboardMarkup(row_width=2)
    if user.default_media_type == users.DefaultMediaType.Video.value:
        b1 = InlineKeyboardButton('🎬⤵️', callback_data='default_media_type:' + str(users.DefaultMediaType.Video.value))
        b2 = InlineKeyboardButton(str(user.video_format) + 'p', callback_data='video_format:' + str(user.video_format))
        b3 = InlineKeyboardButton('Video caption: ' + ('✅' if user.video_caption else '❎'),
                                  callback_data='video_caption:' + str(user.video_caption))
        b4 = InlineKeyboardButton('❌', callback_data=':')
        keyboard.add(b1, b2, b3, b4)
        # [Button.inline('🎬⤵️',
        #                data='default_media_type:' + str(users.DefaultMediaType.Video.value)),
        #  Button.inline(str(user.video_format) + 'p',
        #                data='video_format:' + str(user.video_format))],
        # [Button.inline('Video caption: ' + ('✅' if user.video_caption else '❎'),
        #                data='video_caption:' + str(user.video_caption)),
        #  Button.inline('❌', data=':')]
    else:
        b1 = InlineKeyboardButton('🎧⤵️', callback_data='default_media_type:' + str(users.DefaultMediaType.Audio.value))
        b2 = InlineKeyboardButton('Audio caption: ' + ('✅' if user.audio_caption else '❎'),
                                  callback_data='audio_caption:' + str(user.audio_caption))
        b3 = InlineKeyboardButton('❌', callback_data=':')
        keyboard.add(b1, b2, b3)
        # [Button.inline('🎧⤵️',
        #                data='default_media_type:' + str(users.DefaultMediaType.Audio.value)),
        #  Button.inline('Audio caption: ' + ('✅' if user.audio_caption else '❎'),
        #                data='audio_caption:' + str(user.audio_caption))],
        # [Button.inline('❌', data=':')]
    if edit_id is None:

        await _bot.send_message(user_id, '⚙SETTINGS', reply_markup=keyboard)
        # await bot.send_message(user_id, '⚙SETTINGS', buttons=buttons)
    else:
        await _bot.edit_message_reply_markup(user_id, edit_id, reply_markup=keyboard)
        # msgs = await bot(functions.messages.GetMessagesRequest(id=[edit_id]))
        # await bot.edit_message(msgs.messages[0], '⚙SETTINGS', buttons=buttons)

is_ytb_link_re = re.compile('^((?:https?:)?\/\/)?((?:www|m|music)\.)?((?:youtube\.com|youtu.be))(\/(?:[\w\-]+\?v=|embed\/|v\/)?)([\w\-]+)(\S+)?$')
get_ytb_id_re = re.compile('.*(youtu.be\/|v\/|embed\/|watch\?|youtube.com\/user\/[^#]*#([^\/]*?\/)*)\??v?=?([^#\&\?]*).*')


async def _on_message(message, log):
    if message['from']['is_bot']:
        log.info('Message from bot, skip')
        return

    msg_id = message['message_id']
    chat_id = message['chat']['id']
    if 'text' not in message:
        await _bot.send_message(chat_id, 'Please send me a video link', reply_to_message_id=msg_id)
        # await bot.send_message(chat_id, 'Please send me a video link', reply_to=msg_id)
        return
    msg_txt = message['text']

    log.info('message: ' + msg_txt)

    urls = url_extractor.find_urls(msg_txt)
    cmd = cmd_from_message(message)
    playlist_start = None
    playlist_end = None
    y_format = None

    user = None
    # check cmd and choose video format
    cut_time_start = cut_time_end = None
    if cmd is not None:
        if cmd not in available_cmds:
            await _bot.send_message(chat_id, 'Wrong command', reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, 'Wrong command', reply_to=msg_id)
            return
        elif cmd == 'start':
            await _bot.send_message(chat_id, 'Send me a video links')
            # await bot.send_message(chat_id, 'Send me a video links')
            return
        elif cmd == 'c':
            cut_time_start, cut_time_end = cut_time.parse_time(msg_txt)
        elif cmd == 'ping':
            await _bot.send_message(chat_id, 'pong')
            # await bot.send_message(chat_id, 'pong')
            return
        elif cmd == 'settings':
            user = await users.User.init(chat_id)
            await send_settings(user, chat_id)
            return
        elif cmd in playlist_cmds:
            urls_count = len(urls)
            if urls_count != 1:
                await _bot.send_message(chat_id,
                                        'Wrong command arguments. Correct example: /' + cmd + " 2-4 youtube.com",
                                        reply_to_message_id=msg_id)
                # await bot.send_message(chat_id, 'Wrong command arguments. Correct example: /' + cmd + " 2-4 youtube.com", reply_to=msg_id)
                return
            range_match = playlist_range_re.search(msg_txt)
            if range_match is None:
                await _bot.send_message(chat_id, 'Wrong message format, correct example: /' + cmd + " 4-9 " + urls[0],
                                        reply_to_message_id=msg_id)
                # await bot.send_message(chat_id,
                #                        'Wrong message format, correct example: /' + cmd + " 4-9 " + urls[0],
                #                        reply_to=msg_id)
                return
            _start, _end = range_match.groups()
            playlist_start = int(_start)
            playlist_end = int(_end)
            if playlist_start >= playlist_end:
                await _bot.send_message(chat_id, 'Not correct format, start number must be less then end',
                                        reply_to_message_id=msg_id)
                # await bot.send_message(chat_id,
                #                        'Not correct format, start number must be less then end',
                #                        reply_to=msg_id)
                return
            elif playlist_end - playlist_start > 50:
                await _bot.send_message(chat_id, 'Too big range. Allowed range is less or equal 50 videos',
                                        reply_to_message_id=msg_id)
                # await bot.send_message(chat_id,
                #                        'Too big range. Allowed range is less or equal 50 videos',
                #                        reply_to=msg_id)
                return
            # cut "p" from cmd variable if cmd == "pa" or "pw"
            cmd = cmd if len(cmd) == 1 else cmd[-1]
        if cmd == 'a':
            # audio cmd
            y_format = audio_format
        elif cmd == 'w':
            # wordst video cmd
            y_format = worst_video_format

    if len(urls) == 0:
        if cmd == 'a':
            await _bot.send_message(chat_id, 'Wrong command arguments. Correct example: /a youtube.com',
                                    reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, 'Wrong command arguments. Correct example: /a youtube.com',
            #                        reply_to=msg_id)
        elif cmd == 'w':
            await _bot.send_message(chat_id, 'Wrong command arguments. Correct example: /w youtube.com',
                                    reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, 'Wrong command arguments. Correct example: /w youtube.com',
            #                        reply_to=msg_id)
        else:
            await _bot.send_message(chat_id, 'Please send me link to the video', reply_to_message_id=msg_id)
            # await bot.send_message(chat_id, 'Please send me link to the video', reply_to=msg_id)
        log.info('Message without url: ' + msg_txt)
        return

    if user is None:
        user = await users.User.init(chat_id)
    if user.default_media_type == users.DefaultMediaType.Audio.value:
        cmd = 'a'

    preferred_formats = None
    if cmd != 'a':
        if y_format is not None:
            preferred_formats = [y_format]
        elif user.video_format == users.VideoFormat.HIGH.value:
            preferred_formats = [vid_fhd_format, vid_hd_format, vid_nhd_format]
        elif user.video_format == users.VideoFormat.MED.value:
            preferred_formats = [vid_hd_format, vid_nhd_format]
        elif user.video_format == users.VideoFormat.LOW.value:
            preferred_formats = [vid_nhd_format]
    else:
        if y_format is not None:
            preferred_formats = [y_format]
        else:
            preferred_formats = [audio_format]

    # await _bot.send_chat_action(chat_id, "upload_document")

    async with tgaction.TGAction(_bot, chat_id, "upload_document"):
        for u in set(urls):
            vinfo = None
            params = {'noplaylist': True,
                      'youtube_include_dash_manifest': False,
                      'quiet': True,
                      'no_color': True}
            if playlist_start != None and playlist_end != None:
                if playlist_start == 0 and playlist_end == 0:
                    params['playliststart'] = 1
                    params['playlistend'] = 10
                else:
                    params['playliststart'] = playlist_start
                    params['playlistend'] = playlist_end
            else:
                params['playlist_items'] = '1'

            ydl = youtube_dl.YoutubeDL(params=params)
            recover_playlist_index = None  # to save last playlist position if finding format failed
            for ip, pref_format in enumerate(preferred_formats):
                try:
                    params['format'] = pref_format
                    if recover_playlist_index is not None and 'playliststart' in params:
                        params['playliststart'] += recover_playlist_index
                    ydl.params = params
                    if vinfo is None:
                        for _ in range(2):
                            try:
                                vinfo = await extract_url_info(ydl, u)
                            except youtube_dl.DownloadError as e:
                                # try to use invidio.us youtube frontend to bypass 429 block
                                if e.exc_info[0] is HTTPError and e.exc_info[1].file.code == 429:
                                    if is_ytb_link_re.search(u):
                                        ytb_id_match = get_ytb_id_re.search(u)
                                        if ytb_id_match:
                                            ytb_id = ytb_id_match.groups()[-1]
                                            u = "https://invidio.us/watch?v=" + ytb_id
                                            if cmd == 'a':
                                                u += '&listen=1'
                                            ydl.params['force_generic_extractor'] = True
                                            continue
                                    raise
                                else:
                                    raise
                            break

                        log.debug('video info received')
                    else:
                        params['format'] = pref_format
                        if '_type' in vinfo and vinfo['_type'] == 'playlist':
                            for i, e in enumerate(vinfo['entries']):
                                e['requested_formats'] = None
                                vinfo['entries'][i] = ydl.process_video_result(e, download=False)
                        else:
                            vinfo['requested_formats'] = None
                            vinfo = ydl.process_video_result(vinfo, download=False)
                        log.debug('video info reprocessed with new format')
                except Exception as e:
                    if "Please log in or sign up to view this video" in str(e):
                        if 'vk.com' in u:
                            params['username'] = os.environ['VIDEO_ACCOUNT_USERNAME']
                            params['password'] = os.environ['VIDEO_ACCOUNT_PASSWORD']
                            ydl = youtube_dl.YoutubeDL(params=params)
                            try:
                                vinfo = await extract_url_info(ydl, u)
                            except Exception as e:
                                log.error(e)
                                await _bot.send_message(chat_id, str(e), reply_to_message_id=msg_id)
                                # await bot.send_message(chat_id, str(e), reply_to=msg_id)
                                continue
                        else:
                            log.error(e)
                            await _bot.send_message(chat_id, str(e), reply_to_message_id=msg_id)
                            # await bot.send_message(chat_id, str(e), reply_to=msg_id)
                            continue
                    elif 'are video-only' in str(e):
                        params['format'] = 'bestvideo[ext=mp4]'
                        ydl = youtube_dl.YoutubeDL(params=params)
                        try:
                            vinfo = await extract_url_info(ydl, u)
                        except Exception as e:
                            log.error(e)
                            await _bot.send_message(chat_id, str(e), reply_to_message_id=msg_id)
                            # await bot.send_message(chat_id, str(e), reply_to=msg_id)
                            continue
                    else:
                        raise

                entries = None
                if '_type' in vinfo and vinfo['_type'] == 'playlist':
                    entries = vinfo['entries']
                else:
                    entries = [vinfo]

                for ie, entry in enumerate(entries):
                    formats = entry.get('requested_formats')
                    file_size = None
                    chosen_format = None
                    ffmpeg_av = None
                    http_headers = None
                    if 'http_headers' not in entry:
                        if len(formats) > 0 and 'http_headers' in formats[0]:
                            http_headers = formats[0]['http_headers']
                    else:
                        http_headers = entry['http_headers']
                    http_headers['Referer'] = u

                    _cut_time = (cut_time_start, cut_time_end) if cut_time_start else None
                    if formats is not None:
                        for i, f in enumerate(formats):
                            if f['protocol'] in ['rtsp', 'rtmp', 'rtmpe', 'mms', 'f4m', 'ism', 'http_dash_segments']:
                                # await bot.send_message(chat_id, "ERROR: Failed find suitable format for: " + entry['title'], reply_to=msg_id)
                                continue
                            if 'm3u8' in f['protocol']:
                                file_size = await av_utils.m3u8_video_size(f['url'], http_headers)
                            else:
                                if 'filesize' in f and f['filesize'] != 0 and f['filesize'] is not None:
                                    file_size = f['filesize']
                                else:
                                    file_size = await av_utils.media_size(f['url'], http_headers=http_headers)

                            # Dash video
                            if f['protocol'] == 'https' and \
                                    (True if ('acodec' in f and (f['acodec'] == 'none' or f['acodec'] == None)) else False):
                                vformat = f
                                mformat = None
                                vsize = 0
                                if 'filesize' in vformat and vformat['filesize'] != 0 and vformat['filesize'] is not None:
                                    vsize = vformat['filesize']
                                else:
                                    vsize = await av_utils.media_size(vformat['url'], http_headers=http_headers)
                                msize = 0
                                # if there is one more format than
                                # it's likely an url to audio
                                if len(formats) > i + 1:
                                    mformat = formats[i + 1]
                                    if 'filesize' in mformat and mformat['filesize'] != 0 and mformat[
                                        'filesize'] is not None:
                                        msize = mformat['filesize']
                                    else:
                                        msize = await av_utils.media_size(mformat['url'], http_headers=http_headers)
                                # we can't precisely predict media size so make it large for prevent cutting
                                file_size = vsize + msize + 10 * 1024 * 1024
                                if file_size / (1024 * 1024) < TG_MAX_FILE_SIZE or cut_time_start is not None:
                                    ffmpeg_av = await av_source.FFMpegAV.create(vformat,
                                                                                mformat,
                                                                                headers=http_headers,
                                                                                cut_time_range=_cut_time)
                                    chosen_format = f
                                break
                            # m3u8
                            if ('m3u8' in f['protocol'] and
                                    (file_size / (1024 * 1024) <= TG_MAX_FILE_SIZE or cut_time_start is not None)):
                                chosen_format = f
                                ffmpeg_av = await av_source.FFMpegAV.create(chosen_format,
                                                                            audio_only=True if cmd == 'a' else False,
                                                                            headers=http_headers,
                                                                            cut_time_range=_cut_time)
                                break
                            # regular video stream
                            if (0 < file_size / (1024 * 1024) <= TG_MAX_FILE_SIZE) or cut_time_start is not None:
                                chosen_format = f
                                if cmd == 'a' and not (chosen_format['ext'] == 'mp3'):
                                    ffmpeg_av = await av_source.FFMpegAV.create(chosen_format,
                                                                                audio_only=True,
                                                                                headers=http_headers,
                                                                                cut_time_range=_cut_time)
                                break

                    else:
                        if entry['protocol'] in ['rtsp', 'rtmp', 'rtmpe', 'mms', 'f4m', 'ism', 'http_dash_segments']:
                            # await bot.send_message(chat_id, "ERROR: Failed find suitable format for : " + entry['title'], reply_to=msg_id)
                            # if 'playlist' in entry and entry['playlist'] is not None:
                            recover_playlist_index = ie
                            break
                        if 'm3u8' in entry['protocol']:
                            file_size = await av_utils.m3u8_video_size(entry['url'], http_headers=http_headers)
                        else:
                            if 'filesize' in entry and entry['filesize'] != 0 and entry['filesize'] is not None:
                                file_size = entry['filesize']
                            else:
                                file_size = await av_utils.media_size(entry['url'], http_headers=http_headers)
                        if ('m3u8' in entry['protocol'] and
                                (file_size / (1024 * 1024) <= TG_MAX_FILE_SIZE or cut_time_start is not None)):
                            chosen_format = entry
                            if entry.get('is_live') and not _cut_time:
                                _cut_time = (time(hour=0, minute=0, second=0), time(hour=0, minute=2, second=0))
                            ffmpeg_av = await av_source.FFMpegAV.create(chosen_format,
                                                                        audio_only=True if cmd == 'a' else False,
                                                                        headers=http_headers,
                                                                        cut_time_range=_cut_time)
                        elif (0 < file_size / (1024 * 1024) <= TG_MAX_FILE_SIZE) or cut_time_start is not None:
                            chosen_format = entry
                            if cmd == 'a' and not (chosen_format['ext'] == 'mp3'):
                                ffmpeg_av = await av_source.FFMpegAV.create(chosen_format,
                                                                            audio_only=True,
                                                                            headers=http_headers,
                                                                            cut_time_range=_cut_time)

                    try:
                        if chosen_format is None and ffmpeg_av is None:
                            if len(preferred_formats) - 1 == ip:
                                await _bot.send_message(chat_id, "ERROR: Failed find suitable video format",
                                                        reply_to_message_id=msg_id)
                                # await bot.send_message(chat_id, "ERROR: Failed find suitable video format", reply_to=msg_id)
                                return
                            # if 'playlist' in entry and entry['playlist'] is not None:
                            recover_playlist_index = ie
                            break
                        if chosen_format['ext'] == 'unknown_video':
                            mime = await av_utils.media_mime(chosen_format['url'], http_headers=http_headers)
                            ext = mimetypes.guess_extension(mime)
                            if ext is None or ext == '':
                                if len(preferred_formats) - 1 == ip:
                                    await _bot.send_message(chat_id, "ERROR: Failed find suitable video format",
                                                            reply_to_message_id=msg_id)
                                # await bot.send_message(chat_id, "ERROR: Failed find suitable video format", reply_to=msg_id)
                                continue
                            else:
                                ext = ext[1:]
                                if mime.split('/')[0] == 'audio' and ext == 'webm':
                                    # telegram treat webm audio as video
                                    # so use ogg ext to force audio
                                    chosen_format['ext'] = 'ogg'
                                else:
                                    chosen_format['ext'] = ext
                        if cmd == 'a':
                            # we don't know real size due to converting formats
                            # so increase it in case of real size is less large then estimated
                            file_size += 200000

                        log.debug('uploading file')

                        width = height = duration = None
                        if cmd == 'a':
                            if ('duration' not in entry and 'duration' not in chosen_format):
                                # info = await av_utils.av_info(chosen_format['url'],
                                #                               use_m3u8=('m3u8' in chosen_format['protocol']))
                                info = await av_utils.av_info(chosen_format['url'], http_headers=http_headers)
                                duration = int(float(info['format']['duration']))
                            else:
                                duration = int(entry['duration']) if 'duration' not in entry else int(entry['duration'])

                        elif ('duration' not in entry and 'duration' not in chosen_format) or \
                                ('width' not in chosen_format) or ('height' not in chosen_format):
                            # info =  await av_utils.av_info(chosen_format['url'],
                            #                                use_m3u8=('m3u8' in chosen_format['protocol']))
                            info = await av_utils.av_info(chosen_format['url'], http_headers=http_headers)
                            width = info['streams'][0]['width']
                            height = info['streams'][0]['height']
                            duration = info['format']['duration']
                        else:
                            width, height, duration = chosen_format['width'], chosen_format['height'], \
                                                      int(entry['duration']) if 'duration' not in entry else int(
                                                          entry['duration'])

                        # in case of video is live we don't know real duration
                        if cut_time_start is not None and not entry.get('is_live'):
                            if cut_time.time_to_seconds(cut_time_start) > duration:
                                raise Exception('Cut start time is bigger than all media duration')
                            if cut_time_end is not None and cut_time.time_to_seconds(cut_time_end) > duration:
                                raise Exception('Cut end time is bigger than all media duration')
                            if cut_time_end is None:
                                duration = duration - cut_time.time_to_seconds(cut_time_start)
                            else:
                                duration = cut_time.time_to_seconds(cut_time_end) - cut_time.time_to_seconds(cut_time_start)

                        if cut_time_start is not None and ffmpeg_av is None:
                            ffmpeg_av = await av_source.FFMpegAV.create(chosen_format,
                                                                        headers=http_headers,
                                                                        cut_time_range=_cut_time,
                                                                        ext=chosen_format.get('ext'))
                        upload_file = ffmpeg_av if ffmpeg_av is not None else await av_source.URLav.create(
                            chosen_format['url'],
                            http_headers)
                        file_name = entry['title'] + '.' + \
                                    (chosen_format[
                                         'ext'] if ffmpeg_av is None or ffmpeg_av.format is None else ffmpeg_av.format)
                        file_size = file_size if file_size != 0 and file_size < 1500 * 1024 * 1024 else 1500 * 1024 * 1024

                        ffmpeg_cancel_task = None
                        if ffmpeg_av is not None:
                            ffmpeg_cancel_task = asyncio.get_event_loop().call_later(4000, ffmpeg_av.safe_close)

                        file = await client.upload_file(upload_file,
                                                        file_name=file_name,
                                                        file_size=file_size,
                                                        http_headers=http_headers)

                        if ffmpeg_cancel_task is not None and not ffmpeg_cancel_task.cancelled():
                            ffmpeg_cancel_task.cancel()

                        if upload_file is not None:
                            if inspect.iscoroutinefunction(upload_file.close):
                                await upload_file.close()
                            else:
                                upload_file.close()

                        attributes = None
                        if cmd == 'a':
                            performer = entry['artist'] if ('artist' in entry) and \
                                                           (entry['artist'] is not None) else None
                            title = entry['alt_title'] if ('alt_title' in entry) and \
                                                          (entry['alt_title'] is not None) else entry['title']
                            attributes = DocumentAttributeAudio(duration, title=title, performer=performer)
                        else:
                            attributes = DocumentAttributeVideo(duration,
                                                                width,
                                                                height,
                                                                supports_streaming=False if ffmpeg_av is not None else True)
                        force_document = False
                        if ffmpeg_av is None and (chosen_format['ext'] != 'mp4' and cmd != 'a'):
                            force_document = True
                        log.debug('sending file')
                        video_note = False if cmd == 'a' or force_document else True
                        voice_note = True if cmd == 'a' else False
                        attributes = ((attributes,) if not force_document else None)
                        caption = entry['title'] if (user.default_media_type == users.DefaultMediaType.Video.value
                                                     and user.video_caption) or \
                                                    (((user.default_media_type == users.DefaultMediaType.Audio.value) or
                                                      (cmd == 'a'))
                                                     and user.audio_caption) else ''
                        recover_playlist_index = None
                        _thumb = await thumb.get_thumbnail(entry)
                        for i in range(10):
                            try:
                                await client.send_file(bot_entity, file,
                                                       video_note=video_note,
                                                       voice_note=voice_note,
                                                       attributes=attributes,
                                                       caption=str(chat_id) + ":" + str(msg_id) + ":" + caption,
                                                       force_document=force_document,
                                                       supports_streaming=False if ffmpeg_av is not None else True,
                                                       thumb=_thumb)
                            except Exception as e:
                                log.exception(e)
                                await asyncio.sleep(1)
                            finally:
                                break
                    except Exception as e:
                        log.exception(e)
                        if len(entries) - 1 == ie:
                            # raise exception for notify user about error
                            raise

                if recover_playlist_index is None:
                    break


api_id = int(os.environ['API_ID'])
api_hash = os.environ['API_HASH']

BOT_AGENT_CHAT_ID = int(os.environ['BOT_AGENT_CHAT_ID'])

# YTDL_LAMBDA_URL = os.environ['YTDL_LAMBDA_URL']
# YTDL_LAMBDA_SECRET = os.environ['YTDL_LAMBDA_SECRET']

client = TelegramClient(StringSession(get_client_session()), api_id, api_hash)
# bot = TelegramClient('bot', api_id, api_hash).start(bot_token=os.environ['BOT_TOKEN'])
_bot = Bot(token=os.environ['BOT_TOKEN'])
bot_entity = None

vid_format = '((best[ext=mp4,height<=1080]+best[ext=mp4,height<=480])[protocol^=http]/best[ext=mp4,height<=1080]+best[ext=mp4,height<=480]/best[ext=mp4]+worst[ext=mp4]/best[ext=mp4]/(bestvideo[ext=mp4,height<=1080]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]))[protocol^=http]/bestvideo[ext=mp4]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/best)[protocol!=http_dash_segments]'
vid_fhd_format = '((best[ext=mp4][height<=1080][height>720])[protocol^=http]/best[ext=mp4][height<=1080][height>720]/bestvideo[ext=mp4][height<=1080][height>720]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/  (best[ext=mp4][height<=720][height>360])[protocol^=http]/best[ext=mp4][height<=720][height>360]/bestvideo[ext=mp4][height<=720][height>360]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4]) /  (best[ext=mp4][height<=360])[protocol^=http]/best[ext=mp4][height<=360]/bestvideo[ext=mp4][height<=360]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/   best[ext=mp4]   /bestvideo[ext=mp4]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/best)[protocol!=http_dash_segments]'
vid_hd_format = '((best[ext=mp4][height<=720][height>360])[protocol^=http]/best[ext=mp4][height<=720][height>360]/bestvideo[ext=mp4][height<=720][height>360]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4]) /  (best[ext=mp4][height<=360])[protocol^=http]/best[ext=mp4][height<=360]/bestvideo[ext=mp4][height<=360]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/   best[ext=mp4]   /bestvideo[ext=mp4]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/best)[protocol!=http_dash_segments]'
vid_nhd_format = '((best[ext=mp4][height<=360])[protocol^=http]/best[ext=mp4][height<=360]/bestvideo[ext=mp4][height<=360]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/   best[ext=mp4]   /bestvideo[ext=mp4]+(bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=mp4])/best)[protocol!=http_dash_segments]'
worst_video_format = 'best[ext=mp4,height<=360]/bestvideo[ext=mp4,height<=360]+bestaudio[ext=m4a]/best'
audio_format = '((bestaudio[ext=m4a]/bestaudio[ext=mp3])[protocol^=http]/bestaudio/best[ext=mp4,height<=480]/best[ext=mp4]/best)[protocol!=http_dash_segments]'

url_extractor = URLExtract()

playlist_range_re = re.compile('([0-9]+)-([0-9]+)')
playlist_cmds = ['p', 'pa', 'pw']
available_cmds = ['start', 'ping', 'settings', 'a', 'w', 'c'] + playlist_cmds

TG_MAX_FILE_SIZE = 1500


async def init_bot_enitty():
    try:
        global bot_entity
        bot_entity = await client.get_input_entity(os.environ['CHAT_WITH_BOT_ID'])
    except Exception as e:
        print(e)


async def abort():
    await client.disconnect()
    os.abort()


if __name__ == '__main__':
    app = web.Application()
    app.add_routes([web.post('/bot', on_message)])
    client.start()
    # asyncio.get_event_loop().create_task(bot._run_until_disconnected())
    asyncio.get_event_loop().create_task(init_bot_enitty())
    asyncio.get_event_loop().add_signal_handler(signal.SIGABRT, client.disconnect)
    asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, client.disconnect)
    asyncio.get_event_loop().create_task(web.run_app(app))
    client.run_until_disconnected()
