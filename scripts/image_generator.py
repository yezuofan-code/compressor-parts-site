"""Image Generator for Printer Parts Niche

Generates article cover images and downloads product images from AliExpress.
Supports multiple image generation backends with fallback.
"""
import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional

IMAGE_API_KEY = os.environ.get('IMAGE_API_KEY', '')
IMAGE_API_URL = os.environ.get('IMAGE_API_URL', 'https://ai.t8star.org/v1/images/generations')


def download_product_image(image_url: str, save_path: str) -> bool:
    """Download product image from AliExpress to local path.

    Uses requests with browser-like User-Agent to bypass CDN blocks.
    """
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.aliexpress.com/',
        }
        resp = requests.get(image_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
        print(f"  [ImageGen] Download failed: HTTP {resp.status_code}")
        return False
    except Exception as e:
        print(f"  [ImageGen] Download failed: {e}")
        return False


def generate_ai_image(prompt: str, save_path: str) -> bool:
    """Generate image using AI image API.

    Used as secondary method when no product image is available.
    Falls back to a placeholder if all methods fail.
    """
    if not IMAGE_API_KEY:
        return False

    headers = {
        'Authorization': f'Bearer {IMAGE_API_KEY}',
        'Content-Type': 'application/json',
    }

    try:
        import requests

        # Submit generation
        payload = {
            'model': 'gpt-image-2',
            'prompt': prompt,
            'size': '1536x1024',
            'quality': 'medium',
            'n': 1,
            'response_format': 'url',
        }
        submit_url = f'{IMAGE_API_URL}?async=true'
        resp = requests.post(submit_url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Get task_id
        task_id = data.get('task_id') or data.get('id', '')
        if not task_id:
            # Maybe it returned directly
            if 'data' in data and len(data['data']) > 0 and 'url' in data['data'][0]:
                img_url = data['data'][0]['url']
                return _download_image(img_url, save_path)
            return False

        # Poll for result
        poll_url = f'{IMAGE_API_URL.replace("/v1/images/generations", "/v1/images/tasks")}/{task_id}'
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(15)
            poll_resp = requests.get(poll_url, headers=headers, timeout=30)
            if poll_resp.status_code != 200:
                continue
            poll_data = poll_resp.json()

            inner = poll_data.get('data') or {}
            status = inner.get('status', '')

            if status in ('SUCCESS', 'completed', 'succeeded'):
                img_container = inner.get('data') or {}
                images = img_container.get('data', []) if isinstance(img_container, dict) else []
                if not isinstance(images, list):
                    images = []
                for img in images:
                    url = img.get('url', '')
                    if url:
                        return _download_image(url, save_path)
                return False
            elif status in ('FAILED', 'failed', 'error'):
                print(f"  [ImageGen] AI generation failed: {inner.get('fail_reason', 'unknown')}")
                return False

        return False

    except Exception as e:
        print(f"  [ImageGen] Error: {e}")
        return False


def _download_image(url: str, save_path: str) -> bool:
    """Download image from URL to local path using requests (handles CDN blocks)."""
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.aliexpress.com/',
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
        return False
    except Exception as e:
        print(f"  [ImageGen] Download error: {e}")
        return False


def generate_cover_image_from_prompt(prompt: str, save_path: str) -> bool:
    """Generate an AI cover image from a text prompt and save to disk.

    Priority: AI generation, returns True on success.
    This is called by publish.py as the primary image method.
    """
    # Method 1: AI generation
    if prompt and IMAGE_API_KEY:
        print(f"  [ImageGen] Generating AI cover image...")
        if generate_ai_image(prompt, save_path):
            return True
        print(f"  [ImageGen] AI generation failed, trying fallback")

    return False


def generate_cover_image(result: dict, static_dir: str) -> str:
    """Generate or download cover image for the article.

    Priority:
    1. Download the first product's real image from AliExpress
    2. Generate AI image if API key is available
    3. Return empty string (no image)

    Returns:
        Relative path to the image (e.g., /images/slug.jpg), or empty string
    """
    slug = result.get('slug', '')
    products_data = result.get('products_data', [])
    image_prompt = result.get('image_prompt', '')

    if not slug:
        return ''

    save_path = os.path.join(static_dir, 'images', f'{slug}.jpg')

    # Method 1: Download real product image
    if products_data and products_data[0].get('image_url'):
        img_url = products_data[0]['image_url']
        print(f"  [ImageGen] Downloading product image: {img_url[:60]}...")
        if download_product_image(img_url, save_path):
            return f'/images/{slug}.jpg'

    # Method 2: Generate AI image
    if image_prompt and IMAGE_API_KEY:
        print(f"  [ImageGen] Generating AI image...")
        if generate_ai_image(image_prompt, save_path):
            return f'/images/{slug}.jpg'

    # Method 3: Try other product images
    for pd in products_data[1:]:
        if pd.get('image_url'):
            print(f"  [ImageGen] Downloading alt product image...")
            if download_product_image(pd['image_url'], save_path):
                return f'/images/{slug}.jpg'

    print(f"  [ImageGen] No image available for: {slug}")
    return ''


def download_all_product_images(result: dict, static_dir: str) -> list:
    """Download all product images for gallery use.

    Returns:
        List of downloaded image paths.
    """
    slug = result.get('slug', '')
    products_data = result.get('products_data', [])
    downloaded = []

    for pd in products_data:
        if pd.get('image_url'):
            # Save with product ID as name
            pid = pd['id']
            save_path = os.path.join(static_dir, 'images', f'{slug}-{pid}.jpg')
            if download_product_image(pd['image_url'], save_path):
                downloaded.append(f'/images/{slug}-{pid}.jpg')

    return downloaded


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        slug = sys.argv[1]
        print(f"Testing download for: {slug}")
    else:
        print("Usage: python image_generator.py <slug>")
