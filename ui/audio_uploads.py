"""Disk-backed recording uploads; enforce limits while bytes arrive."""
from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile


class UploadProblem(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


async def receive_recording(request, limit: int, suffix: str = ".media") -> Path:
    length = request.headers.get("content-length")
    if length:
        try:
            declared = int(length)
        except ValueError:
            raise UploadProblem("The upload length is invalid.")
        if declared < 0:
            raise UploadProblem("The upload length is invalid.")
        if declared > limit:
            raise UploadProblem(f"This recording exceeds the {limit // (1024 * 1024):,} MB upload limit. Change it in Settings.", 413)
    handle = tempfile.NamedTemporaryFile(prefix="skate-upload-", suffix=suffix, delete=False)
    path = Path(handle.name)
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise UploadProblem(f"This recording exceeds the {limit // (1024 * 1024):,} MB upload limit. Change it in Settings.", 413)
            if shutil.disk_usage(path.parent).free < len(chunk) + 64 * 1024 * 1024:
                raise UploadProblem("There is not enough free temporary disk space for this recording.", 507)
            await asyncio.to_thread(handle.write, chunk)
        if total == 0:
            raise UploadProblem("The recording file was empty.")
        if length and total != declared:
            raise UploadProblem("The recording upload was incomplete. Please upload the file again.")
        handle.close()
        return path
    except BaseException:
        handle.close()
        path.unlink(missing_ok=True)
        raise


def audio_sections(source: Path, directory: Path, seconds: int = 600):
    """Decode locally into ten-minute WAV sections using bounded PyAV frames.

    Each section is consumed and deleted before the next is decoded, keeping
    Whisper's decoded waveform bounded even for multi-hour video files.
    """
    import av
    import wave

    rate = 16000
    max_frames = seconds * rate
    section = None
    path = directory / "section.wav"
    frames = 0
    offset = 0.0
    try:
        with av.open(str(source)) as container:
            streams = list(container.streams.audio)
            if not streams:
                raise ValueError("The recording has no audio track.")
            duration = float(container.duration or 0) / av.time_base
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)

            def resampled_frames():
                for frame in container.decode(streams[0]):
                    yield from resampler.resample(frame)
                yield from resampler.resample(None)

            for frame in resampled_frames():
                pcm = frame.to_ndarray().tobytes()
                while pcm:
                    if section is None:
                        section = wave.open(str(path), "wb")
                        section.setnchannels(1)
                        section.setsampwidth(2)
                        section.setframerate(rate)
                    take = min(len(pcm), (max_frames - frames) * 2)
                    section.writeframesraw(pcm[:take])
                    pcm = pcm[take:]
                    frames += take // 2
                    if frames == max_frames:
                        section.close()
                        section = None
                        yield path, offset, duration
                        path.unlink(missing_ok=True)
                        offset += frames / rate
                        frames = 0
            if section is not None:
                section.close()
                section = None
                yield path, offset, max(duration, offset + frames / rate)
    finally:
        if section is not None:
            section.close()
        path.unlink(missing_ok=True)
