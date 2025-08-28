from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
import bcrypt
import secrets
import hashlib
import base64
import qrcode
import io
import re # Moved import to top
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import os
import json
from datetime import datetime
import mimetypes

app = Flask(__name__)
app.secret_key = secrets.token_hex(32) # Secure secret key

# --- In-memory Storage (Consider persistence for production) ---
users = {}
chat_sessions = {}
messages = {}
files = {}
session_urls = {}

# --- User Initialization ---
def init_users():
    """Initialize default users with bcrypt hashed passwords."""
    global users
    # Use strong, unique passwords in a real application
    users["demigod"] = {
        "password": bcrypt.hashpw("Demig0d@".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    }
    users["human"] = {
        "password": bcrypt.hashpw("secret123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    }

init_users()

# --- Cryptography Helpers ---
def generate_chat_session():
    """Generate a cryptographically secure random chat session URL component."""
    return "session_" + secrets.token_urlsafe(16)

def generate_key_from_session(session_key, salt=None):
    """Generate a 32-byte AES key from the session key using PBKDF2-HMAC-SHA256."""
    if salt is None:
        # Use a unique, non-hardcoded salt per session in production if possible
        salt = b"stealth_messaging_salt_v5"
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32, # AES-256 key length
        salt=salt,
        iterations=100000, # NIST recommended minimum iterations
    )
    return kdf.derive(session_key.encode("utf-8"))

def encrypt_message(message, key):
    """Encrypt a message using AES-256-GCM."""
    iv = os.urandom(12) # GCM recommended IV size
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(message.encode("utf-8")) + encryptor.finalize()
    # Prepend IV and append tag for decryption
    return base64.b64encode(iv + encryptor.tag + ciphertext).decode("utf-8")

def decrypt_message(encrypted_message, key):
    """Decrypt a message using AES-256-GCM."""
    try:
        data = base64.b64decode(encrypted_message)
        iv = data[:12]
        tag = data[12:28] # GCM tag is 16 bytes
        ciphertext = data[28:]
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
        decryptor = cipher.decryptor()
        # Authenticated decryption: finalize() checks the tag
        return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")
    except Exception as e:
        print(f"[ERROR] Message decryption failed: {e}") # Log error server-side
        return "[DECRYPTION FAILED]"

def encrypt_file(file_data, key):
    """Encrypt file data using AES-256-GCM."""
    iv = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(file_data) + encryptor.finalize()
    return iv + encryptor.tag + ciphertext

def decrypt_file(encrypted_data, key):
    """Decrypt file data using AES-256-GCM."""
    try:
        iv = encrypted_data[:12]
        tag = encrypted_data[12:28]
        ciphertext = encrypted_data[28:]
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as e:
        print(f"[ERROR] File decryption failed: {e}") # Log error server-side
        return None

# --- Utility Functions ---
def generate_qr_code(data):
    """Generate a QR code image as a base64 encoded string."""
    try:
        qr = qrcode.QRCode(
            version=1, 
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10, 
            border=4 # Reduced border slightly
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        # Use red on black theme for QR code
        img = qr.make_image(fill_color="#ff0044", back_color="#000000")
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        
        return base64.b64encode(img_buffer.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"[ERROR] QR Code generation failed: {e}")
        return None # Return None on failure

# --- Flask Routes ---

@app.route("/")
def index():
    """Handles the initial user access point, showing login if user exists."""
    user = request.args.get("user")
    if user not in users:
        # Minimalist denial page
        return render_template_string("""
        <!DOCTYPE html>
        <html><head><title>ACCESS DENIED</title><style>body{background:#000;margin:0;height:100vh;overflow:hidden;}</style></head><body></body></html>
        """)
    
    # Login page for valid users
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>STEALTH LOGIN</title>
        <style>
            :root {
                --primary-color: #ff0044;
                --background-color: #000;
                --font-family: 'Courier New', monospace;
            }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: var(--background-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                padding: 20px;
            }
            .login-container {
                background: rgba(255, 0, 68, 0.1);
                border: 2px solid var(--primary-color);
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 0 20px rgba(255, 0, 68, 0.3);
                animation: pulse 2s infinite;
                width: 100%;
                max-width: 400px;
            }
            @keyframes pulse {
                0%, 100% { box-shadow: 0 0 20px rgba(255, 0, 68, 0.3); }
                50% { box-shadow: 0 0 30px rgba(255, 0, 68, 0.6); border-color: #ff3366; }
            }
            .title {
                text-align: center;
                font-size: 1.5rem; /* 24px */
                margin-bottom: 30px;
                text-shadow: 0 0 10px var(--primary-color);
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .form-group { margin-bottom: 25px; }
            label {
                display: block;
                margin-bottom: 8px;
                font-size: 0.875rem; /* 14px */
                text-transform: uppercase;
            }
            input[type="password"] {
                width: 100%;
                padding: 12px;
                background: var(--background-color);
                border: 2px solid var(--primary-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                font-size: 1rem; /* 16px */
                border-radius: 5px;
                outline: none;
                transition: border-color 0.3s, box-shadow 0.3s;
            }
            input[type="password"]:focus {
                border-color: #ff3366; /* Slightly brighter red */
                box-shadow: 0 0 10px rgba(255, 0, 68, 0.5);
            }
            .login-btn {
                width: 100%;
                padding: 15px;
                background: var(--background-color);
                border: 2px solid var(--primary-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                font-size: 1.125rem; /* 18px */
                cursor: pointer;
                border-radius: 5px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                font-weight: bold;
            }
            .login-btn:hover, .login-btn:focus {
                background: var(--primary-color);
                color: var(--background-color);
                box-shadow: 0 0 15px rgba(255, 0, 68, 0.7);
                outline: none;
            }
            .user-info {
                text-align: center;
                margin-bottom: 25px;
                font-size: 1.125rem; /* 18px */
                text-transform: uppercase;
                opacity: 0.9;
            }
            /* Responsive adjustments */
            @media (max-width: 480px) {
                .login-container { padding: 30px 20px; }
                .title { font-size: 1.25rem; /* 20px */ }
                input[type="password"] { font-size: 0.875rem; padding: 10px; }
                .login-btn { font-size: 1rem; padding: 12px; }
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="title">Stealth Access</div>
            <div class="user-info">User: {{ user|upper }}</div>
            <form method="POST" action="{{ url_for('login') }}">
                <input type="hidden" name="username" value="{{ user }}">
                <div class="form-group">
                    <label for="password">Access Code:</label>
                    <input type="password" name="password" id="password" required>
                </div>
                <button type="submit" class="login-btn">Authenticate</button>
            </form>
        </div>
    </body>
    </html>
    """, user=user)

@app.route("/login", methods=["POST"])
def login():
    """Handles user login authentication."""
    username = request.form.get("username")
    password = request.form.get("password")
    
    user_data = users.get(username)
    if user_data and bcrypt.checkpw(password.encode("utf-8"), user_data["password"].encode("utf-8")):
        session["user"] = username
        session["authenticated"] = True
        # Generate a unique chat session URL for this login
        chat_url_component = generate_chat_session()
        session["chat_url"] = chat_url_component
        session_urls[chat_url_component] = username # Store association
        print(f"[INFO] User '{username}' logged in. Session URL component: {chat_url_component}")
        return redirect(url_for("start"))
    else:
        print(f"[WARN] Failed login attempt for user '{username}'")
        # Provide a generic failure message
        return "ACCESS DENIED - Invalid Credentials", 403

@app.route("/start")
def start():
    """Shows the start page after successful login."""
    if not session.get("authenticated"): 
        return redirect(url_for("index")) # Redirect if not logged in
    
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>STEALTH READY</title>
        <style>
            :root { --primary-color: #ff0044; --background-color: #000; --font-family: 'Courier New', monospace; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: var(--background-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                padding: 20px;
            }
            .start-container {
                text-align: center;
                background: rgba(255, 0, 68, 0.1);
                border: 2px solid var(--primary-color);
                padding: 60px 40px;
                border-radius: 10px;
                box-shadow: 0 0 30px rgba(255, 0, 68, 0.5);
                animation: glow 3s ease-in-out infinite alternate;
                width: 100%;
                max-width: 500px;
            }
            @keyframes glow {
                from { box-shadow: 0 0 30px rgba(255, 0, 68, 0.5); border-color: var(--primary-color); }
                to { box-shadow: 0 0 50px rgba(255, 0, 68, 0.8); border-color: #ff3366; }
            }
            .title {
                font-size: 2rem; /* 32px */
                margin-bottom: 40px;
                text-shadow: 0 0 15px var(--primary-color);
                animation: flicker 1.5s infinite alternate;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
            @keyframes flicker {
                0%, 100% { opacity: 1; text-shadow: 0 0 15px var(--primary-color); }
                50% { opacity: 0.8; text-shadow: 0 0 20px #ff3366; }
            }
            .start-btn {
                background: var(--background-color);
                border: 3px solid var(--primary-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                font-size: 1.5rem; /* 24px */
                padding: 20px 40px;
                cursor: pointer;
                border-radius: 10px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                font-weight: bold;
                letter-spacing: 2px;
                width: 100%;
                max-width: 300px;
                display: inline-block; /* Ensure max-width works */
            }
            .start-btn:hover, .start-btn:focus {
                background: var(--primary-color);
                color: var(--background-color);
                box-shadow: 0 0 25px rgba(255, 0, 68, 0.9);
                transform: scale(1.05);
                outline: none;
            }
            /* Responsive adjustments */
            @media (max-width: 480px) {
                .start-container { padding: 40px 20px; }
                .title { font-size: 1.5rem; /* 24px */ margin-bottom: 30px; }
                .start-btn { font-size: 1.125rem; /* 18px */ padding: 15px 30px; letter-spacing: 1px; }
            }
        </style>
    </head>
    <body>
        <div class="start-container">
            <div class="title">System Ready</div>
            <form method="POST" action="{{ url_for('setup') }}">
                <button type="submit" class="start-btn">Initiate Session</button>
            </form>
        </div>
    </body>
    </html>
    """)

@app.route("/setup", methods=["POST"])
def setup():
    """Generates and displays the unique chat URL and QR code."""
    if not session.get("authenticated"): 
        return redirect(url_for("index"))
    
    chat_url_component = session.get("chat_url")
    if not chat_url_component or chat_url_component not in session_urls:
        # Handle potential session error or URL mismatch
        print(f"[WARN] Session error during setup for user '{session.get('user')}' - chat_url missing or invalid.")
        session.pop("chat_url", None)
        return "SESSION ERROR - Please log in again.", 500
    
    # Construct the full URL for sharing
    # Use url_for for robustness
    full_url = url_for("chat_session", session_url=chat_url_component, _external=True)
    qr_code_b64 = generate_qr_code(full_url)

    if qr_code_b64 is None:
        return "ERROR Generating QR Code", 500
    
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CHAT PORTAL</title>
        <style>
            :root { --primary-color: #ff0044; --background-color: #000; --font-family: 'Courier New', monospace; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                background: var(--background-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                padding: 20px;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
            }
            .setup-container {
                background: rgba(255, 0, 68, 0.1);
                border: 2px solid var(--primary-color);
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 0 25px rgba(255, 0, 68, 0.4);
                text-align: center;
                width: 100%;
                max-width: 600px;
            }
            .title {
                font-size: 1.75rem; /* 28px */
                margin-bottom: 30px;
                text-shadow: 0 0 10px var(--primary-color);
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .url-section {
                margin-bottom: 30px;
                padding: 20px;
                background: rgba(0, 0, 0, 0.5);
                border: 1px solid var(--primary-color);
                border-radius: 5px;
            }
            .url-label {
                font-size: 0.875rem; /* 14px */
                margin-bottom: 10px;
                text-transform: uppercase;
                display: block;
            }
            .chat-url-input {
                background: var(--background-color);
                border: 2px solid var(--primary-color);
                color: var(--primary-color);
                padding: 12px;
                font-family: var(--font-family);
                font-size: 0.875rem; /* 14px */
                width: 100%;
                border-radius: 5px;
                word-break: break-all;
                outline: none;
                text-align: center;
                cursor: pointer; /* Indicate it's selectable */
            }
            .qr-section { margin-bottom: 35px; }
            .qr-code {
                max-width: 200px;
                height: auto;
                border: 3px solid var(--primary-color);
                border-radius: 5px;
                display: block; /* Center the image */
                margin: 10px auto 0;
                background: black; /* Ensure background for QR */
            }
            .access-btn {
                background: var(--background-color);
                border: 2px solid var(--primary-color);
                color: var(--primary-color);
                font-family: var(--font-family);
                font-size: 1.125rem; /* 18px */
                padding: 15px 30px;
                cursor: pointer;
                border-radius: 5px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                text-decoration: none;
                display: inline-block;
                font-weight: bold;
                letter-spacing: 1px;
            }
            .access-btn:hover, .access-btn:focus {
                background: var(--primary-color);
                color: var(--background-color);
                box-shadow: 0 0 15px rgba(255, 0, 68, 0.7);
                outline: none;
            }
            /* Responsive adjustments */
            @media (max-width: 600px) {
                .setup-container { padding: 30px 20px; }
                .title { font-size: 1.375rem; /* 22px */ margin-bottom: 25px; }
                .chat-url-input { font-size: 0.75rem; /* 12px */ padding: 10px; }
                .qr-code { max-width: 160px; }
                .access-btn { font-size: 1rem; /* 16px */ padding: 12px 25px; }
            }
        </style>
    </head>
    <body>
        <div class="setup-container">
            <div class="title">Chat Portal Generated</div>
            
            <div class="url-section">
                <label for="chat-url" class="url-label">Secure Chat URL (Click to Select & Copy):</label>
                <input type="text" id="chat-url" class="chat-url-input" value="{{ chat_url }}" readonly onclick="this.select(); try { document.execCommand('copy'); alert('URL copied to clipboard!'); } catch (err) { alert('Failed to copy URL.'); }">
            </div>
            
            <div class="qr-section">
                <div class="url-label">QR Access Code:</div>
                <img src="data:image/png;base64,{{ qr_code_b64 }}" alt="QR Code for Chat Session" class="qr-code">
            </div>
            
            <a href="{{ url_for('chat_session', session_url=session_url_component) }}" class="access-btn">Access Chat</a>
        </div>
    </body>
    </html>
    """, chat_url=full_url, qr_code_b64=qr_code_b64, session_url_component=chat_url_component)

@app.route("/<path:session_url>")
def chat_session(session_url):
    """Handles the main chat interface for a specific session URL."""
    # Validate session URL exists in our tracking
    if session_url not in session_urls:
        print(f"[WARN] Access attempt to invalid session URL: {session_url}")
        return "INVALID OR EXPIRED SESSION", 404

    # Store the accessed session URL component in the Flask session
    # This helps link the browser session to the specific chat room URL they are viewing
    session['current_session_url_component'] = session_url
    print(f"[INFO] User accessing chat session: {session_url}")

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>STEALTH CHAT</title>
        <style>
            :root {
                --primary-color: #ff0044;
                --background-color: #000;
                --font-family: 'Courier New', monospace;
                --container-bg: rgba(255, 0, 68, 0.05);
                --input-bg: rgba(0, 0, 0, 0.7);
                --message-bg: rgba(255, 0, 68, 0.1);
                --message-own-bg: rgba(255, 0, 68, 0.15); /* Slightly different for own messages */
                --border-color: #ff0044;
                --text-color: #ff0044;
                --link-color: #ff5577; /* Brighter link color */
            }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html { height: 100%; }
            body {
                background: var(--background-color);
                color: var(--text-color);
                font-family: var(--font-family);
                height: 100%;
                overflow: hidden;
                display: flex;
                justify-content: center; /* Center the chat container */
            }
            .chat-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                width: 100%;
                max-width: 800px; /* Limit max width */
                background: var(--container-bg);
                border-left: 1px solid var(--border-color);
                border-right: 1px solid var(--border-color);
            }
            .header {
                background: rgba(255, 0, 68, 0.15);
                border-bottom: 2px solid var(--border-color);
                padding: 12px 20px;
                text-align: center;
                font-size: 1.125rem; /* 18px */
                text-transform: uppercase;
                letter-spacing: 2px;
                text-shadow: 0 0 8px var(--primary-color);
                flex-shrink: 0;
            }
            .setup-section {
                padding: 15px 20px;
                border-bottom: 1px solid var(--border-color);
                background: var(--input-bg);
                flex-shrink: 0;
                transition: opacity 0.5s ease, max-height 0.5s ease; /* Added transition */
                overflow: hidden; /* Needed for max-height transition */
                max-height: 300px; /* Initial max-height, adjust as needed */
                opacity: 1;
            }
            .setup-section.hidden {
                 padding-top: 0;
                 padding-bottom: 0;
                 border-bottom: none;
                 max-height: 0;
                 opacity: 0;
            }
            .input-group {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-bottom: 10px;
                align-items: center;
            }
            .input-group input[type="text"], .input-group input[type="password"] {
                background: var(--background-color);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                padding: 8px 12px;
                font-family: var(--font-family);
                font-size: 0.875rem; /* 14px */
                border-radius: 3px;
                outline: none;
                flex: 1;
                min-width: 120px;
            }
            .input-group input:focus {
                 border-color: #ff3366;
                 box-shadow: 0 0 5px rgba(255, 0, 68, 0.3);
            }
            .join-btn, .unlock-btn {
                background: var(--background-color);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                padding: 8px 16px;
                font-family: var(--font-family);
                font-size: 0.875rem; /* 14px */
                cursor: pointer;
                border-radius: 3px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                white-space: nowrap;
            }
            .join-btn:hover, .unlock-btn:hover,
            .join-btn:focus, .unlock-btn:focus {
                background: var(--primary-color);
                color: var(--background-color);
                outline: none;
            }
            .join-btn:disabled, .unlock-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .lock-icon {
                font-size: 1.5rem; /* 24px */
                cursor: pointer;
                margin-left: 10px;
                transition: all 0.3s ease;
                user-select: none;
                padding: 0 5px;
                line-height: 1;
            }
            .lock-icon:hover {
                text-shadow: 0 0 10px var(--primary-color);
                transform: scale(1.1);
            }
            .unlock-section {
                display: none; /* Initially hidden */
                margin-top: 10px;
                padding: 10px;
                border: 1px dashed var(--border-color);
                border-radius: 5px;
                background: rgba(255, 0, 68, 0.1);
                text-align: center;
            }
            .messages-container {
                flex: 1;
                overflow-y: auto;
                padding: 15px 20px;
                background: rgba(0, 0, 0, 0.8);
                border-bottom: 1px solid var(--border-color);
            }
            /* Scrollbar styling */
            .messages-container::-webkit-scrollbar {
                width: 8px;
            }
            .messages-container::-webkit-scrollbar-track {
                background: rgba(0,0,0,0.5);
            }
            .messages-container::-webkit-scrollbar-thumb {
                background-color: var(--primary-color);
                border-radius: 4px;
                border: 2px solid var(--background-color);
            }
            .message {
                background: var(--message-bg);
                border: 1px solid var(--border-color);
                padding: 10px 12px;
                margin-bottom: 10px;
                border-radius: 5px;
                word-wrap: break-word;
                max-width: 90%; /* Prevent messages spanning full width */
                clear: both; /* Ensure messages don't overlap floats if used */
                float: left; /* Default alignment */
            }
            .message.own-message {
                background: var(--message-own-bg);
                border-color: #ff3366;
                float: right; /* Align own messages to the right */
            }
            .message-header {
                font-size: 0.75rem; /* 12px */
                color: var(--text-color);
                margin-bottom: 5px;
                opacity: 0.7;
                display: flex;
                justify-content: space-between;
            }
            .message-content {
                font-size: 0.875rem; /* 14px */
                line-height: 1.4;
                white-space: pre-wrap; /* Preserve whitespace and newlines */
            }
            .file-link {
                color: var(--link-color);
                text-decoration: underline;
                cursor: pointer;
                font-weight: bold;
            }
            .file-link:hover {
                color: #ffffff;
            }
            .input-section {
                background: rgba(255, 0, 68, 0.15);
                border-top: 2px solid var(--border-color);
                padding: 15px 20px;
                flex-shrink: 0;
                display: none; /* Initially hidden until unlocked */
            }
            .message-input-group {
                display: flex;
                gap: 10px;
                align-items: center;
                flex-wrap: wrap;
            }
            .message-input {
                flex: 1;
                background: var(--background-color);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                padding: 10px;
                font-family: var(--font-family);
                font-size: 0.875rem; /* 14px */
                border-radius: 3px;
                outline: none;
                min-width: 150px;
            }
            .message-input:focus {
                 border-color: #ff3366;
                 box-shadow: 0 0 5px rgba(255, 0, 68, 0.3);
            }
            .file-input-wrapper {
                position: relative;
                overflow: hidden;
                display: inline-block;
                background: var(--background-color);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                padding: 8px 12px;
                font-size: 0.75rem; /* 12px */
                border-radius: 3px;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            .file-input-wrapper:hover {
                background: var(--primary-color);
                color: var(--background-color);
            }
            .file-input {
                position: absolute;
                left: 0;
                top: 0;
                opacity: 0;
                cursor: pointer;
                width: 100%;
                height: 100%;
            }
            #file-name-display {
                font-size: 0.75rem;
                opacity: 0.7;
                margin-left: 5px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                max-width: 150px; /* Limit display width */
                display: inline-block;
                vertical-align: middle;
            }
            .send-btn {
                background: var(--background-color);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                padding: 10px 20px;
                font-family: var(--font-family);
                font-size: 0.875rem; /* 14px */
                cursor: pointer;
                border-radius: 3px;
                transition: all 0.3s ease;
                text-transform: uppercase;
                white-space: nowrap;
            }
            .send-btn:hover, .send-btn:focus {
                background: var(--primary-color);
                color: var(--background-color);
                outline: none;
            }
            .send-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .status {
                padding: 15px;
                text-align: center;
                font-size: 0.875rem; /* 14px */
                opacity: 0.8;
            }
            /* Responsive adjustments */
            @media (max-width: 768px) {
                .header { font-size: 1rem; padding: 10px 15px; letter-spacing: 1px; }
                .setup-section { padding: 15px; }
                .input-group {
                    flex-direction: column;
                    align-items: stretch;
                }
                .input-group input { min-width: auto; margin-bottom: 5px; }
                .join-btn, .unlock-btn { width: 100%; padding: 10px; }
                .lock-icon { margin-left: 0; margin-top: 5px; text-align: center; }
                .messages-container { padding: 10px 15px; }
                .input-section { padding: 10px 15px; }
                .message-input-group {
                    flex-direction: column;
                    align-items: stretch;
                }
                .message-input { min-width: auto; margin-bottom: 10px; }
                .file-input-wrapper { width: 100%; text-align: center; margin-bottom: 10px; }
                #file-name-display { max-width: none; }
                .send-btn { width: 100%; padding: 12px; }
                .message { max-width: 95%; }
            }
            @media (max-width: 480px) {
                .header { font-size: 0.875rem; }
                .message { padding: 8px 10px; }
                .message-content { font-size: 0.8125rem; /* 13px */ }
                .message-header { font-size: 0.6875rem; /* 11px */ }
            }
        </style>
    </head>
    <body>
        <div class="chat-container" id="chat-interface">
            <div class="header">Stealth Communications</div>
            
            <div class="setup-section" id="setup-section">
                <div class="input-group">
                    <input type="text" id="username" placeholder="USERNAME" maxlength="20" autocomplete="off">
                    <input type="password" id="session-key" placeholder="11-DIGIT SESSION KEY" maxlength="11" pattern="[0-9]{11}" inputmode="numeric" autocomplete="off">
                    <button onclick="joinChat()" class="join-btn" id="join-btn">Join</button>
                    <span class="lock-icon" onclick="clickLock()" id="lock-icon" title="">🔒</span>
                </div>
                
                <div class="unlock-section" id="unlock-section">
                    <button onclick="unlockChat()" class="unlock-btn" id="unlock-btn">Unlock Chat</button>
                    <div class="status" id="click-status">Clicks: <span id="click-count">0</span>/7</div>
                </div>
            </div>
            
            <div class="messages-container" id="messages-container">
                <div class="status" id="initial-status">Enter your username and the 11-digit session key to join the secure chat room.</div>
            </div>
            
            <div class="input-section" id="input-section">
                <div class="message-input-group">
                    <input type="text" id="message-input" placeholder="Type your encrypted message..." class="message-input" autocomplete="off">
                    <label class="file-input-wrapper" for="file-input">
                        Attach File
                        <input type="file" id="file-input" class="file-input" accept="*/*">
                    </label>
                    <span id="file-name-display"></span>
                    <button onclick="sendMessage()" class="send-btn" id="send-btn">Send</button>
                </div>
            </div>
        </div>
        
        <script>
            let clickCount = 0;
            let chatUnlocked = false;
            let currentRoom = null;
            let currentUsername = null;
            let messageInterval = null;
            const CLICKS_REQUIRED = 7;

            // DOM Elements
            const setupSection = document.getElementById('setup-section');
            const usernameInput = document.getElementById('username');
            const sessionKeyInput = document.getElementById('session-key');
            const joinBtn = document.getElementById('join-btn');
            const lockIcon = document.getElementById('lock-icon');
            const clickCountSpan = document.getElementById('click-count');
            const clickStatusDiv = document.getElementById('click-status');
            const unlockSection = document.getElementById('unlock-section');
            const unlockBtn = document.getElementById('unlock-btn');
            const messagesContainer = document.getElementById('messages-container');
            const initialStatus = document.getElementById('initial-status');
            const inputSection = document.getElementById('input-section');
            const messageInput = document.getElementById('message-input');
            const fileInput = document.getElementById('file-input');
            const fileNameDisplay = document.getElementById('file-name-display');
            const sendBtn = document.getElementById('send-btn');

            function showStatus(message, isError = false) {
                // Simple status update, could be enhanced (e.g., temporary messages)
                console.log(isError ? `Error: ${message}` : `Status: ${message}`);
                // Optionally update a status bar element if added to HTML
            }

            function clickLock() {
                if (chatUnlocked || !currentRoom) return; // Don't allow clicks if unlocked or not joined

                clickCount++;
                clickCountSpan.textContent = clickCount;
                clickStatusDiv.textContent = `Clicks: ${clickCount}/${CLICKS_REQUIRED}`;
                
                // Visual feedback on click
                lockIcon.style.transform = 'scale(1.2)';
                setTimeout(() => { lockIcon.style.transform = 'scale(1)'; }, 100);

                if (clickCount >= CLICKS_REQUIRED) {
                    unlockSection.style.display = 'block';
                    lockIcon.textContent = '🔓';
                    lockIcon.style.cursor = 'default'; // Indicate it's done
                    clickStatusDiv.textContent = `Ready to Unlock`;
                }
            }

            async function joinChat() {
                const username = usernameInput.value.trim();
                const sessionKey = sessionKeyInput.value.trim();
                
                // --- Client-side Validation ---
                if (!username) {
                    alert('Please enter a username.');
                    usernameInput.focus();
                    return;
                }
                if (!/^[a-zA-Z0-9_.-]+$/.test(username)) {
                     alert('Username can only contain letters, numbers, underscore, dot, and hyphen.');
                     usernameInput.focus();
                     return;
                }
                if (!sessionKey) {
                    alert('Please enter the 11-digit session key.');
                    sessionKeyInput.focus();
                    return;
                }
                if (sessionKey.length !== 11 || !/^[0-9]+$/.test(sessionKey)) {
                    alert('Session key must be exactly 11 digits.');
                    sessionKeyInput.focus();
                    return;
                }
                // --- End Validation ---
                
                joinBtn.disabled = true;
                joinBtn.textContent = 'Joining...';
                showStatus('Attempting to join chat...');

                try {
                    const response = await fetch("{{ url_for('join_chat') }}", {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: username, session_key: sessionKey })
                    });

                    const data = await response.json();

                    if (response.ok && data.success) {
                        currentRoom = sessionKey;
                        currentUsername = username; // Store username for message styling
                        messagesContainer.innerHTML = ''; // Clear initial status
                        const statusDiv = document.createElement('div');
                        statusDiv.className = 'status';
                        statusDiv.textContent = `Connected to room ${sessionKey}.`;
                        messagesContainer.appendChild(statusDiv);
                        usernameInput.disabled = true;
                        sessionKeyInput.disabled = true;
                        joinBtn.textContent = 'Joined';
                        showStatus('Successfully joined room.');
                        // Reset click count for the new session
                        clickCount = 0;
                        clickCountSpan.textContent = '0';
                        clickStatusDiv.textContent = `Clicks: 0/${CLICKS_REQUIRED}`;
                        unlockSection.style.display = 'none';
                        lockIcon.textContent = '🔒';
                        lockIcon.style.cursor = 'pointer';
                        unlockBtn.disabled = false;
                        unlockBtn.textContent = 'Unlock Chat';
                        chatUnlocked = false;
                        inputSection.style.display = 'none';
                        setupSection.classList.remove('hidden'); // Ensure setup is visible when joining
                        if (messageInterval) clearInterval(messageInterval);

                    } else {
                        alert(data.message || `Failed to join chat (HTTP ${response.status})`);
                        showStatus(data.message || `Failed to join chat (HTTP ${response.status})`, true);
                        joinBtn.textContent = 'Join'; // Reset button text
                        usernameInput.disabled = false; // Re-enable inputs on failure
                        sessionKeyInput.disabled = false;
                    }
                } catch (error) {
                    console.error('Join Chat Error:', error);
                    alert('Connection failed during join attempt. Check console for details.');
                    showStatus('Connection failed during join attempt.', true);
                    joinBtn.textContent = 'Join'; // Reset button text
                    usernameInput.disabled = false; // Re-enable inputs on failure
                    sessionKeyInput.disabled = false;
                } finally {
                    joinBtn.disabled = false; // Re-enable button if not successful
                }
            }

            async function unlockChat() {
                if (clickCount < CLICKS_REQUIRED) {
                    alert(`Click the lock ${CLICKS_REQUIRED} times first!`);
                    return;
                }
                if (!currentRoom) {
                    alert('You must join a chat room first!');
                    return;
                }
                
                unlockBtn.disabled = true;
                unlockBtn.textContent = 'Unlocking...';
                showStatus('Attempting to unlock chat...');

                try {
                    const response = await fetch("{{ url_for('unlock') }}", {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_key: currentRoom })
                    });
                    const data = await response.json();

                    if (response.ok && data.success) {
                        chatUnlocked = true;
                        inputSection.style.display = 'block'; // Show message input
                        unlockBtn.textContent = 'Chat Unlocked';
                        unlockSection.style.display = 'none'; // Hide unlock button section
                        setupSection.classList.add('hidden'); // *** HIDE SETUP SECTION ***
                        showStatus('Chat unlocked successfully.');
                        loadMessages(); // Initial load
                        startMessagePolling(); // Start checking for new messages
                        messageInput.focus();
                    } else {
                        alert(data.message || `Failed to unlock chat (HTTP ${response.status})`);
                        showStatus(data.message || `Failed to unlock chat (HTTP ${response.status})`, true);
                        unlockBtn.textContent = 'Unlock Chat'; // Reset text
                        unlockBtn.disabled = false; // Re-enable on failure
                    }
                } catch (error) {
                    console.error('Unlock Chat Error:', error);
                    alert('Connection failed during unlock attempt. Check console for details.');
                    showStatus('Connection failed during unlock attempt.', true);
                    unlockBtn.textContent = 'Unlock Chat'; // Reset text
                    unlockBtn.disabled = false; // Re-enable on failure
                }
            }

            async function sendMessage() {
                if (!chatUnlocked || !currentRoom) {
                    alert('Chat is not unlocked or you are not in a room!');
                    return;
                }
                
                const message = messageInput.value.trim();
                const file = fileInput.files[0];
                
                if (!message && !file) {
                    // No need to alert, just do nothing if both are empty
                    return;
                }
                
                if (message && file) {
                    alert('You can send either a text message OR a file, not both at the same time.');
                    return;
                }
                
                sendBtn.disabled = true;
                sendBtn.textContent = 'Sending...';
                showStatus('Sending message/file...');

                const formData = new FormData();
                formData.append('session_key', currentRoom);
                
                if (file) {
                    // Basic client-side size check (server validates again)
                    if (file.size > 16 * 1024 * 1024) { // 16 MB limit
                        alert('File size exceeds the 16MB limit.');
                        sendBtn.disabled = false;
                        sendBtn.textContent = 'Send';
                        showStatus('File size limit exceeded.', true);
                        return;
                    }
                    formData.append('file', file);
                } else {
                    formData.append('message', message);
                }
                
                try {
                    const response = await fetch("{{ url_for('send_message') }}", {
                        method: 'POST',
                        body: formData // FormData sets Content-Type automatically
                    });
                    const data = await response.json();

                    if (response.ok && data.success) {
                        messageInput.value = ''; // Clear input
                        fileInput.value = ''; // Clear file input
                        fileNameDisplay.textContent = ''; // Clear file name display
                        messageInput.disabled = false; // Re-enable message input
                        messageInput.placeholder = 'Type your encrypted message...';
                        showStatus('Message/File sent successfully.');
                        loadMessages(); // Refresh messages immediately
                    } else {
                        alert(data.message || `Failed to send (HTTP ${response.status})`);
                        showStatus(data.message || `Failed to send (HTTP ${response.status})`, true);
                    }
                } catch (error) {
                    console.error('Send Message Error:', error);
                    alert('Connection failed while sending. Check console for details.');
                    showStatus('Connection failed while sending.', true);
                } finally {
                    sendBtn.disabled = false;
                    sendBtn.textContent = 'Send';
                }
            }

            async function loadMessages() {
                if (!currentRoom || !chatUnlocked) return; // Only load if in a room and unlocked
                
                try {
                    // Pass current username to potentially optimize backend later if needed
                    const response = await fetch(`{{ url_for('get_messages') }}?session_key=${currentRoom}&username=${encodeURIComponent(currentUsername)}`); 
                    if (!response.ok) {
                         // Don't alert on polling errors, just log
                        console.warn(`Failed to fetch messages (HTTP ${response.status})`);
                        return; 
                    }
                    const data = await response.json();
                    if (data.success) {
                        displayMessages(data.messages);
                    } else {
                        console.warn('Failed to load messages:', data.message);
                    }
                } catch (error) {
                    console.error('Error loading messages:', error);
                    // Avoid alerting during polling
                }
            }

            function displayMessages(messages) {
                const isScrolledToBottom = messagesContainer.scrollHeight - messagesContainer.clientHeight <= messagesContainer.scrollTop + 1;
                
                messagesContainer.innerHTML = ''; // Clear existing messages
                
                if (messages.length === 0) {
                    messagesContainer.innerHTML = '<div class="status">No messages yet. Send the first one!</div>';
                    return;
                }
                
                messages.forEach(msg => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = 'message';
                    // Add 'own-message' class if the username matches the current user
                    if (msg.username === currentUsername) {
                        msgDiv.classList.add('own-message');
                    }
                    
                    // Format timestamp
                    const timestamp = new Date(msg.timestamp).toLocaleString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    const header = document.createElement('div');
                    header.className = 'message-header';
                    
                    const userSpan = document.createElement('span');
                    userSpan.textContent = escapeHtml(msg.username); // Escape username
                    const timeSpan = document.createElement('span');
                    timeSpan.textContent = timestamp;
                    
                    header.appendChild(userSpan);
                    header.appendChild(timeSpan);
                    
                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'message-content';
                    
                    if (msg.type === 'file') {
                        const link = document.createElement('a');
                        // Construct URL using url_for for robustness
                        link.href = "{{ url_for('download_file', file_id='FILE_ID_PLACEHOLDER') }}".replace('FILE_ID_PLACEHOLDER', msg.file_id);
                        link.className = 'file-link';
                        link.target = '_blank'; // Open in new tab
                        link.textContent = `📎 ${escapeHtml(msg.filename)}`;
                        link.title = `Download ${escapeHtml(msg.filename)}`;
                        contentDiv.appendChild(link);
                    } else {
                        // Use textContent to prevent XSS from message content
                        contentDiv.textContent = msg.content; 
                    }
                    
                    msgDiv.appendChild(header);
                    msgDiv.appendChild(contentDiv);
                    messagesContainer.appendChild(msgDiv);
                });
                
                // Scroll to bottom only if user was already near the bottom before refresh
                if (isScrolledToBottom) {
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            }

            // Utility to escape HTML special characters
            function escapeHtml(unsafe) {
                if (typeof unsafe !== 'string') return '';
                return unsafe
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");
            }

            function startMessagePolling() {
                if (messageInterval) {
                    clearInterval(messageInterval);
                }
                // Poll every 3 seconds (adjust as needed)
                messageInterval = setInterval(() => {
                    if (chatUnlocked && currentRoom) {
                        loadMessages();
                    }
                }, 3000);
            }

            // --- Event Listeners ---
            messageInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) { // Send on Enter, allow Shift+Enter for newline
                    e.preventDefault(); // Prevent default newline insertion
                    sendMessage();
                }
            });

            sessionKeyInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    joinChat();
                }
            });
            
            usernameInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    joinChat(); // Allow joining by pressing Enter in username field too
                }
            });

            fileInput.addEventListener('change', function() {
                if (fileInput.files.length > 0) {
                    fileNameDisplay.textContent = escapeHtml(fileInput.files[0].name);
                    messageInput.disabled = true; // Disable text input when file selected
                    messageInput.placeholder = 'File selected. Clear selection to type message.';
                } else {
                    fileNameDisplay.textContent = '';
                    messageInput.disabled = false;
                    messageInput.placeholder = 'Type your encrypted message...';
                }
            });

            // Initial setup focus
            usernameInput.focus();

        </script>
    </body>
    </html>
    """)

@app.route("/join_chat", methods=["POST"])
def join_chat():
    """API endpoint for a user to join a specific chat session."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request format'}), 400
        
    username = data.get('username', '').strip()
    session_key = data.get('session_key', '').strip()
    
    # Server-side validation
    if not username:
        return jsonify({'success': False, 'message': 'Username is required'}), 400
    if not session_key:
        return jsonify({'success': False, 'message': 'Session key is required'}), 400
    if len(session_key) != 11 or not session_key.isdigit():
        return jsonify({'success': False, 'message': 'Session key must be exactly 11 digits'}), 400
    if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
         return jsonify({'success': False, 'message': 'Invalid username format (use letters, numbers, _, ., -)'}), 400

    # Check if the session URL associated with this key exists
    # This is an indirect way to check if the key is potentially valid
    # A more robust check might involve looking up the key directly if stored differently
    session_url_component = session.get('current_session_url_component') # Get from the page they are on
    if not session_url_component or session_url_component not in session_urls:
         print(f"[WARN] Join attempt failed: Session URL component '{session_url_component}' not found in session_urls.")
         # Don't reveal if the key is valid, just that the session context is wrong
         return jsonify({'success': False, 'message': 'Invalid session context. Please use the correct chat link.'}), 400

    print(f"[INFO] User '{username}' attempting to join session key '{session_key}' via URL component '{session_url_component}'")

    # Create chat session in memory if it doesn't exist
    if session_key not in chat_sessions:
        print(f"[INFO] Creating new chat session for key: {session_key}")
        chat_sessions[session_key] = {
            'users': set(), # Use a set for efficient add/check
            'key': generate_key_from_session(session_key),
            'unlocked_users': set()
        }
    
    # Add user to the session
    chat_sessions[session_key]['users'].add(username)
    
    # Initialize messages list for this session if new
    if session_key not in messages:
        messages[session_key] = []
        
    # Store the username and current key in the Flask session for this browser
    session['chat_username'] = username
    session['current_chat_key'] = session_key
    print(f"[INFO] User '{username}' successfully joined session '{session_key}'. Session data updated.")

    return jsonify({'success': True, 'message': 'Joined chat successfully'}) 

@app.route("/unlock", methods=["POST"])
def unlock():
    """API endpoint to mark a user as having unlocked the chat for a session."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request format'}), 400
        
    session_key = data.get('session_key', '').strip()
    # Get username from Flask session - set during join_chat
    username = session.get('chat_username') 
    # Get the key expected for this session from Flask session
    expected_session_key = session.get('current_chat_key') 

    print(f"[INFO] Unlock attempt: User='{username}', Key Sent='{session_key}', Expected Key='{expected_session_key}'")

    # --- Rigorous Checks ---
    if not username:
         print(f"[WARN] Unlock failed: User identity not found in session.")
         return jsonify({'success': False, 'message': 'User identity not found in session. Please join first.'}), 401
    if not session_key:
        print(f"[WARN] Unlock failed: Session key missing in request.")
        return jsonify({'success': False, 'message': 'Session key missing.'}), 400
    if session_key != expected_session_key:
        print(f"[WARN] Unlock failed: Session key mismatch. Sent='{session_key}', Expected='{expected_session_key}'.")
        # Security: Don't reveal the expected key in the response
        return jsonify({'success': False, 'message': 'Session key mismatch or invalid session context.'}), 400
    if session_key not in chat_sessions:
        print(f"[WARN] Unlock failed: Session key '{session_key}' not found in active chat_sessions.")
        return jsonify({'success': False, 'message': 'Invalid or inactive session key.'}), 400
    # --- End Checks ---

    # Mark this user as unlocked for this session
    try:
        chat_sessions[session_key]['unlocked_users'].add(username)
        print(f"[INFO] User '{username}' successfully unlocked session '{session_key}'.")
        return jsonify({'success': True, 'message': 'Chat unlocked'}) 
    except KeyError:
        # This shouldn't happen if session_key is in chat_sessions, but as a safeguard
        print(f"[ERROR] Unlock failed: Internal error accessing unlocked_users for session '{session_key}'.")
        return jsonify({'success': False, 'message': 'Internal server error during unlock.'}), 500

@app.route("/send_message", methods=["POST"])
def send_message():
    """API endpoint to receive and store a new message or file."""
    session_key = request.form.get('session_key', '').strip()
    username = session.get('chat_username')
    expected_session_key = session.get('current_chat_key')
    message_text = request.form.get('message', '').strip()
    file = request.files.get('file')

    print(f"[INFO] Send message attempt: User='{username}', Key Sent='{session_key}', Expected Key='{expected_session_key}'")

    # --- Rigorous Checks ---
    if not username:
         print(f"[WARN] Send failed: User identity not found in session.")
         return jsonify({'success': False, 'message': 'User identity not found in session. Please join first.'}), 401
    if not session_key:
        print(f"[WARN] Send failed: Session key missing in request.")
        return jsonify({'success': False, 'message': 'Session key missing.'}), 400
    if session_key != expected_session_key:
        print(f"[WARN] Send failed: Session key mismatch. Sent='{session_key}', Expected='{expected_session_key}'.")
        return jsonify({'success': False, 'message': 'Session key mismatch or invalid session context.'}), 400
    if session_key not in chat_sessions:
        print(f"[WARN] Send failed: Session key '{session_key}' not found in active chat_sessions.")
        return jsonify({'success': False, 'message': 'Invalid or inactive session key.'}), 400
    if username not in chat_sessions[session_key].get('unlocked_users', set()):
         print(f"[WARN] Send failed: User '{username}' has not unlocked session '{session_key}'.")
         return jsonify({'success': False, 'message': 'Chat not unlocked for this user.'}), 403
    if not message_text and not file:
        print(f"[WARN] Send failed: Empty message and no file provided.")
        return jsonify({'success': False, 'message': 'Cannot send empty message or file.'}), 400
    if message_text and file:
         print(f"[WARN] Send failed: Attempt to send text and file simultaneously.")
         return jsonify({'success': False, 'message': 'Cannot send text and file simultaneously.'}), 400
    # --- End Checks ---

    session_data = chat_sessions[session_key]
    encryption_key = session_data['key']
    timestamp = datetime.utcnow().isoformat() + 'Z' # ISO 8601 format UTC

    try:
        if file:
            if file.filename == '':
                 print(f"[WARN] Send failed: File selected but filename is empty.")
                 return jsonify({'success': False, 'message': 'No file selected or filename empty.'}), 400
            
            # --- File Size Check (Server-side) ---
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            MAX_FILE_SIZE = 16 * 1024 * 1024 # 16 MB limit
            if file_size > MAX_FILE_SIZE:
                print(f"[WARN] Send failed: File '{file.filename}' size ({file_size} bytes) exceeds limit ({MAX_FILE_SIZE} bytes).")
                return jsonify({'success': False, 'message': f'File exceeds {MAX_FILE_SIZE // 1024 // 1024}MB limit.'}), 413
            # --- End File Size Check ---

            file_data = file.read()
            encrypted_data = encrypt_file(file_data, encryption_key)
            
            file_id = secrets.token_hex(16)
            files[file_id] = {
                'filename': file.filename,
                'content_type': file.mimetype or mimetypes.guess_type(file.filename)[0] or 'application/octet-stream',
                'data': encrypted_data
            }
            
            message_entry = {
                'username': username,
                'timestamp': timestamp,
                'type': 'file',
                'file_id': file_id,
                'filename': file.filename
            }
            print(f"[INFO] File '{file.filename}' (ID: {file_id}) received from user '{username}' for session '{session_key}'.")
        else: # Text message
            encrypted_message = encrypt_message(message_text, encryption_key)
            message_entry = {
                'username': username,
                'timestamp': timestamp,
                'type': 'text',
                'content_encrypted': encrypted_message
            }
            print(f"[INFO] Text message received from user '{username}' for session '{session_key}'.")

        if session_key not in messages:
            messages[session_key] = []
        messages[session_key].append(message_entry)
        
        # Optional: Limit message history size per session
        MAX_MESSAGES = 200
        if len(messages[session_key]) > MAX_MESSAGES:
            messages[session_key] = messages[session_key][-MAX_MESSAGES:]

        return jsonify({'success': True})

    except Exception as e:
        print(f"[ERROR] Exception during message/file processing for session '{session_key}': {e}")
        return jsonify({'success': False, 'message': 'Internal server error while processing message/file.'}), 500

@app.route("/get_messages")
def get_messages():
    """API endpoint to retrieve messages for a given session key."""
    session_key = request.args.get('session_key', '').strip()
    username = session.get('chat_username')
    expected_session_key = session.get('current_chat_key')

    # print(f"[DEBUG] Get messages request: User='{username}', Key Sent='{session_key}', Expected Key='{expected_session_key}'")

    # --- Rigorous Checks ---
    if not username:
         # Less verbose for polling
         # print(f"[WARN] Get messages failed: User identity not found in session.")
         return jsonify({'success': False, 'message': 'User identity not found in session.'}), 401
    if not session_key:
        # print(f"[WARN] Get messages failed: Session key missing in request.")
        return jsonify({'success': False, 'message': 'Session key missing.'}), 400
    if session_key != expected_session_key:
        # print(f"[WARN] Get messages failed: Session key mismatch. Sent='{session_key}', Expected='{expected_session_key}'.")
        return jsonify({'success': False, 'message': 'Session key mismatch or invalid session context.'}), 400
    if session_key not in chat_sessions:
        # print(f"[WARN] Get messages failed: Session key '{session_key}' not found in active chat_sessions.")
        return jsonify({'success': False, 'message': 'Invalid or inactive session key.'}), 400
    # Ensure user is unlocked to view messages
    if username not in chat_sessions[session_key].get('unlocked_users', set()):
         # print(f"[WARN] Get messages failed: User '{username}' has not unlocked session '{session_key}'.")
         return jsonify({'success': False, 'message': 'Chat not unlocked for this user.'}), 403
    # --- End Checks ---

    session_data = chat_sessions[session_key]
    decryption_key = session_data['key']
    session_messages = messages.get(session_key, [])
    
    decrypted_messages = []
    for msg in session_messages:
        try:
            if msg['type'] == 'text':
                decrypted_content = decrypt_message(msg['content_encrypted'], decryption_key)
                decrypted_messages.append({
                    'username': msg['username'],
                    'timestamp': msg['timestamp'],
                    'type': 'text',
                    'content': decrypted_content
                })
            elif msg['type'] == 'file':
                # File messages don't need decryption here, just pass info
                 decrypted_messages.append({
                    'username': msg['username'],
                    'timestamp': msg['timestamp'],
                    'type': 'file',
                    'file_id': msg['file_id'],
                    'filename': msg['filename']
                })
        except Exception as e:
            print(f"[ERROR] Failed to process message during get_messages for session '{session_key}': {e} - Message: {msg}")
            # Optionally skip the problematic message or add an error placeholder

    return jsonify({'success': True, 'messages': decrypted_messages})

@app.route("/download_file/<file_id>")
def download_file(file_id):
    """API endpoint to download an encrypted file, decrypting it on the fly."""
    session_key = session.get('current_chat_key') # Get key from user's current session
    username = session.get('chat_username')
    
    print(f"[INFO] File download request: User='{username}', File ID='{file_id}', Session Key='{session_key}'")

    # --- Rigorous Checks ---
    if not username:
         print(f"[WARN] File download failed: User identity not found in session.")
         return "Access denied. User session not found.", 403
    if not session_key:
        print(f"[WARN] File download failed: Session key not found in user session.")
        return "Invalid or inactive session.", 403
    if session_key not in chat_sessions:
        print(f"[WARN] File download failed: Session key '{session_key}' not found in active chat_sessions.")
        return "Invalid or inactive session.", 403
    if username not in chat_sessions[session_key].get('unlocked_users', set()):
        print(f"[WARN] File download failed: User '{username}' has not unlocked session '{session_key}'.")
        return "Access denied. Chat not unlocked.", 403
    if file_id not in files:
        print(f"[WARN] File download failed: File ID '{file_id}' not found.")
        return "File not found.", 404
    # --- End Checks ---

    try:
        file_info = files[file_id]
        decryption_key = chat_sessions[session_key]['key']
        
        decrypted_data = decrypt_file(file_info['data'], decryption_key)
        
        if decrypted_data is None:
            print(f"[ERROR] File download failed: Decryption failed for File ID '{file_id}' in session '{session_key}'.")
            return "File decryption failed.", 500

        print(f"[INFO] Successfully decrypted file '{file_info['filename']}' (ID: {file_id}) for user '{username}'. Sending file.")
        return send_file(
            io.BytesIO(decrypted_data),
            mimetype=file_info['content_type'],
            as_attachment=True,
            download_name=file_info['filename']
        )
    except Exception as e:
        print(f"[ERROR] Exception during file download for File ID '{file_id}': {e}")
        return "Internal server error during file download.", 500

# --- Main Execution ---
if __name__ == "__main__":
    # Use a production-ready server like gunicorn or waitress instead of app.run for deployment
    # Example: gunicorn -w 4 -b 0.0.0.0:5000 stealth_messaging_app_v5:app
    print("--- Stealth Messaging App v5 --- ")
    print("Dependencies: Flask, bcrypt, qrcode[pil], cryptography")
    print("Install using: pip install Flask bcrypt \"qrcode[pil]\" cryptography")
    print("Starting server...")
    print("Access URLs (Example - use actual IP/domain if deployed):")
    # Determine a reachable IP (simple approach, might not work in all network configs)
    host_ip = '127.0.0.1' # Default to localhost
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Connect to external server doesn't send data
        host_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass # Stick with localhost if detection fails
    print(f"  User 'demigod': http://{host_ip}:5000/?user=demigod")
    print(f"  User 'human': http://{host_ip}:5000/?user=human")
    print("---------------------------------")
    # Changed default port to 5001 to reduce conflicts
    app.run(debug=True, host='0.0.0.0', port=5001) # debug=True is NOT for production

