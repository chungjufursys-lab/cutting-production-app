import io
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import streamlit as st

DRIVE_FOLDER_ID = "1IqdyN-PptGWpOFaDFoah5QcyUMmzvDbl"

def get_drive_service():
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    return build("drive", "v3", credentials=creds)

def upload_file(file_bytes, filename, mime):
    service = get_drive_service()

    metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mime,
        resumable=False,
    )

    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id"
    ).execute()

    return file.get("id")

def generate_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"

def cleanup_old_files(days=10):
    service = get_drive_service()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"

    query = f"'{DRIVE_FOLDER_ID}' in parents and createdTime < '{cutoff}'"

    results = service.files().list(q=query, fields="files(id)").execute()
    for file in results.get("files", []):
        service.files().delete(fileId=file["id"]).execute()
