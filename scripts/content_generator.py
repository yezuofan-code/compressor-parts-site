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


def _truncate_title(text: str, max_len: int = 40) -> str:
    """Shorten product title for clean display in articles.

    Strips out keyword-stuffing patterns common on AliExpress,
    keeps the core product name short and readable.
    """
    patterns = [
        '-aliexpress', 'Free Shipping', 'Free shipping', 'Wholesale', 'wholesale',
        'In Stock', 'in stock', 'DropShipping', 'dropshipping', 'Direct sale',
        'hot sale', 'Hot Sale', 'New Arrival', 'new arrival', 'High Quality',
        'high quality', 'Original', 'original', 'Accessories', 'accessories',
        'for DJI', 'For DJI', 'For ', 'for ', 'Parts', 'parts',
        'Repair', 'repair', 'Replacement', 'replacement',
    ]
    for p in patterns:
        text = text.replace(p, '').strip()
    # Remove extra whitespace
    text = ' '.join(text.split())
    if len(text) > max_len:
        text = text[:max_len-3] + '...'
    return text.strip()


def search_products_for_keyword(keyword: str, config: dict, max_results: int = 6) -> list:
    """Search AliExpress for products matching the keyword."""
    from aliexpress_api import search_products, extract_products

    min_price = config.get('min_price', 1)
    max_price = config.get('max_price', 200)
    category_ids = config.get('category_ids', '')

    # Try multiple search strategies - but limit results to MAX 3 products
    max_results = min(max_results, 3)
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
    """Generate a problem-solving repair guide using LLM.

    The focus is on being genuinely helpful: teaching the reader how to
    diagnose and fix their printer problem. Products are mentioned only
    briefly as part of the solution, NOT the focus of the article.

    Each section must be DEEP and SPECIFIC — like a real repair manual,
    not a blog skim.
    """
    niche_name = config.get('niche_name', 'Printer Parts')
    site_name = config.get('site_title', 'Printer Parts Review')

    product_notes = []
    for i, p in enumerate(products[:3]):
        product_notes.append(
            f'Part #{i+1}: {p["short_name"]} — ${p["price"]}'
        )
    product_notes_str = '\n'.join(product_notes)
    product_ids = [p['id'] for p in products]

    # Determine article type
    article_type = _get_article_type(keyword)

    # Build type-specific prompt - all focused on HELPING, not selling
    type_instructions = {
        "problem_solution": (
            "This is a DIAGNOSIS & REPAIR GUIDE. Structure it like a repair manual:\n"
            "1. SYMPTOMS — What the user experiences (error code, weird noise, paper jam, streaks)\n"
            "2. DIAGNOSIS — How to confirm the root cause (step-by-step checks)\n"
            "3. ROOT CAUSE — Explain why this happens (worn gear, broken roller, etc.)\n"
            "4. REPAIR OPTIONS — DIY vs professional, cost comparison\n"
            "5. REPAIR STEPS — Brief overview of what's involved\n"
            "6. PARTS NEEDED — Briefly list the parts (this is where products appear)"
        ),
        "replacement_guide": (
            "This is a REPLACEMENT TUTORIAL. Structure it like a workshop guide:\n"
            "1. WHEN TO REPLACE — Signs that replacement is needed\n"
            "2. TOOLS NEEDED — What you'll need\n"
            "3. REPLACEMENT STEPS — Step by step process\n"
            "4. PARTS OPTIONS — What to buy (briefly, this is where products appear)\n"
            "5. TIPS — Common mistakes and how to avoid them"
        ),
        "compatibility": (
            "This is a COMPATIBILITY REFERENCE GUIDE:\n"
            "1. WHAT FITS WHAT — Cross-reference table of models and compatible parts\n"
            "2. OEM vs COMPATIBLE — Real differences explained\n"
            "3. HOW TO VERIFY — Check before you buy\n"
            "4. PARTS LIST — Parts that work (brief product mentions)"
        ),
        "comparison": (
            "This is a SIDE-BY-SIDE COMPARISON FOR INFORMED BUYING:\n"
            "1. WHAT TO LOOK FOR — Key specs that matter\n"
            "2. COMPARISON TABLE — Side by side specs\n"
            "3. REAL DIFFERENCES — Price vs quality vs lifespan\n"
            "4. RECOMMENDATION — Brief, honest pick"
        ),
        "buying_guide": (
            "This is an EDUCATIONAL BUYING GUIDE:\n"
            "1. UNDERSTAND THE PART — What it does, how it works\n"
            "2. KEY SPECS — What to pay attention to\n"
            "3. BRAND OPTIONS — Different choices explained\n"
            "4. PRICE RANGE — What you should expect to pay"
        ),
    }

    # Default to problem_solution if not specified
    instructions = type_instructions.get(article_type, type_instructions["problem_solution"])

    prompt = f"""You write in-depth repair guides for {site_name}. Write a comprehensive, detailed article about: {keyword}

Your reader's device JUST BROKE. They are frustrated and searching for answers.
They want to understand EXACTLY what's wrong and how to fix it.

⚠️ CRITICAL FORMATTING REQUIREMENT:
Every section below MUST be written in PROPER MARKDOWN FORMAT.
Use numbered lists for steps, bullet points for items, and blank lines between paragraphs.
Do NOT write walls of text. Readers need scannable, formatted content.

REQUIRED STRUCTURE — each section must be 4-8 detailed paragraphs:

1. THE PROBLEM IN DETAIL
   - Describe EXACTLY what the user experiences (specific sounds, error codes on screen, visual symptoms, behavior changes)
   - Include multiple scenarios: "Some users report X, while others experience Y"
   - When does it happen? (on startup, during use, after a crash, after firmware update)
   - How does it progress? (gets worse over time? sudden failure?)

2. STEP-BY-STEP DIAGNOSIS
   - Numbered steps the reader can follow RIGHT NOW with basic tools
   - Include what NORMAL looks like vs ABNORMAL
   - Include a "quick check" for beginners AND a "detailed check" for advanced users
   - Mention tools needed for each step (exact sizes, settings)

3. ROOT CAUSE — Why This Happens
   - Explain the engineering/mechanics behind the failure
   - Give specific part names and numbers
   - Explain what conditions accelerate this failure (heat, dust, crash force, age, wear)
   - Reference specific models and known issues

4. CAN YOU FIX IT? — Honest Assessment
   - Difficulty level (1-5) and why
   - Time required (in minutes)
   - Skill level needed (soldering? just screwdriver?)
   - Risks and what could go wrong
   - Tools required with specifics

5. DIY vs PROFESSIONAL — Real Cost Comparison
   - DIY: specific part costs from the available parts
   - Professional: typical repair shop rates
   - When to skip DIY

6. REPAIR PROCESS OVERVIEW
   - Major steps the repair involves
   - Common mistakes and how to avoid them

7. AFTER REPAIR — Verification
   - How to know the repair worked
   - What to watch for in the first few hours

Available parts for reference (mention only in section 5):
{product_notes_str}

CRITICAL RULES:
- This is a REPAIR GUIDE, not a product review. 90% of content is the problem and fix.
- Products appear ONLY in section 5 as a brief cost mention.
- Every paragraph must contain NEW useful information, not fluff.
- Include specific model names, error codes, part numbers, and measurements.
- NEVER write "you should check if it's broken" — instead write WHAT to look for.
- NEVER write "it might be this or that" — give a METHOD to determine which.

Write the article in JSON format. IMPORTANT: ALL text fields MUST use Markdown formatting:
{{
  "title": "Problem-focused title, e.g. 'DJI Mini 4 Pro Arm Broken After Crash? Full Diagnosis & Repair Guide'",
  "summary": "One paragraph summary of what problem this solves",
  "problem_detail": "FULL MARKDOWN TEXT. Use numbered lists, bullet points, **bold** for emphasis. Blank lines between paragraphs.",
  "diagnosis": "FULL MARKDOWN TEXT. MUST start with numbered steps like:\n\n1. First check this...\n2. Then check that...\n3. Normal vs abnormal comparison...",
  "root_cause": "FULL MARKDOWN TEXT. Use paragraphs and bullet points for different causes.",
  "fix_assessment": "FULL MARKDOWN TEXT. Use bullet points for difficulty/skill/time/risks.",
  "cost_analysis": "FULL MARKDOWN TEXT. Use bullet points for cost breakdown.",
  "repair_process": "FULL MARKDOWN TEXT. Numbered steps for the repair process.",
  "after_repair": "FULL MARKDOWN TEXT. Bullet points for verification steps.",
  "body_sections": [],
  "image_prompt": "Detailed prompt for cover image",
  "meta_description": "SEO description under 160 chars, start with the problem",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "one of: fuser-assembly pickup-roller drum-unit transfer-belt printhead maintenance-kit toner"
}}

FORMATTING REQUIREMENTS:
✅ Each diagnosis step MUST be on its own line starting with a number: 1. , 2. , 3.
✅ Use blank lines between every step or paragraph
✅ Use **bold** for key terms (part names, error codes, tool names)
✅ Use bullet points for lists of tools, causes, options
✅ Never write more than 4 sentences without a line break
❌ No wall-of-text paragraphs

Example of correct formatting for the diagnosis field:

\"\"\"
1. **Visual Inspection**: Remove the battery and look at the arm closely. Normal: the arm is straight and the hinge is tight. Abnormal: you see a hairline crack or the arm wiggles.

2. **Flex Test**: Gently try to bend the arm upward. Normal: it resists and springs back. Abnormal: it bends easily or makes a cracking sound.

3. **Motor Alignment Check**: Spin the motor by hand. Normal: smooth rotation. Abnormal: the motor rubs against the arm because the mount is bent.
\"\"\"

DEPTH CHECKLIST — your article fails if:
☐ Symptoms section doesn't mention specific error codes or sounds
☐ Diagnosis doesn't have numbered steps the reader can actually do
☐ Root cause doesn't explain WHY (not just "it's worn out")
☐ Cost comparison doesn't have real dollar amounts
☐ The reader could have written this after 2 minutes of Googling
☐ Any sentence is vague enough to apply to a different problem
☐ Text is not properly formatted with line breaks and bullet points"""

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
        'max_tokens': 8000,
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

    Uses product data from parts_needed instead of products array,
    since the article is now fix-focused not product-focused.
    """
    title = article.get('title', 'Printer Parts Review')
    slug = article.get('slug', _slugify(title))
    date = article.get('date', datetime.now().strftime('%Y-%m-%d'))
    tags = article.get('tags', ['printer-parts'])
    category = article.get('category', 'general')
    meta_desc = article.get('meta_description', '')

    # Use first product for metadata
    products = article.get('products', [])

    # Find first product with details
    first_product = products[0] if products else {}

    # Get affiliate link
    aliexpress_link = ''
    for p in products:
        if p.get('affiliate_link'):
            aliexpress_link = p['affiliate_link']
            break

    tags_yaml = '\n  - ' + '\n  - '.join(tags)
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
    """Render article body in markdown - repair guide format.

    The structure follows: problem → diagnose → cause → fix → parts.
    Products are shown only at the end in a compact parts list.
    """
    lines = []
    summary = article.get('summary', '')
    if summary:
        lines.append(f'> {summary}')
        lines.append('')

    # === 1. PROBLEM DETAIL ===
    problem = article.get('problem_detail', '')
    if problem:
        lines.append('## What\'s Happening — Symptoms in Detail')
        lines.append('')
        lines.append(problem)
        lines.append('')

    # === 2. DIAGNOSIS ===
    diagnosis = article.get('diagnosis', '')
    if diagnosis:
        lines.append('## How to Diagnose the Problem Step by Step')
        lines.append('')
        lines.append(diagnosis)
        lines.append('')

    # === 3. ROOT CAUSE ===
    root_cause = article.get('root_cause', '')
    if root_cause:
        lines.append('## Why This Happens — Root Cause')
        lines.append('')
        lines.append(root_cause)
        lines.append('')

    # === 4. FIX ASSESSMENT ===
    fix = article.get('fix_assessment', '')
    if fix:
        lines.append('## Can You Fix It Yourself?')
        lines.append('')
        lines.append(fix)
        lines.append('')

    # === 5. COST ANALYSIS ===
    cost = article.get('cost_analysis', '')
    if cost:
        lines.append('## Cost Breakdown — DIY vs Professional')
        lines.append('')
        lines.append(cost)
        lines.append('')

    # === 6. REPAIR PROCESS ===
    repair = article.get('repair_process', '')
    if repair:
        lines.append('## Repair Process Overview')
        lines.append('')
        lines.append(repair)
        lines.append('')

    # === 7. AFTER REPAIR ===
    after = article.get('after_repair', '')
    if after:
        lines.append('## After the Repair — Testing & Verification')
        lines.append('')
        lines.append(after)
        lines.append('')

    # === PARTS YOU'LL NEED — clean table at the very end ===
    products = article.get('products', [])
    if products:
        lines.append('---')
        lines.append('')
        lines.append('## Parts You\'ll Need')
        lines.append('')
        lines.append('Here are the parts that match this repair. Click the link to check the current price on AliExpress.')
        lines.append('')
        lines.append('| Product | Price |')
        lines.append('|---------|-------|')

        for p in products:
            name = p.get('short_name', 'Replacement part')
            price = f"${p.get('price', '?')}" if p.get('price') else 'Check price'
            link = p.get('affiliate_link', '')
            if link:
                name = f'[{name}]({link})'
            lines.append(f'| {name} | {price} |')

        lines.append('')
        lines.append('> Prices and availability are subject to change on AliExpress.')
        lines.append('')

        lines.append('')

    # === FINAL VERDICT ===
    verdict = article.get('final_verdict', '')
    if verdict:
        lines.append('---')
        lines.append('')
        lines.append(f'_{verdict}_')
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
            'motor': ['stepper motor driver', 'gearbox motor reduction', 'servo motor encoder', 'AC motor capacitor'],
            'sensor': ['proximity sensor switch', 'photoelectric sensor', 'temperature controller', 'encoder cable'],
            'compressor': ['air compressor parts', 'pneumatic solenoid valve', 'compressor pressure switch', 'air cylinder'],
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
