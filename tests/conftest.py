import shutil
from pathlib import Path

import pytest

from videopip import ff


def make_clip(path: Path, seconds: float = 16.0, hue: int = 0, size: str = "1280x720"):
    """Synthetic product clip: 2s static 'logo card', moving footage, 2s static end card."""
    body = seconds - 4
    ff.run([
        "-y",
        "-f", "lavfi", "-i", f"color=c=0x202060:s={size}:d=2:r=30",
        "-f", "lavfi", "-i", f"testsrc2=s={size}:d={body}:r=30",
        "-f", "lavfi", "-i", f"color=c=0x602020:s={size}:d=2:r=30",
        "-f", "lavfi", "-i", f"sine=f={300 + hue * 50}:d={seconds}:sample_rate=48000",
        "-filter_complex",
        f"[1:v]hue=h={hue * 60}[b];[0:v][b][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-t", seconds,
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    ])
    return path


@pytest.fixture(scope="session")
def clips_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    for i in range(1, 4):
        make_clip(d / f"{i}.mp4", 16.0, i)
    return d


@pytest.fixture()
def project_dir(tmp_path, clips_dir, monkeypatch):
    monkeypatch.setenv("VIDEOPIP_CACHE", str(tmp_path / "tts-cache"))
    shutil.copytree(clips_dir, tmp_path / "clips")
    return tmp_path
