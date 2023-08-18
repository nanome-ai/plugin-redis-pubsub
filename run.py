import os
import asyncio
from nanome.beta.nanome_sdk.plugin_server import PluginServer

from plugin.RedisPubSub import RedisPubSubPlugin


def main():
    server = PluginServer()
    host = os.environ['NTS_HOST']
    port = int(os.environ['NTS_PORT'])
    default_name = 'Redis API'
    plugin_name = os.environ.get('PLUGIN_NAME') or default_name

    default_description = 'Interact with your Nanome session via our Redis API.'
    description = os.environ.get('PLUGIN_DESCRIPTION') or default_description
    plugin_class = RedisPubSubPlugin
    asyncio.run(server.run(host, port, plugin_name, description, plugin_class))


if __name__ == '__main__':
    main()
