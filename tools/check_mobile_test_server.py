"""Bounded startup handshake with our synthetic child, no remote access."""
import json
import os
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def main():
    pid = int(sys.argv[1])
    run_id = os.environ['YEOBAEK_TEST_RUN_ID']
    origin = os.environ['EXPO_PUBLIC_TEST_API_URL']
    # This exact loopback probe is local, not an outbound proxy bypass.
    http = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            raise SystemExit('Test API exited. Check the error above; Metro was not started.')
        try:
            with http.open(Request('http://127.0.0.1:8000/__mobile_test__'), timeout=1) as response:
                marker = json.load(response)
            if (marker.get('syntheticOnly') is not True or marker.get('runId') != run_id
                    or marker.get('runnerVersion') != 'codespaces-origin-v2'
                    or marker.get('publicOrigin') != origin):
                raise SystemExit('Port 8000 is serving another runner. Stop its terminal first; Metro was not started.')
            print('Test API ready: codespaces-origin-v2 (new runner confirmed)', flush=True)
            return
        except (URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.2)
    raise SystemExit('Test API did not become ready within 20 seconds; Metro was not started.')


if __name__ == '__main__':
    main()
