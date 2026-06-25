"""Google Drive MCP server.

Exposes a single write tool over stdio:
  - upload_text_file(filename, content, folder_id, mime_type) -> confirmation with file id + link

Authentication uses the OAuth "installed app" flow with the narrow drive.file scope
(the app can only see/manage files it creates). On first use it opens a browser to sign in
and caches a token so later runs are non-interactive.

Bootstrap the sign-in once before running the pipeline:
    python mcp_servers/gdrive_server.py --auth
"""

import io
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from mcp.server.fastmcp import FastMCP

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = os.environ.get("GDRIVE_CREDENTIALS", "credentials.json")
TOKEN_FILE = os.environ.get("GDRIVE_TOKEN", "token.json")

mcp = FastMCP("gdrive")


def _build_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Google OAuth client secret not found at '{CREDENTIALS_FILE}'. "
                    "Download it from Google Cloud Console (OAuth client, type 'Desktop app')."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


@mcp.tool()
def upload_text_file(
    filename: str,
    content: str,
    folder_id: str = "",
    mime_type: str = "text/markdown",
) -> str:
    """Create a text file in Google Drive with the given content.

    If folder_id is provided the file is placed in that folder, otherwise in My Drive root.
    Returns a confirmation containing the new file's id and shareable link.
    """
    service = _build_service()
    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")), mimetype=mime_type, resumable=False
    )
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )
    return (
        f"Uploaded '{created.get('name')}' "
        f"(id={created.get('id')}) {created.get('webViewLink', '')}".strip()
    )


if __name__ == "__main__":
    if "--auth" in sys.argv:
        _build_service()
        print(f"Authenticated. Token cached at {TOKEN_FILE}.")
    else:
        mcp.run()
