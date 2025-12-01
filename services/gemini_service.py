"""
Google Gemini Service with Nano Banana Image Editing
Handles Google Gemini API interactions for image generation and editing

OLD PROMPT (BACKUP - PRE-SMART SCENARIO DETECTION):
================================================================================
This was the original industrial/construction-focused prompt before we added
smart product category detection (furniture/lifestyle vs tools/industrial).

The old prompt was heavily focused on workplace/construction scenarios with:
- Workers in safety gear
- Workshop/construction environments
- Active installation and tool usage
- Workplace signage (CAUTION, WARNING, etc.)

The NEW prompt now intelligently detects product categories and chooses:
- LIFESTYLE scenarios for furniture/outdoor/garden products (person sitting on bench in garden)
- INDUSTRIAL scenarios for tools/equipment/construction products (worker installing/using)

Original prompt sections preserved below for reference/rollback if needed.
================================================================================
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

        # LAZY LOADING: Store clients dict (initialized on first use to avoid worker timeout)
        self.clients = {}  # key_index -> client
        self.key_names = []  # For logging which key is being used
        self._clients_initialized = False
        self._init_lock = threading.Lock()  # Thread-safe lazy init

        # Pre-populate key names
        for idx in range(len(self.api_keys)):
            self.key_names.append(f"Key {idx + 1}")

        if not self.api_keys:
            logger.warning("⚠️ No valid Gemini API keys provided")
        else:
            logger.info(f"🔄 Multi-key rotation enabled: {len(self.api_keys)} API keys configured (lazy loading)")
            logger.info(f"   📊 Clients will be initialized on first use to avoid worker timeout")
            logger.info(f"   ")
            logger.info(f"   ⚙️  DYNAMIC QUOTA MANAGEMENT:")
            logger.info(f"   1️⃣  Use Key 1 → Run until API returns quota error")
            if len(self.api_keys) > 1:
                for i in range(2, len(self.api_keys) + 1):
                    logger.info(f"   {i}️⃣  Switch to Key {i} → Run until API returns quota error")
            logger.info(f"   ⏸️  When ALL keys exhausted → Auto-pause processing")
            logger.info(f"   💤 Wait until midnight Pacific Time (quota resets)")
            logger.info(f"   ▶️  Auto-resume processing with fresh quota")
            logger.info(f"   ")
            logger.info(f"   📊 Quota Detection: Dynamic (waits for 429/RESOURCE_EXHAUSTED errors)")
            logger.info(f"   📊 Total API keys: {len(self.api_keys)} keys")
            logger.info(f"   📊 Mode: Pro Mode (2 images per product)")

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

    def _ensure_client_initialized(self, key_index):
        """
        Lazy initialization: Create client for a specific key index if not already created
        Thread-safe initialization
        """
        if key_index in self.clients:
            return  # Already initialized

        with self._init_lock:
            # Double-check after acquiring lock
            if key_index in self.clients:
                return

            # Initialize this specific client
            try:
                key = self.api_keys[key_index]
                client = genai.Client(api_key=key)
                self.clients[key_index] = client
                logger.info(f"✅ Lazy-initialized Gemini Client #{key_index + 1}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Gemini Client #{key_index + 1}: {str(e)}")
                raise

    def _get_next_client(self):
        """
        Get the next client in round-robin rotation (thread-safe)
        Skips keys that have exhausted their quota
        Returns: (client, key_name) tuple or (None, None) if all keys exhausted
        """
        if not self.api_keys:
            return None, None

        with self._rotation_lock:
            # Try to find a non-exhausted key
            attempts = 0
            max_attempts = len(self.api_keys)  # Use api_keys length, not clients

            while attempts < max_attempts:
                # Lazy-initialize client if needed
                self._ensure_client_initialized(self._current_key_index)

                client = self.clients[self._current_key_index]
                key_name = self.key_names[self._current_key_index]

                # Move to next key for next request
                self._current_key_index = (self._current_key_index + 1) % len(self.api_keys)

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
            logger.error(f"❌ ALL {len(self.api_keys)} API keys have exhausted their quota")
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

    def edit_product_image(self, original_image_url, product_title, variation="main", all_image_urls=None):
        """
        Edit an existing product image using Nano Banana (Gemini 2.5 Flash Image)
        This uses Gemini's image editing capabilities to create variations

        Args:
            original_image_url: URL of the original product image to edit
            product_title: Product title for context
            variation: Image variation type ("main", "angle1", "angle2")
            all_image_urls: List of all product image URLs for size/scale context (optional)

        Returns:
            str: Base64 data URL of edited image or None if editing fails
        """
        try:
            # Get next client in rotation
            client, key_name = self._get_next_client()
            if not client:
                # Check if all keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")

                    # Raise exception to trigger wait-and-resume
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
                    logger.warning("Gemini client not configured")
                    return None

            logger.info(f"🍌 Nano Banana [{key_name}]: Editing product image for: {product_title} (variation: {variation})")

            # Download primary image
            response = requests.get(original_image_url, timeout=10)
            response.raise_for_status()
            image_data = response.content

            # Load primary image
            primary_image = Image.open(io.BytesIO(image_data))

            # Download and load ALL images for context (if provided)
            context_images = []
            if all_image_urls and len(all_image_urls) > 1:
                logger.info(f"📸 Loading {len(all_image_urls)} images for size/scale context...")
                for idx, img_url in enumerate(all_image_urls):
                    try:
                        if img_url != original_image_url:  # Skip primary image (already loaded)
                            img_response = requests.get(img_url, timeout=10)
                            img_response.raise_for_status()
                            context_img = Image.open(io.BytesIO(img_response.content))
                            context_images.append(context_img)
                            logger.info(f"   ✅ Loaded context image {idx + 1}/{len(all_image_urls)}")
                    except Exception as e:
                        logger.warning(f"   ⚠️ Failed to load context image {idx + 1}: {str(e)}")
                        # Continue even if some context images fail
                        continue

            # Get variation-specific edit instructions
            edit_instructions = self._get_edit_instructions(variation)

            # Detect product category for smart scenario selection
            product_lower = product_title.lower()
            is_furniture = any(keyword in product_lower for keyword in [
                'bench', 'chair', 'seat', 'table', 'sofa', 'couch', 'stool', 'furniture',
                'lounger', 'hammock', 'swing', 'gazebo', 'pergola', 'planter', 'pot'
            ])
            is_outdoor_lifestyle = any(keyword in product_lower for keyword in [
                'garden', 'outdoor', 'patio', 'deck', 'bbq', 'grill', 'fire pit',
                'umbrella', 'parasol', 'fountain', 'statue', 'ornament'
            ])

            # Choose appropriate scenario based on product type
            if is_furniture or is_outdoor_lifestyle:
                scenario_type = "LIFESTYLE"
            else:
                scenario_type = "INDUSTRIAL"

            # Create edit prompt with size/scale emphasis
            size_context = ""
            if context_images:
                size_context = f"""
