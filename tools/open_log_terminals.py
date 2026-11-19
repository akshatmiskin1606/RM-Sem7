"""Open separate Konsole windows that follow the local web and model logs."""

import argparse
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def open_log(title, log):
    log.touch(mode=0o600, exist_ok=True)
    terminals = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'konsole'],
                               capture_output=True, text=True).stdout.split()
    for pid in terminals:
        try:
            arguments = (Path('/proc') / pid / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if os.fsencode(log) in arguments:
            print(f'{title} is already open in Konsole (PID {pid}).')
            return

    process = subprocess.Popen(
        ['konsole', '--separate', '--workdir', str(ROOT), '-p', f'LocalTabTitleFormat={title}',
         '-e', 'tail', '-n', '30', '-F', str(log)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        process.wait(timeout=0.75)
    except subprocess.TimeoutExpired:
        print(f'Opened {title} in Konsole (PID {process.pid}).')
    else:
        raise SystemExit(f'Konsole exited while opening {title} (status {process.returncode}).')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765, help='Port of the background KAQG workspace')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535.')
    runtime = ROOT / '.kaqg-runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    open_log('KAQG Backend', runtime / f'web-{args.port}.log')
    open_log('Qwen Model', runtime / 'ollama.log')


if __name__ == '__main__':
    main()
