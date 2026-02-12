import os
import json
import httpx
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel

from auth import require_auth, get_pool, close_pool

app = FastAPI(title="Ollama Extract API")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:0.5b")


class ExtractRequest(BaseModel):
    text: str
    schema_json: dict
    instructions: str = ""


class ChatRequest(BaseModel):
    message: str
    system: str = ""


@app.on_event("startup")
async def startup():
    """Descarga el modelo e inicializa DB pool."""
    await get_pool()
    async with httpx.AsyncClient(timeout=600) as client:
        try:
            res = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": MODEL_NAME, "stream": False},
            )
            print(f"Modelo {MODEL_NAME}: {res.status_code}")
        except Exception as e:
            print(f"Error descargando modelo: {e}")


@app.on_event("shutdown")
async def shutdown():
    await close_pool()


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/extract")
async def extract(req: ExtractRequest, auth: dict = Depends(require_auth)):
    """Extrae datos de un texto y devuelve JSON estructurado."""
    prompt = f"""Extrae la información del siguiente texto y responde SOLO con un objeto JSON válido, sin explicaciones ni texto adicional.

Schema esperado:
{json.dumps(req.schema_json, ensure_ascii=False, indent=2)}

{f"Instrucciones adicionales: {req.instructions}" if req.instructions else ""}

Texto:
\"\"\"
{req.text}
\"\"\""""

    result = await _chat(prompt, "Eres un extractor de datos. Solo respondes con JSON válido.")

    try:
        parsed = json.loads(result)
        return {"success": True, "data": parsed, "tenant_id": auth["tenant_id"]}
    except json.JSONDecodeError:
        start = result.find("{")
        end = result.rfind("}") + 1
        if start != -1 and end > start:
            try:
                parsed = json.loads(result[start:end])
                return {"success": True, "data": parsed, "tenant_id": auth["tenant_id"]}
            except json.JSONDecodeError:
                pass
        return {"success": False, "data": None, "raw": result}


@app.post("/chat")
async def chat(req: ChatRequest, auth: dict = Depends(require_auth)):
    """Chat libre con el modelo."""
    result = await _chat(req.message, req.system)
    return {"response": result, "tenant_id": auth["tenant_id"]}


async def _chat(message: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            res = await client.post(
                f"{OLLAMA_URL}/v1/chat/completions",
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.1,
                },
            )
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error: {str(e)}")
