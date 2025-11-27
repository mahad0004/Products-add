"""
Google Gemini Service with Nano Banana Image Editing
Handles Google Gemini API interactions for image generation and editing
"""

from google import genai
from google.genai import types
from PIL import Image
import io
import logging
import base64
import requests
import threading
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)


class GeminiQuotaExhaustedError(Exception):
    """Raised when Gemini API quota is exhausted"""
    def __init__(self, message, reset_time=None):
        super().__init__(message)
        self.reset_time = reset_time


class GeminiService:
    """Service for interacting with Google Gemini API (Nano Banana) with multi-key rotation"""

    def __init__(self, api_keys):
        """
        Initialize Gemini service with one or more API keys

        Args:
            api_keys: Single API key string or comma-separated string of multiple keys
        """
        # Parse API keys (support comma-separated list)
        if isinstance(api_keys, str):
            # Remove whitespace and split by comma
            self.api_keys = [key.strip() for key in api_keys.split(',') if key.strip()]
        else:
            self.api_keys = api_keys if api_keys else []

        # Create a client for each API key
        self.clients = []
        self.key_names = []  # For logging which key is being used

        for idx, key in enumerate(self.api_keys, 1):
            try:
                client = genai.Client(api_key=key)
                self.clients.append(client)
                self.key_names.append(f"Key {idx}")
                logger.info(f"✅ Initialized Gemini Client #{idx} with Nano Banana (gemini-2.5-flash-image)")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Gemini Client #{idx}: {str(e)}")

        if not self.clients:
            logger.warning("⚠️ No valid Gemini API keys provided")
        else:
            logger.info(f"🔄 Multi-key rotation enabled: {len(self.clients)} API keys loaded")
            logger.info(f"   Total capacity: {len(self.clients) * 2000} requests/day (Tier 1)")
            logger.info(f"   Max products/day: {len(self.clients) * 2000} products (Pro Mode - 1 image per product)")

        # Round-robin rotation index (thread-safe)
        self._current_key_index = 0
        self._rotation_lock = threading.Lock()

        # Usage tracking per key
        self.usage_counts = {f"Key {i+1}": 0 for i in range(len(self.clients))}

        # Track quota exhaustion per key
        self.quota_exhausted = {f"Key {i+1}": False for i in range(len(self.clients))}

    def _calculate_quota_reset_time(self):
        """
        Calculate time until next quota reset (midnight Pacific Time)
        Returns: (seconds_until_reset, reset_datetime)
        """
        # Get current time in Pacific timezone
        pacific_tz = pytz.timezone('America/Los_Angeles')
        now_pacific = datetime.now(pacific_tz)

        # Calculate next midnight Pacific Time
        next_midnight = (now_pacific + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Calculate seconds until midnight
        time_until_reset = (next_midnight - now_pacific).total_seconds()

        logger.info(f"⏰ Current Pacific Time: {now_pacific.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"⏰ Quota resets at: {next_midnight.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"⏰ Time until reset: {time_until_reset / 3600:.2f} hours")

        return time_until_reset, next_midnight

    def _get_next_client(self):
        """
        Get the next client in round-robin rotation (thread-safe)
        Returns: (client, key_name) tuple
        """
        if not self.clients:
            return None, None

        with self._rotation_lock:
            client = self.clients[self._current_key_index]
            key_name = self.key_names[self._current_key_index]

            # Increment usage counter
            self.usage_counts[key_name] = self.usage_counts.get(key_name, 0) + 1

            # Move to next key for next request
            self._current_key_index = (self._current_key_index + 1) % len(self.clients)

            return client, key_name

    def get_usage_stats(self):
        """
        Get usage statistics for all API keys
        Returns: dict with usage counts per key
        """
        return self.usage_counts.copy()

    def log_usage_stats(self):
        """Log current usage statistics for all API keys"""
        if not self.clients:
            logger.info("No Gemini API keys configured")
            return

        logger.info(f"🔄 Gemini API Usage Statistics:")
        logger.info(f"   Total API keys: {len(self.clients)}")
        logger.info(f"   Total requests made: {sum(self.usage_counts.values())}")
        for key_name, count in self.usage_counts.items():
            logger.info(f"   {key_name}: {count} requests")

    def are_all_keys_exhausted(self):
        """
        Check if all API keys have exhausted their quota
        Returns: True if all keys are exhausted, False otherwise
        """
        if not self.clients:
            return True

        # Check if all keys are marked as quota exhausted
        all_exhausted = all(self.quota_exhausted.values())

        if all_exhausted:
            logger.warning(f"⚠️ ALL {len(self.clients)} API keys have exhausted their quota")

        return all_exhausted

    def reset_quota_flags(self):
        """
        Reset quota exhaustion flags for all keys (call this after quota reset at midnight Pacific)
        """
        for key_name in self.quota_exhausted:
            self.quota_exhausted[key_name] = False

        logger.info(f"✅ Reset quota exhaustion flags for all {len(self.clients)} API keys")

    def edit_product_image(self, original_image_url, product_title, variation="main"):
        """
        Edit an existing product image using Nano Banana (Gemini 2.5 Flash Image)
        This uses Gemini's image editing capabilities to create variations

        Args:
            original_image_url: URL of the original product image to edit
            product_title: Product title for context
            variation: Image variation type ("main", "angle1", "angle2")

        Returns:
            str: Base64 data URL of edited image or None if editing fails
        """
        try:
            # Get next client in rotation
            client, key_name = self._get_next_client()
            if not client:
                logger.warning("Gemini client not configured")
                return None

            logger.info(f"🍌 Nano Banana [{key_name}]: Editing product image for: {product_title} (variation: {variation})")

            # Download original image
            response = requests.get(original_image_url, timeout=10)
            response.raise_for_status()
            image_data = response.content

            # Load image
            image = Image.open(io.BytesIO(image_data))

            # Get variation-specific edit instructions
            edit_instructions = self._get_edit_instructions(variation)

            # Create edit prompt
            edit_prompt = f"""You are a professional product photographer. Edit this product image to create an ultra-realistic, professional e-commerce photograph.

PRODUCT: {product_title}

{edit_instructions}

🎨 ULTRA-REALISTIC PROFESSIONAL PHOTOGRAPHY REQUIREMENTS:

1. PHOTOREALISM - Make it look like a real photograph taken by a professional photographer:
   - Natural, realistic textures and materials
   - Accurate lighting with soft shadows and natural highlights
   - Proper depth of field with slight background blur
   - Professional color grading (not oversaturated, natural tones)
   - Studio-quality composition and framing

2. PROFESSIONAL QUALITY:
   - Ultra-sharp focus on the product
   - High resolution, crisp details
   - Clean, professional presentation
   - Perfect product exposure (not too bright, not too dark)
   - Natural reflections and surface details

3. BACKGROUND:
   - Clean, minimal background (white, light gray, or subtle gradient)
   - NO distracting elements or patterns
   - Professional studio backdrop appearance
   - Seamless background-to-product transition

🚫 ABSOLUTELY NO TEXT OR BRANDING - CRITICAL:
1. Remove ALL text: letters, numbers, words, symbols, logos, brand names, labels, watermarks, tags
2. Remove ALL company names, manufacturer marks, model numbers, serial numbers
3. Replace text areas with CLEAN, BLANK surfaces that match the product's material and color
4. If there are labels or stickers, replace with plain solid-color matching surfaces
5. The product must be COMPLETELY TEXT-FREE and BRAND-FREE
6. No visible typography or written characters of ANY kind anywhere in the image
7. Product surface should be clean and unmarked where text was removed

✅ WHAT TO PRESERVE:
1. Keep the EXACT SAME PRODUCT - only change angle, lighting, and background
2. DO NOT change product shape, design, structure, or physical features
3. Maintain accurate product colors and materials
4. Keep product dimensions and proportions identical
5. Preserve all product features except text/branding

🎯 FINAL RESULT:
A photorealistic, professional product photograph that looks like it was shot in a high-end photography studio - clean, sharp, professional, and completely text-free."""

            logger.info(f"Nano Banana edit prompt: {edit_prompt[:120]}...")

            # Use Nano Banana (Gemini 2.5 Flash Image) to edit the image
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[edit_prompt, image],
            )

            # Extract edited image from response
            # Access parts through response.candidates[0].content.parts
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data is not None:
                            # Get image data
                            image_data = part.inline_data.data
                            mime_type = part.inline_data.mime_type

                            # Convert to base64 data URL
                            data_url = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

                            logger.info(f"✅ Nano Banana [{key_name}]: Successfully edited image (variation: {variation})")
                            return data_url

            logger.error("No edited image data found in Nano Banana response")
            logger.error(f"Response structure: {dir(response)}")
            return None

        except Exception as e:
            error_str = str(e)

            # Check if this is a quota exhaustion error
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str:
                logger.error(f"❌ [{key_name}] QUOTA EXHAUSTED for {product_title}")
                logger.error(f"   Error: {error_str}")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Calculate time until quota reset
                seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                # Raise custom exception
                raise GeminiQuotaExhaustedError(
                    f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                    reset_time=reset_time
                )

            # Other errors
            logger.error(f"❌ Error editing image with Nano Banana: {error_str}")
            logger.error(f"   Product: {product_title}")
            logger.error(f"   Variation: {variation}")
            logger.error(f"   Image URL: {original_image_url[:100]}...")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return None

    def generate_product_image(self, image_prompt, product_title, variation="main"):
        """
        Generate a product image using Nano Banana (Gemini 2.5 Flash Image)

        Args:
            image_prompt: The prompt for image generation
            product_title: Product title for context
            variation: Image variation type ("main", "angle1", "angle2", "lifestyle")

        Returns:
            str: Base64 data URL of generated image or None if generation fails
        """
        try:
            # Get next client in rotation
            client, key_name = self._get_next_client()
            if not client:
                logger.warning("Gemini client not configured")
                return None

            logger.info(f"🍌 Nano Banana [{key_name}]: Generating image for: {product_title} (variation: {variation})")
            logger.info(f"Base prompt: {image_prompt[:150]}...")

            # Create variation-specific modifications
            variation_modifier = self._get_variation_modifier(variation)

            # Add critical requirements for professional product images
            enhanced_prompt = f"""{image_prompt}

{variation_modifier}

⚠️ CRITICAL REQUIREMENTS:
1. If any product has cloth/clothing: Place the clothing item on a relevant person. Ensure the product is realistic, consistent, and unchanged in design.
2. Do not add watermarks, logos, text, or distortions anywhere on the image.
3. Avoid fantasy, surreal, abstract, or patterned backgrounds; use a clean, simple, natural, premium environment.
4. Remove any existing watermark, vendor name on any image and reconstruct the product surface accurately.
5. Include only the real product with no extra objects or artifacts.
6. Generate this image with ABSOLUTELY NO TEXT, letters, numbers, logos, brands, or typography visible anywhere on the product or in the image.
7. Replace any text areas with clean, blank surfaces that match the product's material and color.
8. The image must be completely text-free and professional e-commerce quality.
9. Use high resolution, ultra-sharp focus, professional studio quality lighting."""

            # Use Nano Banana (Gemini 2.5 Flash Image) to generate image
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[enhanced_prompt],
            )

            # Extract generated image from response
            # Access parts through response.candidates[0].content.parts
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data is not None:
                            # Get image data
                            image_data = part.inline_data.data
                            mime_type = part.inline_data.mime_type

                            # Convert to base64 data URL
                            data_url = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

                            logger.info(f"✅ Nano Banana [{key_name}]: Successfully generated image (variation: {variation})")
                            return data_url

            logger.error("No image data found in Nano Banana response")
            logger.error(f"Response structure: {dir(response)}")
            return None

        except Exception as e:
            error_str = str(e)

            # Check if this is a quota exhaustion error
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str:
                logger.error(f"❌ [{key_name}] QUOTA EXHAUSTED for {product_title}")
                logger.error(f"   Error: {error_str}")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Calculate time until quota reset
                seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                # Raise custom exception
                raise GeminiQuotaExhaustedError(
                    f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                    reset_time=reset_time
                )

            # Other errors
            logger.error(f"Error generating image with Nano Banana: {error_str}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def generate_image_prompt_from_url(self, image_url, product_title, product_price):
        """
        Generate a detailed image generation prompt based on the original product image
        This uses Gemini Vision to analyze the image and create a prompt for image generation

        Args:
            image_url: URL of the original product image
            product_title: Product title
            product_price: Product price

        Returns:
            str: A detailed prompt for image generation
        """
        try:
            # Get next client in rotation
            client, key_name = self._get_next_client()
            if not client:
                logger.warning("Gemini client not configured, using fallback prompt")
                return f"Professional e-commerce product photography of {product_title}, clean white background, studio lighting, high resolution, photorealistic"

            # Download image from URL
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            image_data = response.content

            # Load image
            image = Image.open(io.BytesIO(image_data))

            # Create prompt for Gemini to analyze and generate image description
            analysis_prompt = f"""Analyze this product image for: {product_title} (Price: £{product_price})

Create an EXTREMELY DETAILED image generation prompt that will recreate this EXACT image as closely as possible.

The prompt MUST include:
1. EXACT product type, shape, dimensions, and every visible feature
2. PRECISE colors (use specific color names/codes), materials, textures, and surface details
3. EXACT camera angle, perspective, and distance from product
4. PRECISE lighting setup - direction, intensity, shadows, highlights, reflections
5. EXACT background (color, texture, whether it's white, gradient, or has elements)
6. EXACT product positioning and orientation in frame
7. All visible physical details - buttons, seams, edges, corners, patterns, surface finish
8. Any packaging or accessories visible (but describe WITHOUT any text)
9. Image quality characteristics - sharpness, depth of field, focus points

⚠️ CRITICAL REQUIREMENTS - NO TEXT ON IMAGES:
- DO NOT include ANY text, letters, numbers, or characters in the generated image
- DO NOT include brand names, logos, labels, or typography
- DO NOT include product markings, model numbers, or printed text
- If the original has text/logos, REPLACE THEM with: plain surface, blank area, or generic design
- The product should be CLEAN with NO visible text anywhere
- Focus on physical product features ONLY, not text elements

GOAL: Generate an image that looks IDENTICAL to the original in terms of:
- Physical appearance, shape, colors, materials
- Camera angle, lighting, composition
- Background and overall aesthetic
BUT with ALL text, logos, and typography COMPLETELY REMOVED and replaced with clean surfaces.

Return ONLY the ultra-detailed image generation prompt, no additional text."""

            # Use Gemini Vision (text model) to analyze and create prompt
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[analysis_prompt, image]
            )

            image_prompt = response.text.strip()
            logger.info(f"[{key_name}] Generated image prompt for {product_title}: {image_prompt[:100]}...")

            return image_prompt

        except Exception as e:
            logger.error(f"Error generating image prompt: {str(e)}")
            # Fallback prompt
            return f"Professional e-commerce product photography of {product_title}, clean white background, studio lighting, high resolution, photorealistic"

    def _get_variation_modifier(self, variation):
        """
        Get camera angle and lighting variations for different product shots

        Args:
            variation: Type of variation ("main", "angle1", "angle2", "lifestyle")

        Returns:
            str: Prompt modifier for the variation
        """
        variations = {
            "main": """
📸 CAMERA & COMPOSITION (Main Shot):
- Shot from straight-on front view at eye level
- Product centered perfectly in frame
- Slight zoom to show all product details clearly
- Professional product photography composition
- Clean, symmetrical framing

💡 LIGHTING SETUP (Main Shot):
- Three-point lighting: key light from 45° front-left, fill light from right, rim light from behind
- Soft, diffused lighting for minimal harsh shadows
- Bright, even illumination across entire product
- Subtle highlights to show texture and depth
- Professional studio lighting quality
""",
            "angle1": """
📸 CAMERA & COMPOSITION (Angled Shot):
- Shot from 45-degree angle showing both front and side of product
- Camera positioned slightly above product (15-20 degrees)
- Product fills 70% of frame with breathing room
- Dynamic, professional e-commerce composition
- Asymmetrical but balanced framing

💡 LIGHTING SETUP (Angled Shot):
- Dramatic side lighting from 60° to emphasize product dimensions
- Softer fill light from opposite side to prevent deep shadows
- Backlight to create subtle rim lighting and separation from background
- Slightly more contrast than main shot
- Creates depth and three-dimensional appearance
""",
            "angle2": """
📸 CAMERA & COMPOSITION (Alternative Angle):
- Shot from side or three-quarter view showing different product features
- Camera at same height as product for intimate perspective
- Product positioned off-center following rule of thirds
- Show different details than main and angle1 shots
- Professional catalog photography style

💡 LIGHTING SETUP (Alternative Angle):
- Soft natural-style lighting from top-front at 30° angle
- Gentle fill light to maintain detail in shadows
- Optional accent light to highlight specific product features
- Warm color temperature for inviting feel
- Balanced exposure with subtle shadows for dimension
""",
            "lifestyle": """
📸 CAMERA & COMPOSITION (Lifestyle Shot):
- Shot in realistic environment where product would be used
- Product naturally integrated into scene
- Camera positioned to show product in context
- More relaxed composition, less formal
- Environmental storytelling

💡 LIGHTING SETUP (Lifestyle Shot):
- Natural or natural-looking lighting
- Soft ambient light mimicking window or daylight
- Subtle shadows for realism
- Warm, inviting color temperature
- Less perfect, more authentic feel
"""
        }

        return variations.get(variation, variations["main"])

    def _get_edit_instructions(self, variation):
        """
        Get image editing instructions for creating variations
        These preserve the original product but change angle and lighting

        Args:
            variation: Type of variation ("main", "angle1", "angle2")

        Returns:
            str: Editing instructions
        """
        instructions = {
            "main": """
📸 IMAGE 1 SPECIFICATION - DIRECT FRONT VIEW (STRAIGHT-ON):

🎯 CAMERA ANGLE & COMPOSITION:
- DIRECT front-facing view at EXACT EYE LEVEL (0° tilt, 0° rotation)
- Camera positioned STRAIGHT-ON, perpendicular to product's front face
- Product PERFECTLY CENTERED in frame
- Show ONLY the FRONT FACE - no sides, no depth, no 3D perspective
- Completely FLAT, 2D-style presentation (like a catalog shot)
- Fill 80% of frame with product
- Eye-level horizontal alignment - NOT from above or below

💡 LIGHTING STYLE:
- Bright, even, SOFT DIFFUSED lighting from directly in front
- NO harsh shadows - completely shadow-free or minimal soft shadows
- High-key, bright exposure (slightly overexposed for clean look)
- Pure white or very light gray seamless background
- Professional studio softbox lighting setup
- Bright, airy, clean aesthetic

📐 PERSPECTIVE:
- ZERO perspective distortion
- FLAT, orthographic-style view
- NO depth or 3D dimensionality visible
- Product appears as if photographed head-on for a technical manual

🎯 FINAL RESULT: Ultra-clean, bright, direct front view with no angle - professional catalog-style product photography
""",
            "angle1": """
📸 IMAGE 2 SPECIFICATION - TOP-DOWN ANGLED VIEW (BIRD'S EYE):

🎯 CAMERA ANGLE & COMPOSITION:
- Camera positioned HIGH ABOVE product, looking DOWN at steep 60-70° angle from vertical
- BIRD'S EYE VIEW / TOP-DOWN perspective
- Show BOTH the TOP SURFACE and FRONT FACE simultaneously
- This creates DRAMATIC 3D DEPTH and dimensionality
- Product positioned at 45° rotation to camera (shows corner/edge)
- Fill 70% of frame showing full 3D structure
- COMPLETELY DIFFERENT from Image 1 - this is an angled, dimensional view

💡 LIGHTING STYLE:
- Dramatic SIDE LIGHTING from 90° angle (strong directional light)
- Creates DISTINCT shadows and highlights showing product depth
- Medium contrast (not too bright, shows texture and dimension)
- Light gray or subtle gradient background
- Single key light from side creates depth and drama
- Slightly darker than Image 1 to emphasize 3D form

📐 PERSPECTIVE:
- STRONG perspective distortion showing depth
- 3D dimensional view showing height, width, AND depth
- Visible TOP, FRONT, and potentially SIDE surfaces
- Product corners and edges clearly visible
- Shows product as a three-dimensional object

⚡ KEY DIFFERENCE FROM IMAGE 1:
- Image 1 = Flat, straight-on, bright, no shadows, 2D appearance
- Image 2 = Angled, top-down, dramatic shadows, 3D appearance
- These must look like TWO COMPLETELY DIFFERENT PHOTOGRAPHS

🎯 FINAL RESULT: Dramatic top-down angled view showing full 3D structure with depth and dimension - looks TOTALLY DIFFERENT from Image 1
""",
            "angle2": """
EDIT INSTRUCTIONS (Side/Three-Quarter View):
- Adjust camera angle to side or three-quarter view
- Show different product features than main view
- Apply soft natural-style lighting from top-front (30° angle)
- Gentle shadows for dimension
- Warm, inviting color temperature
- Professional catalog photography style
- Clean background
- Keep product EXACTLY as it is - only adjust angle and lighting
""",
            "lifestyle": """
EDIT INSTRUCTIONS (Lifestyle Context):
- Place product in realistic usage environment
- Natural or natural-looking lighting
- Soft ambient light mimicking window light
- Authentic, less formal composition
- Show product in context where it would be used
- Keep product EXACTLY as it is - only adjust setting and lighting
"""
        }

        return instructions.get(variation, instructions["main"])