📏 SIZE & SCALE CONTEXT:
- You have been provided with {len(all_image_urls)} reference images of this product
- Analyze ALL images to understand the product's ACTUAL REAL-WORLD SIZE and proportions
- The product title "{product_title}" indicates the true nature and scale of this product
- PAY CLOSE ATTENTION to size indicators in the images (people, objects, measurements)
- Ensure the generated image shows the product at its CORRECT REAL-WORLD SCALE
- If the product is large (barriers, bollards, parking equipment, industrial items), show it at FULL SIZE
- If the product is small (tools, accessories), show it at appropriate human-scale

🎯 COMPLETE PRODUCT SETUP:
- Study ALL {len(all_image_urls)} reference images to see the COMPLETE product setup
- If images show containers/tanks ON a pallet (like IBC Spill Pallets) → show WITH containers
- If images show items IN/ON racks or shelves → show WITH items stored
- If images show equipment WITH accessories or attachments → show COMPLETE assembly
- DO NOT generate just an empty base/frame if references show it loaded or complete
- The reference images show how the product is MEANT TO LOOK - replicate that exactly
"""

            edit_prompt = f"""You are a professional lifestyle product photographer. Transform this product image into a compelling, real-world application photograph showing the product in use.

PRODUCT: {product_title}
{size_context}
{edit_instructions}

🎯 PHOTOGRAPHY OBJECTIVE:
Create a REALISTIC, professional photograph showing this product being used in its INTENDED REAL-WORLD APPLICATION.
The product SIZE and SCALE must be ACCURATE based on the product title and reference images provided.

