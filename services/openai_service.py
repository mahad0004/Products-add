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

1. Output only JSON (no extra commentary).
2. Keep JSON keys exactly as specified in the schema: title, seo_title, seo_description, body_html, meta_keywords, meta_description, meta_tags, short_title, slug.
3. Produce:
   - title: a long, attention-grabbing product title built by prepending and appending relevant words/phrases to the original title (use synonyms, adjectives, target keywords). Make it long but natural (max 150 chars).
   - short_title: a concise, cleaned version for UI (max 60 chars).
   - seo_title: highly SEO-optimized title (include primary keyword near the front, max 70 chars).
   - seo_description: short meta description for search results (110-160 chars), includes main keyword and a call to action.
   - body_html: a very large, marketer-style HTML description (3-6 paragraphs) with headings, bullet lists of features, benefits, use cases, technical specs, and a persuasive closing paragraph + a short FAQ section (2-3 Q&A). Include the main keyword 4-6 times naturally. Use <h2>, <p>, <ul>, <li>, <strong>.
   - meta_keywords: comma-separated list of 8-15 keyword/phrase variants (primary keywords, long-tail).
   - meta_tags: array of short tags (3-8 items).
   - slug: URL-safe slug derived from short_title (lowercase, hyphens).
   - meta_description: same as seo_description (duplicate is OK).

CRITICAL - MUST REMOVE:
4. Remove ALL brand names, company names, vendor names, manufacturer names from title, seo_title, body_html, and all descriptions.
5. Remove ALL contact information: phone numbers, email addresses, websites, social media handles, addresses.
6. Remove ALL trademarked names, logos references, and branded terms.
7. Use GENERIC descriptive terms instead (e.g., "Premium" instead of "Nike", "Professional" instead of brand names).
8. Focus on product features, benefits, and specifications WITHOUT mentioning specific brands.

CONTENT RULES:
9. If numeric specs (weight, dimensions, capacity, etc.) are present in the raw description, surface them in a TECHNICAL SPECS bullet list.
10. Always preserve factual numbers from input (do not invent specs). You may expand phrasing but not invent new numeric values.
11. Use US English. Avoid adding price or stock information.
12. Ensure body_html is at least ~300-800 words depending on the product; emphasize benefits and use-cases.
13. When forming keywords, include variations, synonyms, and long-tail phrases.
14. Return valid JSON only. Do not include any commentary, explanations, or extra fields."""

        user_prompt = f"""Raw product input (do not modify; use as source of truth):
{{
  "input_title": "{title}",
  "input_description": "{description[:1000]}",
  "brand": "{vendor}"
}}

Instructions:
- Use the raw input fields above to generate the JSON output required by the system prompt.
- Primary keyword = the most important noun phrase from input_title (choose best guess).
- Prepend and append strong adjectives and relevant search phrases to create a long marketing title (but keep it natural).
- Produce a short_title for UI and a slug derived from it.
- Create body_html (~300-800+ words) containing headings, 3-5 benefit bullets, 3 use-cases, technical specs section (use specs if provided), and 2-3 short FAQ Q&A.
- Create meta fields (meta_keywords array or comma list) including synonyms and long-tail phrases.
- Make seo_title <= 70 chars and seo_description 110-160 chars.
- Do not invent numeric specs. If specs not provided, do not add numbers.

CRITICAL - CONTENT CLEANING:
- REMOVE ALL brand names, company names, vendor names from title, seo_title, body_html, and descriptions
- REMOVE ALL contact info: phone numbers (any format), email addresses, websites, URLs, social media handles, physical addresses
- REMOVE ALL trademarked names and branded terms
- Replace brand references with generic descriptive terms (e.g., "Premium Quality", "Professional Grade", "High-Performance")
- Focus ONLY on product features, materials, benefits, and specifications

- Output only JSON following the exact keys required.

Return JSON with these keys:
{{ "title","short_title","seo_title","seo_description","body_html","meta_keywords","meta_description","meta_tags","slug" }}"""

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
