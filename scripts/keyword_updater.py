"""Keyword Auto-Updater

Periodically refreshes keyword pools with trending repair/search terms.
Uses LLM to analyze current repair trends and update config.

Why: Drone/printer repair keywords change as new models launch and
new problems emerge. This script keeps the pool fresh.

Schedule: run weekly to keep keywords current.
"""
import json
import os
import sys
import yaml
import re
from datetime import datetime


LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_API_URL = os.environ.get('LLM_API_URL', 'https://api.deepseek.com/chat/completions')
LLM_MODEL = os.environ.get('LLM_MODEL', 'deepseek-chat')


def get_trending_keywords(niche: str, current_keywords: list, count: int = 60) -> list:
    """Use LLM to generate trending repair keywords for the niche.

    The LLM acts like a repair community expert who knows what problems
    people are searching for right now.

    Args:
        niche: "drone repair" or "printer repair"
        current_keywords: existing keywords for context
        count: number of new keywords to generate

    Returns:
        List of keyword strings
    """
    if not LLM_API_KEY:
        print("[KeywordUpdater] No LLM_API_KEY set, skipping update")
        return current_keywords

    # Sample current keywords to give the LLM context
    sample = current_keywords[:20] if current_keywords else []

    # Build niche-specific context
    niche_contexts = {
        "drone": {
            "name": "无人机维修",
            "new_models": ["DJI Mini 5 Pro", "DJI Flip", "DJI Neo", "DJI Air 4", "Avata 2"],
            "common_problems": [
                "crash damage", "gimbal failure", "motor burn-out", "battery swelling",
                "antenna breakage", "ESC failure", "flight controller crash",
                "arm fracture", "propeller damage", "camera feed loss"
            ],
            "sources": [
                "r/dji", "r/fpv", "r/drones", "DJI forums", "YouTube repair channels",
                "drone repair shops"
            ]
        },
        "printer": {
            "name": "打印机维修",
            "new_models": ["HP LaserJet M系列", "Brother HL-L系列新机", "EPSON EcoTank新型号"],
            "common_problems": [
                "paper jam sensor", "fuser error", "drum replacement needed",
                "toner cartridge not recognized", "print quality streaks",
                "printer offline issue", "pickup roller worn", "ghosting image"
            ],
            "sources": [
                "printer repair forums", "HP support community", "Brother troubleshooting",
                "printer technician blogs"
            ]
        }
    }

    context = niche_contexts.get(niche, {})

    prompt = f"""You are a repair technician who works at a busy {niche} repair shop.
You overhear what customers search for every day.

Generate {count} search keywords that people are ACTUALLY searching for RIGHT NOW
when their {niche} breaks.

Requirements:
- Each keyword must be a REAL problem someone would search (e.g. "DJI Mini 3 gimbal not working fix")
- Include specific model names and specific problems
- Cover both common and emerging problems
- Include newer models that are currently popular
- Think like someone whose device just broke - what would they type into Google?

Current year is 2026. Include recent/popular models.

Current keywords for reference (don't just copy these, add fresh ones):
{sample}

{'New/popular models to include: ' + ', '.join(context.get('new_models', [])) if niche in niche_contexts else ''}
{'Common problem types: ' + ', '.join(context.get('common_problems', [])) if niche in niche_contexts else ''}

Return ONLY a JSON array of strings, one keyword per entry. No markdown.
["keyword 1", "keyword 2", ...]"""

    headers = {
        'Authorization': f'Bearer {LLM_API_KEY}',
        'Content-Type': 'application/json',
    }

    try:
        import requests
        resp = requests.post(LLM_API_URL, headers=headers, json={
            'model': LLM_MODEL,
            'messages': [
                {'role': 'system', 'content': 'You are a repair shop expert who knows what people search for. Output only valid JSON arrays.'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.8,
            'max_tokens': 4000,
        }, timeout=60)
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()

        # Clean any markdown formatting
        if content.startswith('```'):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

        new_keywords = json.loads(content)

        if not isinstance(new_keywords, list) or len(new_keywords) < 10:
            print(f"[KeywordUpdater] LLM returned invalid data, keeping existing")
            return current_keywords

        # Remove duplicates and merge with existing
        seen = set(k.lower().strip() for k in current_keywords)
        merged = list(current_keywords)  # Keep existing

        for kw in new_keywords:
            if isinstance(kw, str) and kw.lower().strip() not in seen:
                merged.append(kw.strip())
                seen.add(kw.lower().strip())

        # Keep only the freshest keywords (newest models at the top)
        # Sort: put newer-model keywords first, then fill with existing
        print(f"[KeywordUpdater] Generated {len(new_keywords)} fresh keywords")
        print(f"[KeywordUpdater] Merged pool: {len(merged)} total")
        return merged

    except Exception as e:
        print(f"[KeywordUpdater] Error: {e}")
        return current_keywords


def update_config_file(config_path: str, new_keywords: list):
    """Update the keywords in a YAML config file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    old_count = len(config.get('keywords', []))
    config['keywords'] = new_keywords
    config['last_updated'] = datetime.now().strftime('%Y-%m-%d')

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[KeywordUpdater] Updated {config_path}: {old_count} → {len(new_keywords)} keywords")


def run_update(niche: str, config_path: str):
    """Run keyword update for one niche."""
    print(f"\n{'='*50}")
    print(f"[KeywordUpdater] Updating keywords for: {niche}")
    print(f"{'='*50}")

    # Load current keywords
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    current_keywords = config.get('keywords', [])
    print(f"[KeywordUpdater] Current: {len(current_keywords)} keywords")

    # Get fresh keywords from LLM
    new_keywords = get_trending_keywords(niche, current_keywords, count=60)

    # Update config
    update_config_file(config_path, new_keywords)

    return len(new_keywords)


if __name__ == '__main__':
    # Usage: python keyword_updater.py drone
    #        python keyword_updater.py printer
    #        python keyword_updater.py all
    if len(sys.argv) < 2:
        print("Usage: python keyword_updater.py <niche|all>")
        print("  niche: drone, printer")
        print("  all: update both")
        sys.exit(1)

    target = sys.argv[1]

    configs = []
    if target in ('drone', 'all'):
        configs.append(('drone', 'config/drone.yaml'))
    if target in ('printer', 'all'):
        configs.append(('printer', 'config/printer.yaml'))

    for niche, config_path in configs:
        run_update(niche, config_path)
