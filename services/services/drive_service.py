import io
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import streamlit as st

DRIVE_FOLDER_ID = "1IqdyN-PptGWpOFaDFoah5QcyUMmzvDbl"

def get_drive_service():
    scope = [
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    return build("drive", "v3", credentials=creds)


def upload_pdf_to_drive(file_bytes, filename):
    service = get_drive_service()

    file_metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype="application/pdf",
        resumable=False,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    return file.get("id")


def delete_drive_file(file_id):
    service = get_drive_service()
    service.files().delete(fileId=file_id).execute()


def generate_drive_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"
