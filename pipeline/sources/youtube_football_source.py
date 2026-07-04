from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import subprocess
from pathlib import Path

from pipeline.path_utils import canonical_path

# ----------------------------
# USE STABLE YOUTUBE SCOPE
# ----------------------------
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


# ----------------------------
# PROJECT ROOT
# ----------------------------
def get_project_root():
    return canonical_path(__file__).parents[2]


def get_paths():
    root = get_project_root()

    client_secret_path = root / "pipeline" / "upload" / "client_secret.json"
    token_path = root / "pipeline" / "upload" / "token.pickle"

    return client_secret_path, token_path


# ----------------------------
# AUTH FLOW (CLEAN + STABLE)
# ----------------------------
def get_youtube_client():

    creds = None
    client_secret_path, token_path = get_paths()

    # load existing token if available
    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    # refresh or login
    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret_path),
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)

        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ----------------------------
# SEARCH FOOTBALL VIDEOS
# ----------------------------
def search_football_videos(query="football highlights today", max_results=5):

    youtube = get_youtube_client()

    request = youtube.search().list(
        q=query,
        part="id,snippet",
        maxResults=max_results,
        type="video",
        order="date"
    )

    response = request.execute()

    videos = []

    for item in response.get("items", []):
        vid = item["id"].get("videoId")
        if vid:
            videos.append({
                "title": item["snippet"]["title"],
                "video_id": vid
            })

    return videos


# ----------------------------
# DOWNLOAD VIDEO
# ----------------------------
def download_video(video_id, output_path):

    url = f"https://www.youtube.com/watch?v={video_id}"

    subprocess.run([
        "yt-dlp",
        "-f", "mp4",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ], check=True)

    return output_path


# ----------------------------
# MAIN PIPELINE ENTRY
# ----------------------------
def get_latest_football_clip(work_dir: Path):

    highlights_dir = work_dir / "highlights"
    highlights_dir.mkdir(parents=True, exist_ok=True)

    videos = search_football_videos()

    if not videos:
        raise Exception("No football videos found")

    video = videos[0]

    output_file = highlights_dir / "source.mp4"

    download_video(video["video_id"], str(output_file))

    return str(output_file)
