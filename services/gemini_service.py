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

logger = logging.getLogger(__name__)


class GeminiService:
    """Service for interacting with Google Gemini API (Nano Banana)"""

    def __init__(self, api_key):
        self.api_key = api_key
        if api_key:
            self.client = genai.Client(api_key=api_key)
            logger.info("✅ Initialized Gemini Client with Nano Banana (gemini-2.5-flash-image)")
        else:
            self.client = None
            logger.warning("No Gemini API key provided")

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
            if not self.client:
                logger.warning("Gemini client not configured")
                return None

            logger.info(f"🍌 Nano Banana: Editing product image for: {product_title} (variation: {variation})")

            # Download original image
            response = requests.get(original_image_url, timeout=10)
            response.raise_for_status()
            image_data = response.content

            # Load image
            image = Image.open(io.BytesIO(image_data))

            # Get variation-specific edit instructions
            edit_instructions = self._get_edit_instructions(variation)

            # Create edit prompt
            edit_prompt = f"""Edit this product image of {product_title}.

{edit_instructions}

🚫 CRITICAL - ABSOLUTELY NO TEXT ANYWHERE:
1. Remove ALL text, letters, numbers, words, logos, brand names, labels, watermarks
2. Replace any text areas with CLEAN, BLANK surfaces matching the product's material
3. The product must be COMPLETELY TEXT-FREE - no visible typography anywhere
4. If there are labels or stickers, replace them with plain solid-color surfaces
5. No product model numbers, no brand marks, no printed words of any kind

✅ WHAT TO KEEP:
1. Keep the EXACT SAME PRODUCT - only change angle, lighting, and background
2. DO NOT change product design, colors, or features
3. Maintain product realism and quality
4. Professional e-commerce photography quality
5. High resolution, ultra-sharp focus
6. Clean, professional background"""

            logger.info(f"Nano Banana edit prompt: {edit_prompt[:120]}...")

            # Use Nano Banana to edit the image
            response = self.client.models.generate_content(
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

                            logger.info(f"✅ Nano Banana: Successfully edited image (variation: {variation})")
                            return data_url

            logger.error("No edited image data found in Nano Banana response")
            logger.error(f"Response structure: {dir(response)}")
            return None

        except Exception as e:
            logger.error(f"❌ Error editing image with Nano Banana: {str(e)}")
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
            if not self.client:
                logger.warning("Gemini client not configured")
                return None

            logger.info(f"🍌 Nano Banana: Generating image for: {product_title} (variation: {variation})")
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

            # Use Nano Banana to generate image
            response = self.client.models.generate_content(
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

                            logger.info(f"✅ Nano Banana: Successfully generated image (variation: {variation})")
                            return data_url

            logger.error("No image data found in Nano Banana response")
            logger.error(f"Response structure: {dir(response)}")
            return None

        except Exception as e:
            logger.error(f"Error generating image with Nano Banana: {str(e)}")
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
            if not self.client:
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
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[analysis_prompt, image]
            )

            image_prompt = response.text.strip()
            logger.info(f"Generated image prompt for {product_title}: {image_prompt[:100]}...")

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
EDIT INSTRUCTIONS (Main Front View - Image 1):
🎯 CAMERA POSITION:
- DIRECT front-facing view, STRAIGHT-ON at exact eye level (0° rotation)
- Camera is DIRECTLY in front of the product center
- Product is PERFECTLY CENTERED in frame
- Show the FRONT FACE of the product prominently
- NO side or depth visible - completely flat front view

💡 LIGHTING:
- Bright, even, FLAT lighting from front
- Soft diffused light eliminates all shadows
- Very bright, high-key lighting
- Clean white or very light gray background
- Professional studio flash lighting setup

✅ RESULT: Clean, bright, straight-on front product shot with no angle or depth
""",
            "angle1": """
EDIT INSTRUCTIONS (Top-Down Angled View - Image 2):
🎯 CAMERA POSITION:
- Camera positioned HIGH ABOVE the product looking DOWN at 60-70° angle
- Show the TOP and FRONT surfaces of the product simultaneously
- Product viewed from BIRD'S EYE perspective
- This creates a DRAMATICALLY DIFFERENT view than Image 1
- Show depth, height, and three-dimensional form
- Product fills frame but shows its 3D structure

💡 LIGHTING:
- Strong directional side lighting from 90° angle (side)
- Creates VISIBLE shadows and highlights
- More dramatic contrast than Image 1
- Light gray or gradient background
- Emphasizes product depth and dimensions

✅ RESULT: Dramatic top-down angled shot showing product depth and 3D structure - CLEARLY DIFFERENT from Image 1
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