⚠️ CRITICAL: PRESERVE THE EXACT PRODUCT APPEARANCE
🔒 PRODUCT INTEGRITY - MUST NOT CHANGE:
1. Keep the product's EXACT PHYSICAL DESIGN - do not alter shape, form, or structure
2. Preserve EXACT COLORS - maintain all original colors of the product precisely
3. Keep EXACT MATERIALS and textures - metal stays metal, plastic stays plastic, etc.
4. Maintain EXACT DIMENSIONS and proportions as shown in reference images
5. Keep ALL PHYSICAL FEATURES - buttons, grooves, edges, patterns exactly as they are
6. Do NOT redesign, modify, or "improve" the product in any way
7. The product must be IDENTICAL to the original - only remove text/logos/brands

✅ WHAT YOU CAN CHANGE:
- The ENVIRONMENT and background (add realistic workplace/lifestyle setting)
- The LIGHTING and photography angle
- Add PEOPLE interacting with the product (hands, workers, users)
- Add CONTEXT objects (tools, vehicles, other environmental items)
- The SCENARIO showing how the product is used

❌ WHAT YOU CANNOT CHANGE:
- The product's physical appearance, design, or features
- The product's colors or materials
- The product's size or proportions
- The product's shape or structure

🎯 RESULT: The SAME product in a NEW realistic environment/scenario

SCENARIO TYPE: {scenario_type}

👤 HUMAN INTERACTION:
{"LIFESTYLE SCENARIO - Natural, Relaxed Usage:" if scenario_type == "LIFESTYLE" else "ACTIVE USE SCENARIO - Installation/Operation:"}
{"- Show person naturally using or enjoying the product (sitting, relaxing, etc.)" if scenario_type == "LIFESTYLE" else "- Show professional worker, craftsman, or user actively installing or operating the product"}
{"- Person dressed casually and comfortably for the setting" if scenario_type == "LIFESTYLE" else "- Person dressed appropriately (safety gear, work clothes, etc.)"}
{"- Natural, relaxed posture - enjoying the product" if scenario_type == "LIFESTYLE" else "- Focus on HANDS and product interaction - holding, installing, operating"}
{"- Person can be partially visible or in background" if scenario_type == "LIFESTYLE" else "- Person's face can be partially visible or out of focus"}
{"- Authentic lifestyle moment captured naturally" if scenario_type == "LIFESTYLE" else "- Natural, authentic body language and realistic usage posture"}

🏗️ ENVIRONMENT & SETTING:
{"LIFESTYLE SETTING - Beautiful, Natural Environment:" if scenario_type == "LIFESTYLE" else "WORKPLACE SETTING - Authentic Work Environment:"}
{"- Outdoor garden, patio, deck, backyard, or beautiful home setting" if scenario_type == "LIFESTYLE" else "- Job site, workshop, garage, construction area, or workplace"}
{"- Lush greenery, flowers, natural landscaping in background (softly blurred)" if scenario_type == "LIFESTYLE" else "- Work surfaces, tools, equipment, materials in background (blurred)"}
{"- Natural sunlight, golden hour lighting, or soft outdoor illumination" if scenario_type == "LIFESTYLE" else "- Workshop lighting, natural daylight, or work environment lighting"}
{"- Well-maintained, inviting outdoor or home environment" if scenario_type == "LIFESTYLE" else "- Realistic workplace with authentic surfaces (concrete, metal, wood)"}
{"- NO workplace signage needed - pure lifestyle aesthetic" if scenario_type == "LIFESTYLE" else "- Optional: Safety signs in background (CAUTION, WARNING, EXIT) for authenticity"}

📸 PROFESSIONAL PHOTOGRAPHY QUALITY:
1. Photorealistic, looks like actual {"lifestyle magazine" if scenario_type == "LIFESTYLE" else "documentary-style"} product photography
2. Natural lighting appropriate to the environment
3. Shallow depth of field - product and person in focus, background beautifully blurred
4. Professional color grading with authentic, natural tones
5. {"Inviting, aspirational composition showing desirable lifestyle" if scenario_type == "LIFESTYLE" else "Dynamic composition showing action, movement, or active use"}
6. Camera angle: Eye-level or slightly above, showing product in perfect context

