"""Validate one explicit token-bound guest barrier record."""
import json

def parse_phase(line, phase, token):
    try: record=json.loads(line)
    except (ValueError, TypeError) as exc: raise ValueError('invalid JSON') from exc
    if not isinstance(record,dict) or record.get('phase')!=phase or record.get('token')!=token:
        raise ValueError('phase or token mismatch')
    for key in ('pid','ppid','pgid','sid','result','errno'):
        if type(record.get(key)) is not int: raise ValueError('non-integer '+key)
    if any(record[key]<=0 for key in ('pid','pgid','sid')) or record['ppid']<0:
        raise ValueError('invalid identity')
    return record
