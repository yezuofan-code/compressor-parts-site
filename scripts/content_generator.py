"""AI Content Generator for Printer Parts Niche

Generates articles using DeepSeek/Claude API, with product data from AliExpress.
"""
import json
import os
import re
import yaml
import sys
import random
from datetime import datetime
from typing import Optional

# API config from environment
LLM_API_KEY = os.environ.get('LLM_API_KEY', 'sk-0bc443950c3a4708ae9f68f90056a61d')
LLM_API_URL = os.environ.get('LLM_API_URL', 'https://api.deepseek.com/chat/completions')
LLM_MODEL = os.environ.get('LLM_MODEL', 'deepseek-chat')

# Available article types (randomly pick each day)
ARTICLE_TYPES = [
    "comparison",       # Compare 3-4 similar products
    "buying_guide",     # What to look for when buying X
    "review",           # Single product deep review
    "compatibility",    # Which models are compatible with X
    "replacement_guide", # How to replace / upgrade X
    "problem_solution", # "Printer showing error X? Here's the fix"
]


def load_config(config_path: str) -> dict:
    """Load niche YAML config."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _get_next_keyword(config: dict) -> str:
    """Get next keyword from pool (round-robin with randomness)."""
    keywords = config.get('keywords', [])
    if not keywords:
        return "printer repair parts"

    # Pick a random keyword from the pool
    return random.choice(keywords)


def _get_article_type(keyword: str) -> str:
    """Determine article type - strongly biased toward problem/solution."""
    # If keyword sounds like a problem, always use problem_solution
    if any(w in keyword.lower() for w in ['error', 'fix', 'problem', 'jam', 'not ', 'issue',
                                           'replace', 'repair', 'broken', 'worn', 'failure',
                                           'streak', 'ghost', 'stuck', 'noise', 'smudge']):
        return "problem_solution"

    # 60% chance of problem_solution even for non-problem keywords
    if random.random() < 0.6:
        return "problem_solution"

    return random.choice([t for t in ARTICLE_TYPES if t != "problem_solution"])


def _slugify(text: str) -> str:
    """Convert text to URL slug."""
    text = text.lower().strip()
    # Remove year references
    text = re.sub(r'\s+20\d{2}', '', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def _truncate_title(text: str, max_len: int = 70) -> str:
    """Truncate product title for use in article."""
    patterns = ['-aliexpress', 'Free Shipping', 'Free shipping', 'Wholesale', 'wholesale',
                'In Stock', 'in stock', 'DropShipping', 'dropshipping']
    for p in patterns:
        text = text.replace(p, '').strip()
    if len(text) > max_len:
        text = text[:max_len-3] + '...'
    return text.strip()


def search_products_for_keyword(keyword: str, config: dict, max_results: int = 6) -> list:
    """Search AliExpress for products matching the keyword."""
    from aliexpress_api import search_products, extract_products

    min_price = config.get('min_price', 1)
    max_price = config.get('max_price', 200)
    category_ids = config.get('category_ids', '')

    # Try multiple search strategies
    for sort in ['LAST_VOLUME_DESC', 'SALE_PRICE_ASC']:
        resp = search_products(
            keywords=keyword,
            category_ids=category_ids,
            min_price=min_price,
            max_price=max_price,
            page=1,
            page_size=max_results + 4,
            sort=sort
        )
        products, total = extract_products(resp)
        if products:
            break

    if not products:
        return []

    # Format products for content generation
    results = []
    for p in products[:max_results]:
        pid = str(p.get('product_id', ''))
        title = p.get('product_title', '') or ''
        price = p.get('sale_price', '')
        rating = p.get('star_rating', '')
        sales = p.get('sales_count', 0)
        img = p.get('product_main_image_url', '') or ''
        link = p.get('affiliate_link', '') or p.get('promotion_link', '')
        commission = p.get('commission_rate', '')

        if pid and title:
            results.append({
                'id': pid,
                'title': title,
                'short_name': _truncate_title(title),
                'price': price,
                'rating': rating,
                'sales': sales,
                'image': img,
                'affiliate_link': link,
                'commission_rate': commission,
            })

    return results


def generate_article(keyword: str, products: list, config: dict) -> dict:
    """Generate a printer parts article using LLM."""
    niche_name = config.get('niche_name', 'Printer Parts')
    site_name = config.get('site_title', 'Printer Parts Review')

    # Build product catalogue for AI
    product_catalogue = []
    for i, p in enumerate(products):
        product_catalogue.append(
            f'Product #{i+1}: ID={p["id"]}\n'
            f'  Name: {p["title"][:80]}\n'
            f'  Short Name: {p["short_name"]}\n'
            f'  Price: ${p["price"]}\n'
            f'  Rating: {p["rating"]}/5\n'
            f'  Sales (30d): {p["sales"]}\n'
        )
    product_catalogue_str = '\n'.join(product_catalogue)
    product_ids = [p['id'] for p in products]

    # Determine article type
    article_type = _get_article_type(keyword)

    # Build type-specific prompt
    type_instructions = {
        "comparison": (
            "Write a COMPARISON article comparing these products side by side.\n"
            "- Compare prices, build quality, compatibility\n"
            "- Award winners: 'Best Overall', 'Best Budget', 'Best Value'\n"
            "- Use a comparison table in one section"
        ),
        "buying_guide": (
            "Write a BUYING GUIDE / buyer's guide article.\n"
            "- Explain what to look for when choosing this part\n"
            "- Feature the products as recommendations throughout\n"
            "- Include a 'What to Consider' section"
        ),
        "review": (
            "Write a PRODUCT REVIEW article.\n"
            "- Pick the best 2-3 products as top picks\n"
            "- Include pros/cons for each featured product\n"
            "- End with a final verdict"
        ),
        "compatibility": (
            "Write a COMPATIBILITY GUIDE.\n"
            "- Explain which printer models are compatible with this part\n"
            "- Cross-reference different brand/model compatibility\n"
            "- Include a compatibility table"
        ),
        "replacement_guide": (
            "Write a REPLACEMENT GUIDE / upgrade guide.\n"
            "- Explain when/how to replace this part\n"
            "- Recommend specific products for the job\n"
            "- Include tips for DIY installation"
        ),
        "problem_solution": (
            "Write a PROBLEM-SOLVING / FIX guide article.\n"
            "- Start with a REAL printer problem: error code, paper jam, streaks, noise, ghosting, etc.\n"
            "- Explain WHY this problem happens (root cause: worn part, broken gear, etc.)\n"
            "- Walk through diagnosis step by step\n"
            "- Recommend the specific replacement part as the solution\n"
            "- Include a 'Symptoms Checklist' so readers can self-diagnose\n"
            "- Price the repair: 'Fix it yourself for $X vs repair shop $300'\n"
            "- TONE: like a knowledgeable repair tech, not a salesman"
        ),
    }
    article_instructions = type_instructions.get(article_type, type_instructions['buying_guide'])

    prompt = f"""You are an expert printer repair parts reviewer for {site_name}. Write a detailed, helpful article about {keyword}.

