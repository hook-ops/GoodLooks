from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variable to store scraped data
scraped_data = {}

# Function to scrape product data using Selenium
def scrape_product_selenium(url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run Chrome in headless mode
    chrome_options.add_argument("--disable-gpu")
    
    # Provide path to ChromeDriver
    service = Service(executable_path="C:\\chromedriver-win64\\chromedriver-win64\\chromedriver.exe")  # Set your ChromeDriver path here
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        driver.implicitly_wait(10)  # Wait for elements to load

        product = {}

        # Scraping product details
        title_element = driver.find_element(By.TAG_NAME, 'h3')
        product['Title'] = title_element.text if title_element else 'No title found'
        product['Brand'] = 'Jordan'  # Static value for this site

        color_element = driver.find_element(By.TAG_NAME, 'h4')
        product['Color'] = color_element.text if color_element else 'No color found'
        product['Gender'] = 'Unisex'
        product['Material'] = 'Leather'
        product['Age group'] = 'Adult'

        # Scraping image src
        slide_div = driver.find_element(By.CSS_SELECTOR, 'div[data-slick-index="0"] img')
        if slide_div:
            img_src = slide_div.get_attribute('src')
            product['Image'] = "https:" + img_src if img_src.startswith("//") else img_src
        else:
            product['Image'] = "No image found"

        print(f"Scraped product: {product}")
        return product

    except Exception as e:
        print(f"Error occurred: {e}")
        return None

    finally:
        driver.quit()

# Route to serve frontend
@app.route('/')
def index():
    product = {
        'Image': 'path_to_image',  # Replace with the actual image path or URL
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

    # Scrape product data using Selenium
    scraped_data = scrape_product_selenium(url)
    if isinstance(scraped_data, dict):  # Ensure it's a dictionary
        socketio.emit('update', {'message': f"Scraped product: {scraped_data.get('Title', 'No title found')}"})
        return jsonify(scraped_data)
    else:
        return "Error: Expected a dictionary", 500

# Shopify API integration and uploading function
def connect_to_shopify(api_key, password, store_url):
    # Add Shopify connection logic here (assuming you have Shopify Python API package)
    pass

def upload_to_shopify(product_data, sku, shipping_info):
    # Implement Shopify product upload logic here
    pass

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
