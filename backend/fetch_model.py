"""Download an explicitly configured checkpoint and verify its SHA-256."""
import argparse
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import urlparse
import requests


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_model(url, expected_sha, destination):
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha):
        raise ValueError('R34_MODEL_SHA256 must be an exact 64-character SHA-256.')
    expected_sha = expected_sha.lower()
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('R34_MODEL_URL must be an HTTPS download URL without embedded credentials.')
    destination = Path(destination)
    if destination.exists() and sha256(destination) == expected_sha:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + '.part')
    try:
        response = requests.get(url, stream=True, timeout=(15, 180))
        response.raise_for_status()
        if urlparse(response.url).scheme != 'https':
            raise ValueError('The model download redirected to a non-HTTPS address.')
        digest, size = hashlib.sha256(), 0
        with part.open('wb') as stream:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > 512 * 1024 * 1024:
                    raise ValueError('Checkpoint exceeds the 512 MiB download limit.')
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest() != expected_sha:
            raise ValueError('Checkpoint SHA-256 mismatch. The existing model was not replaced.')
        part.replace(destination)
    except requests.RequestException:
        raise RuntimeError('Model download failed. Check the published Release asset and R34_MODEL_URL.') from None
    finally:
        part.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.models/model.pth'))
    args = parser.parse_args()
    try:
        path = fetch_model(os.environ.get('R34_MODEL_URL', ''), os.environ.get('R34_MODEL_SHA256', ''), args.output)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Checkpoint verified: {path.name}')


if __name__ == '__main__':
    main()
