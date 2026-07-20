import hashlib
import random
import string
import json
import urllib.request
import urllib.parse
from urllib.error import URLError, HTTPError
from app.core.logging import logger

def _generate_salt(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def _build_auth_params(username, password):
    salt = _generate_salt()
    token = hashlib.md5((password + salt).encode('utf-8')).hexdigest()
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "Harmony",
        "f": "json"
    }

def _build_auth_params_from_token(username, token, salt):
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "Harmony",
        "f": "json"
    }

def _make_request(url, endpoint, params):
    try:
        url = url.rstrip('/')
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}/rest/{endpoint}?{query_string}"

        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("subsonic-response", {})
    except HTTPError as e:
        logger.error(f"HTTPError connecting to Subsonic API: {e.code} - {e.reason}")
        return {"status": "failed", "error": {"message": f"HTTP Error {e.code}: {e.reason}"}}
    except URLError as e:
        logger.error(f"URLError connecting to Subsonic API: {e.reason}")
        return {"status": "failed", "error": {"message": f"Connection Error: {e.reason}"}}
    except Exception as e:
        logger.error(f"Unknown error connecting to Subsonic API: {e}")
        return {"status": "failed", "error": {"message": str(e)}}

def ping(url, username, password=None, token=None, salt=None):
    if password is not None:
        params = _build_auth_params(username, password)
    elif token is not None and salt is not None:
        params = _build_auth_params_from_token(username, token, salt)
    else:
        return False, "Missing credentials", {}

    response = _make_request(url, "ping.view", params)

    if response.get("status") == "ok":
        return True, "Connection successful", params
    return False, response.get("error", {}).get("message", "Unknown error"), params

def get_server_info(url, username, password=None, token=None, salt=None):
    if password is not None:
        params = _build_auth_params(username, password)
    elif token is not None and salt is not None:
        params = _build_auth_params_from_token(username, token, salt)
    else:
        return {"status": "failed", "error": "Missing credentials"}

    response = _make_request(url, "ping.view", params) # ping also returns version
    return response

def trigger_scan(url, username, password=None, token=None, salt=None):
    if password is not None:
        params = _build_auth_params(username, password)
    elif token is not None and salt is not None:
        params = _build_auth_params_from_token(username, token, salt)
    else:
        return False

    params["fullScan"] = "false"
    response = _make_request(url, "startScan.view", params)
    return response.get("status") == "ok"

def get_scan_status(url, username, password=None, token=None, salt=None):
    if password is not None:
        params = _build_auth_params(username, password)
    elif token is not None and salt is not None:
        params = _build_auth_params_from_token(username, token, salt)
    else:
        return None

    response = _make_request(url, "getScanStatus.view", params)
    return response.get("scanStatus", {})
