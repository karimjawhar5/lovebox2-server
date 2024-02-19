from flask import Flask, request, jsonify, send_file
from PIL import Image
import io
import base64
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import SERVER_TIMESTAMP, Increment
import threading
import os
import json
import array

# Parse the JSON string from the environment variable

cred_json = os.environ.get("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)

# Use the dictionary to initialize the credentials
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()

# A lock to manage access to global variables in a thread-safe manner
lock = threading.Lock()

cached_message_data = None

new_message_status = False
message_read_status = True

app = Flask(__name__)
CORS(app)

#Firebase Firestore Functions
def get_next_index():
    # Reference to a document that stores the current index
    index_doc_ref = db.collection('metadata').document('message_index')
    
    # Atomically increment the index and retrieve the new value
    transaction = db.transaction()
    @firestore.transactional
    def increment_index(transaction, index_doc_ref):
        snapshot = index_doc_ref.get(transaction=transaction)
        current_index = snapshot.get('index') if snapshot.exists else 0
        new_index = current_index + 1  # Increment the index
        transaction.set(index_doc_ref, {'index': new_index})  # Update the document with the new index
        return new_index  # Return the incremented index
    
    return increment_index(transaction, index_doc_ref)

def save_love_message(text_data, image_data):
    # Get the next index for the new message
    message_index = get_next_index()
    
    # Create a new document reference in the 'messages' collection
    doc_ref = db.collection('messages').document()
    doc_ref.set({
        'text_data': text_data,
        'image_data': image_data,
        'index': message_index,  # Use the message index
        'created_at': firestore.SERVER_TIMESTAMP  # Optional: keep the timestamp for other purposes
    })
    print("Message saved successfully with index:", message_index)

def get_most_recent_love_message():
    # Query the 'messages' collection ordered by 'index' in descending order
    docs = db.collection('messages').order_by('index', direction=firestore.Query.DESCENDING).limit(1).stream()

    for doc in docs:
        return doc.to_dict()  # Return the most recent document's data

    # If there are no documents in the collection
    print("No messages found.")
    return None

def get_love_message_by_index(index):
    # Query for a document in the 'messages' collection with a specific 'index'
    docs = db.collection('messages').where('index', '==', index).limit(1).stream()

    for doc in docs:
        return doc.to_dict()  # Return the found document's data

    # If no document with the specified index was found
    print(f"No message found with index {index}.")
    return None

#Convert RGB image to RGB565
def rgb565_convert(image):
    rgb565_data = array.array('H')  # 'H' for unsigned short (2 bytes)
    for pixel in image.getdata():
        r, g, b = pixel
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        rgb565_data.append(rgb565)
    return rgb565_data

#Server Endpoints:

#Endpoint: Uploads Image & Text Data To DB and Trigger new message available
@app.route('/upload', methods=['POST'])
def upload():
    global new_message_status, message_read_status

    data = request.json
    image_data = data['image_data']
    text_data = data['text_data']

    # Save the message and array to Firestore DB
    save_love_message(text_data, image_data)
    
    with lock:
        new_message_status = True
        message_read_status = False

    return jsonify({'status':True})

#Endpoint: returns new message status
@app.route('/get_new_message', methods=['GET'])
def get_new_message():
    global new_message_status, cached_message_data

    if(new_message_status):
        new_message = get_most_recent_love_message()
        cached_message_data = new_message
        
        text_data = new_message["text_data"]
        image_data = new_message["text_data"]

        new_message_status = False

        if(image_data):
            return jsonify({'status': True, 'data':{'text':text_data,'image':True}})
        else:
            return jsonify({'status': True, 'data':{'text':text_data,'image':False}})
    
    else:
        return jsonify({'status': False})

#Endpoint: returns latest message index
@app.route('/get_latest_message_index', methods=['GET'])
def get_latest_message_index():
    global new_message_status, cached_message_data
    latest_message = get_most_recent_love_message()
    if(latest_message):
        index = latest_message["index"]
        return jsonify({'status': True, 'data':{'index':index}})
    else:
        return jsonify({'status': False, 'data':{'index':-1}})


#Endpoint: returns message at given index status
@app.route('/get_index_message/<int:message_index>', methods=['GET'])
def get_index_message(message_index):
    global cached_message_data
    
    message = get_love_message_by_index(message_index)

    if(message):
        cached_message_data = message
        
        text_data = message["text_data"]
        image_data = message["text_data"]
        index = message["index"]

        if(image_data):
            return jsonify({'status': True, 'data':{'text':text_data,'index':index, 'image':True}})
        else:
            return jsonify({'status': True, 'data':{'text':text_data,'image':False}})
    
    else:
        return jsonify({'status': False})

#Endpoint: Returns the cashed image data as bytes file
@app.route('/get_image_data', methods=['GET'])
def get_image_data():
    global cached_message_data

    message = cached_message_data

    if(message):
        image_data = message["image_data"]

        # Decode the base64 image
        decoded = base64.b64decode(image_data.split(",")[1])
        image = Image.open(io.BytesIO(decoded))

        # Convert to RGB, if not already
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Convert to RGB565
        rgb565_data = rgb565_convert(image)
        rgb565_bytes = rgb565_data.tobytes()

        return send_file(
            io.BytesIO(rgb565_bytes),
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name='image.rgb565'  # Use 'download_name' instead of 'attachment_filename'
        )
    else:
        return jsonify({"error": "No image data available"}), 404 

#Enpoint: Returns Message Read Status Value (True or False)
@app.route('/get_message_read_status', methods=['GET'])
def get_message_read_status():
    global message_read_status
    return jsonify({'status': message_read_status})

#Enpoint: Sets Message Read global variable to True 
@app.route('/set_message_read', methods=['GET'])
def set_message_read():
    global message_read_status
    with lock:
        message_read_status = True
    return jsonify({'status': True})

#Endpoint: Returns a JSON conataining a message for Testing only.
@app.route('/test', methods=['GET'])
def test():
    return jsonify({'message': 'This is a test endpoint'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
