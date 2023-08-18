import asyncio
import functools
import inspect
import json
import os
import random
import string
import redis
import time
import threading

import nanome
from nanome._internal.serializer_fields import TypeSerializer
from nanome.util import async_callback, Logs
from nanome.util.enums import NotificationTypes, PluginListButtonType
from marshmallow import Schema, fields

from nanome.api import schemas, ui
from nanome.beta.nanome_sdk import NanomePlugin
from nanome.api.schemas.api_definitions import api_function_definitions

BASE_PATH = os.path.dirname(f'{os.path.realpath(__file__)}')
MENU_PATH = os.path.join(BASE_PATH, 'default_menu.json')

REDIS_HOST = os.environ.get('REDIS_HOST')
REDIS_PORT = os.environ.get('REDIS_PORT')
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')


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

        self.rds = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            decode_responses=True)

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
        await self.poll_redis_for_requests(self.redis_channel)

    async def poll_redis_for_requests(self, redis_channel):
        """Start a non-halting loop polling for and processing Plugin Requests.

        Subscribe to provided redis channel, and process any requests received.
        """
        pubsub = self.rds.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(redis_channel)

        while True:
            # Check if any new messages have been received
            message = pubsub.get_message()
            if not message:
                continue
            if message.get('type') == 'message':
                new_task = asyncio.create_task(self.process_message(message))
                self._tasks.append(new_task)

    async def process_message(self, message):
        """Deserialize message and forward request to NTS."""
        process_start_time = time.time()
        try:
            data = json.loads(message.get('data'))
        except json.JSONDecodeError:
            error_message = 'JSON Decode Failure'
            self.send_notification(NotificationTypes.error, error_message)

        Logs.message(f"Received Request: {data.get('function')}")
        fn_name = data['function']
        serialized_args = data['args']
        response_channel = data.get('response_channel')
        fn_definition = api_function_definitions[fn_name]
        fn_args = []
        fn_kwargs = {}

        # Deserialize args and kwargs into python classes
        for ser_arg, schema_or_field in zip(serialized_args, fn_definition.params):
            if isinstance(schema_or_field, Schema):
                arg = schema_or_field.load(ser_arg)
            elif isinstance(schema_or_field, fields.Field):
                # Field that does not need to be deserialized
                arg = schema_or_field.deserialize(ser_arg)
            fn_args.append(arg)
        function_to_call = getattr(self.client, fn_name)

        # Set up callback function
        argspec = inspect.getargspec(function_to_call)
        callback_fn = None
        if 'callback' in argspec.args:
            callback_fn = functools.partial(
                self.message_callback, fn_definition, response_channel, process_start_time)
            fn_args.append(callback_fn)
        # Call API function
        function_to_call(*fn_args, **fn_kwargs)
        if not callback_fn:
            # If no callback function, send a success notification
            success_message = f'Successfully called {fn_name}'
            process_end_time = time.time()
            elapsed_time = process_end_time - process_start_time
            Logs.message(f'{success_message} in {round(elapsed_time, 2)} seconds')

    def message_callback(self, fn_definition, response_channel, process_start_time, *responses):
        """When response data received from NTS, serialize and publish to response channel."""
        output_schema = fn_definition.output
        serialized_response = {}
        if len(responses) == 1:
            response = responses[0]
        else:
            # Some functions return multiple values, like create_writing_stream
            # We only care about the first response
            response, _ = responses[0], responses[1:]

        if output_schema:
            if isinstance(output_schema, Schema):
                serialized_response = output_schema.dump(response)
            elif isinstance(output_schema, fields.Field):
                # Field that does not need to be deserialized
                serialized_response = output_schema.serialize(response)

        if fn_definition.__class__.__name__ == 'CreateWritingStream':
            Logs.message("Saving Stream to Plugin Instance")
            if response:
                self.streams.append(response)
            else:
                Logs.error("Error creating stream")

        json_response = json.dumps(serialized_response)
        if response_channel:
            Logs.message(f'Publishing Response to {response_channel}')
            self.rds.publish(response_channel, json_response)
        else:
            Logs.warning('No response channel provided, response will not be sent')
        process_end_time = time.time()
        elapsed_time = process_end_time - process_start_time
        Logs.message(f'Message processed after {round(elapsed_time, 2)} seconds')

    def deserialize_arg(self, arg_data):
        """Deserialize arguments recursively."""
        if isinstance(arg_data, list):
            for arg_item in arg_data:
                self.deserialize_arg(arg_item)
        if arg_data.__class__ in schemas.structure_schema_map:
            schema_class = schemas.structure_schema_map[arg_data.__class__]
            schema = schema_class()
            arg = schema.load(arg_data)
        return arg

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
        plugin_id = self._network._plugin_id
        session_id = self._network._session_id
        version_table = TypeSerializer.get_version_table()
        data = {
            'plugin_id': plugin_id,
            'session_id': session_id,
            'version_table': version_table
        }
        return data

    @property
    def request_futs(self):
        return self.client.request_futs
