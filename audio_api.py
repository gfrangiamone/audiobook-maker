import io
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from pydub import AudioSegment

app = FastAPI(title="Audio Processing API", version="1.0.0")

@app.get("/health")
async def health():
    """Endpoint di healthcheck."""
    return {"status": "ok"}

@app.post("/audio/info")
async def audio_info(file: UploadFile = File(...)):
    """Restituisce i metadati del file audio caricato."""
    try:
        audio = AudioSegment.from_file(file.file)
        return {
            "filename": file.filename,
            "duration_seconds": len(audio) / 1000.0,
            "channels": audio.channels,
            "sample_width": audio.sample_width,
            "frame_rate": audio.frame_rate,
            "frame_width": audio.frame_width,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file audio: {str(e)}")

@app.post("/audio/convert")
async def convert_audio(
    file: UploadFile = File(...),
    target_format: str = Form("mp3")
):
    """Converte un file audio nel formato specificato."""
    try:
        audio = AudioSegment.from_file(file.file)
        
        # Utilizziamo un file temporaneo per l'esportazione
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{target_format}") as tmp:
            tmp_path = tmp.name
            
        audio.export(tmp_path, format=target_format)
        
        def iterfile():
            with open(tmp_path, "rb") as f:
                yield from f
            os.unlink(tmp_path)
            
        return StreamingResponse(iterfile(), media_type=f"audio/{target_format}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore durante la conversione: {str(e)}")

@app.post("/audio/trim")
async def trim_audio(
    file: UploadFile = File(...),
    start_ms: int = Form(0),
    end_ms: int = Form(None)
):
    """Ritaglia un file audio tra start_ms ed end_ms."""
    try:
        audio = AudioSegment.from_file(file.file)
        
        if end_ms is None:
            end_ms = len(audio)
            
        if start_ms < 0 or end_ms > len(audio) or start_ms >= end_ms:
            raise HTTPException(status_code=400, detail="Intervalli di tempo non validi.")
            
        trimmed_audio = audio[start_ms:end_ms]
        
        # Esportiamo in un buffer in memoria per evitare I/O su disco
        buffer = io.BytesIO()
        trimmed_audio.export(buffer, format="wav")
        buffer.seek(0)
        
        return StreamingResponse(buffer, media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore durante il ritaglio: {str(e)}")