Below are REAL products from AliExpress related to this topic. Feature them naturally in the article.

{product_catalogue_str}

{article_instructions}

Write the article in this exact JSON format (no markdown, no code fences, just raw JSON):
{{
  "title": "SEO-friendly article title (include the keyword naturally)",
  "summary": "2-3 sentence overview of what the article covers.",
  "body_sections": [
    {{
      "heading": "Section heading",
      "text": "2-3 paragraphs of helpful content. Be specific, technical but accessible.",
      "embed_product_ids": ["id1", "id2"],
      "pros": ["Pro 1", "Pro 2", "Pro 3"],
      "cons": ["Con 1", "Con 2"],
      "best_for": "Best Overall / Best Budget / Editor's Pick"
    }}
  ],
  "final_verdict": "Short paragraph with final recommendation.",
  "image_prompt": "Detailed prompt for article cover image (product close-up style)",
  "meta_description": "SEO meta description under 160 characters",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "fuser-assembly or pickup-roller or drum-unit or transfer-belt or printhead or maintenance-kit or toner"
}}

CRITICAL REQUIREMENTS:
1. Use Short Names in article text (not full raw product names)
2. Conversational, expert tone. Not salesy.
3. Each section: 100-180 words. 5-7 sections total.
4. Include product_ids across ALL sections
5. Include prices and ratings naturally in the text
6. Write like a real knowledgeable blogger who has experience with printer repair
7. The article must be genuinely helpful - someone fixing their printer should learn something"""

    headers = {
        'Authorization': f'Bearer {LLM_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': 'You are a printer repair parts expert. Output only valid JSON, no markdown formatting.'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.7,
        'max_tokens': 4000,
    }

    try:
        import requests
        resp = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content'].strip()

        # Clean potential markdown code fences
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

        article = json.loads(content)
        article['keyword'] = keyword
        article['product_ids'] = product_ids
        article['products'] = products
        article['slug'] = _slugify(article.get('title', keyword))
        article['article_type'] = article_type
        article['date'] = datetime.now().strftime('%Y-%m-%d')
        return article

    except Exception as e:
        return {'error': f'LLM API error: {e}'}


def generate_frontmatter(article: dict, image_path: str = '') -> str:
    """Generate Hugo frontmatter from article data.

    Returns the full markdown text ready to save as a Hugo post.
    """
    title = article.get('title', 'Printer Parts Review')
    slug = article.get('slug', _slugify(title))
    date = article.get('date', datetime.now().strftime('%Y-%m-%d'))
    tags = article.get('tags', ['printer-parts'])
    category = article.get('category', 'general')
    meta_desc = article.get('meta_description', '')

    # Get first product for frontmatter metadata
    products = article.get('products', [])
    first_product = products[0] if products else {}

    # Get affiliate link from first product
    aliexpress_link = ''
    for p in products:
        if p.get('affiliate_link'):
            aliexpress_link = p['affiliate_link']
            break

    # Format tags as YAML list
    tags_yaml = '\n  - ' + '\n  - '.join(tags)

    # Use the first product's AliExpress image URL directly (no download needed)
    product_image = first_product.get('image', '') or ''

    frontmatter = f"""---
