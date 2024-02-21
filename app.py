from flask import Flask, request, jsonify, send_file
from PIL import Image
import io
import base64
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import SERVER_TIMESTAMP, Increment
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

app = Flask(__name__)
CORS(app)

# Collection references
meta_data_ref = db.collection('metaData').document('yourMetaDataDocId')
messages_ref = db.collection('messages')

def getNextMessageIndex():
    latest_message_index = meta_data_ref.get().to_dict()['latestMessageIndex']
    new_index = latest_message_index + 1
    meta_data_ref.update({'latestMessageIndex': new_index})
    return new_index

def getLatestMessageIndex():
    # Retrieve the latest message index from Firestore without changing it
    latest_message_index = meta_data_ref.get().to_dict()['latestMessageIndex']
    return latest_message_index

def getNewMessageStatus():
    return meta_data_ref.get().to_dict()['newMessageStatus']

def setNewMessageStatus(newStatus):
    meta_data_ref.update({'newMessageStatus': newStatus})

def getMessageReadStatus():
    return meta_data_ref.get().to_dict()['messageReadStatus']

def setMessageReadStatus(newStatus):
    meta_data_ref.update({'messageReadStatus': newStatus})

def getCurrentIndex():
    return meta_data_ref.get().to_dict()['currentIndex']

def setCurrentIndex(newIndex):
    # Set the currentIndex in Firestore to the provided newIndex value
    meta_data_ref.update({'currentIndex': newIndex})
    return newIndex

def SaveNewMessage(text_data, image_data):
    # Get the next message index
    next_message_index = getNextMessageIndex()
    
    # Save the new message in the 'messages' collection with the next index
    messages_ref.add({
        'Index': next_message_index,
        'text_data': text_data,
        'image_data': image_data
    })
    
    # Update the newMessageStatus and messageReadStatus
    setNewMessageStatus(True)
    setMessageReadStatus(False)

def getLatestMessage():
    # Query the 'messages' collection to get the document with the greatest index
    latest_message_query = messages_ref.order_by('Index', direction=firestore.Query.DESCENDING).limit(1)
    latest_message = latest_message_query.get()
    
    # Check if there are any messages
    if latest_message:
        # Extract the message data from the document
        latest_message_data = latest_message[0].to_dict()
        return latest_message_data
    else:
        return None  # Return None if there are no messages in the collection

def getMessageByIndex(index: int):
    # Query the 'messages' collection for a document with the specified index
    message_query = messages_ref.where('Index', '==', index).limit(1)
    message_docs = message_query.get()
    
    # Check if the message exists
    if message_docs:
        # Extract the message data from the document
        message_data = message_docs[0].to_dict()
        return message_data
    else:
        return None  # Return None if no message is found with the specified index

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
    data = request.json
    image_data = data.get('image_data')
    text_data = data.get('text_data')

    if not image_data or not text_data:
        return jsonify({'status': False, 'message': 'Missing text or image data'}), 400

    try:
        # Save the message to Firestore DB
        SaveNewMessage(text_data, image_data)
        return jsonify({'status': True, 'message': 'Message uploaded successfully'}), 200
    except Exception as e:
        # Log the exception e
        return jsonify({'status': False, 'message': 'Failed to upload message'}), 500

#Endpoint: returns new message status and info about latest message
@app.route('/get_new_message', methods=['GET'])
def get_new_message():
    # Check if there's a new message available
    if getNewMessageStatus():
        new_message = getLatestMessage()
        
        
        
        text_data = new_message.get("text_data", "")
        image_data = new_message.get("image_data", None)
        index = new_message.get("index", -1)
        setCurrentIndex(index)

        setNewMessageStatus(False)

        return jsonify({
            'status': True,
            'data': {
                'text': text_data,
                'image': bool(image_data)  # True if there's any image_data, otherwise False
            }
        })
    else:
        return jsonify({'status': False, 'message': 'No new message available'})

#Endpoint: returns latest message index
@app.route('/get_latest_message_index', methods=['GET'])
def get_latest_message_index():
    latest_message_index = getLatestMessageIndex()
    if latest_message_index:
        setCurrentIndex(latest_message_index)
        return jsonify({'status': True, 'data': {'index': latest_message_index}})
    else:
        return jsonify({'status': False, 'data': {'index': -1}})

#Endpoint: returns message at given index status and info about message
@app.route('/get_index_message/<int:message_index>', methods=['GET'])
def get_index_message(message_index):
    message = getMessageByIndex(message_index)
    if message:

        text_data = message["text_data"]
        image_data = message["image_data"]
        index = message["index"]

        setCurrentIndex(index)

        if(image_data):
            return jsonify({'status': True, 'data':{'text':text_data,'index':index, 'image':True}})
        else:
            return jsonify({'status': True, 'data':{'text':text_data,'image':False}})
    else:
        return jsonify({'status': False})

#Endpoint: Returns the cashed image data as bytes file
@app.route('/get_image_data', methods=['GET'])
def get_image_data():
    message = getMessageByIndex(getCurrentIndex())

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
            download_name='image.rgb565'
        )
    else:
        return jsonify({"error": "No image data available"}), 404 

#Enpoint: Returns Message Read Status Value (True or False)
@app.route('/get_message_read_status', methods=['GET'])
def get_message_read_status():
    return jsonify({'status': getMessageReadStatus()})

#Enpoint: Sets Message Read global variable to True 
@app.route('/set_message_read', methods=['GET'])
def set_message_read():
    setMessageReadStatus(True)
    return jsonify({'status': True})

#Endpoint: Returns a JSON conataining a message for Testing only.
@app.route('/test', methods=['GET'])
def test():
    return jsonify({'message': 'This is a test endpoint'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
