import os
import nanome

from plugin.RedisPubSub import RedisPubSubPlugin
from nanome.api import Plugin


def main():
    parser = Plugin.create_parser()
    args, _ = parser.parse_known_args()

    default_name = 'Redis API'
    arg_name = args.name or []
    plugin_name = ' '.join(arg_name) or default_name

    default_description = 'Interact with your Nanome session via our Redis API.'
    description = os.environ.get('PLUGIN_DESCRIPTION') or default_description
    tags = ['Interactions']

    plugin = nanome.Plugin(plugin_name, description, tags)
    plugin.set_plugin_class(RedisPubSubPlugin)
    plugin.run()


if __name__ == '__main__':
    main()
