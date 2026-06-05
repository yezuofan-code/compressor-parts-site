"""AliExpress Affiliate API - IOP Protocol (api-sg.aliexpress.com)

Reused from existing tools-site project.
Uses the International Open Platform (IOP) gateway with HMAC-SHA256 signing.
"""
import hashlib
import hmac as hmac_mod
import json
import urllib.parse
import urllib.request
import urllib.error
import time as time_mod
import os

# Read from environment variables with fallback for local development
APP_KEY = os.environ.get('ALIEXPRESS_APP_KEY', '535462')
APP_SECRET = os.environ.get('ALIEXPRESS_APP_SECRET', 'E8IyGKElDYQg6SQ6WtWJwwJDrb5tbXsL')
TRACKING_ID = os.environ.get('ALIEXPRESS_TRACKING_ID', 'huanhaiwan')

# IOP Gateway
GATEWAY = 'https://api-sg.aliexpress.com/sync'


def sign(params: dict, secret: str) -> str:
    """IOP signature: sorted key-value pairs, HMAC-SHA256, UPPERCASE hex."""
    keys = sorted(params.keys())
    raw = ''.join(f'{k}{params[k]}' for k in keys)
    h = hmac_mod.new(secret.encode('utf-8'), raw.encode('utf-8'), hashlib.sha256)
    return h.hexdigest().upper()


def call_api(method: str, biz_params: dict = None, access_token: str = None) -> dict:
    """Call AliExpress IOP API with HMAC-SHA256 signing."""
    params = {
        'method': method,
        'app_key': APP_KEY,
        'sign_method': 'sha256',
        'timestamp': str(int(time_mod.time() * 1000)),
        'v': '2.0',
    }
    if access_token:
        params['access_token'] = access_token
    if biz_params:
        for k in sorted(biz_params.keys()):
            params[k] = biz_params[k]
    params['sign'] = sign(params, APP_SECRET)

    query = urllib.parse.urlencode(params)
    url = f'{GATEWAY}?{query}'
    try:
        req = urllib.request.Request(url, method='GET')
        resp = urllib.request.urlopen(req, timeout=20)
        return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')[:500]
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {'error': f'HTTP {e.code}', 'body': body}
    except urllib.error.URLError as e:
        return {'error': f'URL Error: {e.reason}'}
    except Exception as e:
        return {'error': str(e)}


def call_api_post(method: str, biz_params: dict = None, access_token: str = None) -> dict:
    """POST version for APIs that require it."""
    params = {
        'method': method,
        'app_key': APP_KEY,
        'sign_method': 'sha256',
        'timestamp': str(int(time_mod.time() * 1000)),
        'v': '2.0',
    }
    if access_token:
        params['access_token'] = access_token
    if biz_params:
        for k in sorted(biz_params.keys()):
            params[k] = biz_params[k]
    params['sign'] = sign(params, APP_SECRET)

    data = urllib.parse.urlencode(params).encode('utf-8')
    try:
        req = urllib.request.Request(GATEWAY, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded;charset=utf-8')
        resp = urllib.request.urlopen(req, timeout=20)
        return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')[:500]
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {'error': f'HTTP {e.code}', 'body': body}
    except urllib.error.URLError as e:
        return {'error': f'URL Error: {e.reason}'}
    except Exception as e:
        return {'error': str(e)}


def search_products(keywords: str = '', category_ids: str = '',
                    min_price: float = None, max_price: float = None,
                    page: int = 1, page_size: int = 20,
                    sort: str = 'LAST_VOLUME_DESC') -> dict:
    """Search AliExpress products via affiliate API."""
    biz = {
        'page_no': str(page),
        'page_size': str(page_size),
        'sort': sort,
        'tracking_id': TRACKING_ID,
    }
    if keywords:
        biz['keywords'] = keywords
    if category_ids:
        biz['category_ids'] = category_ids
    if min_price is not None:
        biz['min_sale_price'] = str(min_price)
    if max_price is not None:
        biz['max_sale_price'] = str(max_price)

    return call_api('aliexpress.affiliate.product.query', biz)


def generate_link(product_ids: list, tracking_id: str = None) -> dict:
    """Generate affiliate links for given product IDs."""
    source_vals = ','.join(f'https://www.aliexpress.com/item/{pid}.html'
                          for pid in product_ids)
    biz = {
        'product_ids': ','.join(str(pid) for pid in product_ids),
        'tracking_id': tracking_id or TRACKING_ID,
        'promotion_link_type': '0',
        'source_values': source_vals,
    }
    return call_api_post('aliexpress.affiliate.link.generate', biz)


def get_product_detail(product_ids: list, tracking_id: str = None,
                       fields: str = '', target_currency: str = 'USD',
                       target_language: str = 'EN') -> dict:
    """Get detailed product info by product ID(s)."""
    biz = {
        'product_ids': ','.join(str(pid) for pid in product_ids),
        'tracking_id': tracking_id or TRACKING_ID,
        'target_currency': target_currency,
        'target_language': target_language,
    }
    if fields:
        biz['fields'] = fields
    return call_api('aliexpress.affiliate.productdetail.get', biz)


def extract_products(resp: dict):
    """Extract product list from IOP API response."""
    try:
        for key in ('aliexpress_affiliate_product_query_response',
                    'aliexpress_affiliate_productdetail_get_response'):
            if key in resp:
                resp = resp[key]
                break

        result = resp.get('resp_result', {})
        result = result.get('result', {})

        products = result.get('products', {}).get('product', [])
        if isinstance(products, dict):
            products = [products]

        total = result.get('total_record_count', '0')
        if isinstance(total, str):
            total = int(total) if total.isdigit() else 0
        elif isinstance(total, (int, float)):
            total = int(total)

        for p in products:
            normalize_product(p)

        return products, total
    except Exception:
        return [], 0


def normalize_product(p: dict):
    """Normalize product fields to consistent format."""
    p['sale_price'] = p.get('target_app_sale_price') or p.get('target_sale_price') or ''
    orig = p.get('target_original_price', '')
    p['original_price'] = {'amount': orig} if orig else {}
    p['product_image_urls'] = p.get('product_main_image_url', '')

    small_imgs = p.get('product_small_image_urls', {})
    if isinstance(small_imgs, dict):
        p['gallery_images'] = small_imgs.get('string', [])
    else:
        p['gallery_images'] = []

    if 'evaluate_rate' in p:
        rate_str = p['evaluate_rate'].rstrip('%')
        try:
            p['star_rating'] = str(round(float(rate_str) / 20, 1))
        except (ValueError, TypeError):
            p['star_rating'] = '?'

    p['sales_count'] = p.get('lastest_volume', 0)
    # Use promotion_link if available
    p['affiliate_link'] = p.get('promotion_link', '') or p.get('product_detail_url', '')


if __name__ == '__main__':
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else 'printer fuser assembly'
    print(f"Searching: {kw}")
    result = search_products(keywords=kw, page_size=3)
    products, total = extract_products(result)
    print(f"Found {total} products, showing {len(products)}")
    for p in products[:3]:
        print(f"  - {p.get('product_title', '?')[:60]} | ${p.get('sale_price', '?')} | {p.get('star_rating', '?')}/5")
