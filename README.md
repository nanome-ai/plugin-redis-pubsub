# Redis Pubsub interface for Nanome Workspaces

Nanome is an immersive XR platform for collaborative computationally-driven molecular design. Learn more about Nanome at https://nanome.ai.

This plugin creates an interface for interacting with your workspace via Redis PubSub messages. This enables simpler programmatic communication between applications. For example, Nanome's Jupyter notebooks communicate with your workspace via this interface. (https://github.com/nanome-ai/plugin-cookbook)

## Installation

### Requirements:
- Docker (https://docs.docker.com/get-docker/)
- Docker Compose (https://docs.docker.com/compose/install/)
- nanome-lib[schemas] (`pip install nanome-lib[schemas]`) (schemas adds extra tools for working with Nanome's JSON schemas)

### Clone, Build, and deploy
1) Use Git to clone this repository to your computer.
```sh
git clone https://github.com/nanome-ai/plugin-redis-pubsub.git
````

2) Create .env file, containing NTS connection values, as well as credentials for a running Redis instance
```sh
cp .env.sample .env
```

3) Build and deploy
```sh
python run.py
```

## Redis RPC architecture
- `plugin` container runs your standard plugin instance. When activated in Nanome, a room id is assigned, and the plugin subscribes to a unique Redis channel corresponding to the room id. The plugin starts polling, waiting to receive messages containing info on what function to run.

```
{
  "function": <function_name>
  "args": [...],
  "kwargs": {...},
  "response_channel": "uuid4()"
}
```

![alt text](assets/pubsub.png)

## Contributors
@mjrosengrant
@ajm13
