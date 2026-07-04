"""
YouTube Shorts Upload Module (REAL VERSION - OAuth)
AFOS Live Publisher
"""

from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os


class YouTubeUploadError(Exception):
    pass


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_service():
    """
    Handles OAuth login + token storage
    """

    creds = None
    token_path = "pipeline/upload/token.pickle"
    client_secret = "pipeline/upload/client_secret.json"

    # Load existing token
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    # If no valid creds → login
    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret):
                raise YouTubeUploadError("client_secret.json missing")

            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret,
                SCOPES
            )

            creds = flow.run_local_server(port=0)

        # Save token
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path: str, title: str, description: str):
    """
    REAL YouTube upload
    """

    video = Path(video_path)

    if not video.exists():
        raise YouTubeUploadError("Video file not found")

    youtube = _get_service()

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public"
        }
    }

    media = MediaFileUpload(str(video), chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )

    response = request.execute()

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"

    print("\n🚀 REAL UPLOAD SUCCESS")
    print(f"Title: {title}")
    print(f"Video: {video_path}")
    print(f"URL: {url}")

    return {
        "video_id": video_id,
        "url": url
    }