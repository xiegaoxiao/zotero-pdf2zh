"""Build and verify the fork's Release assets from Git-tracked sources."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'xiegaoxiao/zotero-pdf2zh'
ADDON_ID = 'pdf2zh@guaguastandup.com'
XPI_NAME = 'zotero-pdf-2-zh.xpi'


def build(output):
    package = json.loads((ROOT / 'plugin/package.json').read_text(encoding='utf8'))
    version = package['version']
    server = (ROOT / 'server/server.py').read_text(encoding='utf8')
    match = re.search(r'^__version__\s*=\s*["\x27]([^"\x27]+)', server, re.M)
    if not match or match[1] != version:
        raise ValueError('Plugin and Server versions must match')
    source_xpi = ROOT / 'plugin/build' / XPI_NAME
    with zipfile.ZipFile(source_xpi) as archive:
        if archive.testzip():
            raise ValueError('Corrupt XPI archive')
        manifest = json.loads(archive.read('manifest.json'))
    addon = manifest['applications']['zotero']
    feed_name = 'update-beta.json' if '-' in version else 'update.json'
    expected_feed = f'https://github.com/{REPOSITORY}/releases/download/release/{feed_name}'
    if manifest['version'] != version or addon['id'] != ADDON_ID:
        raise ValueError('XPI ID/version does not match the source')
    if addon['update_url'] != expected_feed:
        raise ValueError('XPI update URL does not point to the fork feed')
    if manifest['homepage_url'] != package['homepage'] or REPOSITORY not in manifest['homepage_url']:
        raise ValueError('XPI homepage does not point to the fork')

    output.mkdir(parents=True, exist_ok=True)
    xpi = output / XPI_NAME
    shutil.copy2(source_xpi, xpi)
    update = {'addons': {ADDON_ID: {'updates': [{
        'version': version,
        'update_link': f'https://github.com/{REPOSITORY}/releases/download/v{version}/{XPI_NAME}',
        'update_hash': 'sha512:' + hashlib.sha512(xpi.read_bytes()).hexdigest(),
        'applications': {'zotero': {
            key: addon[key] for key in ('strict_min_version', 'strict_max_version')
        }},
    }]}}}
    for name in ('update.json', 'update-beta.json'):
        (output / name).write_text(json.dumps(update, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

    # Use the index as the allowlist: local configs, credentials, caches and
    # virtual environments must never become release assets.
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', 'server'], cwd=ROOT)
    names = sorted(n.decode('utf8') for n in tracked.split(b'\0') if n)
    required = {'server/server.py', 'server/config/config.toml.example',
                'server/update_packages.py', 'server/utils/thinking_control.py',
                'server/utils/task_manager.py', 'server/utils/pdf_layout_repair.py',
                'server/utils/author_filter.py'}
    if not required.issubset(names):
        raise ValueError('Stage all release sources before packaging')
    private = re.compile(r'(^|/)(?:__pycache__|\.venv|tmp|output|translated|zotero-pdf2zh[^/]*venv[^/]*)/|'
                         r'^server/config/(?:config\.(?:json|toml)|venv\.json|package_update_state\.json)$|'
                         r'\.(?:pyc|bak|log|before_zotero_layout_repair)$')
    forbidden = [n for n in names if private.search(n)]
    if forbidden:
        raise ValueError('Private/runtime files are tracked: ' + ', '.join(forbidden))
    server_zip = output / 'server.zip'
    with zipfile.ZipFile(server_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, name)
        for name in ('LICENSE', 'FORK_NOTES.md'):
            archive.write(ROOT / name, name)
    with zipfile.ZipFile(server_zip) as archive:
        if archive.testzip() or not required.issubset(archive.namelist()):
            raise ValueError('Invalid Server archive')

    assets = [xpi, server_zip, output / 'update.json', output / 'update-beta.json']
    checksums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets)
    (output / 'SHA256SUMS').write_text(checksums, encoding='utf8')
    print(f'Validated v{version} for {REPOSITORY}: {len(names)} Server files')
    print(output.resolve())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/release')
    build(parser.parse_args().output)