🎨 REALISM & AUTHENTICITY:
1. Must look like a REAL PHOTOGRAPH, not CGI or artificial
2. Natural textures, authentic materials
3. {"Beautiful, well-maintained environment - NOT overly perfect, naturally inviting" if scenario_type == "LIFESTYLE" else "Genuine work environment - NOT overly clean or staged"}
4. Realistic lighting with natural shadows
5. Authentic product proportions and scale relative to human body

🔍 CRITICAL: ANALYZE ALL REFERENCE IMAGES TO UNDERSTAND THE COMPLETE PRODUCT:
1. Study ALL provided reference images carefully - they show the COMPLETE product setup
2. Look at what the reference images show:
   - If images show a container/tank ON a pallet → generate with container ON pallet
   - If images show a rack WITH items stored → generate with items IN/ON the rack
   - If images show a holder WITH tools/objects → generate with those objects in place
   - The reference images show the INTENDED COMPLETE SETUP - replicate that!
3. Understand the product's PURPOSE from reference images:
   - Pallets HOLD containers/IBCs - show them holding the containers
   - Racks STORE items - show them with items stored
   - Stands SUPPORT equipment - show them supporting equipment
   - If you only see the base/structure in some images, check OTHER images for complete setup
4. Cross-reference ALL images to see the full context and intended use
5. Generate the product exactly as shown in reference images - COMPLETE and FUNCTIONAL

🚫 BRAND & LOGO REMOVAL - CRITICAL:
1. Remove ALL text from the PRODUCT itself:
   - Brand names, model numbers, manufacturer marks, logos
   - Product labels, serial numbers, company names
   - Replace with CLEAN surfaces matching the product's material
   - The product must be completely TEXT-FREE and BRAND-FREE

2. KEEP realistic environmental text for authenticity:
   ✅ KEEP: Safety signs ("DANGER", "CAUTION", "WARNING", "SAFETY FIRST")
   ✅ KEEP: Directional signs ("EXIT", "ENTRANCE", "UP", "DOWN")
   ✅ KEEP: Generic workplace signage ("FIRE EXTINGUISHER", "FIRST AID")
   ✅ KEEP: Measurement markings on tools or rulers in background
   ✅ KEEP: Generic instructional text on equipment

3. REMOVE from environment:
   ❌ REMOVE: Company names, business logos, brand names
   ❌ REMOVE: Specific company signage or branded posters
   ❌ REMOVE: Manufacturer logos on background equipment
   ❌ REMOVE: Phone numbers, websites, email addresses

4. Environmental text should be:
   - Generic and universal (not company-specific)
   - Safety-oriented or functional
   - Realistic for the work environment
   - Not promotional or branded

✅ WHAT TO SHOW:
1. Product in ACTIVE USE or being handled/installed
2. Appropriate human interaction (hands holding, using, installing)
3. Real-world application environment
4. Natural, realistic usage scenario
5. Professional, engaging composition that tells a story

