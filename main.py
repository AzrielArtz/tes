import os
import aiofiles
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import socketio

# Define the storage directory
VIDEO_DIR = "static_videos"
os.makedirs(VIDEO_DIR, exist_ok=True)

# Initialize FastAPI and Socket.IO
# cors_allowed_origins='*' allows any device to connect
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI(title="Local Sync Cinema")

# Wrap FastAPI with the Socket.IO ASGI app
app.mount("/ws", socketio.ASGIApp(sio))

# Mount the static directory. FastAPI's StaticFiles automatically handles 
# 'Accept-Ranges' requests, enabling HTML5 video seeking out-of-the-box.
app.mount("/videos", StaticFiles(directory=VIDEO_DIR), name="videos")

@app.get("/")
async def get_index():
    """Serve the single-file frontend."""
    if not os.path.exists("index.html"):
        raise HTTPException(status_code=404, detail="index.html not found.")
    return FileResponse("index.html")

@app.get("/videos_list")
async def get_videos_list():
    """Scan the directory and return a list of available MP4 videos."""
    videos = [f for f in os.listdir(VIDEO_DIR) if f.endswith('.mp4')]
    videos.sort()
    return {"videos": videos}

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Handle video uploads asynchronously. 
    Uses chunking to ensure low RAM usage.
    """
    if not file.filename.endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Only .mp4 files are supported.")

    file_path = os.path.join(VIDEO_DIR, file.filename)
    
    # Save the file asynchronously in 1MB chunks
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # 1MB chunk
                await out_file.write(content)
                
        # Notify all connected clients that the video list has changed
        await sio.emit('video_list_updated')
        return {"message": "Upload successful", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- WebSockets / Real-Time Sync Logic ---

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.event
async def client_event(sid, data):
    """
    Receives an event (play, pause, seek) from one client 
    and broadcasts it to all OTHER clients to keep them in sync.
    """
    action = data.get('action')
    time = data.get('time')
    print(f"Sync event from {sid}: {action} at {time}s")
    
    # Broadcast to everyone EXCEPT the sender to prevent echo loops
    await sio.emit('sync_event', data, skip_sid=sid)

@sio.event
async def change_video(sid, data):
    """
    Receives a request to change the video and broadcasts it to everyone.
    """
    filename = data.get('filename')
    print(f"Client {sid} changed video to: {filename}")
    # Broadcast to ALL clients (including sender so they start loading it too)
    await sio.emit('load_video', {'filename': filename})

# To ensure ASGI routing works gracefully with uvicorn
app = socketio.ASGIApp(sio, other_asgi_app=app)
      
