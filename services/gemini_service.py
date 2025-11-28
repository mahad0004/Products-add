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
        Skips keys that have exhausted their quota
        Returns: (client, key_name) tuple or (None, None) if all keys exhausted
        """
        if not self.clients:
            return None, None

        with self._rotation_lock:
            # Try to find a non-exhausted key
            attempts = 0
            max_attempts = len(self.clients)

            while attempts < max_attempts:
                client = self.clients[self._current_key_index]
                key_name = self.key_names[self._current_key_index]

                # Move to next key for next request
                self._current_key_index = (self._current_key_index + 1) % len(self.clients)

                # Check if this key is exhausted
                if not self.quota_exhausted.get(key_name, False):
                    # Increment usage counter
                    self.usage_counts[key_name] = self.usage_counts.get(key_name, 0) + 1
                    logger.debug(f"✅ Using [{key_name}] - {self.usage_counts[key_name]} requests so far")
                    return client, key_name

                # This key is exhausted, try next one
                logger.debug(f"⏭️  Skipping [{key_name}] - quota exhausted")
                attempts += 1

            # All keys are exhausted
            logger.error(f"❌ ALL {len(self.clients)} API keys have exhausted their quota")
            return None, None

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
            edit_prompt = f"""You are a professional lifestyle product photographer. Transform this product image into a compelling, real-world application photograph showing the product in use.

PRODUCT: {product_title}

{edit_instructions}

🎯 LIFESTYLE PHOTOGRAPHY OBJECTIVE:
Create a REALISTIC, professional photograph showing this product being used in its INTENDED REAL-WORLD APPLICATION with appropriate people, environment, or workplace setting.

👤 HUMAN INTERACTION (When Applicable):
1. Show a professional worker, craftsman, or user actively using or interacting with the product
2. Person should be dressed appropriately for the product's use case:
   - Construction/Industrial products: Worker in safety gear, hard hat, work clothes
   - Tools/Equipment: Tradesperson in work attire using the product
   - Office/Tech products: Professional in business casual
   - Home/DIY products: Casual user in appropriate setting
3. Focus on HANDS and product interaction - show product being held, installed, or operated
4. Person's face can be partially visible or out of focus (focus stays on product)
5. Natural, authentic body language and realistic usage posture

🏗️ ENVIRONMENT & SETTING:
1. Choose the MOST APPROPRIATE real-world setting for this product:
   - Construction products: Job site, construction area, workshop
   - Industrial equipment: Factory floor, warehouse, industrial setting
   - Tools: Workshop, garage, workbench with other tools nearby
   - Safety equipment: Active work environment showing its protective use
   - Office products: Modern office, desk setup
   - Home products: Residential setting, home workshop
2. Include relevant environmental context:
   - Other related equipment or materials in background (blurred)
   - Authentic workplace surfaces (concrete, metal workbench, wood, etc.)
   - Natural work environment lighting
   - Realistic clutter or workspace organization

📸 PROFESSIONAL PHOTOGRAPHY QUALITY:
1. Photorealistic, looks like actual documentary-style product photography
2. Natural lighting appropriate to the environment (workshop lighting, outdoor light, etc.)
3. Shallow depth of field - product and hands in sharp focus, background slightly blurred
4. Professional color grading with authentic, natural tones
5. Dynamic composition showing action, movement, or active use
6. Camera angle: Eye-level or slightly above, showing both product and usage context

🎨 REALISM & AUTHENTICITY:
1. Must look like a REAL PHOTOGRAPH, not CGI or artificial
2. Natural wear patterns, realistic textures, authentic materials
3. Genuine work environment - NOT overly clean or staged
4. Realistic lighting with natural shadows
5. Authentic product proportions and scale relative to human hands/body

🚫 ABSOLUTELY NO TEXT OR BRANDING - CRITICAL:
1. Remove ALL text from product: brand names, model numbers, labels, markings
2. Remove ALL text from environment: signs, posters, labels on other items
3. Remove company names, logos, manufacturer marks
4. Replace text areas with CLEAN surfaces matching the product's material
5. Remove any visible typography anywhere in the entire image
6. Product must be completely TEXT-FREE and BRAND-FREE
7. Background items should also be text-free

✅ WHAT TO SHOW:
1. Product in ACTIVE USE or being handled/installed
2. Appropriate human interaction (hands holding, using, installing)
3. Real-world application environment
4. Natural, realistic usage scenario
5. Professional, engaging composition that tells a story

