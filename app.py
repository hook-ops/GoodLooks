from bson import ObjectId
from flask import Flask, request, redirect, url_for, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
import pymongo
from pymongo.errors import ConnectionFailure
from requests.packages.urllib3.util.retry import Retry # type: ignore
from upload_shopify import upload_product_to_shopify
from bs4 import BeautifulSoup
import time
import re
import os
import shopify

import json

app = Flask(__name__)

# MongoDB Configuration
try:
    client = pymongo.MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    # The serverSelectionTimeoutMS option limits the amount of time the connection attempt will wait for a response
    db = client['admin']  # Database name
    collectionA = db['adidas']  # Collection name
    collectionB = db['nike']
    collectionC = db['jordan']
    # Check if the server is available
    client.admin.command('ping')
    print("MongoDB connection successful!")
    
except ConnectionFailure as e:
    print(f"MongoDB connection failed: {e}")
CORS(app)  # Allow cross-origin requests
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
time.sleep(4)


# When user click scraped product's image, user can change product image
UPLOAD_FOLDER = 'static/uploads/'  # Folder where uploaded images are saved
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('message', {'message': 'Welcome to the chat!'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('message')
def handle_message(data):
    print(f'Message received: {data}')
    emit('message', {'message': data}, broadcast=True)

# Configure retries and timeout
def requests_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
}

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/upload-image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"success": False, "message": "No file part"})

    file = request.files['image']
    if file.filename == '':
        return jsonify({"success": False, "message": "No selected file"})

    if file:
        filename = file.filename
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        image_url = f"/{UPLOAD_FOLDER}/{filename}"  # Assuming you serve static files from this folder
        return jsonify({"success": True, "imageUrl": image_url})

    return jsonify({"success": False, "message": "Upload failed"})

# Function to scrape product data from USG Store
def scrape_product(url, brand):
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    # Initialize an empty product dictionary to avoid UnboundLocalError
    product = {}
    variants = []  # To store variants/sub-products

    try:
        response = session.get(url)
        response.raise_for_status()  # Raise an error for invalid responses
        soup = BeautifulSoup(response.content, 'html.parser')

        # Scraping product details
        product['Title'] = soup.find('h3').get_text(strip=True)  # Assuming h3 is for product title
        product['Brand'] = brand  
        product['Color'] = soup.find('h4').get_text(strip=True)  # Assuming color is in h4
        
        product['Material'] = 'Leather'
        product['Age group'] = 'Adult'
        
        price_meta_tag = soup.find('meta', property='og:price:amount')
        if price_meta_tag:
            product['price'] = price_meta_tag.get('content')
            print(f"Price: {product['price']}")
        else:
            product['price'] = 'Price not found'
            print('Price meta tag not found')
        # Check if there is embedded JavaScript containing product data
        script_tag = soup.find('script', text=re.compile('new Shopify\\.OptionSelectors'))
        
        if script_tag:
            # Extract the text of the script tag
            script_content = script_tag.string

            # Use regex to find specific product fields like 'SKU', 'Size', etc.
            size_match = re.search(r'"Size":"(.*?)"', script_content)
            sku_match = re.search(r'"sku":"(.*?)"', script_content)
            barcode_match = re.search(r'"barcode":"(.*?)"', script_content)
            weight_match = re.search(r'"weight":(\d+)', script_content)
            quantity_match = re.search(r'"inventory_quantity":(\d+)', script_content)
            id_match = re.search(r'"id":(\d+)', script_content)
            gender_match = re.search(r'"type":"(.*?)"', script_content)

            # Extract and store the found values
            product['Size'] = size_match.group(1) if size_match else 'Size not found'
            product['SKU'] = sku_match.group(1) if sku_match else 'SKU not found'
            product['Barcode'] = barcode_match.group(1) if barcode_match else 'Barcode not found'
            product['Weight'] = weight_match.group(1) if weight_match else 'Weight not found'
            product['Quantity'] = quantity_match.group(1) if quantity_match else 'Quantity not found'
            product['id'] = id_match.group(1) if id_match else 'ID not found'
            product['Gender'] = gender_match.group(1) if gender_match else 'gender not found'

            # Add variants logic
            product_data_match = re.search(r'product:\s*(\{.*\})', script_content)
            if product_data_match:
                product_data_json = product_data_match.group(1)
                product_data = json.loads(product_data_json)

                # Add the original product details
                product['id'] = product_data.get('id', 'ID not found')
                
                # Loop through each variant to extract its specific details
                for variant in product_data['variants']:
                    variant_data = {

                        'Size': variant.get('option2', 'Size not found'),
                        'ID': variant.get('id', 'ID not found'),
                        'SKU': variant.get('sku', 'SKU not found'),
                        'Barcode': variant.get('barcode', 'Barcode not found'),
                        'Quantity': variant.get('inventory_quantity', 'Quantity not found'),
                        'Weight': variant.get('weight', 'Weight not found')
                        
                    }
                    variants.append(variant_data)

        else:
            print('No JavaScript object found containing product details')

        # Add variants to the main product dictionary
        product['Variants'] = variants

        details_div = soup.find('div', class_='product-details-tabs-description-flex-col')

        if details_div:
            # Find the <ul> tag within the div
            ul_tag = details_div.find('ul')
            
            if ul_tag:
                # Extract text from all <li> tags inside the <ul>
                list_items = [li.get_text(strip=True) for li in ul_tag.find_all('li')]
                
                # Combine list items with proper formatting
                product_details = "\n".join(list_items)

                # Replace 'USG' with 'GOOD LOOKS'
                product_details = product_details.replace('USG', 'GOOD LOOKS')

                # Store and print the product details
                product['product_detail'] = product_details
                print(f"Product details:\n{product['product_detail']}")
            else:
                product = {'product_detail': 'No list found'}
                print('No list found in product details')
        else:
            product = {'product_detail': 'Details not found'}
            print('No product details found')

        # Find the main div containing the thumbnail images
        # Find the main div containing the thumbnail images1
        thumbnail_slider = soup.find('div', class_='product-image-slider')

        if thumbnail_slider:
            # Get the div with class 'slick-track' that contains the images

            # Initialize a list to store all image URLs
            images = []

            # Loop through all the img tags within the slick-track div
            for img_tag in thumbnail_slider.find_all('img'):
                if img_tag and 'src' in img_tag.attrs:
                    img_src = img_tag['src']

                    # If the src starts with '//', add the https: prefix
                    if img_src.startswith('//'):
                        img_src = 'https:' + img_src

                    # Append the image URL to the images list
                    images.append(img_src)

            # Store all the image URLs in the product dictionary
            product['Images'] = images

            print(f"All image URLs: {images}")
        else:
            print('No thumbnail slider found')

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

