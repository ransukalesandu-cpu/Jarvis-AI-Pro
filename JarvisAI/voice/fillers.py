"""
Jarvis AI Pro - Natural Conversational Acknowledgment Engine
Prevents dead silence during network latency or heavy computations.
"""

import random

TASK_FILLERS = {
    "radar": [
        "Scanning nearby airspace now, Sir.",
        "Querying transponder frequencies.",
        "Retrieving flight vectors."
    ],
    "system": [
        "Running diagnostics on local cores.",
        "Accessing system telemetry.",
        "Checking hardware status."
    ],
    "web": [
        "Interrogating the network, one moment.",
        "Accessing online data streams.",
        "Pulling relevant intelligence now, Sir."
    ],
    "default": [
        "Right away, Sir.",
        "On it.",
        "One moment, Sir.",
        "Analyzing parameters now."
    ]
}

def get_filler_phrase(category: str = "default") -> str:
    phrases = TASK_FILLERS.get(category, TASK_FILLERS["default"])
    return random.choice(phrases)
