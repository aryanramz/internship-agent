"""Shared bounded private profile reader; never echo private values in errors."""
import json


def read_profile(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    try:
        with open(path, 'rb') as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError, OSError):
        raise ValueError('Invalid ranking configuration') from None
