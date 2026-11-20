"""Storage and process locks for successful synthesized clips."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

def is_cached_clip(path):
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size == 0)):
        raise ValueError("Invalid cached speech clip")
    return path.is_file()


@contextmanager
def speech_clip_lock(path, timeout=300):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    if lock_path.is_symlink():
        raise ValueError("Invalid speech cache lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(lock_path, flags, 0o600), "r+b") as lock:
        if os.name == "nt":
            import msvcrt

            def acquire():
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for cached speech synthesis") from error
                time.sleep(0.1)
        yield


def publish_cached_clip(source, destination):
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".arrumo-speech-") as directory:
        pending = Path(directory) / "clip.wav"
        shutil.copyfile(source, pending)
        with pending.open("r+b") as stream:
            os.fsync(stream.fileno())
        try:
            destination.hardlink_to(pending)
        except FileExistsError:
            if not is_cached_clip(destination):
                raise


def reuse_cached_clip(source, destination):
    shutil.copyfile(source, destination)
    os.utime(source, None, follow_symlinks=False)


def prune_cached_clips(cache, *, max_age_days=None, max_bytes=None, dry_run=False):
    if cache.is_symlink() or (cache.exists() and not cache.is_dir()):
        raise ValueError("Speech cache must be a local directory")
    entries = []
    for path in cache.glob("*.wav"):
        if re.fullmatch(r"[0-9a-f]{64}\.wav", path.name) and not path.is_symlink() and path.is_file():
            try:
                info = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            entries.append((info.st_mtime_ns, path, info.st_size))
    remaining = sum(size for _, _, size in entries)
    expiry = None if max_age_days is None else time.time_ns() - max_age_days * 86_400_000_000_000
    removed = skipped = reclaimed = 0
    for accessed, path, size in sorted(entries):
        expired = expiry is not None and accessed <= expiry
        if not expired and (max_bytes is None or remaining <= max_bytes):
            continue
        if not dry_run:
            try:
                with speech_clip_lock(path, timeout=0):
                    if path.is_symlink():
                        skipped += 1
                        continue
                    current = path.stat(follow_symlinks=False)
                    if (current.st_mtime_ns, current.st_size) != (accessed, size):
                        skipped += 1
                        continue
                    path.unlink()
            except TimeoutError:
                skipped += 1
                continue
            except FileNotFoundError:
                remaining -= size
                continue
        removed += 1
        reclaimed += size
        remaining -= size
    return {
        "dryRun": dry_run,
        "clipsSelected": removed,
        "bytesSelected": reclaimed,
        "remainingBytes": remaining,
        "clipsSkipped": skipped,
    }