🎯 FINAL RESULT:
A compelling, photorealistic lifestyle image showing the product being used in its intended real-world application, with appropriate human interaction and environment - professional, authentic, engaging, and completely text-free."""

            logger.info(f"Nano Banana edit prompt: {edit_prompt[:120]}...")

            # Build contents list: prompt + primary image + all context images
            contents = [edit_prompt, primary_image]
            if context_images:
                logger.info(f"📸 Adding {len(context_images)} context images to Gemini API request for better size understanding")
                contents.extend(context_images)

            # Use Nano Banana (Gemini 2.5 Flash Image) to edit the image
            # Pass ALL images so AI can understand true size/scale
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=contents,
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
                # Get actual usage count for this key
                usage_count = self.usage_counts.get(key_name, 0)
                logger.warning(f"⚠️ [{key_name}] QUOTA EXHAUSTED after {usage_count} requests")
                logger.warning(f"   Product: {product_title}")
                logger.warning(f"   API Error: {error_str[:100]}...")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Check if ALL keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    # Log total usage across all keys
                    total_requests = sum(self.usage_counts.values())
                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")
                    logger.error(f"   Total requests processed: {total_requests}")
                    for k, count in self.usage_counts.items():
                        logger.error(f"   {k}: {count} requests")

                    # Raise custom exception only when ALL keys are exhausted
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
                    # Some keys still available - return None to try again with next key
                    remaining_keys = sum(1 for exhausted in self.quota_exhausted.values() if not exhausted)
                    logger.info(f"📊 {remaining_keys}/{len(self.clients)} API keys still available - switching to next key")
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
                # Check if all keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")

                    # Raise exception to trigger wait-and-resume
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
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
                # Get actual usage count for this key
                usage_count = self.usage_counts.get(key_name, 0)
                logger.warning(f"⚠️ [{key_name}] QUOTA EXHAUSTED after {usage_count} requests")
                logger.warning(f"   Product: {product_title}")
                logger.warning(f"   API Error: {error_str[:100]}...")

                # Mark this key as quota exhausted
                self.quota_exhausted[key_name] = True

                # Check if ALL keys are exhausted
                if self.are_all_keys_exhausted():
                    # Calculate time until quota reset
                    seconds_until_reset, reset_time = self._calculate_quota_reset_time()

                    # Log total usage across all keys
                    total_requests = sum(self.usage_counts.values())
                    logger.error(f"❌ ALL {len(self.clients)} API KEYS EXHAUSTED!")
                    logger.error(f"   Total requests processed: {total_requests}")
                    for k, count in self.usage_counts.items():
                        logger.error(f"   {k}: {count} requests")

                    # Raise custom exception only when ALL keys are exhausted
                    raise GeminiQuotaExhaustedError(
                        f"Gemini API quota exhausted. Quota resets at {reset_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                        reset_time=reset_time
                    )
                else:
                    # Some keys still available - return None to try again with next key
                    remaining_keys = sum(1 for exhausted in self.quota_exhausted.values() if not exhausted)
                    logger.info(f"📊 {remaining_keys}/{len(self.clients)} API keys still available - switching to next key")
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
        Get image editing instructions for creating TWO images per product

        Args:
            variation: Type of variation ("product_in_use", "installation")

        Returns:
            str: Editing instructions
        """
        instructions = {
            "product_in_use": """
📸 IMAGE 1: PRODUCT IN USE (CLEAN, PROFESSIONAL, NO WORKERS)

🎯 OBJECTIVE:
Create a clean, professional product image showing the product in its intended use ALREADY INSTALLED and functioning as designed.

⚠️ CRITICAL: NO WORKERS, NO HANDS, NO TOOLS visible in this image.

🔒 PRESERVE EXACT PRODUCT APPEARANCE:
- The product itself must remain IDENTICAL to the original reference images
- Do NOT change the product's color, shape, size, design, or any physical features
- ONLY change the environment/background/context around the product
- The product is perfect as-is - DO NOT redesign or modify it

📸 CRITICAL: SHOW COMPLETE PRODUCT AS SEEN IN REFERENCE IMAGES:
- Study ALL reference images to see how the product is MEANT to be shown
- If reference images show containers ON pallets → show containers ON pallet
- If reference images show items IN/ON racks → show items stored properly
- If reference images show equipment WITH accessories → show complete setup
- DO NOT show just the base/frame if reference images show complete assembly
- The reference images are your guide - replicate the COMPLETE setup you see

🔧 PRODUCT PRESENTATION:
- Show the product ALREADY INSTALLED and in use
- Product functioning as designed in its final, installed state
- COMPLETE SETUP as shown in reference images (not just base/empty structure)
- Clean, professional presentation
- Product should look like it's being used, but WITHOUT people visibly interacting with it
- The SAME EXACT COMPLETE product from the reference images, just in a real-world setting

🌍 ENVIRONMENT & CONTEXT:
- Realistic environment relevant to the product
- Use realistic lighting and correct scale
- Clean, well-maintained environment
- Include ONLY objects necessary to show the product's purpose
  Example: A wheel stop with a car wheel touching it (no person visible)
  Example: Safety barrier installed on a road edge (no workers)
  Example: Bollard installed in parking lot with cars nearby (no people)

📸 COMPOSITION:
- Professional, catalog-quality photography
- Straight-on or slight angle to show product clearly
- Natural, appropriate lighting for the environment
- Sharp focus on product
- Clean, uncluttered background

🚫 WHAT NOT TO SHOW:
- NO workers or people
- NO hands touching the product
- NO tools or installation equipment
- NO installation process

🚫 BRANDING:
- NO brand names, logos, or text on the product
- NO company signage or branded materials
- Clean surfaces only

🎯 FINAL RESULT:
A professional, clean image showing the product already installed and serving its purpose, photographed as if for a high-quality product catalog.
""",
            "installation": """
📸 IMAGE 2: REAL-LIFE APPLICATION (PRODUCT IN ACTUAL USE)

🎯 OBJECTIVE:
Show the product being used in a REAL-LIFE APPLICATION - how it actually functions in the real world.
This is NOT an installation scene - this shows the product DOING ITS JOB.

🎯 WHAT TO SHOW:
Analyze the product title and reference images to understand its PURPOSE, then show it fulfilling that purpose:

Examples by product type:
- IBC Spill Pallet → Show in chemical storage area/warehouse with IBC container on top, realistic workplace setting
- Parking Bollard → Show installed in parking lot protecting area, cars nearby, real parking environment
- Wheel Stop → Show in parking space with vehicle wheel against it
- Safety Barrier → Show protecting hazard area in active workplace
- Floor Tape/Markers → Show applied on floor with workplace activity (people walking, forklifts, etc.)
- Storage Rack → Show in warehouse with items stored, realistic facility
- Speed Bump → Show installed on road/driveway with vehicles
- Sign/Post → Show in its intended location serving its warning/direction purpose

🎯 KEY PRINCIPLE: FUNCTION OVER INSTALLATION
- Show the product WORKING, not being installed
- Show the product SERVING ITS PURPOSE in its natural environment
- The viewer should understand WHY this product exists and what it does

🔒 PRESERVE EXACT PRODUCT APPEARANCE:
- The product being installed must be IDENTICAL to the original reference images
- Do NOT change the product's color, shape, size, design, or any physical features
- ONLY change the environment/scenario around the product (add workers, tools, workplace)
- The product is perfect as-is - DO NOT redesign or modify it
- Show the EXACT SAME product being installed in a realistic workplace setting

📸 CRITICAL: SHOW COMPLETE PRODUCT AS SEEN IN REFERENCE IMAGES:
- Study ALL reference images to understand the COMPLETE product
- If product is designed to HOLD items (pallets, racks, stands):
  * Show the COMPLETE setup - the base product WITH what it's meant to hold
  * IBC pallet → Show WITH IBC container on top
  * Storage rack → Show WITH items stored on shelves
  * Tool holder → Show WITH tools in place
- Show the product LOADED and FUNCTIONAL as it would be in real use
- DO NOT show just an empty base/frame if it's meant to hold something

👥 PEOPLE IN THE SCENE (OPTIONAL - USE ONLY IF IT ADDS CONTEXT):
- People are OPTIONAL, not required - only include if it helps show the application
- If people are shown, they should be:
  * In the background or periphery, not the focus
  * Using/interacting with the area where product is (walking on marked floor, parking near bollard, etc.)
  * Dressed appropriately for the setting (work clothes, safety gear if needed)
  * Natural and authentic, not posed
- For most products, NO people needed - just show the product working in its environment

🌍 REAL-LIFE ENVIRONMENT:
Choose the authentic environment where this product would actually be used:
- Pallets/IBCs → Chemical storage area, warehouse, outdoor containment area
- Parking equipment (bollards, wheel stops, speed bumps) → Parking lots, driveways, roads
- Storage/racks → Warehouses, facilities, organized storage areas
- Safety equipment (barriers, tape, signs) → Active workplaces, construction sites, facilities
- Floor markings → Warehouse floors with forklifts/activity, parking areas

Show realistic context:
- Other relevant equipment in background (forklifts, vehicles, machinery, shelving)
- Proper workplace setting (concrete floors, industrial lighting, outdoor paving)
- Active environment that shows the product is needed and functional
- NOT studio setting - real workplace or outdoor location

📸 COMPOSITION & STYLE:
- Professional industrial/commercial photography
- Documentary-style showing real-world application
- Wide or medium shot that shows product AND its working environment
- Natural lighting appropriate to the setting (warehouse lights, outdoor daylight)
- Focus on the product serving its purpose
- Authentic, not overly staged or perfect

🚫 BRANDING:
- NO brand names or logos on product
- NO company signage in environment
- NO text except generic safety markings if appropriate for setting

🎯 FINAL RESULT:
A professional photograph showing the product in REAL-LIFE APPLICATION - actively serving its purpose in its natural environment. The viewer should clearly understand what this product does and why it's useful. Show the COMPLETE product (loaded/functional) in an authentic workplace or outdoor setting that demonstrates its real-world use case.

Examples of final results:
- IBC Spill Pallet → In warehouse with IBC container on top, chemical storage setting
- Parking Bollard → Installed in parking lot, protecting area, cars visible
- Floor Tape → Applied on warehouse floor, active workplace environment
- Storage Rack → In facility with items stored, realistic warehouse setting
""",
            "application": """
📸 IMAGE 2: PRODUCT APPLICATION (HANDS APPLYING/USING THE PRODUCT)

🎯 OBJECTIVE:
Create a realistic scene showing someone actively APPLYING or USING this product in its intended way - appropriate for small items, markers, tape, paint, labels, accessories, etc.

🔒 PRESERVE EXACT PRODUCT APPEARANCE:
- The product being used must be IDENTICAL to the original reference images
- Do NOT change the product's color, shape, size, design, or any physical features
- ONLY show the product being used/applied in a realistic scenario
- The product is perfect as-is - DO NOT redesign or modify it

🤲 HANDS & APPLICATION:
- Show HANDS actively applying, using, or handling the product
- Hands should be in close-up, clearly showing the application process
- Natural, realistic hand positioning for the specific product type
- Hands can be wearing work gloves if appropriate (e.g., for industrial markers, tape)
- Focus on the APPLICATION ACTION - peeling tape, marking floors, applying labels, etc.

🔧 APPLICATION SCENARIOS BY PRODUCT TYPE:
For FLOOR MARKERS / TAPE / LINES:
- Show hands applying the marker/tape to a floor surface
- Display the application process (peeling backing, pressing down, smoothing)
- Show partially applied product to demonstrate usage
- Realistic floor surface (concrete, asphalt, warehouse floor)

For PAINT / COATING / SPRAY:
- Show hands applying paint to appropriate surface
- May include brush, roller, or spray application
- Show product container/can being used
- Realistic application surface

For LABELS / STICKERS / SIGNS:
- Show hands peeling and applying label
- Display backing being removed
- Show application to relevant surface (box, equipment, wall)

For SMALL TOOLS / ACCESSORIES:
- Show hands using the tool/accessory for its intended purpose
- Demonstrate proper handling and usage
- Include any objects the tool interacts with

For SAFETY / PPE ITEMS:
- Show hands putting on, adjusting, or using the safety item
- Demonstrate proper usage/placement
- Show on appropriate body part or location

🌍 ENVIRONMENT & SURFACE:
- Realistic environment for the product's use case
- Appropriate surface (floor, wall, equipment, package, etc.)
- Clean, professional setting
- Natural or workplace lighting
- Close-up/macro shot to show detail

📸 COMPOSITION & STYLE:
- Close-up, detail-focused photography
- Hands-on demonstration style
- Clear view of the product being applied/used
- Professional instructional/tutorial photo quality
- Sharp focus on hands and product
- Background slightly blurred to emphasize action

🚫 WHAT NOT TO SHOW:
- NO heavy machinery or power tools (drills, saws, etc.) unless product specifically requires them
- NO workers in full high-vis gear (just hands, maybe gloves)
- NO installation equipment inappropriate for the product
- NO construction site setting for small/simple products
- Just hands + product + application surface

🚫 BRANDING:
- NO brand names or logos on product
- NO company signage or branded materials
- Clean product surfaces only

🎯 FINAL RESULT:
A professional, close-up demonstration photo showing hands actively applying or using the product in its real-world application - clear, instructional, and contextually appropriate for the specific product type.
"""
        }

        # For backward compatibility, map old variations to new ones
        if variation in ["main", "angle1"]:
            return instructions.get("product_in_use", instructions["product_in_use"])
        elif variation in ["angle2", "lifestyle"]:
            return instructions.get("installation", instructions["installation"])

        return instructions.get(variation, instructions["product_in_use"])
