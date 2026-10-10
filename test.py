# import os, requests
# from dotenv import load_dotenv
# load_dotenv()
# r = requests.get("https://api.groq.com/openai/v1/models",
#                  headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
# print([m["id"] for m in r.json()["data"]])


import os, time
from dotenv import load_dotenv
from openai import OpenAI
from llm_input import build_llm_input
from analyze import SYSTEM
import json

load_dotenv()
g = OpenAI(base_url="https://api.groq.com/openai/v1",
           api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=60)
data, _ = build_llm_input(0.05, 1000)

for model in ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]:
    t = time.time()
    try:
        r = g.chat.completions.create(
            model=model, max_tokens=5000,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
        )
        print(model, f"{time.time()-t:.1f}s", "in", r.usage.prompt_tokens,
              "out", r.usage.completion_tokens, r.choices[0].finish_reason)
        print((r.choices[0].message.content or "")[:300], "\n")
    except Exception as e:
        print(model, "ERR", getattr(e, "body", e), "\n")