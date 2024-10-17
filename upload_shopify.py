import shopify
import pymongo
from pymongo.errors import ConnectionFailure
import time
import base64
import requests
from dotenv import load_dotenv
import os


load_dotenv()
ACCESS_TOKEN = os.environ.get('ACCESS_TOKEN')
mongo_uri = os.environ.get('MONGODB_URI')
# MongoDB Configuration
try:
    # client = pymongo.MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    client = pymongo.MongoClient('mongo_uri')

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

# Create session with Access Token for authentication
shop_url = f"https://revamped-retail-boutique.myshopify.com/admin/api/2023-10"
headers = {
    "X-Shopify-Access-Token": ACCESS_TOKEN
}
shopify.ShopifyResource.set_site(shop_url)
shopify.ShopifyResource.headers.update(headers)

# Step 1: Get the location ID where the inventory will be updated
locations = shopify.Location.find()
location_id = None

# We assume there's only one location. If there are multiple, you need to choose the right one
if locations:
    location_id = locations[0].id  # Get the first location ID

if location_id:
    print(f"Location ID: {location_id}")
else:
    print("No location found. Please ensure you have set up inventory locations in your Shopify store.")
    exit()

# Function to read the image and encode it for Shopify
def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        return encoded_string
# Function to check if a product with the same SKU already exists
def product_exists_by_sku(sku):
    since_id = None
    while True:
        if since_id:
            products = shopify.Product.find(since_id=since_id)
        else:
            products = shopify.Product.find()

        if not products:
            break  # Exit if no more products are found

        for product in products:
            for variant in product.variants:
                if variant.sku and variant.sku.strip() == sku.strip():  # Check if SKU is not None
                    return product

        since_id = products[-1].id  # Update since_id to the last product's ID

    return None



adidas_products = collectionA.find()
nike_products = collectionB.find()
jordan_products = collectionC.find()

def transform_mongo_to_shopify(mongo_data):
    # Convert "product_detail" to "body_html" with <ul> and <li> tags
    product_detail_lines = mongo_data['product_detail'].split('\n')
    body_html = "<ul>" + "".join([f"<li>{line.strip()}</li>" for line in product_detail_lines]) + "</ul>"
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Construct the full path to the "static/uploads" folder based on the script's location
    uploads_dir = os.path.join(script_dir, 'static', 'uploads')
    # Transform Images
    images = []
    for img_url in mongo_data['Images']:
        if img_url.startswith("/uploads"):  # Local image
            # Encode the image for uploading to Shopify
            local_image_path = os.path.join(uploads_dir, os.path.basename(img_url))  # Assuming the image is in a relative uploads folder
            if os.path.exists(local_image_path):
                encoded_image = encode_image_to_base64(local_image_path)
                images.append({"attachment": encoded_image})
            else:
                print(f"Local image not found: {local_image_path}")
        else:
            # Use the URL as-is for Shopify
            images.append({"src": img_url})

    # Transform Variants
    variants = []
    for variant in mongo_data['Variants']:
        variant_transformed = {
            "option1": variant["Size"],   # Renaming "Size" to "option1"
            "sku": variant["SKU"],        # Renaming "SKU" to "sku"
            "barcode": variant["Barcode"],  # Renaming "Barcode" to "barcode"
            "inventory_quantity": variant["Quantity"],  # Renaming "Quantity" to "inventory_quantity"
            "inventory_management": "shopify",  # Shopify inventory management
            "inventory_policy": "deny",  # Deny orders if out of stock
            "fulfillment_service": "manual",  # Manual fulfillment
            "requires_shipping": True,    # Requires shipping
            "price": mongo_data["price"]
        }
        variants.append(variant_transformed)

    # Create "options" for Shoe Size
    shoe_sizes = [variant['Size'] for variant in mongo_data['Variants']]
    options = [
        {
            "name": "Shoe Size",  # Default name
            "values": shoe_sizes  # Sizes from Variants
        }
    ]

    # Create the final product structure
    product_data = {
        "title": mongo_data["title"],  # Title from MongoDB
        "body_html": body_html,  # Convert product_detail to body_html
        "vendor": mongo_data["brand"],  # Convert "brand" to "vendor"
        "product_type": "Shoes",  # Static product type
        "tags": ["Shoes", "Footwear", "Sneakers", "Athletic"],  # Default tags
        "options": options,  # Options for shoe size
        "variants": variants,  # Variants with inventory and SKU information
        "images": images,  # Image conversion
        "status": "draft"
    }

    return product_data
def update_existing_product(existing_product, new_product_data):
    # Update basic fields like title, body_html, vendor, etc.
    existing_product.title = new_product_data['title']
    existing_product.body_html = new_product_data['body_html']
    existing_product.vendor = new_product_data['vendor']
    existing_product.product_type = new_product_data['product_type']
    existing_product.tags = new_product_data['tags']
    existing_product.status = new_product_data['status']
    # Update or create variants
    for i, new_variant in enumerate(new_product_data['variants']):
        if i < len(existing_product.variants):
            existing_variant = existing_product.variants[i].attributes
            existing_variant['option1'] = new_variant['option1']
            existing_variant['sku'] = new_variant['sku']
            existing_variant['barcode'] = new_variant['barcode']
            existing_variant['inventory_quantity'] = new_variant['inventory_quantity']
            existing_variant['price'] = new_variant['price']
        else:
            # Create a new variant object and append it
            variant = shopify.Variant(new_variant)
            existing_product.variants.append(variant)

    # Update images
    existing_product.images = new_product_data['images']

    # Save updated product
    existing_product.save()
    return existing_product

# Retry function for inventory updates
def set_inventory_with_retry(location_id, inventory_item_id, quantity, retries=5, delay=2):
    """Set inventory level with retry logic and exponential backoff."""
    for attempt in range(retries):
        try:
            inventory_level = shopify.InventoryLevel.set(location_id, inventory_item_id, quantity)
            print(f"Successfully updated variant with {quantity} units at location {location_id}")
            return inventory_level  # Exit if successful
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}. Retrying...")
            time.sleep(delay * (2 ** attempt))  # Exponential backoff
    print(f"Failed to update inventory after {retries} attempts.")

# Main process to upload or update products
def upload_product_to_shopify(m_product):
    
    product_data = transform_mongo_to_shopify(adidas_products[0])
    print(f"Checking SKU: {product_data['variants'][0]['sku']}")
    # Check if the product already exists by SKU
    existing_product = product_exists_by_sku(product_data['variants'][0]['sku'])  # Use SKU of first variant

    if existing_product:
        print(f"Product with SKU {product_data['variants'][0]['sku']} already exists with ID: {existing_product.id}")
        # Update the existing product with new data
        updated_product = update_existing_product(existing_product, product_data)
        print(f"Product '{updated_product.title}' updated successfully.")
    else:
        # Create a new product if it doesn't exist
        new_product = shopify.Product.create(product_data) 
        if new_product.errors:
            print(f"Error creating product {product_data['title']}: {new_product.errors.full_messages()}")
        else:
            print(f"Product '{new_product.title}' created successfully with ID: {new_product.id}")

            # Step 3: Update inventory for each variant
            for variant in new_product.variants:
                inventory_item_id = variant.inventory_item_id
                for variant_data in product_data['variants']:
                    if variant_data['option1'] == variant.option1:
                        quantity = variant_data['inventory_quantity']
                        break

                # Update inventory level at the specific location with retry logic
                set_inventory_with_retry(location_id, inventory_item_id, quantity)