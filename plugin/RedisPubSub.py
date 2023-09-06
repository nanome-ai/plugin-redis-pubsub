import asyncio
import pickle
import os
import random
import string
import redis.asyncio as redis
import sys
import time

import nanome
from nanome.util import Logs
from nanome.util.enums import NotificationTypes, PluginListButtonType
from nanome.api import ui
from nanome.beta.nanome_sdk import NanomePlugin


BASE_PATH = os.path.dirname(f'{os.path.realpath(__file__)}')
MENU_PATH = os.path.join(BASE_PATH, 'default_menu.json')

REDIS_HOST = os.environ.get('REDIS_HOST')
REDIS_PORT = os.environ.get('REDIS_PORT')
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')


sys.setrecursionlimit(1000000)

class RedisPubSubPlugin(NanomePlugin):

    async def on_start(self):
        redis_channel = os.environ.get('REDIS_CHANNEL')
        # Create random channel name if not explicitly set.
        if not redis_channel:
            redis_channel = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        self.redis_channel = redis_channel
        Logs.message(f"Starting {self.__class__.__name__} on Redis Channel {self.redis_channel}")
        self.streams = []
        self.shapes = []
        self.rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)
        self._tasks = []

    async def on_run(self):
        default_url = os.environ.get('DEFAULT_URL')
        if default_url:
            url = default_url
            Logs.message(f'Opening {url}')
            self.open_url(url)
        # Render menu with room name on it
        self.menu = ui.Menu()
        id_node = self.menu.root.create_child_node()
        id_node.add_new_label(f'Room ID: {self.redis_channel}')
        text_node = self.menu.root.create_child_node()
        text_node.add_new_label('Use this code to access your workspace')
        self.menu.enabled = True
        Logs.message("Polling for requests")
        self.client.set_plugin_list_button(PluginListButtonType.run, text='Live', usable=False)
        self.client.update_menu(self.menu)
        self.poll_task = asyncio.create_task(self.poll_redis_for_requests(self.redis_channel))

    async def poll_redis_for_requests(self, redis_channel):
        """Start a non-halting loop polling for and processing Plugin Requests.

        Subscribe to provided redis channel, and process any requests received.
        """
        pubsub = self.rds.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(redis_channel)

        while True:
            # Check if any new messages have been received
            message = await pubsub.get_message()
            if not message:
                continue
            if message.get('type') == 'message':
                new_task = asyncio.create_task(self.process_message(message))
                self._tasks.append(new_task)
                self._tasks = [task for task in self._tasks if not task.done()]

    async def process_message(self, message):
        """Deserialize message and forward request to NTS."""
        process_start_time = time.time()
        try:
            message_data = pickle.loads(message.get('data'))
        except Exception:
            error_message = 'Pickle Decode Failure'
            self.client.send_notification(NotificationTypes.error, error_message)
            return
        fn_name = message_data['function']
        response_channel = message_data.get('response_channel')
        Logs.message(f"Received Request: {fn_name}")

        if fn_name == 'get_plugin_data':
            response = self.get_plugin_data()
            pickled_response = pickle.dumps(response)
            if response_channel:
                Logs.message(f'Publishing Response to {response_channel}')
                await self.rds.publish(response_channel, pickled_response)

        else:
            request_id = message_data.get('request_id')
            packet = message_data.get('packet')
            response_channel = message_data.get('response_channel')
            response = await self.send_packet_to_nts(request_id, packet, response_channel)
            if not response_channel:
                return
            pickled_response = pickle.dumps(response)
            if response_channel:
                Logs.message(f'Publishing Response to {response_channel}')
                await self.rds.publish(response_channel, pickled_response)
            else:
                Logs.warning('No response channel provided, response will not be sent')
            process_end_time = time.time()
            elapsed_time = process_end_time - process_start_time
            Logs.message(f'Message processed after {round(elapsed_time, 2)} seconds')

    async def send_packet_to_nts(self, request_id, packet, response_channel):
        # Store future to receive any response required
        if response_channel:
            fut = asyncio.Future()
            self.client.request_futs[request_id] = fut

        self.client.writer.write(packet)

        if response_channel:
            await self.client.request_futs[request_id]
            Logs.debug("Responses received")
            response = fut.result()
            return response

    def stream_update(self, stream_id, stream_data):
        """Function to update stream."""
        stream = next(strm for strm in self.streams if strm._Stream__id == stream_id)
        output = stream.update(stream_data)
        return output

    def stream_destroy(self, stream_id):
        """Function to destroy stream."""
        stream = next(strm for strm in self.streams if strm._Stream__id == stream_id)
        output = stream.destroy()
        return output

    async def upload_shapes(self, shape_list):
        for shape in shape_list:
            Logs.message(shape.index)
        response = await nanome.api.shapes.Shape.upload_multiple(shape_list)
        self.shapes.extend(response)
        for shape in shape_list:
            Logs.message(shape.index)
        return shape_list

    def get_plugin_data(self):
        """Return data required for interface to serialize message requests."""
        plugin_id = self.client.plugin_id
        session_id = self.client.session_id
        version_table = self.client.version_table
        data = {
            'plugin_id': plugin_id,
            'session_id': session_id,
            'version_table': version_table
        }
        return data
