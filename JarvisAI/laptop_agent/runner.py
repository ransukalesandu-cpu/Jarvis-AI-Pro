"""Assemble and run the agent: config, ADB, tool host, hub connection."""
from __future__ import annotations

import asyncio


async def run_agent(config=None) -> None:
    from laptop_agent.genai_shim import install
    install()                       # before any tool imports google.genai
    from core.user_data import user_data_dir
    from laptop_agent.android_tools import AndroidTools
    from laptop_agent.client import AgentClient
    from laptop_agent.config import load_agent_config
    from laptop_agent.devices.android import AndroidManager
    from laptop_agent.tool_host import ToolHost

    config = config or load_agent_config()
    if not config.token:
        print("This agent is not paired yet. Run: python -m laptop_agent pair <URL printed by the hub>")
        return
    manager = AndroidManager([])
    host = ToolHost(AndroidTools(manager), state_dir=user_data_dir())
    host.load_declarations()
    local_audio = None
    if config.local_audio:
        from laptop_agent.local_audio import LocalAudio
        local_audio = LocalAudio()
    client = AgentClient(config, host, manager, local_audio)
    extras = []
    try:
        from laptop_agent.files import FileServer
        client.file_server = FileServer(client)
    except ImportError:
        pass
    if config.keep_awake:
        try:
            from laptop_agent.keep_awake import keep_awake
            extras.append(keep_awake())
        except ImportError:
            pass
    if local_audio is not None:
        local_audio.start(client)
    relay = None
    if config.relay_port:
        from laptop_agent.relay import start_relay
        relay = await start_relay(config.hub_url, int(config.relay_port))
    try:
        await client.run()
    finally:
        client.stop_event.set()
        if relay is not None:
            relay.close()
        for item in extras:
            if hasattr(item, "release"):
                item.release()
        await asyncio.sleep(0)