@app.route('/upload_product/<string:product_id>', methods=['POST'])
def upload_product(product_id):
    # Fetch the product by its ID from MongoDB collections
    product = collectionA.find_one({"_id": ObjectId(product_id)})
    if not product:
        product = collectionB.find_one({"_id": ObjectId(product_id)})
    if not product:
        product = collectionC.find_one({"_id": ObjectId(product_id)})

    if not product:
        return jsonify({"error": "Product not found"}), 404

    shop = shopify.Shop.current()
    print(shop)


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

@app.route('/products', methods=['GET'])
def get_products():
    # Get the brand parameter from the query string
    brand = request.args.get('brand')

    # Fetch data based on the brand
    if brand == 'Adidas':
        products = list(collectionA.find())
    elif brand == 'Nike':
        products = list(collectionB.find())
    elif brand == 'Jordan':
        products = list(collectionC.find())
    else:
        # If brand is not recognized, return an empty list or handle it as needed
        products = []

    # Convert ObjectId to string (MongoDB uses ObjectId for _id)
    for product in products:
        product['_id'] = str(product['_id'])

    return jsonify(products)


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
@app.route('/product/<string:product_id>', methods=['GET', 'POST'])
def get_product_detail(product_id):
    # Fetch the product by its ID from MongoDB collections
    product = collectionA.find_one({"_id": ObjectId(product_id)})
    if not product:
        product = collectionB.find_one({"_id": ObjectId(product_id)})
    if not product:
        product = collectionC.find_one({"_id": ObjectId(product_id)})

    if request.method == 'POST':
        # Handle price update
        new_price = request.form.get('price')
        if new_price:
            collectionA.update_one({'_id': ObjectId(product_id)}, {'$set': {'price': new_price}})
            product['price'] = new_price

        # Handle image upload
        image_index = int(request.args.get('image_index', 0))
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)

                # Update the specific image at the given index
                product['Images'][image_index] = f'/uploads/{filename}'  # Update image URL
                collectionA.update_one({'_id': ObjectId(product_id)}, {'$set': {'Images': product['Images']}})

        return redirect(url_for('get_product_detail', product_id=product_id))

    if product:
        product['_id'] = str(product['_id'])  # Convert ObjectId to string for frontend rendering
        return render_template('product_detail.html', product=product)
    else:
        return "Product not found", 404
    
# Route for scraping and storing data
@socketio.on('scrape')
def scrape(data):
    global scraped_data
    print("Received scraping request: ", data)  # Add print statement for debugging
    url = data.get('url')
    brand = data.get('brand')
