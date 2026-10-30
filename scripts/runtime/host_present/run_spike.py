#!/usr/bin/env python3
"""Single-frame artifact handoff; reuses actual guest readback, does not rerender guest."""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
LAB=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(LAB))
from scripts.runtime.host_present.verify_pixels import verify,SHA
OUT=LAB/'logs/host-present'
SOURCE=LAB/'logs/vk-offscreen/framebuffer.raw'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2)+'\n')
def run(label):
    root=OUT/label;root.mkdir(parents=True,exist_ok=False)
    raw=SOURCE.read_bytes()
    if len(raw)!=16384 or hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Source provenance mismatch')
    helper=LAB/'sources/host-present-spike/presenter'
    stdout=root/'host.stdout.log';stderr=root/'host.stderr.log'
    started=time.monotonic_ns()
    with stdout.open('w') as out,stderr.open('w') as err:
        p=subprocess.Popen([str(helper),str(root)],stdout=out,stderr=err,start_new_session=True)
        try:
            limit=time.monotonic()+10
            while 'stage=HELPER_READY' not in stdout.read_text():
                if p.poll() is not None:raise RuntimeError('Helper exited before ready; inspect raw stderr')
                if time.monotonic()>limit:raise TimeoutError('AppKit readiness timeout')
                time.sleep(0.005)
            # Both payload and readiness marker become visible only by atomic rename.
            publish_process=subprocess.run([str(helper),'--publish',str(root),str(SOURCE)],capture_output=True,text=True,timeout=5)
            (root/'publisher.stdout.log').write_text(publish_process.stdout)
            (root/'publisher.stderr.log').write_text(publish_process.stderr)
            if publish_process.returncode:raise RuntimeError('native publisher failed')
            marker=json.loads((root/'frame.ready.json').read_text())
            copy_begin=marker['copy_begin_ns'];publish=marker['publish_ns']
            rc=p.wait(timeout=15)
        finally:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=2)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
    if rc:raise RuntimeError('Host helper exit '+str(rc)+'; retain logs and mark UNKNOWN')
    host=json.loads((root/'host-result.json').read_text())
    pixels=verify(raw,(root/'host-view.rgba').read_bytes(),host['width'],host['height'])
    save(root/'pixel-verification.json',pixels)
    elapsed_ms=(time.monotonic_ns()-started)/1e6
    publish_capture=host['publish_to_capture_ms']
    receipt={'status':'PASS' if pixels['exact'] and host['is_visible'] and host['occlusion_visible'] and host['on_active_space'] else 'INCOMPLETE',
        'source':str(SOURCE),'source_sha256':SHA,'helper_sha256':sha(helper),
        'source_unchanged_after':sha(SOURCE)==SHA,'host_exit':rc,
        'host_window_created':host['window_number']>0,'is_visible':host['is_visible'],
        'occlusion_visible':host['occlusion_visible'],'on_active_space':host['on_active_space'],
        'view_pixels_exact':pixels['exact'],'pixels_compared':pixels['pixels_compared'],
        'view_screenshot':str(root/'host-view.png'),'screenshot_method':host['screenshot_method'],
        'system_screenshot_or_permissions_used':False,'human_visual_confirmation':'UNKNOWN',
        'backing_scale':host['backing_scale'],'host_content_points':[host['content_width_points'],host['content_height_points']],
        'native_backing_pixels':[host['backing_width'],host['backing_height']],
        'copy_begin_to_publish_ms':(publish-copy_begin)/1e6,
        'publish_to_receive_ms':(host['receive_ns']-publish)/1e6,
        'receive_to_commit_ms':host['receive_to_commit_ms'],
        'receive_to_capture_ms':host['receive_to_capture_ms'],
        'publish_to_capture_ms':publish_capture,
        'copy_begin_to_capture_ms':(host['capture_ns']-copy_begin)/1e6,
        'effective_single_frame_payload_bytes_per_second':16384/(publish_capture/1000),
        'throughput_scope':'one 16384-byte frame / publish-to-view-capture latency; not sustained throughput or FPS',
        'clock':host['clock'],'capture_settle_ms':150,'whole_helper_duration_ms':elapsed_ms,
        'proven_scope':'reuse verified guest-produced bytes -> file handoff -> native AppKit window and own-view capture',
        'guest_render_rerun':False,'original_wine_window_visible':'NOT_PROVEN',
        'wine_driver_integration':'UNKNOWN','window_management':'UNKNOWN','input_roundtrip':'UNKNOWN','dpi_policy':'UNKNOWN','multiwindow':'UNKNOWN'}
    save(root/'receipt.json',receipt)
    print(json.dumps(receipt,indent=2))
    if receipt['status']!='PASS':raise RuntimeError('Evidence incomplete; no presentation claim')
if __name__=='__main__':
    label=sys.argv[1] if len(sys.argv)>1 else 'trial1'
    if not label.isalnum():raise ValueError('simple trial label required')
    run(label)
