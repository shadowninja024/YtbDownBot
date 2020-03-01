
from cloudant.adapters import Replay429Adapter
from cloudant.client import Cloudant
import os
import asyncio
from enum import Enum


class VideoFormat(Enum):
    LOW = 360
    MED = 720
    HIGH = 1080


class DefaultMediaType(Enum):
    Video = 0
    Audio = 1


class User:
    def __init__(self):
        self.settings = None

    @staticmethod
    async def init(id):
        user = User()
        user_settings = await asyncio.get_event_loop().run_in_executor(None, get_user, id)
        if user_settings != None:
            user.settings = user_settings
            return user
        user_id = 'user'+str(id)
        user_settings = {
            '_id': user_id,
            'default_media_type': DefaultMediaType.Video.value,
            'video_format': VideoFormat.MED.value,
            'audio_caption': False,
            'video_caption': False
        }
        user_settings = await asyncio.get_event_loop().run_in_executor(None, create_user, user_settings)
        user.settings = user_settings

        return user

    @property
    def default_media_type(self):
        return self.settings['default_media_type']

    async def set_default_media_type(self, m_type):
        self.settings['default_media_type'] = m_type.value
        await asyncio.get_event_loop().run_in_executor(None, self.settings.save)

    @property
    def video_format(self):
        return self.settings['video_format']

    async def set_video_format(self, vid_format):
        self.settings['video_format'] = vid_format.value
        await asyncio.get_event_loop().run_in_executor(None, self.settings.save)

    @property
    def audio_caption(self):
        return self.settings['audio_caption']

    async def set_audio_caption(self, toggle):
        self.settings['audio_caption'] = toggle
        await asyncio.get_event_loop().run_in_executor(None, self.settings.save)

    @property
    def video_caption(self):
        return self.settings['video_caption']

    async def set_video_caption(self, toggle):
        self.settings['video_caption'] = toggle
        await asyncio.get_event_loop().run_in_executor(None, self.settings.save)


client = Cloudant(os.environ['CLOUDANT_USERNAME'],
                  os.environ['CLOUDANT_PASSWORD'],
                  url=os.environ['CLOUDANT_URL'],
                  adapter=Replay429Adapter(retries=10),
                  connect=True)


def get_user(id):
    db = client['ytbdownbot']
    user_id = 'user' + str(id)
    if user_id in db:
        return db[user_id]
    else:
        return None


def create_user(user):
    db = client['ytbdownbot']
    return db.create_document(user)
