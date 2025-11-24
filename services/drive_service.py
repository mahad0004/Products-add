"""
Google Drive Service
Handles Google Drive API interactions for image hosting
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import logging

logger = logging.getLogger(__name__)


class DriveService:
    """Service for interacting with Google Drive API"""

    def __init__(self, credentials_path):
        self.credentials_path = credentials_path
        self.folder_id = "1v9pw6JLXmAhjnvHGtd1kcGm5hgEkkRM2"  # From N8N workflow

        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=['https://www.googleapis.com/auth/drive']
            )
            self.service = build('drive', 'v3', credentials=credentials)
        except Exception as e:
            logger.error(f"Error initializing Google Drive service: {str(e)}")
            self.service = None

    def upload_and_share(self, image_data, filename):
        """
        Upload an image to Google Drive and make it publicly accessible
        Returns: public URL of the uploaded file
        """
        if not self.service:
            logger.error("Google Drive service not initialized")
            return None

        try:
            # Prepare file metadata
            file_metadata = {
                'name': filename,
                'parents': [self.folder_id]
            }

            # Create media upload
            media = MediaIoBaseUpload(
                io.BytesIO(image_data),
                mimetype='image/jpeg',
                resumable=True
            )

            # Upload file
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink, webContentLink'
            ).execute()

            file_id = file.get('id')
            logger.info(f"File uploaded to Google Drive: {file_id}")

            # Make file publicly accessible
            self.service.permissions().create(
                fileId=file_id,
                body={
                    'type': 'anyone',
                    'role': 'reader'
                }
            ).execute()

            # Get direct download link
            direct_link = f"https://drive.google.com/uc?export=view&id={file_id}"

            logger.info(f"File shared publicly: {direct_link}")
            return direct_link

        except Exception as e:
            logger.error(f"Error uploading to Google Drive: {str(e)}")
            return None

    def delete_file(self, file_id):
        """Delete a file from Google Drive"""
        if not self.service:
            return False

        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"File deleted: {file_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return False