title: "{title}"
date: {date}
slug: {slug}
image: {product_image}
tags:{tags_yaml}
categories:
  - {category}
price: "{first_product.get('price', '')}"
rating: "{first_product.get('rating', '')}"
sales: "{first_product.get('sales', 0)}"
aliexpress_link: "{aliexpress_link}"
meta_description: "{meta_desc}"
draft: false
---
"""
    return frontmatter


def render_article_body(article: dict) -> str:
    """Render article body in markdown with product cards."""
    lines = []

    # Summary
    summary = article.get('summary', '')
    if summary:
        lines.append(f'> {summary}')
        lines.append('')

    # Body sections
    for section in article.get('body_sections', []):
        heading = section.get('heading', '')
        text = section.get('text', '')
        pros = section.get('pros', [])
        cons = section.get('cons', [])
        best_for = section.get('best_for', '')
        embed_ids = section.get('embed_product_ids', [])

        if heading:
            lines.append(f'## {heading}')
            lines.append('')

        if text:
            lines.append(text)
            lines.append('')

        # Pros & Cons
        if pros or cons:
            lines.append('| ✅ Pros | ❌ Cons |')
            lines.append('|--------|--------|')
            max_len = max(len(pros), len(cons), 1)
            for i in range(max_len):
                pro = pros[i] if i < len(pros) else ''
                con = cons[i] if i < len(cons) else ''
                lines.append(f'| {pro} | {con} |')
            lines.append('')

        # Best for badge
        if best_for:
            lines.append(f'> **🏆 {best_for}**')
            lines.append('')

        # Embed product cards for products in this section
        products = article.get('products', [])
        for p in products:
            if p['id'] in embed_ids:
                link = p.get('affiliate_link', '') or '#'
                lines.append(f'**{p["short_name"]}**')
                lines.append(f'- 💰 Price: **${p["price"]}**')
                if p.get('rating'):
                    lines.append(f'- ⭐ Rating: {p["rating"]}/5')
                if p.get('sales'):
                    lines.append(f'- 📦 Monthly Sales: {p["sales"]}')
                if link and link != '#':
                    lines.append(f'- [🔗 Check Price on AliExpress]({link})')
                lines.append('')

    # Final verdict
    final_verdict = article.get('final_verdict', '')
    if final_verdict:
        lines.append('---')
        lines.append('')
        lines.append('## Final Verdict')
        lines.append('')
        lines.append(final_verdict)
        lines.append('')

    # Product summary table
    products = article.get('products', [])
    if len(products) > 1:
        lines.append('---')
        lines.append('')
        lines.append('## Products Mentioned')
        lines.append('')
        lines.append('| Product | Price | Rating | Sales |')
        lines.append('|---------|-------|--------|-------|')
        for p in products:
            name = p.get('short_name', p.get('title', '')[:40])
            price = f'${p.get("price", "?")}' if p.get('price') else '?'
            rating = f'{p.get("rating", "?")}/5' if p.get('rating') else '?'
            sales = p.get('sales', 0)
            lines.append(f'| {name} | {price} | {rating} | {sales} |')
        lines.append('')

    return '\n'.join(lines)


def generate_and_save(config_path: str, output_dir: str) -> dict:
    """Main entry point: generate article and save as Hugo markdown."""
    # Load config
    config = load_config(config_path)

    # Try up to 3 different keywords until we find products
    products = []
    keyword = None
    for attempt in range(3):
        keyword = _get_next_keyword(config)
        print(f"[ContentGen] Keyword (attempt {attempt+1}): {keyword}")
        products = search_products_for_keyword(keyword, config)
        if products:
            print(f"[ContentGen] Found {len(products)} products")
            break
        print(f"[ContentGen] No products found for: {keyword}, trying another keyword...")

    if not products:
        # Final fallback: use niche-specific fallback keywords
        niche_key = config.get('niche_key', 'printer')
        fallback_map = {
            'printer': ['printer fuser assembly', 'pickup roller printer', 'drum unit printer', 'printer toner cartridge'],
            'drone': ['drone motor replacement', 'DJI propeller', 'drone battery', 'FPV camera', 'drone arm parts'],
        }
        fallbacks = fallback_map.get(niche_key, ['printer repair parts'])
        for fb in fallbacks:
            keyword = fb
            print(f"[ContentGen] Fallback keyword: {keyword}")
            products = search_products_for_keyword(keyword, config)
            if products:
                print(f"[ContentGen] Found {len(products)} products with fallback")
                break
    if not products:
        return {'error': f'No products found after 3 keyword attempts'}
    print(f"[ContentGen] Found {len(products)} products")

    # Generate article
    article = generate_article(keyword, products, config)
    if 'error' in article:
        print(f"[ContentGen] Article generation failed: {article['error']}")
        return article
    print(f"[ContentGen] Article: {article.get('title', '?')}")

    # Generate frontmatter + body
    frontmatter = generate_frontmatter(article)
    body = render_article_body(article)

    full_content = frontmatter + '\n' + body

    # Save as Hugo markdown post
    slug = article['slug']
    post_path = os.path.join(output_dir, f'{slug}.md')
    os.makedirs(os.path.dirname(post_path), exist_ok=True)
    with open(post_path, 'w', encoding='utf-8') as f:
        f.write(full_content)
    print(f"[ContentGen] Saved: {post_path}")

    # Save product images info for image generator
    products_data = []
    for p in products[:3]:
        if p.get('image'):
            products_data.append({
                'id': p['id'],
                'image_url': p['image'],
                'slug': slug,
            })

    return {
        'slug': slug,
        'title': article.get('title', ''),
        'product_count': len(products),
        'post_path': post_path,
        'products_data': products_data,
        'image_prompt': article.get('image_prompt', ''),
        'tags': article.get('tags', []),
        'category': article.get('category', 'general'),
    }


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python content_generator.py <config.yaml> [output_dir]")
        sys.exit(1)

    config_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'site/content/posts'

    result = generate_and_save(config_path, output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
