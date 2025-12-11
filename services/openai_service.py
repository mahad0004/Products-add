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
   - REMOVE vendor names completely - do NOT include in description

3. ABSOLUTELY NO LINKS ALLOWED - REMOVE ALL URLs:
   - NO hyperlinks (<a href="...">)
   - NO website URLs (www., http://, https://, .com, .co.uk, .net, etc.)
   - NO link text like "Click here", "Visit our website", "Learn more at"
   - If description mentions a website, DELETE the entire sentence

4. REMOVE ALL CONTACT INFORMATION from title and body_html:
   - Phone numbers: ALL formats (e.g., 01234 567890, +44 1234 567890, (123) 456-7890, 123-456-7890)
   - Email addresses: ALL formats (e.g., info@company.com, sales@example.co.uk)
   - Fax numbers: ALL formats
   - Social media: ALL handles and links (@company, facebook.com/company, LinkedIn, Twitter, etc.)
   - Physical addresses: ALL street addresses, postcodes, locations, "Contact us at..."
   - Contact phrases: "Call us", "Email us", "Reach us at", "Contact information"

5. ABSOLUTELY NO IMAGES OR PICTURES IN DESCRIPTION:
   - ❌ NO <img> tags in the description HTML
   - ❌ NO <picture> tags
   - ❌ NO image URLs or image links
   - ❌ NO base64 encoded images
   - ❌ NO references to "see picture", "shown in image", "refer to photo", "image shows"
   - ❌ NO QR codes or barcode references
   - ❌ NO visual content embedded in body_html
   - ✅ ONLY text-based HTML: headings, paragraphs, lists, tables

6. SCAN THE ENTIRE DESCRIPTION and remove ANY occurrence of:
   - Phone numbers (look for patterns like: 0xxxx xxxxxx, +xx, xxx-xxx-xxxx)
   - Email addresses (look for: xxx@xxx.xxx)
   - Websites (look for: www., http, .com, .co.uk, .net, etc.)
   - Company names in footer/header sections
   - Any form of contact invitation
   - Any <img> tags or image references

7. If you find contact info, brand names, links, or images - DELETE them completely - do NOT replace with placeholders

8. TITLE IS MANDATORY - YOU MUST GENERATE A TITLE:
   - If input title is missing or empty, create a descriptive title from the description
   - Title must ALWAYS be 80-150 characters (aim for 100+)
   - Title is the MOST IMPORTANT field - never leave it empty
   - Use product description to extract key features and create comprehensive title

========== JSON OUTPUT FORMAT ==========
9. Output only JSON (no extra commentary).
10. Keep JSON keys exactly as specified: title, seo_title, seo_description, body_html, meta_keywords, meta_description, short_title, slug.
11. Produce:
   - title: MANDATORY! LONG, highly descriptive, SEO-optimized product title (80-150 chars, aim for 100+ chars). Include key features, materials, specifications, and benefits. Make it comprehensive and keyword-rich. NO BRAND NAMES! NEVER LEAVE EMPTY!
   - short_title: concise version for UI (max 60 chars). NO BRAND NAMES! NEVER LEAVE EMPTY!
   - seo_title: SEO-optimized title with keyword near front (max 70 chars). NO BRAND NAMES!
   - seo_description: meta description (110-160 chars) with keyword and call to action. NO BRAND NAMES!
   - body_html: large HTML description (3-6 paragraphs) with headings, bullet lists, features, benefits, specs, FAQ. NO BRAND NAMES! NO CONTACT INFO! NO IMAGES! NO <img> TAGS!
   - meta_keywords: comma-separated list of 8-15 keyword variants. NO BRAND NAMES!
   - slug: URL-safe slug from short_title (lowercase, hyphens). NO BRAND NAMES!
   - meta_description: same as seo_description

NOTE: DO NOT generate "tags" or "meta_tags" - tags are added automatically from the source website.

⚠️ CRITICAL TITLE REQUIREMENTS - YOU WILL BE PENALIZED FOR SHORT TITLES:
- Title MUST be MINIMUM 80 characters, MAXIMUM 150 characters (STRICT REQUIREMENT)
- AIM FOR 100-120 characters for best SEO
- Short titles under 80 characters are UNACCEPTABLE and will be REJECTED
- Include: product type + key features + materials + specifications + benefits
- Use descriptive adjectives: Premium, Professional, Heavy Duty, Industrial Grade, High-Performance, Durable
- Add specific details: sizes, materials, colors, key features, benefits
- Make it comprehensive and keyword-rich

✅ Examples of CORRECT titles (80-150 chars):
  * "Premium Heavy Duty Safety Boot with Composite Toe Cap, Metal-Free Construction, and Slip-Resistant Rubber Outsole" (117 chars) ✅
  * "Professional Industrial Storage Box 48L - Clear Stackable Container with Secure Lid for Warehouse Organization" (113 chars) ✅
  * "High-Performance Anti-Slip Floor Tape 50mm x 18m - Yellow & Black Hazard Warning with Strong Adhesive Backing" (112 chars) ✅
  * "Durable Metal Parking Bollard 90mm Diameter - Fixed Security Post for Vehicle Access Control and Protection" (110 chars) ✅

❌ Examples of UNACCEPTABLE titles (too short - FORBIDDEN):
  * "Safety Boot" (11 chars) ❌ REJECTED - TOO SHORT
  * "Storage Box 48L" (15 chars) ❌ REJECTED - TOO SHORT
  * "Floor Tape" (10 chars) ❌ REJECTED - TOO SHORT
  * "Metal Bollard for Parking" (25 chars) ❌ REJECTED - TOO SHORT

⚠️ IF YOUR GENERATED TITLE IS UNDER 80 CHARACTERS, YOU MUST EXPAND IT BY ADDING:
- More descriptive adjectives (Premium, Professional, Heavy Duty, Industrial, Commercial-Grade)
- Key features (Metal-Free, Composite Toe, Slip-Resistant, Stackable, Weather-Resistant)
- Materials (Steel, Plastic, Rubber, Aluminum, Powder-Coated)
- Specifications (sizes, dimensions, capacity, weight, load rating)
- Benefits (Safety, Security, Organization, Protection, Durability)
- Applications (Warehouse, Industrial, Commercial, Workshop, Parking)

========== CONTENT RULES ==========
9. PRESERVE ALL DETAILS FROM ORIGINAL DESCRIPTION - CRITICAL:
   - You MUST extract and preserve EVERY detail from the input_description
   - This includes: dimensions, measurements, specifications, features, materials, colors, sizes, variants
   - Weight, capacity, volume, load ratings, certifications
   - Size charts, dimension tables, specification tables
   - Material specifications (gauge, grade, thickness, composition)
   - Color options, finish types, design details
   - Compatibility information, usage instructions, safety notes
   - Warranty information, compliance standards, certifications
   - ALL technical details must be included in the output
   - Do NOT summarize or abbreviate - include EVERYTHING
10. CONDITIONAL DIMENSIONS SECTION:
   - ONLY create dimension tables if the input_description contains actual measurements
   - Check for patterns: mm, cm, m, inches, kg, lbs, L x W x H, dimensions, specifications
   - If dimensions exist → Format as professional HTML table
   - If NO dimensions found → Skip table completely, use regular text or omit section
11. Do NOT invent new specs - only use what's provided in input_description
12. Use US English
13. Ensure body_html is comprehensive (300-1500 words, longer if needed for ALL specs/dimensions/details)
14. Focus ONLY on product features, materials, benefits, and specifications from original description
15. INCLUDE ALL DETAILS - even if the description is long, ALL information must be preserved
16. Return ONLY valid JSON - no extra text or commentary"""

        user_prompt = f"""Raw product input:
{{
  "input_title": "{title}",
  "input_description": "{description[:3000]}",
  "brand": "{vendor}"
}}

========== YOUR TASK ==========
1. FIRST - SCAN for and REMOVE these from BOTH title AND description:
   - Brand names: Black Bull, System Tek, Euroslide, ModSec, Securus, ANY proper noun brands
   - Vendor names: ANY company/manufacturer names
   - Phone numbers in ANY format: digits like 1234567890, patterns with dashes or spaces
   - Emails: any patterns like info at company dot com
   - Websites: URLs like www dot example dot com or https patterns
   - Links: ANY <a href="..."> tags or clickable text
   - Pictures/Images: NO <img> tags, NO <picture> tags, NO image URLs, NO base64 images
   - Image references: NO "see image", "shown in picture", "refer to photo"
   - Contact info: NO "call us", "email us", addresses, fax numbers

CRITICAL: body_html must ONLY contain text-based HTML:
✅ Allowed: <h2>, <h3>, <p>, <ul>, <li>, <table>, <tr>, <td>, <th>, <strong>, <em>, <br>
❌ Forbidden: <img>, <picture>, <iframe>, <video>, <embed>, <object>, image URLs

2. CRITICAL - EXTRACT AND PRESERVE ALL PRODUCT INFORMATION:
   - EXTRACT EVERY SINGLE DETAIL from input_description - this is MANDATORY
   - YOU MUST INCLUDE ALL OF THE FOLLOWING IN body_html:
     * ALL dimensions, measurements, sizes (e.g., "1800mm x 600mm", "L x W x H", etc.)
     * ALL size charts, dimension tables, specification tables
     * ALL color options, material types, finish options
     * ALL variant information (sizes, colors, configurations)
     * ALL technical specifications (weight, capacity, load rating, material thickness, gauge, etc.)
     * ALL features and benefits mentioned
     * ALL usage instructions and applications
     * ALL safety information and warnings
     * ALL compatibility information
     * ALL certifications, standards, compliance information
     * ALL warranty details if mentioned
   - FORMAT ALL DATA PROFESSIONALLY:
     * IF dimensions exist: FORMAT as professional HTML tables with inline CSS styling
     * IF size charts exist: FORMAT as clean HTML tables with headers
     * IF color/material options exist: LIST them clearly in bullet points or tables
     * Tables MUST include inline CSS styling for professional appearance
   - IF input_description has lots of details, your body_html must be COMPREHENSIVE (even 1000-1500 words)
   - DO NOT ABBREVIATE - include EVERYTHING from the original
   - These details are CRITICAL for customers - NOTHING should be omitted

2. SECOND - Replace removed brand names with GENERIC terms:
   - Use: Premium, Professional, Heavy Duty, High-Performance, Industrial Grade, Commercial
   - Example: Black Bull Protection Guard becomes Premium Protection Guard
   - Example: System Tek Workbench becomes Professional Workbench

3. THIRD - Generate SEO-optimized JSON with:
   - title: LONG (80-150 chars, aim for 100+), highly descriptive, keyword-rich title. Include key features, materials, specs, and benefits. Use descriptive adjectives (Premium, Professional, Heavy Duty, etc.). NO brand names, NO vendor names!
   - short_title: Concise UI version with NO brand names, NO vendor names (max 60 chars)
   - seo_title: SEO title with NO brand names, NO vendor names (max 70 chars)
   - seo_description: Meta description with NO brand names, NO vendor names (110-160 chars)
   - body_html: Rich HTML description (300-800 words) with NO brand names, NO vendor names, NO contact info, NO links, NO images
   - meta_keywords: Keyword list with NO brand names, NO vendor names (8-15 items)
   - slug: URL-safe slug with NO brand names, NO vendor names
   - meta_description: Same as seo_description

   NOTE: DO NOT include "tags" or "meta_tags" in the output - they are handled separately

   TITLE MUST BE LONG AND DESCRIPTIVE:
   - Minimum 80 characters, ideal 100-150 characters
   - Include product type + key features + materials + specifications
   - Use descriptive words: Premium, Professional, Heavy Duty, Industrial, Durable, High-Performance
   - Add dimensions/sizes if available in input
   - Make it comprehensive and SEO-friendly

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
   - CRITICAL: SCAN ENTIRE HTML for and REMOVE:
     * Phone numbers, emails, websites, fax numbers
     * Links (<a href="...">) and URLs
     * Vendor/brand names
     * Contact information of any kind
     * Image tags (<img>, <picture>) or image references
     * Any visual content (base64 images, image URLs)
     * Any references to images ("see image", "shown in picture", etc.)
   - Do NOT invent specs - only use what's in the input description
   - ONLY use text-based HTML: <h2>, <p>, <ul>, <li>, <table>, <strong>, <em>

========== OUTPUT ==========
Return ONLY valid JSON with these exact keys:
{{ "title","short_title","seo_title","seo_description","body_html","meta_keywords","meta_description","slug" }}

DO NOT include "tags" or "meta_tags" - they are managed separately.
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
                max_tokens=4000  # Increased for comprehensive body_html with all details
            )

            content = response.choices[0].message.content.strip()
            logger.info(f"✅ OpenAI: Got response ({len(content)} chars)")

            # Parse JSON response
            ai_data = self._parse_json_response(content)

            if ai_data:
                # CRITICAL SANITIZATION: Remove ANY images, links, contact info that slipped through
                if 'body_html' in ai_data:
                    original_html = ai_data['body_html']
                    sanitized_html = self._sanitize_html(original_html)
                    if sanitized_html != original_html:
                        logger.warning("⚠️ OpenAI: Found and removed prohibited content from body_html")
                    ai_data['body_html'] = sanitized_html

                # Also sanitize title and other fields
                for field in ['title', 'short_title', 'seo_title', 'seo_description', 'meta_description']:
                    if field in ai_data and ai_data[field]:
                        ai_data[field] = self._sanitize_html(ai_data[field])

                # CRITICAL: Validate and fix title length
                generated_title = ai_data.get('title', '')

                if generated_title and len(generated_title) < 80:
                    logger.warning(f"⚠️ OpenAI: Title too short ({len(generated_title)} chars): '{generated_title}'")
                    logger.warning(f"   Expanding title to meet 80 character minimum...")

                    # Expand the title by adding descriptive terms
                    short_title = generated_title
                    product_type = short_title.split()[0] if short_title else "Product"

                    # Add descriptive prefix if not already present
                    if not any(word in short_title.lower() for word in ['premium', 'professional', 'heavy duty', 'industrial', 'commercial', 'high-performance']):
                        short_title = f"Premium {short_title}"

                    # Add benefits/features suffix to reach minimum length
                    if len(short_title) < 80:
                        short_title += " - High-Quality Professional Grade for Industrial and Commercial Applications"

                    # Ensure it doesn't exceed maximum
                    if len(short_title) > 150:
                        short_title = short_title[:147] + "..."

                    ai_data['title'] = short_title
                    logger.info(f"✅ OpenAI: Title expanded to {len(short_title)} chars: '{short_title[:80]}...'")

                elif not generated_title:
                    # No title generated - create one from description or original title
                    logger.warning(f"⚠️ OpenAI: No title generated, creating from original...")
                    fallback_title = title if title else "Professional Industrial Product"
                    if len(fallback_title) < 80:
                        fallback_title = f"Premium {fallback_title} - High-Quality Professional Grade for Industrial Use"
                    ai_data['title'] = fallback_title[:150]
                    logger.info(f"✅ OpenAI: Fallback title created: '{ai_data['title'][:80]}...'")

                # Merge AI data with original product
                enhanced = {**product, **ai_data}
                final_title = enhanced.get('title', 'Untitled')
                logger.info(f"✅ OpenAI: Final title ({len(final_title)} chars): '{final_title[:80]}...'")
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

    def _sanitize_html(self, html_content):
        """
        CRITICAL: Remove ALL images, links, and contact info from HTML
        This is a failsafe to ensure nothing slips through OpenAI
        """
        if not html_content:
            return html_content

        import re

        # Remove ALL image tags
        html_content = re.sub(r'<img[^>]*>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<picture[^>]*>.*?</picture>', '', html_content, flags=re.IGNORECASE | re.DOTALL)

        # Remove ALL links (but keep the text)
        html_content = re.sub(r'<a[^>]*>(.*?)</a>', r'\1', html_content, flags=re.IGNORECASE | re.DOTALL)

        # Remove data URIs and base64 images
        html_content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', html_content, flags=re.IGNORECASE)

        # Remove email addresses
        html_content = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REMOVED]', html_content)

        # Remove phone numbers (various formats)
        html_content = re.sub(r'\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[REMOVED]', html_content)
        html_content = re.sub(r'\b0\d{4}\s?\d{6}\b', '[REMOVED]', html_content)  # UK format

        # Remove URLs
        html_content = re.sub(r'https?://[^\s<>"]+', '[REMOVED]', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'www\.[^\s<>"]+', '[REMOVED]', html_content, flags=re.IGNORECASE)

        # Remove common contact phrases
        contact_patterns = [
            r'call\s+us\s+(at|on)',
            r'email\s+us\s+(at)?',
            r'contact\s+us\s+(at|on)',
            r'reach\s+us\s+(at|on)',
            r'phone\s*:',
            r'tel\s*:',
            r'email\s*:',
            r'fax\s*:',
        ]
        for pattern in contact_patterns:
            html_content = re.sub(pattern, '', html_content, flags=re.IGNORECASE)

        return html_content

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
