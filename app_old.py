from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests
socketio = SocketIO(app, cors_allowed_origins="*")



# Global variable to store scraped data
scraped_data = {}

# Function to scrape product data from USG Store
def scrape_product(url):
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    # Initialize an empty product dictionary to avoid UnboundLocalError
    product = {}

    try:
        response = session.get(url)
        response.raise_for_status()  # Raise an error for invalid responses
        soup = BeautifulSoup(response.content, 'html.parser')

        # Scraping product details
        product['Title'] = soup.find('h3').get_text(strip=True)  # Assuming h3 is for product title
        product['Brand'] = 'Jordan'  # Static value for this site
        product['Color'] = soup.find('h4').get_text(strip=True)  # Assuming color is in h4
        product['Gender'] = 'Unisex'
        product['Material'] = 'Leather'
        product['Age group'] = 'Adult'

        # Scraping the first image where index=0
        slide_div = soup.find('div', {'data-slick-index': '0'})
        if slide_div:
            img_tag = slide_div.find('img')
            if img_tag and 'src' in img_tag.attrs:
                img_src = img_tag['src']
                # Add https: if the src starts with //
                if img_src.startswith("//"):
                    img_src = "https:" + img_src
                product['Image'] = img_src
            else:
                product['Image'] = "No image found"
        else:
            product['Image'] = "No image found"

        # Return the complete product dictionary
        print(f"Scraped product: {product}")
        return product

    except Exception as e:
        print(f"Error occurred: {e}")
        return None


        

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        # Store the error message in the product dictionary
        product['Error'] = str(e)

    return product


# Shopify API integration (assuming shopify package is already installed and configured)
def connect_to_shopify(api_key, password, store_url):
    shop_url = f"https://{api_key}:{password}@{store_url}.myshopify.com/admin"
    shopify.ShopifyResource.set_site(shop_url)

def upload_to_shopify(product_data, sku, shipping_info):
    new_product = shopify.Product()
    new_product.title = product_data['Title']
    new_product.body_html = product_data['Product detail']
    new_product.vendor = product_data['Brand']
    new_product.product_type = 'Shoes'
    
    # Add SKU if provided by user
    product_sku = sku if sku != 'N/A' else product_data['SKU']

    # Adding product variants (size, SKU, etc.)
    new_product.variants = [{
        'price': '199.99',  # Example price
        'sku': product_sku,
        'barcode': product_data['GTIN/UPC/barcode'],
        'weight': product_data['Weight'],
        'inventory_quantity': product_data['Quantity'],
        'size': product_data['Size']
    }]
    new_product.save()

    # Set shipping and return policies as metafields
    metafields = [
        shopify.Metafield({
            'namespace': 'shipping',
            'key': 'shipping_weight',
            'value': shipping_info['Shipping weight'],
            'value_type': 'string'
        }),
        shopify.Metafield({
            'namespace': 'shipping',
            'key': 'shipping_policy',
            'value': shipping_info['Shipping policy'],
            'value_type': 'string'
        }),
        shopify.Metafield({
            'namespace': 'returns',
            'key': 'returns_policy',
            'value': shipping_info['Returns and refunds policy'],
            'value_type': 'string'
        })
    ]

    for metafield in metafields:
        new_product.add_metafield(metafield)

    return new_product

# Route to serve frontend
@app.route('/')
def index():
    product = {
        'Image': 'path_to_image',  # Replace with the actual image path or URL
        # Add other product fields here as necessary
        'Title': 'Air Jordan 1 Retro High OG "Midnight Navy"',
        'Category': 'Shoes',
        'Gender': 'Unisex'
    }
    return render_template('frontend.html', product=product)


# Route for scraping and storing data
@app.route('/scrape', methods=['POST'])
def scrape():
    global scraped_data
    data = request.json
    url = data.get('url')
    
    # Emit real-time updates
    socketio.emit('update', {'message': 'Starting scraping...'})
    time.sleep(1)  # Simulate delay

    # Scrape product data
    scraped_data = scrape_product(url)
    if isinstance(scraped_data, dict):  # Ensure it's a dictionary
        socketio.emit('update', {'message': f"Scraped product: {scraped_data.get('Title', 'No title found')}"})
        return jsonify(scraped_data)
    else:
        return "Error: Expected a dictionary", 500
    # socketio.emit('update', {'message': f'Scraped product: {scraped_data["Title"]}'})


    return jsonify({'status': 'success', 'product': scraped_data})

# Route for uploading to Shopify
@app.route('/upload', methods=['POST'])
def upload():
    global scraped_data
    data = request.json
    sku = data.get('sku')

    # Emit real-time updates
    socketio.emit('update', {'message': 'Uploading to Shopify...'})

    # Shopify API credentials
    api_key = 'your_api_key'
    password = 'your_password'
    store_url = 'your_store_url'
    connect_to_shopify(api_key, password, store_url)

    # Define shipping and return policy
    shipping_info = {
        'Shipping weight': '1 kg',
        'Shipping policy': 'Standard shipping in 5-7 business days.',
        'Returns and refunds policy': 'Returns accepted within 30 days.'
    }

    # Upload product to Shopify
    upload_to_shopify(scraped_data, sku, shipping_info)
    socketio.emit('update', {'message': 'Upload completed!'})

    return jsonify({'status': 'success'})

# Run the app
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
