"""
AFOS Routing Engine
Decides: WHAT → WHERE → WHICH ACCOUNT
"""

from dataclasses import dataclass


# ----------------------------
# ACCOUNT STRUCTURE
# ----------------------------

ACCOUNTS = {
    "youtube": {
        "football": "yt_football_main",
        "minecraft": "yt_minecraft_main",
    },
    "tiktok": {
        "football": "tt_football_01",
        "minecraft": "tt_minecraft_01",
    },
    "instagram": {
        "football": "ig_football_main",
        "minecraft": "ig_minecraft_main",
    }
}


# ----------------------------
# ROUTING LOGIC
# ----------------------------

def detect_content_type(topic: str) -> str:
    topic = topic.lower()

    if "football" in topic or "soccer" in topic:
        return "football"

    if "minecraft" in topic:
        return "minecraft"

    return "general"


def select_platforms(content_type: str) -> list[str]:
    """
    Decide where content should go
    """
    if content_type == "football":
        return ["youtube", "tiktok", "instagram"]

    if content_type == "minecraft":
        return ["youtube", "tiktok"]

    return ["youtube"]


def route(topic: str) -> dict:
    """
    MAIN ENTRY POINT
    """

    content_type = detect_content_type(topic)
    platforms = select_platforms(content_type)

    routing_plan = []

    for platform in platforms:
        account = ACCOUNTS[platform].get(content_type)

        if account:
            routing_plan.append({
                "topic": topic,
                "content_type": content_type,
                "platform": platform,
                "account": account
            })

    return {
        "routing_plan": routing_plan
    }