# Append brand-specific path to the base URL
    if brand.lower() == 'adidas':
        url += '/collections/adidas'
    elif brand.lower() == 'nike':
        url += '/collections/nike'
    elif brand.lower() == 'jordan':
        url += '/collections/jordan'
    
    # Emit real-time updates via SocketIO
    socketio.emit('update', {'message': f'Starting to scrape {brand} products...'})
    socketio.sleep(1) # Simulate delay

     # Fetch the main product collection page
    session = requests_retry_session()
    response = session.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch the page'}), 400

    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all products on the collection page
    products = []
    for item in soup.select('a.collection-item'):
        product_url = item['href']
        product_name = item.text.strip()
        products.append({
            'name': product_name,
            'link': product_url
        })

    # Scrape detailed information from each product page
    scraped_products = []

    for product in products:
        product_detail_url = f"https://usgstore.com.au{product['link']}"
        product_response = requests.get(product_detail_url)

        if product_response.status_code == 200:
            product_data = scrape_product(product_detail_url, brand)
            if product_data:
                # Save the scraped product data to MongoDB
                gender = product_data.get('Gender', '').strip()  # Ensure to strip any leading/trailing spaces
                print("gender: ", gender)  # Debugging to see the actual gender value
                # Make comparison case-insensitive
                if gender.lower() not in ["mens footwear", "womens footwear"]:
                    continue
            
                product_item = {
                    "sku": product_data.get('SKU'),
                    "title": product_data.get('Title'),
                    "brand": product_data.get('Brand'),
                    "color": product_data.get('Color'),
                    "gender": product_data.get('Gender'),
                    "material": product_data.get('Material'),
                    "age_group": product_data.get('Age group'),
                    "size": product_data.get('Size'),
                    "barcode": product_data.get('Barcode'),
                    "weight": product_data.get('Weight'),
                    "quantity": product_data.get('Quantity'),
                    "Variants": product_data.get('Variants'),
                    "Images": product_data.get('Images'),
                    "product_detail": product_data.get('product_detail'),
                    "price": product_data.get("price")
                }
                if product_item["brand"] == "Adidas":
                    collection = collectionA
                elif product_item["brand"] == "Nike":
                    collection = collectionB
                elif product_item["brand"] == "Jordan":
                    collection = collectionC
                else:
                    print(f"Brand {product_item['brand']} is not supported.")
                    return  # Exit the function or handle other brands accordingly
                # Check if the product with the same SKU already exists
                existing_product = collection.find_one({"sku": product_item["sku"]})

                if existing_product:
                    # If the product exists, check for changes
                    # If there are any changes, update the record
                    if existing_product != product_item:
                        collection.update_one({"sku": product_item["sku"]}, {"$set": product_item})
                        print(f"Product with SKU {product_item['sku']} updated in MongoDB.")
                else:
                    # If the product does not exist, insert it into the database
                    collection.insert_one(product_item)
                    print(f"Product with SKU {product_item['sku']} inserted into MongoDB.")
            
                # Emit the scraped data for each product immediately
                socketio.emit('update', {
                    'message': f"Scraped and saved product: {product_data['Title']}",
                    'product': {
                        'Image': product_data.get('Images')[0] if product_data.get('Images') and len(product_data.get('Images')) > 0 else '',
                        'Title': product_data.get('Title', 'N/A'),
                        'Brand': product_data.get('Brand', 'N/A'),
                        'Color': product_data.get('Color', 'N/A'),
                        'Gender': product_data.get('Gender', 'N/A'),
                        'Material': product_data.get('Material', 'N/A'),
                        'Age group': product_data.get('Age group', 'N/A'),
                        'Size': product_data.get('Size', 'N/A'),
                        'SKU': product_data.get('SKU', 'N/A'),
                        'Barcode': product_data.get('Barcode', 'N/A'),
                        'Weight': product_data.get('Weight', 'N/A'),
                        'Product detail': product_data.get('product_detail', 'N/A'),
                        'Quantity': product_data.get('Quantity', 'N/A'),
                        'Variants': product_data.get('Variants', []),
                    }
                })
                socketio.sleep(1)
            else:
                # Emit a message indicating that scraping failed for this product
                socketio.emit('update', {'message': f"Failed to scrape product: {product['name']}"})
                socketio.sleep(1)
        else:
            # Emit a message indicating that fetching the product detail page failed
            socketio.emit('update', {'message': f"Failed to fetch product detail page for: {product['name']}"})
            socketio.sleep(1)

    # Emit a completion message after all products are processed
    socketio.emit('update', {'message': 'All products have been processed.'})
    socketio.sleep(1)


    # # Return all scraped data as JSON at the end of the process
    # return jsonify({'products': scraped_products})

# Run the app
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
