import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(dotenv_path="ciro/.env")
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)

print("Flash/Pro models found:")
try:
    for m in genai.list_models():
        name = m.name
        if 'generateContent' in m.supported_generation_methods:
            if 'flash' in name.lower() or 'pro' in name.lower():
                print(f" - {name}")
except Exception as e:
    print(f"Error: {e}")
