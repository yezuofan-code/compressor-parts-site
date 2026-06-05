"""Main publisher script - orchestrates the full content generation pipeline.

Reads niches from YAML config files and generates content to the correct
output directory for each site (e.g. printer → site/, drone → site-drone/).
"""
import json
import os
import sys
import yaml


def run_pipeline(config_path: str) -> dict:
    """Run the full content generation pipeline for one niche config."""
    from content_generator import generate_and_save
    from image_generator import generate_cover_image_from_prompt, download_product_image

    # Load config
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    output_dir = config.get('output_dir', 'site/content/posts')
    static_dir = config.get('static_dir', 'site/static')
    niche_name = config.get('niche_name', 'Unknown')

    print("=" * 50)
    print(f"Pipeline starting for: {niche_name}")
    print(f"  Output:  {output_dir}")
    print(f"  Static:  {static_dir}")
    print("=" * 50)

    # Generate article
    result = generate_and_save(config_path, output_dir)
    if 'error' in result:
        print(f"Pipeline failed: {result['error']}")
        return result

    print(f"Article generated: {result['title']}")
    print(f"  Slug: {result['slug']}")
    print(f"  Products: {result['product_count']}")

    # Generate cover image via AI
    image_prompt = result.get('image_prompt', '')
    slug = result.get('slug', '')
    image_path = ''

    if image_prompt and slug:
        save_path = os.path.join(static_dir, 'images', f'{slug}.jpg')
        print(f"  Generating AI cover image...")
        if generate_cover_image_from_prompt(image_prompt, save_path):
            image_path = f'/images/{slug}.jpg'
            post_path = result.get('post_path', '')
            if post_path:
                _update_image_in_frontmatter(post_path, image_path)
            print(f"  Image: {image_path}")
        else:
            print(f"  AI image failed, using product image fallback")

    # Fallback: use first product image
    if not image_path:
        products_data = result.get('products_data', [])
        if products_data and products_data[0].get('image_url') and slug:
            save_path = os.path.join(static_dir, 'images', f'{slug}.jpg')
            if download_product_image(products_data[0]['image_url'], save_path):
                image_path = f'/images/{slug}.jpg'
                post_path = result.get('post_path', '')
                if post_path:
                    _update_image_in_frontmatter(post_path, image_path)
                print(f"  Image (product fallback): {image_path}")

    if not image_path:
        print(f"  No image available")

    result['image_path'] = image_path
    print("Pipeline completed successfully!")
    return result


def _update_image_in_frontmatter(post_path: str, image_path: str):
    """Update the image field in frontmatter after generating the cover."""
    import re
    with open(post_path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(r'^image:.*$', f'image: {image_path}', content, flags=re.MULTILINE)
    with open(post_path, 'w', encoding='utf-8') as f:
        f.write(content)


def run_for_configs(config_paths: list) -> list:
    """Run pipeline for multiple config files."""
    results = []
    for config_path in config_paths:
        print(f"\n{'#'*60}")
        result = run_pipeline(config_path)
        print(f"{'#'*60}\n")
        results.append(result)
    return results


if __name__ == '__main__':
    # Usage:
    #   python publish.py              → run printer only (default)
    #   python publish.py config/printer.yaml
    #   python publish.py config/drone.yaml
    #   python publish.py --all        → run printer + drone

    config_dir = 'config'

    if '--all' in sys.argv:
        # Run all configs
        import glob
        configs = sorted(
            glob.glob(os.path.join(config_dir, '*.yaml')) +
            glob.glob(os.path.join(config_dir, '*.yml'))
        )
        results = run_for_configs(configs)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1].endswith('.yaml'):
        # Single config specified
        result = run_pipeline(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        # Default: just printer
        result = run_pipeline(f'{config_dir}/printer.yaml')
        print(json.dumps(result, ensure_ascii=False, indent=2))
