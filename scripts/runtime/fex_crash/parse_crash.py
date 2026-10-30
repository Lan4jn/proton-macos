import json

with open("logs/fex-crash/elfuse-crash.ips") as f:
    lines = f.readlines()

meta = json.loads(lines[0])
report = json.loads("".join(lines[1:]))

out = []
name = meta.get("name")
pid = report.get("pid")
time_str = report.get("captureTime")
exc_type = report.get("exception", {}).get("type")
exc_sig = report.get("exception", {}).get("signal")
exc_sub = report.get("exception", {}).get("subtype")
far_val = report.get("exception", {}).get("rawCodes", [0, 0])[1]

out.append("=== HOST CRASH BACKTRACE (macOS DiagnosticReport) ===")
out.append(f"Process: {name} (PID {pid})")
out.append(f"Capture Time: {time_str}")
out.append(f"Exception Type: {exc_type} ({exc_sig})")
out.append(f"Subtype: {exc_sub}")
out.append(f"Fault Address (FAR): 0x{far_val:x}")
out.append(f"Faulting Thread ID: {report.get('faultingThread')}")
out.append("")
out.append("Thread 1 (CRASHED THREAD - preempt_thread_main):")
fault_th = report["threads"][report.get("faultingThread", 1)]
for i, fr in enumerate(fault_th.get("frames", [])):
    s = fr.get("symbol", "?")
    loc = fr.get("symbolLocation", 0)
    off = fr.get("imageOffset", 0)
    out.append(f"  frame #{i}: 0x{off:x} {s} + {loc}")

out.append("")
out.append("Thread 0 (MAIN THREAD - teardown in guest_destroy):")
main_th = report["threads"][0]
for i, fr in enumerate(main_th.get("frames", [])):
    s = fr.get("symbol", "?")
    loc = fr.get("symbolLocation", 0)
    off = fr.get("imageOffset", 0)
    out.append(f"  frame #{i}: 0x{off:x} {s} + {loc}")

text = "\n".join(out)
print(text)
with open("logs/fex-crash/crash_backtrace.txt", "w") as out_f:
    out_f.write(text + "\n")
