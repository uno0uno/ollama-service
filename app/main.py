import os
import json
import httpx
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional

from auth import require_auth, get_pool, close_pool

app = FastAPI(title="Ollama Extract API")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:1.5b")


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
    """Extrae datos de un texto y devuelve JSON estructurado.

    Uses Ollama's native structured outputs (format parameter) to guarantee
    valid JSON matching the provided schema at the token/grammar level.
    """
    prompt = f"""{req.instructions}

Ahora extrae los datos del siguiente texto OCR:
\"\"\"
{req.text}
\"\"\""""

    result = await _chat_structured(
        message=prompt,
        system="Eres un extractor de datos de facturas. Responde SOLO con JSON válido.",
        format_schema=req.schema_json,
    )

    try:
        parsed = json.loads(result)
        return {"success": True, "data": parsed, "tenant_id": auth["tenant_id"]}
    except json.JSONDecodeError:
        # Fallback: try to find JSON in the response
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


async def _chat_structured(message: str, system: str = "", format_schema: dict = None) -> str:
    """Call Ollama native API with structured output (format parameter).

    The format parameter forces the model to generate tokens that match
    the JSON Schema grammar, making invalid JSON impossible.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0,
        },
    }

    # Add format parameter for grammar-constrained JSON generation
    if format_schema:
        payload["format"] = format_schema

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
            )
            res.raise_for_status()
            data = res.json()
            return data["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error: {str(e)}")


async def _chat(message: str, system: str = "") -> str:
    """Call Ollama for free-form chat (no structured output)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                    },
                },
            )
            res.raise_for_status()
            data = res.json()
            return data["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error: {str(e)}")