🎯 FINAL RESULT:
A compelling, photorealistic lifestyle image showing the product being used in its intended real-world application, with appropriate human interaction and environment - professional, authentic, engaging, and completely text-free."""

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

                # Check finish_reason for content safety issues
                if hasattr(candidate, 'finish_reason'):
                    finish_reason = str(candidate.finish_reason)
                    if 'SAFETY' in finish_reason or 'RECITATION' in finish_reason or 'BLOCKED' in finish_reason:
                        logger.warning(f"⚠️ Nano Banana [{key_name}]: Image rejected by safety filters - {finish_reason}")
                        logger.warning(f"   Product: {product_title}")
                        logger.warning(f"   Likely cause: Brand logos, text, or copyrighted content detected in source image")
                        logger.warning(f"   Skipping this product (no edited image available)")
                        return None

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

            logger.error(f"❌ No edited image data found in Nano Banana response for: {product_title}")
            logger.error(f"   This usually means the source image was rejected by safety filters")
            logger.error(f"   Common causes: Brand logos, prominent text, or copyrighted imagery")
            return None

        except Exception as e:
            error_str = str(e)

            # Check if this is a quota exhaustion error
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "Quota exceeded" in error_str:
                logger.warning(f"⚠️ [{key_name}] QUOTA EXHAUSTED for {product_title}")
                logger.warning(f"   Error: {error_str}")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Check if ALL keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")

                    # Raise custom exception only when ALL keys are exhausted
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
                    # Some keys still available - return None to try again with next key
                    remaining_keys = sum(1 for exhausted in self.quota_exhausted.values() if not exhausted)
                    logger.info(f"📊 {remaining_keys}/{len(self.clients)} API keys still available - continuing with next key")
                    return None

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
                logger.warning(f"⚠️ [{key_name}] QUOTA EXHAUSTED for {product_title}")
                logger.warning(f"   Error: {error_str}")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Check if ALL keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")

                    # Raise custom exception only when ALL keys are exhausted
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
                    # Some keys still available - return None to try again with next key
                    remaining_keys = sum(1 for exhausted in self.quota_exhausted.values() if not exhausted)
                    logger.info(f"📊 {remaining_keys}/{len(self.clients)} API keys still available - continuing with next key")
                    return None

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
📸 LIFESTYLE IMAGE - IN-USE SCENARIO:

🎯 SCENE SETUP:
- Show the product being ACTIVELY USED in its primary application
- Include human hands holding, operating, or installing the product
- Person dressed appropriately for the product's use case
- Camera at eye-level or slightly above, capturing both product and user interaction

👤 HUMAN ELEMENT:
- Professional worker or tradesperson using the product
- Focus on HANDS and product - face can be blurred or partially visible
- Natural grip, authentic usage posture
- Gloved hands if appropriate for safety equipment
- Realistic body position for the task

🏗️ ENVIRONMENT:
- Authentic workplace or application setting (workshop, construction site, garage, etc.)
- Include relevant context: workbench, other tools, materials in background (blurred)
- Natural work environment surfaces and textures
- Realistic lighting for the setting (workshop lights, natural daylight, etc.)

📸 COMPOSITION:
- Product and hands in SHARP FOCUS
- Background slightly blurred (shallow depth of field)
- Dynamic angle showing action and engagement
- Professional color grading with natural, realistic tones
- Show the product solving a real problem or being used for its intended purpose

🎯 MOOD: Professional, authentic, action-oriented, showing real-world application
""",
            "angle1": """
📸 LIFESTYLE IMAGE - INSTALLATION/SETUP VIEW:

🎯 SCENE SETUP:
- Show the product being INSTALLED, SET UP, or PREPARED for use
- Different angle from main image - focus on preparation or assembly
- Include human hands positioning, adjusting, or working with the product
- Camera angle from side or three-quarter view

👤 HUMAN ELEMENT:
- Show hands positioning, measuring, or installing the product
- Person preparing the product for use or adjusting settings
- Different hand position/grip than main image
- Tool usage if applicable (wrench, screwdriver, etc.)

🏗️ ENVIRONMENT:
- Same or similar authentic work environment
- Show preparation surface: workbench, floor, mounting location
- Include installation context (mounting brackets, screws, other materials)
- Different environmental angle than main image

📸 COMPOSITION:
- Side angle or three-quarter view showing different product perspective
- Hands and product interaction from different angle
- Background with relevant work environment details (blurred)
- Shows a DIFFERENT MOMENT in the product's use cycle than main image

🎯 MOOD: Professional setup/installation scenario, showing product versatility and ease of use
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
