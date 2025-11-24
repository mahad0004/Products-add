"""
Image Processor
Handles image extraction, downloading, and processing
"""

import requests
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Handles image processing operations"""

    def __init__(self):
        self.timeout = 30

    def extract_image_urls(self, product) -> List[str]:
        """
        Extract image URLs from product data
        Replicates Code in JavaScript3 and Code in JavaScript7 logic
        """
        urls = []

        # Check original data first
        original = product.get('_original') or product

        # Extract from various fields
        fields_to_check = [
            'extractedUrls',
            'image_url',
            'imageUrl',
            'image',
            'images',
            'medias',
            'media'
        ]

        for field in fields_to_check:
            data = original.get(field)

            if not data:
                continue

            # Handle arrays
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.startswith('http'):
                        urls.append(item)
                    elif isinstance(item, dict):
                        # Check for Image type (Shopify format)
                        if item.get('type') == 'Image' and item.get('url'):
                            urls.append(item['url'])
                        # Check for url field
                        elif item.get('url'):
                            urls.append(item['url'])
                        elif item.get('src'):
                            urls.append(item['src'])

            # Handle strings
            elif isinstance(data, str) and data.startswith('http'):
                urls.append(data)

            # Handle objects
            elif isinstance(data, dict):
                if data.get('url'):
                    urls.append(data['url'])
                elif data.get('src'):
                    urls.append(data['src'])

        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        logger.info(f"Extracted {len(unique_urls)} image URLs")
        return unique_urls

    def download_image(self, url: str, max_retries: int = 3) -> Optional[bytes]:
        """
        Download an image from a URL
        Returns: image bytes or None on failure
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading image (attempt {attempt + 1}/{max_retries}): {url}")

                response = requests.get(
                    url,
                    timeout=self.timeout,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )

                response.raise_for_status()

                # Check content type
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    logger.warning(f"URL does not return an image: {content_type}")
                    return None

                image_data = response.content

                # Basic validation
                if len(image_data) < 1000:  # Less than 1KB is suspicious
                    logger.warning(f"Downloaded image is too small: {len(image_data)} bytes")
                    return None

                logger.info(f"Successfully downloaded image: {len(image_data)} bytes")
                return image_data

            except requests.RequestException as e:
                logger.error(f"Error downloading image (attempt {attempt + 1}): {str(e)}")

                if attempt == max_retries - 1:
                    return None

        return None

    def validate_image(self, image_data: bytes) -> bool:
        """
        Validate that image data is a valid image
        """
        if not image_data or len(image_data) < 1000:
            return False

        # Check for common image format signatures
        signatures = [
            b'\xff\xd8\xff',  # JPEG
            b'\x89PNG',       # PNG
            b'GIF87a',        # GIF
            b'GIF89a',        # GIF
            b'RIFF',          # WebP (partial)
        ]

        for sig in signatures:
            if image_data.startswith(sig):
                return True

        return False

    def get_image_dimensions(self, image_data: bytes) -> tuple:
        """
        Get image dimensions
        Returns: (width, height) or (0, 0) if unable to determine
        """
        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(image_data))
            return image.size

        except Exception as e:
            logger.error(f"Error getting image dimensions: {str(e)}")
            return (0, 0)

    def resize_image(self, image_data: bytes, max_width: int = 2048, max_height: int = 2048) -> bytes:
        """
        Resize image if it exceeds max dimensions
        """
        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(image_data))

            # Check if resize is needed
            if image.width <= max_width and image.height <= max_height:
                return image_data

            # Calculate new dimensions maintaining aspect ratio
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # Save to bytes
            output = io.BytesIO()
            image.save(output, format=image.format or 'JPEG', quality=90)
            output.seek(0)

            resized_data = output.read()
            logger.info(f"Image resized from {image.size} to {(max_width, max_height)}")

            return resized_data

        except Exception as e:
            logger.error(f"Error resizing image: {str(e)}")
            return image_data

    def optimize_image(self, image_data: bytes, quality: int = 85) -> bytes:
        """
        Optimize image for web by reducing quality/size
        """
        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(image_data))

            # Convert to RGB if necessary (for JPEG)
            if image.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background

            # Save with optimization
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=quality, optimize=True)
            output.seek(0)

            optimized_data = output.read()

            logger.info(f"Image optimized: {len(image_data)} -> {len(optimized_data)} bytes "
                       f"({(1 - len(optimized_data)/len(image_data))*100:.1f}% reduction)")

            return optimized_data

        except Exception as e:
            logger.error(f"Error optimizing image: {str(e)}")
            return image_data
