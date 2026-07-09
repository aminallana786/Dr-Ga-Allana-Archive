import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from deep_translator import GoogleTranslator
from aksharamukha import transliterate
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

app = Flask(_name_)
CORS(app)

# --- Firebase Admin init ---
# Expects GOOGLE_APPLICATION_CREDENTIALS env var to point to your service
# account JSON, or that Application Default Credentials are available
# (e.g. configured on Render/GCP another way).
if not firebase_admin._apps:
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()


def verify_token(auth_header):
    """Verify a Firebase ID token from an Authorization header.
    Returns the decoded token dict, or None if invalid/missing."""
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    id_token = auth_header.split(' ', 1)[1]
    try:
        return firebase_auth.verify_id_token(id_token)
    except Exception:
        return None


@app.route('/api/translate', methods=['POST'])
def translate_api():
    decoded_token = verify_token(request.headers.get('Authorization'))
    if not decoded_token:
        return jsonify({"error": "Unauthorized. Please register or log in first."}), 401

    data = request.json or {}
    source_text = data.get('text', '')

    if not source_text.strip():
        return jsonify({"error": "No text provided"}), 400

    result = {}
    errors = {}

    def safe_translate(key, target):
        try:
            result[key] = GoogleTranslator(source='auto', target=target).translate(source_text)
        except Exception as e:
            errors[key] = str(e)
            result[key] = None

    try:
        # 1. Base Translations (Auto-Detect Source)
        safe_translate('English', 'en')
        safe_translate('Urdu', 'ur')
        safe_translate('Gujarati', 'gu')
        safe_translate('Sindhi_Arabic', 'sd')
        safe_translate('Hindi', 'hi')
        safe_translate('Pashto', 'ps')
        safe_translate('Punjabi_Gurmukhi', 'pa')

        # Balochi is not a supported Google Translate code. There is no
        # reliable free MT engine for Balochi at the time of writing, so we
        # surface that clearly rather than silently failing or faking it.
        result['Balochi'] = None
        errors['Balochi'] = "Balochi is not currently supported by the translation engine."

        # 2. Advanced Script Mapping & Transliteration
        # Punjabi Shahmukhi (Gurmukhi -> Shahmukhi)
        if result.get('Punjabi_Gurmukhi'):
            try:
                result['Punjabi_Shahmukhi'] = transliterate.process(
                    'Gurmukhi', 'Shahmukhi', result['Punjabi_Gurmukhi']
                )
            except Exception as e:
                errors['Punjabi_Shahmukhi'] = str(e)
                result['Punjabi_Shahmukhi'] = None
        else:
            result['Punjabi_Shahmukhi'] = None

        # Khojki Mapping (via Hindi/Devanagari base of the Sindhi text)
        if result.get('Sindhi_Arabic'):
            try:
                sindhi_devanagari = GoogleTranslator(source='auto', target='hi').translate(
                    result['Sindhi_Arabic']
                )
                result['Khojki'] = transliterate.process('Devanagari', 'Khojki', sindhi_devanagari)
            except Exception as e:
                errors['Khojki'] = str(e)
                result['Khojki'] = None
        else:
            result['Khojki'] = None

        # Roman Sindhi Mapping (Arabic-script Urdu/Sindhi -> ISO 15919 romanization)
        # NOTE: original code used 'PersoArabic' -> 'Iso15919', which are not
        # valid Aksharamukha script identifiers and silently no-op. Correct
        # names are 'Urdu' and 'ISO'.
        if result.get('Sindhi_Arabic'):
            try:
                roman_sindhi = transliterate.process('Urdu', 'ISO', result['Sindhi_Arabic'])
                roman_sindhi = (
                    roman_sindhi.replace('ā', 'a').replace('ī', 'i').replace('ū', 'u')
                )
                result['Roman_Sindhi'] = roman_sindhi.capitalize()
            except Exception as e:
                errors['Roman_Sindhi'] = str(e)
                result['Roman_Sindhi'] = None
        else:
            result['Roman_Sindhi'] = None

        response_body = dict(result)
        if errors:
            response_body['_errors'] = errors

        return jsonify(response_body)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if _name_ == '_main_':
    app.run(debug=True, port=5000)