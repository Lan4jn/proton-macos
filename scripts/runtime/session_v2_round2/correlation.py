"""Conservative correlation for a uniquely shaped, barrier-held host tree."""

def evaluate(owner, pre, post, token, pre_token, post_token):
    def unknown(reason): return {'status': 'UNKNOWN', 'reason': reason}
    if not token or pre_token != token or post_token != token:
        return unknown('token mismatch')
    def tree(rows):
        by_pid = {r['pid']: r for r in rows}
        if len(by_pid) != len(rows): return None
        leader = by_pid.get(owner['pid'])
        if not leader or leader['identity'] != owner['identity'] or leader['pgid'] != owner['pgid']: return None
        descendants = {owner['pid']}
        while True:
            found = {r['pid'] for r in rows if r['ppid'] in descendants} - descendants
            if not found: break
            descendants |= found
        return {pid: by_pid[pid] for pid in descendants}
    a, b = tree(pre), tree(post)
    if a is None or b is None or len(a) < 3 or len(b) < 3: return unknown('leader or child missing')
    if len(a) != 3 or set(a) != set(b): return unknown('ambiguous or changed tree')
    for pid in a:
        if a[pid]['identity'] != b[pid]['identity'] or a[pid]['ppid'] != b[pid]['ppid']:
            return unknown('identity or parent changed')
        if a[pid]['pgid'] != owner['pgid'] or b[pid]['pgid'] != owner['pgid']:
            return {'status': 'FAIL', 'reason': 'observed group mismatch'}
    children = [r for r in a.values() if r['pid'] != owner['pid']]
    if not any(r['ppid'] == children[0]['pid'] for r in children):
        if not any(r['ppid'] == children[1]['pid'] for r in children): return unknown('not a chain')
    return {'status': 'PASS', 'correlation': 'bounded_inference', 'observed': list(a.values())}
