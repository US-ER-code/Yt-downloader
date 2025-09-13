# app.py
import os
import io
import tempfile
from typing import List, Dict, Tuple, Optional

import streamlit as st
from yt_dlp import YoutubeDL


# -------- Helpers --------
def get_video_info(url: str) -> Dict:
    ydl_opts = {"quiet": True, "skip_download": True}
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def list_available_resolutions(info: Dict) -> List[int]:
    # Collect unique video heights (exclude audio-only)
    heights = set()
    for f in info.get("formats", []):
        if f.get("vcodec") != "none" and f.get("height"):
            heights.add(int(f["height"]))
    return sorted(heights, reverse=True)


def list_audio_formats(info: Dict) -> List[Tuple[str, Optional[int]]]:
    # Return list of (ext, abr) for audio-only formats
    audio = []
    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none"):
            abr = f.get("abr")
            ext = f.get("ext") or "m4a"
            audio.append((ext, int(abr) if abr else None))
    # Deduplicate by (ext, abr) and sort by abr desc then ext
    audio = list({(a, b) for (a, b) in audio})
    audio.sort(key=lambda x: (x[1] or 0), reverse=True)
    return audio


def detect_mime_from_ext(ext: str) -> str:
    mapping = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mkv": "video/x-matroska",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
        "opus": "audio/ogg",
        "wav": "audio/wav",
    }
    return mapping.get(ext.lower(), "application/octet-stream")


def read_first_file_by_prefix(folder: str, prefix: str = "output.") -> Tuple[bytes, str, str]:
    # Finds the first file starting with prefix in folder, returns (bytes, filename, mime)
    for name in os.listdir(folder):
        if name.startswith(prefix):
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                data = f.read()
            ext = name.split(".")[-1]
            return data, name, detect_mime_from_ext(ext)
    raise FileNotFoundError("Downloaded file not found.")


# -------- Downloaders --------
def download_video(url: str, height: Optional[int]) -> Tuple[bytes, str, str]:
    """
    Downloads selected video height merged with best audio.
    Uses ffmpeg under the hood (must be installed).
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Build a flexible format selector.
        # Try exact height; fallback to best if not available.
        if height:
            format_selector = f"bestvideo[height={height}]+bestaudio/best[height={height}]/best"
        else:
            format_selector = "bestvideo+bestaudio/best"

        ydl_opts = {
            "format": format_selector,
            "outtmpl": os.path.join(tmp, "output.%(ext)s"),
            "merge_output_format": "mp4",  # Ensures unified container
            "quiet": True,
            "postprocessor_args": [],
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        data, filename, mime = read_first_file_by_prefix(tmp, "output.")
        return data, filename, mime


def download_audio(
    url: str,
    target_codec: str = "m4a",
    target_quality_kbps: Optional[int] = None,
) -> Tuple[bytes, str, str]:
    """
    Downloads best audio and extracts to target codec using ffmpeg.
    target_codec: mp3 | m4a | aac | opus | wav
    target_quality_kbps: 64-320 for most codecs (yt-dlp passes as ffmpeg quality hints)
    """
    with tempfile.TemporaryDirectory() as tmp:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp, "output.%(ext)s"),
            "quiet": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": target_codec,
                    "preferredquality": str(target_quality_kbps or 192),
                }
            ],
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        data, filename, mime = read_first_file_by_prefix(tmp, "output.")
        return data, filename, mime


# -------- UI --------
st.set_page_config(page_title="YouTube Downloader", page_icon="⬇️", layout="centered")

st.title("⬇️ YouTube Downloader")
st.caption("Minimal, fast, and clean — powered by yt-dlp + Streamlit")

url = st.text_input("Enter YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
choice = st.radio("Download type", options=["Video", "Audio"], horizontal=True)

info = None
if url:
    try:
        info = get_video_info(url)
    except Exception as e:
        st.error(f"Failed to fetch video info: {e}")

if info:
    st.write(f"**Title**: {info.get('title', 'Unknown')}")

    if choice == "Video":
        # Resolutions
        heights = list_available_resolutions(info)
        height_labels = ["Best available"] + [f"{h}p" for h in heights]
        sel_label = st.selectbox("Choose resolution", options=height_labels, index=0)
        sel_height = None if sel_label == "Best available" else int(sel_label.replace("p", ""))

        if st.button("Download Video"):
            with st.spinner("Downloading video..."):
                try:
                    data, filename, mime = download_video(url, sel_height)
                    st.success("Video ready!")
                    st.download_button(
                        label=f"Save {filename}",
                        data=data,
                        file_name=filename,
                        mime=mime,
                    )
                except Exception as e:
                    st.error(f"Download failed: {e}")

    elif choice == "Audio":
        # Audio formats and quality
        audio_formats = list_audio_formats(info)
        default_codec = "m4a"
        codecs = sorted({ext for ext, _ in audio_formats} | {"mp3", "m4a"})
        sel_codec = st.selectbox("Audio format", options=codecs, index=codecs.index(default_codec) if default_codec in codecs else 0)

        # Offer common quality options
        quality_options = [320, 256, 192, 160, 128, 96, 64]
        sel_quality = st.select_slider("Target bitrate (kbps)", options=quality_options, value=192)

        if st.button("Download Audio"):
            with st.spinner("Downloading audio..."):
                try:
                    data, filename, mime = download_audio(url, target_codec=sel_codec, target_quality_kbps=sel_quality)
                    st.success("Audio ready!")
                    st.download_button(
                        label=f"Save {filename}",
                        data=data,
                        file_name=filename,
                        mime=mime,
                    )
                except Exception as e:
                    st.error(f"Download failed: {e}")

# Footer note
st.caption("Note: Requires FFmpeg installed and in PATH for merging and audio extraction.")