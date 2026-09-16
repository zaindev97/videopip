"""Optional YouTube upload using the user's OWN Google Cloud OAuth client.

Tokens are stored in ~/.videopip/youtube-token.json. Nothing is uploaded unless
the user runs `videopip upload`; the default privacy is private.
"""
from __future__ import annotations

from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
TOKEN = Path.home() / ".videopip" / "youtube-token.json"


def _service(client_secret: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise SystemExit('YouTube upload needs extras: pip install "videopip[youtube]"') from e
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.parent.mkdir(parents=True, exist_ok=True)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload_video(video: Path, title: str, description: str, tags: list[str], privacy: str,
                 client_secret: Path, thumbnail: Path | None = None) -> str:
    from googleapiclient.http import MediaFileUpload
    yt = _service(client_secret)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags, "categoryId": "28"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  uploaded {int(status.progress() * 100)}%")
    vid = resp["id"]
    if thumbnail:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail))).execute()
    return vid
