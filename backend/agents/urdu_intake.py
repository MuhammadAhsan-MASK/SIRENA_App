import os
import json
import google.generativeai as genai
from typing import Optional, Dict, Any

class UrduIntakeAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            # Fallback to general env or raise warning
            api_key = os.getenv("GOOGLE_API_KEY")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
        self.system_instruction = """
        You are the SIRENA Intake Agent. You handle crisis reports from citizens.
        Input may be Roman Urdu, English, or mixed.
        
        Roman Urdu Dictionary:
        paani=water, aag=fire, hadsa=accident, bijli gayi=power outage,
        baadh/selaab=flood, rasta band=road blocked, garmi/lu=heatwave, madad=help
        
        Strict workflow:
        1. Analyze the user text.
        2. Identify: 
           - Crisis Type (Flood, Heatwave, Accident, Road Blockage, Power Outage)
           - Location (City and Zone if mentioned)
           - Severity (High, Medium, Low)
        3. Determine if the information is sufficient to trigger a response.
        4. If vague (e.g. "it's hot" without city, or "water everywhere" without location), ask a SHORT clarifying question in the same language style.
        5. If clear, output a structured JSON and state you are initiating response.

        Output Format (JSON):
        {
          "thought": "Internal reasoning about the report",
          "resolved": true/false,
          "clarification_question": "string or null",
          "extracted_info": {
            "city": "Islamabad/Karachi/null",
            "zone": "string or null",
            "crisis_type": "string or null",
            "severity": "high/medium/low"
          },
          "response": "User-facing message"
        }
        """

    async def process_chat(self, message: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        prompt = f"{self.system_instruction}\n\nUser Message: {message}\nContext: {json.dumps(context or {})}\n\nOutput JSON:"
        
        try:
            response = self.model.generate_content(prompt)
            # Find the JSON part in the response
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "{" in text:
                text = text[text.find("{"):text.rfind("}")+1]
            
            result = json.loads(text.strip())
            return result
        except Exception as e:
            print(f"Intake Agent Error: {e}")
            return {
                "thought": f"Error processing: {str(e)}",
                "resolved": False,
                "clarification_question": "Guzarish hai ke apna masla dobara batayein? (Please say that again?)",
                "extracted_info": {},
                "response": "Maaf kijiye, system mein masla hai. (Sorry, there is a system error.)"
            }

intake_agent = UrduIntakeAgent()
