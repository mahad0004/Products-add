"""
OpenAI Service
Handles OpenAI API interactions for product description enhancement
"""

from openai import OpenAI
import json
import logging

logger = logging.getLogger(__name__)


class OpenAIService:
    """Service for interacting with OpenAI API"""

    def __init__(self, api_key):
        self.api_key = api_key
        self.client = OpenAI(api_key=api_key) if api_key else None

    def enhance_product_description(self, product):
        """
        Generate SEO-optimized product content using OpenAI
        Returns: enhanced product with AI-generated fields
        """
        title = product.get('title', 'Product')
        description = product.get('description', '') or product.get('body_html', '')
        price = product.get('price', {})

        # Extract price value
        if isinstance(price, dict):
            price_value = price.get('current', 0)
        else:
            price_value = price

        # Extract vendor/brand
        vendor = product.get('vendor', '')
        product_type = product.get('product_type', '')

        # Build prompt
        system_prompt = """You are a professional e-commerce copywriter and SEO specialist. Your task is to take a raw product title and raw product description and produce a clean, highly-SEO optimized product payload for publishing. Always follow these rules:

========== MOST IMPORTANT - BRAND & CONTACT REMOVAL (DO THIS FIRST!) ==========
1. REMOVE ALL BRAND NAMES from title, seo_title, body_html, and ALL text fields:
   - Examples to remove: "Black Bull", "BLACK BULL", "System Tek", "Euroslide", "ModSec", "Securus", "ConeLITE", etc.
   - Replace with GENERIC terms: "Premium", "Professional", "Heavy Duty", "High-Performance", "Industrial", etc.

2. REMOVE ALL COMPANY NAMES and MANUFACTURER NAMES from ALL fields:
   - Any proper nouns that are company/brand names MUST be removed
   - Do NOT keep ANY branded product line names

3. REMOVE ALL CONTACT INFORMATION from title and body_html:
   - Phone numbers: ALL formats (e.g., 01234 567890, +44 1234 567890, (123) 456-7890, 123-456-7890)
   - Email addresses: ALL formats (e.g., info@company.com, sales@example.co.uk)
   - Websites: ALL URLs and domain names (e.g., www.example.com, example.co.uk, https://...)
   - Social media: ALL handles and links (@company, facebook.com/company)
   - Physical addresses: ALL street addresses, postcodes, locations

4. SCAN THE ENTIRE DESCRIPTION and remove ANY occurrence of:
   - Phone numbers (look for patterns like: 0xxxx xxxxxx, +xx, xxx-xxx-xxxx)
   - Email addresses (look for: xxx@xxx.xxx)
   - Websites (look for: www., http, .com, .co.uk, .net, etc.)
   - Company names in footer/header sections

5. If you find contact info or brand names, DELETE them completely - do NOT replace with placeholders

========== JSON OUTPUT FORMAT ==========
6. Output only JSON (no extra commentary).
7. Keep JSON keys exactly as specified: title, seo_title, seo_description, body_html, meta_keywords, meta_description, meta_tags, short_title, slug.
8. Produce:
   - title: attention-grabbing product title with GENERIC descriptive terms (max 150 chars). NO BRAND NAMES!
   - short_title: concise version for UI (max 60 chars). NO BRAND NAMES!
   - seo_title: SEO-optimized title with keyword near front (max 70 chars). NO BRAND NAMES!
   - seo_description: meta description (110-160 chars) with keyword and call to action. NO BRAND NAMES!
   - body_html: large HTML description (3-6 paragraphs) with headings, bullet lists, features, benefits, specs, FAQ. NO BRAND NAMES! NO CONTACT INFO!
   - meta_keywords: comma-separated list of 8-15 keyword variants. NO BRAND NAMES!
   - meta_tags: array of 3-8 short tags. NO BRAND NAMES!
   - slug: URL-safe slug from short_title (lowercase, hyphens). NO BRAND NAMES!
   - meta_description: same as seo_description

========== CONTENT RULES ==========
9. PRESERVE ALL factual numbers, dimensions, and measurements:
   - Dimensions (length, width, height, diameter, thickness)
   - Weight, capacity, volume
   - Size charts and dimension tables
   - Technical specifications
   - Material specifications (gauge, grade, etc.)
10. CONDITIONAL DIMENSIONS SECTION:
   - ONLY create dimension tables if the input_description contains actual measurements
   - Check for patterns: mm, cm, m, inches, kg, lbs, L x W x H, dimensions, specifications
   - If dimensions exist → Format as professional HTML table
   - If NO dimensions found → Skip table completely, use regular text or omit section
11. Do NOT invent new specs - only use what's provided
12. Use US English
13. Ensure body_html is 300-1000 words (longer if needed for specs/dimensions)
14. Focus ONLY on product features, materials, benefits, and specifications
15. Return ONLY valid JSON - no extra text or commentary"""

        user_prompt = f"""Raw product input:
{{
  "input_title": "{title}",
  "input_description": "{description[:3000]}",
  "brand": "{vendor}"
}}

========== YOUR TASK ==========
1. FIRST - SCAN for and REMOVE these from BOTH title AND description:
   - Brand names: Black Bull, System Tek, Euroslide, ModSec, Securus, ANY proper noun brands
   - Phone numbers in ANY format: digits like 1234567890, patterns with dashes or spaces
   - Emails: any patterns like info at company dot com
   - Websites: URLs like www dot example dot com or https patterns

2. CRITICAL - CHECK FOR AND PRESERVE PRODUCT INFORMATION:
   - FIRST: Check if input_description contains dimensions/measurements (mm, cm, m, kg, lbs, inches, L x W x H, etc.)
   - IF dimensions exist:
     * KEEP ALL dimensions, measurements, sizes (e.g., "1800mm x 600mm", "L x W x H", etc.)
     * KEEP ALL size charts, dimension tables, specification tables
     * FORMAT dimensions as professional HTML tables (see examples in system prompt)
     * FORMAT size charts as clean, styled HTML tables with headers
     * KEEP ALL technical specifications (weight, capacity, material thickness, etc.)
     * Tables MUST include inline CSS styling for professional appearance
   - IF NO dimensions exist in input:
     * Skip dimension tables completely
     * Use regular paragraphs and bullet points for features
   - KEEP ALL compatibility information (regardless of dimensions)
   - These are CRITICAL for customers - do NOT remove or abbreviate them
   - Physical addresses: street names, postcodes, city names with addresses
   - Social media: handles and links to social platforms

2. SECOND - Replace removed brand names with GENERIC terms:
   - Use: Premium, Professional, Heavy Duty, High-Performance, Industrial Grade, Commercial
   - Example: Black Bull Protection Guard becomes Premium Protection Guard
   - Example: System Tek Workbench becomes Professional Workbench

3. THIRD - Generate SEO-optimized JSON with:
   - title: Long, keyword-rich title with NO brand names (max 150 chars)
   - short_title: Concise UI version with NO brand names (max 60 chars)
   - seo_title: SEO title with NO brand names (max 70 chars)
   - seo_description: Meta description with NO brand names (110-160 chars)
   - body_html: Rich HTML description (300-800 words) with NO brand names, NO contact info
   - meta_keywords: Keyword list with NO brand names (8-15 items)
   - meta_tags: Short tags with NO brand names (3-8 items)
   - slug: URL-safe slug with NO brand names
   - meta_description: Same as seo_description

4. IMPORTANT - In body_html structure:
   - Include headings (<h2>), paragraphs (<p>), bullet lists (<ul><li>)

   - CONDITIONAL: Only add <h2>Dimensions & Specifications</h2> section if input_description contains measurements

   - FORMAT DIMENSIONS AS HTML TABLE (only if dimension data exists in input):
     ```html
     <table style="width:100%; border-collapse:collapse; margin:20px 0;">
       <thead>
         <tr style="background-color:#f8f9fa; border-bottom:2px solid #dee2e6;">
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Specification</th>
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Measurement</th>
         </tr>
       </thead>
       <tbody>
         <tr><td style="padding:10px; border:1px solid #dee2e6;">Length</td><td style="padding:10px; border:1px solid #dee2e6;">1800mm</td></tr>
         <tr><td style="padding:10px; border:1px solid #dee2e6;">Width</td><td style="padding:10px; border:1px solid #dee2e6;">600mm</td></tr>
         <tr><td style="padding:10px; border:1px solid #dee2e6;">Height</td><td style="padding:10px; border:1px solid #dee2e6;">1200mm</td></tr>
       </tbody>
     </table>
     ```

   - FORMAT SIZE CHARTS AS HTML TABLE (if multiple sizes/variants exist):
     ```html
     <table style="width:100%; border-collapse:collapse; margin:20px 0;">
       <thead>
         <tr style="background-color:#f8f9fa; border-bottom:2px solid #dee2e6;">
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Size</th>
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Length</th>
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Width</th>
           <th style="padding:12px; text-align:left; border:1px solid #dee2e6;">Height</th>
         </tr>
       </thead>
       <tbody>
         <tr><td style="padding:10px; border:1px solid #dee2e6;">Small</td><td>...</td><td>...</td><td>...</td></tr>
       </tbody>
     </table>
     ```

   - Add <h2>Technical Specifications</h2> section (can also use table format)
   - Add 2-3 short FAQ Q&A
   - SCAN ENTIRE HTML for phone numbers, emails, websites and REMOVE them
   - Do NOT invent specs - only use what's in the input description

========== OUTPUT ==========
Return ONLY valid JSON with these exact keys:
{{ "title","short_title","seo_title","seo_description","body_html","meta_keywords","meta_description","meta_tags","slug" }}

NO explanations, NO comments, ONLY JSON."""

        try:
            if not self.client:
                logger.error("❌ OpenAI API key not configured - cannot enhance products!")
                logger.error("   Set OPENAI_API_KEY in Railway environment variables")
                return product

            logger.info(f"🔄 OpenAI: Enhancing '{title[:50]}...'")

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Use gpt-4o-mini (faster and cheaper) or gpt-4o
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2500  # Increased for longer body_html content
            )

            content = response.choices[0].message.content.strip()
            logger.info(f"✅ OpenAI: Got response ({len(content)} chars)")

            # Parse JSON response
            ai_data = self._parse_json_response(content)

            if ai_data:
                # Merge AI data with original product
                enhanced = {**product, **ai_data}
                logger.info(f"✅ OpenAI: Enhanced title: '{enhanced.get('title', 'Untitled')[:80]}...'")
                logger.info(f"✅ OpenAI: Enhanced description: {len(enhanced.get('body_html', ''))} chars")
                return enhanced
            else:
                logger.error("❌ OpenAI: Failed to parse JSON response")
                logger.error(f"   Response preview: {content[:200]}...")
                logger.error("   Returning original product unchanged")
                return product

        except Exception as e:
            logger.error(f"❌ OpenAI API Error: {str(e)}")
            logger.error(f"   Product: {title[:50]}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.error("   Returning original product unchanged")
            return product

    def _parse_json_response(self, content):
        """
        Parse JSON from OpenAI response
        Handles various formats including code blocks
        """
        try:
            # Try direct JSON parse
            return json.loads(content)
        except:
            pass

        # Try extracting from code blocks
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                try:
                    return json.loads(content[start:end].strip())
                except:
                    pass

        # Try extracting from any code block
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                try:
                    return json.loads(content[start:end].strip())
                except:
                    pass

        # Try finding JSON object
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except:
                pass

        logger.error("Could not parse JSON from OpenAI response")
        return None

    def generate_product_image(self, image_prompt, product_title):
        """
        Generate a product image using DALL-E 3

        Args:
            image_prompt: Detailed prompt for image generation
            product_title: Product title for context

        Returns:
            str: URL of generated image
        """
        try:
            if not self.client:
                logger.warning("OpenAI API key not configured, cannot generate images")
                return None

            logger.info(f"Generating image with DALL-E 3 for: {product_title}")

            # Use DALL-E 3 to generate image
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=image_prompt[:4000],  # DALL-E 3 has a 4000 char limit
                size="1024x1024",
                quality="standard",
                n=1
            )

            image_url = response.data[0].url
            logger.info(f"Successfully generated image: {image_url[:100]}...")

            return image_url

        except Exception as e:
            logger.error(f"Error generating image with DALL-E 3: {str(e)}")
            return None
