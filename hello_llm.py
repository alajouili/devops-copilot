import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1")

MODEL = "openai/gpt-oss-120b"

response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": "Tu es un professeur DevOps. Réponds en 3 phrases maximum, en français."},
        {"role": "user", "content": "Qu'est-ce que Kubernetes ?"},
    ],
    temperature=0.7,
)

print(response.choices[0].message.content)
print("Tokens utilisés :", response.usage.total_tokens)